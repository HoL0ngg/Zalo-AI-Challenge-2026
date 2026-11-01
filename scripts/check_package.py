"""CPU-only health check of a data package (no LLM): ingest, canonical layer, periods and the gate.

    python scripts/check_package.py dataset/train [--answers dataset/train/answers.jsonl]
Reports per business whether the canonical layer is complete and what ingest warned about, how many
questions resolved a period (and two periods for growth-style questions), and, when gold answers are
given, how the gate compares with the `unanswerable` gold.
"""
import argparse
import collections
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datamate.core import Question  # noqa: E402
from datamate.gate import gate  # noqa: E402
from datamate.ingest.loader import BusinessLoader  # noqa: E402
from datamate.io.question_reader import read_records  # noqa: E402
from datamate.linking import link  # noqa: E402
from datamate.understanding import understand  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--business", nargs="*", help="only these business ids (quick check)")
    args = parser.parse_args()
    questions = list(read_records(args.data_dir / "questions.jsonl"))
    if args.business:
        questions = [q for q in questions if q["business_id"] in set(args.business)]
    gold = {r["id"]: r for r in read_records(args.answers)} if args.answers else {}
    stats = collections.Counter()
    reasons = collections.Counter()
    blocked_samples = []
    complete_ids = []
    problems: dict[str, list[str]] = {}
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="check-") as work:
        loader = BusinessLoader(args.data_dir, Path(work))
        for business in sorted({q["business_id"] for q in questions}):
            try:
                context = loader.load(business)
            except Exception as error:  # noqa: BLE001
                problems[business] = [f"LOAD FAILED: {error}"]
                stats["business_load_failed"] += 1
                continue
            canonical = context.canonical
            stats["business_ok"] += 1
            if canonical and canonical.complete:
                complete_ids.append(business)
            stats["canonical_complete"] += bool(canonical and canonical.complete)
            notes = [w for w in context.warnings if not w.startswith("consistency:")]
            if not (canonical and canonical.complete) or notes:
                problems[business] = [f"complete={bool(canonical and canonical.complete)}"] + notes[:3]
        for record in questions:
            if record["business_id"] in problems and problems[record["business_id"]][0].startswith("LOAD"):
                continue
            question = Question.model_validate(record)
            context = loader.load(question.business_id)
            resolved = understand(question, context)
            linked = link(resolved, context)
            decision = gate(linked)
            expected = (linked.schema or {}).get("expected") or {}
            stats["questions"] += 1
            stats["with_period"] += bool(resolved.periods)
            if expected.get("type") == "percent":
                stats["percent_q"] += 1
                stats["percent_two_periods"] += len(resolved.periods) >= 2
            if gold:
                is_gold_unanswerable = gold[record["id"]]["type"] == "unanswerable"
                stats["gold_unanswerable"] += is_gold_unanswerable
                stats["gate_blocks_correctly"] += (not decision.allowed) and is_gold_unanswerable
                stats["gate_blocks_wrongly"] += (not decision.allowed) and not is_gold_unanswerable
                if (not decision.allowed) and not is_gold_unanswerable:
                    reasons[str(decision.reason)[:80]] += 1
                    if len(blocked_samples) < 8:
                        blocked_samples.append([record["business_id"], record["question"], str(decision.reason)[:100]])
    print(json.dumps({"seconds": round(time.time() - started), **stats}, indent=1))
    print("complete businesses:", complete_ids)
    print("wrong-block reasons:", dict(reasons))
    for sample in blocked_samples:
        print("  blocked:", sample)
    for business, notes in list(problems.items())[:15]:
        print(business, notes)
    print(f"... {len(problems)} business(es) with problems")


if __name__ == "__main__":
    main()
