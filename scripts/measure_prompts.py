"""Measure prompt size per question (chars, and tokens when a local tokenizer is given).

    python scripts/measure_prompts.py --data-dir dataset/train [--tokenizer models/qwen-coder-awq]

Runs ingest -> understand -> link -> gate -> build_prompt only (no model), so it is CPU-only and offline.
Use it to choose prompt caps against `max_model_len - max_tokens`.
"""
import argparse
import json
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

from datamate.codegen.prompt_builder import SYSTEM_PROMPT, build_prompt
from datamate.core import Question
from datamate.gate import gate
from datamate.ingest.loader import BusinessLoader
from datamate.io.question_reader import read_records
from datamate.linking import link
from datamate.understanding import understand


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=None, help="local tokenizer directory (optional)")
    parser.add_argument("--limit", type=int, default=0, help="max questions (0 = all)")
    parser.add_argument("--uncapped", action="store_true", help="measure without the readme/rulebook caps")
    args = parser.parse_args()
    count = None
    if args.tokenizer is not None:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), local_files_only=True)
        count = lambda text: len(tokenizer(text)["input_ids"])  # noqa: E731
    sizes: dict[str, list[int]] = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix="datamate-measure-") as temporary:
        loader = BusinessLoader(args.data_dir.resolve(), Path(temporary))
        for index, record in enumerate(read_records(args.data_dir / "questions.jsonl")):
            if args.limit and index >= args.limit:
                break
            question = Question.model_validate(record)
            linked = link(understand(question, loader.load(question.business_id)), loader.load(question.business_id))
            if not gate(linked).allowed:
                continue
            prompt = SYSTEM_PROMPT + build_prompt(linked, caps=not args.uncapped)
            sizes[question.business_id].append(count(prompt) if count else len(prompt))
    unit = "tokens" if count else "chars"
    every = [n for values in sizes.values() for n in values]
    print(json.dumps({
        "unit": unit, "questions": len(every), "mean": round(statistics.mean(every)),
        "p50": percentile(every, .5), "p95": percentile(every, .95), "max": max(every),
        "per_business_max": {b: max(v) for b, v in sorted(sizes.items())},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
