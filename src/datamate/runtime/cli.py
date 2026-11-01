import argparse
import json
from pathlib import Path

from datamate.eval.report import build_report
from datamate.eval.scorer import score
from datamate.formatting.schemas import ANSWER_SCHEMA
from datamate.io.question_reader import read_records
from datamate.runtime.runner import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="datamate")
    sub = parser.add_subparsers(dest="command", required=True)
    running = sub.add_parser("run")
    running.add_argument("--data-dir", type=Path, default=Path("/data"))
    running.add_argument("--result-dir", type=Path, default=Path("/result"))
    running.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    running.add_argument("--max-per-business", type=int, default=None,
                         help="answer only the first N questions of each business (quick sample, not for submission)")
    validating = sub.add_parser("validate")
    validating.add_argument("submission", type=Path)
    evaluating = sub.add_parser("eval")
    evaluating.add_argument("submission", type=Path)
    evaluating.add_argument("answers", type=Path)
    evaluating.add_argument("--logged-only", action="store_true",
                            help="score only the questions in the run's logs (for --max-per-business samples)")
    reporting = sub.add_parser("report", help="stage-by-stage accuracy and failure report for a finished run")
    reporting.add_argument("result_dir", type=Path)
    reporting.add_argument("answers", type=Path)
    reporting.add_argument("--meta", type=Path, default=None,
                           help="synth questions_meta.jsonl: adds accuracy per question template")
    args = parser.parse_args()
    if args.command == "run":
        result = run(args.data_dir, args.result_dir, args.config, max_per_business=args.max_per_business)
    elif args.command == "report":
        templates = ({m["id"]: m["spec"]["template"] for m in read_records(args.meta)} if args.meta else None)
        logs = list(read_records(args.result_dir / "logs" / "questions.jsonl"))
        done = {log["id"] for log in logs}   # a sampled run is reported against the questions it answered
        result = build_report(list(read_records(args.result_dir / "submission.jsonl")), logs,
                              [a for a in read_records(args.answers) if a["id"] in done], templates)
    elif args.command == "eval":
        gold = list(read_records(args.answers))
        if args.logged_only:
            logged = args.submission.parent / "logs" / "questions.jsonl"
            done = {log["id"] for log in read_records(logged)}
            gold = [g for g in gold if g["id"] in done]
        result = score(list(read_records(args.submission)), gold)
        result["scored"] = len(gold)
        result["accuracy"] = round(result["correct"] / len(gold), 4) if gold else None
        # Official scoring (rulebook section 9): +1 right, -1 wrong, 0 abstain.
        result["points"] = result["correct"] - result["wrong"]
    else:
        records = list(read_records(args.submission))
        for record in records:
            ANSWER_SCHEMA.validate_python(record)
        if len({r["id"] for r in records}) != len(records):
            raise ValueError("Duplicate submission IDs")
        result = {"valid": len(records)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
