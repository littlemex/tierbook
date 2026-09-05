"""Pinned upstream checkouts with a local patch series, and the checks that keep the series honest.

Two repositories this project depends on are not ours: contribution to one is prohibited outright and the
other is infrastructure that deliberately does not carry individual application charts. Both are still on
the critical path. The structure that resolves that is old and well understood -- **vendor a pinned revision
and carry a patch series against it until upstream takes the change** -- and it is already how this project
physically ships changes, because Code Defender blocks direct pushes to those remotes and patches already
travel as a `git format-patch` series.

Known pattern, named so it is not reinvented: this is quilt's model, and the same shape as Yocto's and
Buildroot's `SRC_URI` patch directories, and Debian's `debian/patches` with a `series` file. Nothing here is
novel; what is worth writing is the set of failures that a naive version has, because every one of them has
already happened to somebody.

## The failures this is built to refuse

**A patch that no longer applies must stop the build, not be skipped.** A series that silently drops a patch
produces a tree nobody has ever tested while every check still passes. `apply_series` treats a failed patch
as fatal and names it.

**A patch that upstream has already taken must be detected and removed.** Otherwise the series grows
forever, and eventually two copies of the same change fight. Detection is by content, not by message:
`landed_upstream` asks whether the pinned tree already contains the patch's effect, because a maintainer who
rewrote the commit message or squashed it still took the change.

**A pin that has gone stale must be visible without a network call at build time.** The manifest records the
revision *and* the date it was pinned, so `age_days` is answerable offline. A build that needs the network to
tell you whether it is current is a build that succeeds differently on a plane.

**The reason for each patch must be in the series, not in someone's memory.** Every entry carries the
upstream issue it corresponds to and the condition under which it can be dropped. A patch with no issue is
allowed -- sometimes you are ahead of the conversation -- but it has to say so, because "no issue yet" and
"issue forgotten" look identical in a directory listing.

## What this module does not do

**It does not fetch, and it does not push.** Network operations belong to the caller's workflow, which in
this project goes through an S3 relay to an EC2 host for reasons that have nothing to do with vendoring.
This module reads a manifest, applies a series to a checkout, and answers questions about drift.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from tierbook.evidence import EvidenceError


@dataclass(frozen=True)
class Patch:
    """One local change against a pinned upstream, and the conditions for dropping it."""

    path: Path
    #: The upstream issue this corresponds to, or None when we are ahead of the conversation. None is
    #: allowed and must be explicit, because "not filed yet" and "forgotten" look the same in a listing.
    issue: str | None
    #: One sentence: what this patch changes and why upstream would want it.
    why: str
    #: How we will know it can be dropped. Free text, but required: a patch with no drop condition is a
    #: patch that will be carried forever by default.
    drop_when: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()[:12]


@dataclass(frozen=True)
class Upstream:
    """A pinned dependency we do not own."""

    name: str
    remote: str
    revision: str                 # a full commit sha; a tag or branch is refused
    pinned_on: date
    #: Why this project cannot simply use upstream as-is. Required, because a vendored tree with no stated
    #: reason is a fork nobody decided to make.
    reason: str
    #: True when we may not contribute at all and must file issues instead. Recorded because it changes the
    #: expected lifetime of every patch in the series.
    contribution_prohibited: bool
    patches: tuple[Patch, ...] = ()

    def age_days(self, today: date | None = None) -> int:
        return ((today or date.today()) - self.pinned_on).days

    def stale(self, *, max_age_days: int, today: date | None = None) -> bool:
        return self.age_days(today) > max_age_days


def load_manifest(path: str | Path) -> list[Upstream]:
    """Read the pin manifest, refusing the shapes that make a pin meaningless."""
    p = Path(path)
    doc = json.loads(p.read_text())
    out: list[Upstream] = []
    for entry in doc.get("upstreams") or []:
        rev = str(entry.get("revision") or "")
        if len(rev) != 40 or any(c not in "0123456789abcdef" for c in rev.lower()):
            raise EvidenceError(
                f"{entry.get('name')!r} is pinned to {rev!r}, which is not a full commit sha. A tag or a "
                f"branch is not a pin: it moves, and then the patch series is against something else.")
        for key in ("reason", "remote", "pinned_on"):
            if not entry.get(key):
                raise EvidenceError(f"{entry.get('name')!r} has no {key}; a pin without one is undecidable")
        patches = []
        for q in entry.get("patches") or []:
            for key in ("path", "why", "drop_when"):
                if not q.get(key):
                    raise EvidenceError(
                        f"a patch on {entry['name']!r} has no {key}. `drop_when` is required because a "
                        f"patch with no drop condition is carried forever by default, and `why` is required "
                        f"because the series is the only place the reason survives.")
            patches.append(Patch(path=p.parent / q["path"], issue=q.get("issue"),
                                 why=q["why"], drop_when=q["drop_when"]))
        out.append(Upstream(
            name=entry["name"], remote=entry["remote"], revision=rev,
            pinned_on=date.fromisoformat(entry["pinned_on"]), reason=entry["reason"],
            contribution_prohibited=bool(entry.get("contribution_prohibited")),
            patches=tuple(patches)))
    if not out:
        raise EvidenceError(f"{p} declares no upstreams")
    return out


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


@dataclass
class ApplyReport:
    """What happened when the series was applied."""

    upstream: str
    applied: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def __str__(self) -> str:
        lines = [f"{self.upstream}: {len(self.applied)} applied, "
                 f"{len(self.already_present)} already upstream, {len(self.failed)} FAILED"]
        for name in self.already_present:
            lines.append(f"  already upstream, drop it: {name}")
        for name, why in self.failed:
            lines.append(f"  FAILED {name}: {why}")
        return "\n".join(lines)


def landed_upstream(repo: Path, patch: Patch) -> bool:
    """Whether the pinned tree already contains this patch's effect.

    Asked by content rather than by commit message. A maintainer who rewrote the message, squashed the
    change, or reimplemented it still took it, and a series that checks messages would carry a duplicate
    until the two copies conflicted.
    """
    r = _git(repo, "apply", "--reverse", "--check", str(patch.path), check=False)
    return r.returncode == 0


def apply_series(repo: str | Path, upstream: Upstream, *, allow_dirty: bool = False) -> ApplyReport:
    """Check out the pin and apply the series. A patch that does not apply is fatal.

    Returns a report rather than raising on a failed patch, so a caller can see the whole series' state in
    one pass instead of one failure at a time -- but `ok` is False and the caller is expected to treat that
    as a build failure. Skipping is what this refuses to do silently, not what it refuses to report.
    """
    r = Path(repo)
    if not (r / ".git").exists():
        raise EvidenceError(f"{r} is not a git checkout, so nothing can be pinned in it")
    if not allow_dirty:
        dirty = _git(r, "status", "--porcelain").stdout.strip()
        if dirty:
            raise EvidenceError(
                f"{r} has uncommitted changes, so applying a series would mix them with ours:\n{dirty[:400]}")
    have = _git(r, "rev-parse", "HEAD").stdout.strip()
    if have != upstream.revision:
        raise EvidenceError(
            f"{upstream.name} is checked out at {have[:12]} but pinned to {upstream.revision[:12]}. The "
            f"series is written against the pin; applying it to another revision is how a patch that "
            f"'still applies' changes meaning.")
    report = ApplyReport(upstream.name)
    for patch in upstream.patches:
        if not patch.path.exists():
            report.failed.append((patch.path.name, "the patch file named in the manifest does not exist"))
            continue
        if landed_upstream(r, patch):
            report.already_present.append(patch.path.name)
            continue
        res = _git(r, "apply", "--index", str(patch.path), check=False)
        if res.returncode != 0:
            report.failed.append((patch.path.name, (res.stderr or res.stdout).strip()[:300]))
        else:
            report.applied.append(patch.path.name)
    return report


def drift_report(upstreams: list[Upstream], *, max_age_days: int = 60,
                 today: date | None = None) -> list[str]:
    """Offline answers to "is any pin stale, and is any patch undocumented".

    Offline on purpose: a check that needs the network tells you something different on a plane, and a pin's
    age is a property of the manifest rather than of the remote.
    """
    out: list[str] = []
    for u in upstreams:
        age = u.age_days(today)
        if u.stale(max_age_days=max_age_days, today=today):
            out.append(f"{u.name}: pinned {age} days ago, over the {max_age_days}-day limit")
        for q in u.patches:
            if q.issue is None:
                out.append(f"{u.name}: {q.path.name} has no upstream issue"
                           + (" (contribution is prohibited here, so an issue is the only route)"
                              if u.contribution_prohibited else ""))
    return out
