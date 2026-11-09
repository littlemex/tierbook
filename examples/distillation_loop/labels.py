"""The example's two caller-side pieces for a closed-label task: the prompt a generation arm is sent, and the grader.

tierbook grades nothing. A generation arm's answer is accepted only when its first word is exactly the gold label
(case-insensitive); a decision model or a distilled student answers with a label directly and is graded the same way.

    python -I labels.py prompts --items cert.jsonl --out cert-prompts.jsonl
    python -I labels.py grade --calls calls.jsonl --items cert.jsonl --out outcomes.jsonl
"""
from __future__ import annotations

import argparse
import json
import re

PROMPT = ("Classify the sentiment of this financial news headline as bearish, bullish or neutral. "
          "Answer with one word only.\n\nHeadline: {text}\nSentiment:")
_WORD = re.compile(r"[A-Za-z]+")


def first_word(text: str) -> str | None:
    m = _WORD.search(text or "")
    return m.group(0).lower() if m else None


def grade(calls: list[dict], items: dict[str, dict], grader: str = "label-exact") -> list[dict]:
    out = []
    for c in calls:
        body = c.get("response")
        if c.get("error") or not body:
            continue
        try:
            text = body["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            continue
        got = first_word(text)
        out.append({"item": c["item"], "arm": c["arm"], "run": c.get("run", ""),
                    "outcome": "accepted" if got == items[c["item"]]["label"] else "rejected",
                    "reason": "" if got else "no word in the answer", "grader": grader})
    return out


def _read(path):
    return [json.loads(line) for line in open(path) if line.strip()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prompts")
    a.add_argument("--items", required=True)
    a.add_argument("--out", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--calls", required=True)
    g.add_argument("--items", nargs="+", required=True)
    g.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if args.cmd == "prompts":
        rows = _read(args.items)
        with open(args.out, "w") as f:
            for r in rows:
                f.write(json.dumps({**r, "prompt": PROMPT.format(text=r["text"])}) + "\n")
        print(f"wrote {len(rows)} prompts to {args.out}")
    else:
        items = {r["item"]: r for path in args.items for r in _read(path)}
        rows = grade(_read(args.calls), items)
        with open(args.out, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        print(f"graded {len(rows)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
