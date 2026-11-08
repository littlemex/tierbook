"""Sample MMLU-Pro items into the JSONL the drive reads: one line per item, with the prompt and the key.

The category is the task type, because it is also a label the router can compute at request time: vLLM Semantic
Router's domain classifier emits MMLU-Pro's category names. The prompt does not name the category, so the router has
to classify the question rather than read the answer off the prompt.

    python -I prepare_mmlu_pro.py --parquet mmlu_pro_test.parquet --categories math,law,history,biology \
        --per-category 100 --seed 1 --out items.jsonl
"""
from __future__ import annotations

import argparse
import json
import random

LETTERS = "ABCDEFGHIJ"


def prompt_for(question: str, options: list[str]) -> str:
    lines = [f"{LETTERS[i]}. {o}" for i, o in enumerate(options)]
    return ("Answer the following multiple choice question with only the letter of the correct option.\n\n"
            f"Question: {question}\n" + "\n".join(lines) + "\nAnswer:")


def sample(rows: list[dict], categories: list[str], per_category: int, seed: int, skip: int = 0) -> list[dict]:
    """`skip` drops the first items of each shuffled category, so a second sample never overlaps the first."""
    out = []
    for cat in categories:
        pool = sorted((r for r in rows if r["category"] == cat), key=lambda r: r["question_id"])
        random.Random(f"{seed}:{cat}").shuffle(pool)
        if len(pool) < skip + per_category:
            raise SystemExit(f"{cat!r} has {len(pool)} items, fewer than skip {skip} + {per_category}")
        for r in pool[skip:skip + per_category]:
            out.append({"item": f"mmlu-pro:{r['question_id']}", "task_type": cat,
                        "prompt": prompt_for(r["question"], list(r["options"])), "answer": r["answer"]})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parquet", required=True)
    p.add_argument("--categories", required=True)
    p.add_argument("--per-category", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    import pyarrow.parquet as pq

    rows = pq.read_table(a.parquet).to_pylist()
    items = sample(rows, [c.strip() for c in a.categories.split(",")], a.per_category, a.seed, a.skip)
    with open(a.out, "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    print(f"wrote {len(items)} items to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
