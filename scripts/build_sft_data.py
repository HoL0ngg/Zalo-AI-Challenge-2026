"""Build the fine-tuning set from a run of the base model on the official train data (rejection sampling).

The train set has answers but no reference SQL. A question becomes a training example only when the SQL the
model wrote for it produced an answer that the scorer accepts against the official answer. The prompt is
rebuilt with the same code the pipeline uses at inference, so training and inference see identical input.

    python scripts/build_sft_data.py <run_dir> <train_dir> --out sft/train.jsonl --holdout-out sft/holdout.json

A few businesses are held out (never trained on) so the tuned model can be compared with the base model on
businesses it has not seen, as in the private test.
"""
import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datamate.codegen.prompt_builder import SYSTEM_PROMPT, build_prompt  # noqa: E402
from datamate.core import Candidate, ExecResult, Question  # noqa: E402
from datamate.eval.scorer import matches  # noqa: E402
from datamate.formatting.formatter import format_answer  # noqa: E402
from datamate.gate import gate  # noqa: E402
from datamate.ingest.loader import BusinessLoader  # noqa: E402
from datamate.io.question_reader import read_records  # noqa: E402
from datamate.linking import link  # noqa: E402
from datamate.understanding import understand  # noqa: E402


def pick_holdout(businesses: list[str], every: int) -> list[str]:
    """Every `every`-th business in sorted order: deterministic and spread over the package."""
    return [b for i, b in enumerate(sorted(businesses)) if i % every == every - 1]


def example(prompt: str, code: str) -> dict:
    return {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt},
                         {"role": "assistant", "content": f"<sql>\n{code.strip()}\n</sql>"}]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("train_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--holdout-out", type=Path, required=True)
    parser.add_argument("--holdout-every", type=int, default=5, help="hold out every N-th business (default 5: 6 of 30)")
    args = parser.parse_args()
    logs = list(read_records(args.run_dir / "logs" / "questions.jsonl"))
    gold = {r["id"]: r for r in read_records(args.train_dir / "answers.jsonl")}
    submission = {r["id"]: r for r in read_records(args.run_dir / "submission.jsonl")}
    businesses = sorted({log["question"]["business_id"] for log in logs})
    holdout = pick_holdout(businesses, args.holdout_every)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    with tempfile.TemporaryDirectory(prefix="sft-") as work, args.out.open("w", encoding="utf-8", newline="\n") as stream:
        loader = BusinessLoader(args.train_dir, Path(work))
        for log in logs:
            record = log["question"]
            stats["questions"] += 1
            if record["business_id"] in holdout:
                stats["held_out"] += 1
                continue
            answer = submission.get(record["id"])
            if not answer or answer["type"] in {"abstain", "unanswerable"} or not matches(answer, gold[record["id"]]):
                stats["not_correct"] += 1
                continue
            good = [a for a in log["attempts"] if a.get("error") is None]
            if not good:
                continue
            question = Question.model_validate(record)
            context = loader.load(question.business_id)
            linked = link(understand(question, context), context)
            if not gate(linked).allowed:
                continue
            code = good[-1]["candidate"]["code"]
            stream.write(json.dumps(example(build_prompt(linked), code), ensure_ascii=False) + "\n")
            stats["examples"] += 1
    args.holdout_out.write_text(json.dumps({"businesses": holdout}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({**stats, "holdout_businesses": holdout}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
