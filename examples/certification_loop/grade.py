"""The caller's grader for this example: the first option letter in the answer, against the key.

tierbook does not grade. This file is the example's grader, and it is deliberately the crude, checkable one: an
answer with no option letter in it is `rejected` (the model answered, and the answer was unusable), which is a
different thing from `unobserved` (no answer came back), and ingest keeps the two apart.
"""
from __future__ import annotations

import argparse
import json
import re

_LEADING = re.compile(r"^\**(?:\(([A-J])\)|([A-J])\**(?:[.):\n]|$))")
_STATED = re.compile(r"answer is:?\s*\**\(?([A-J])\)?", re.IGNORECASE)


def letter_of(text: str) -> str | None:
    """The option the answer commits to: a leading letter, or an explicit "the answer is X".

    Strict on purpose. Searching for any standalone capital letter would read the article in "A function ..." as
    option A, so an answer that does not commit to a letter is not credited with one.
    """
    t = (text or "").strip()
    m = _LEADING.match(t)
    if m:
        return m.group(1) or m.group(2)
    m = _STATED.search(t)
    return m.group(1) if m else None


def grade(calls: list[dict], items: dict[str, dict]) -> list[dict]:
    out = []
    for c in calls:
        body = c.get("response")
        if c.get("error") or not body:
            continue
        try:
            text = body["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            continue
        got = letter_of(text)
        key = items[c["item"]]["answer"]
        out.append({"item": c["item"], "arm": c["arm"], "run": c.get("run", ""),
                    "outcome": "accepted" if got == key else "rejected",
                    "reason": "" if got else "no option letter in the answer", "grader": "mmlu-pro-letter"})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--calls", required=True)
    p.add_argument("--items", nargs="+", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    items = {}
    for path in a.items:
        for line in open(path):
            if line.strip():
                it = json.loads(line)
                items[it["item"]] = it
    calls = [json.loads(line) for line in open(a.calls) if line.strip()]
    rows = grade(calls, items)
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"graded {len(rows)} of {len(calls)} calls -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
