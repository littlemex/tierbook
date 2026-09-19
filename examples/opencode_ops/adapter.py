"""The seam a coding agent plugs into, and the fake the tests drive it with.

**Why a seam rather than an integration.** A coding agent's model call is one function that takes a request body and
returns a reply. That is the whole surface the loop needs, so the example asks for exactly that and nothing more -- an
adapter written against a specific agent's internals would have to be rewritten for the next one, and would put a
dependency in front of an example whose point is the shape of the loop.

For a real agent, the adapter is the agent's own call wrapped so that the body is visible on the way past. The body is
what the harness is read from, which is why it is the parameter rather than a prompt string: `tierbook.harness` reads a
request, and a string has already thrown away the tools, the readout and the sampler settings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class Reply:
    """What the loop needs back from a call, and nothing about how it was produced.

    `accepted` is the example's quality signal and is deliberately crude: whether the answer was taken. A real
    deployment replaces it with whatever it can actually observe -- a test suite passing, a patch applying, a human
    keeping the edit -- and the loop does not change, because it only ever asks whether the answer was taken.
    """

    text: str
    accepted: bool
    input_mtok: float
    output_mtok: float


class Agent(Protocol):
    """A coding agent, reduced to the one thing the loop needs of it."""

    def __call__(self, body: dict, *, candidate: str) -> Reply:  # pragma: no cover - a protocol
        ...


def opencode_adapter(call: Callable[[dict], object]) -> Agent:
    """Wrap a real agent's model call so the loop can drive it.

    Deliberately thin. It exists to document where a real agent attaches, and it does not try to normalise anything:
    the reply's shape is the agent's, and translating it is the caller's one job here.
    """
    def agent(body: dict, *, candidate: str) -> Reply:  # pragma: no cover - needs a real agent
        raw = call({**body, "model": candidate})
        return Reply(text=getattr(raw, "text", str(raw)),
                     accepted=bool(getattr(raw, "accepted", True)),
                     input_mtok=float(getattr(raw, "input_mtok", 0.0)),
                     output_mtok=float(getattr(raw, "output_mtok", 0.0)))
    return agent


@dataclass
class ScriptedAgent:
    """A fake agent whose answers are fixed per candidate, so a test can assert what the loop did rather than what a
    model happened to say.

    `accepts` is the acceptance rate per candidate, applied deterministically by position rather than by sampling: a
    test that has to average over randomness cannot say whether the loop moved traffic or the coin did.
    """

    accepts: dict[str, float]
    input_mtok: float = 0.01
    output_mtok: float = 0.002
    calls: list[tuple[str, dict]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def __call__(self, body: dict, *, candidate: str) -> Reply:
        seen = sum(1 for c, _ in self.calls if c == candidate)
        rate = self.accepts[candidate]
        # Deterministic, and the arithmetic matters: accept on call n when the running quota crosses a whole number, so
        # over n calls the count is exactly floor(n * rate). The first version used `round` and gave one acceptance in
        # four at rate 0.5, which would have made every assertion about the loop actually an assertion about the fake.
        accepted = int((seen + 1) * rate) > int(seen * rate)
        self.calls.append((candidate, body))
        return Reply(text=f"answer from {candidate}", accepted=accepted,
                     input_mtok=self.input_mtok, output_mtok=self.output_mtok)


def request_body(task: str, *, terse: bool = True) -> dict:
    """A request shaped the way a coding agent sends one, so the harness has something real to read.

    The instruction is in a system message because that is where the harness reads it from, and the two wordings differ
    by more than politeness: on this project's own corpus one sentence moved accuracy 12.04 points, so an example that
    sent the same instruction every time would be demonstrating a loop with one arm.
    """
    instruction = ("Answer with the patch only. Do not explain."
                   if terse else "Think step by step, then give the patch.")
    return {
        "messages": [{"role": "system", "content": instruction},
                     {"role": "user", "content": task}],
        "tools": [{"function": {"name": "read_file", "parameters": {"type": "object"}}},
                  {"function": {"name": "write_file", "parameters": {"type": "object"}}}],
        "temperature": 0.0,
    }
