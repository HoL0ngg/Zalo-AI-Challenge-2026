import argparse
import json
from pathlib import Path

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
    validating = sub.add_parser("validate")
    validating.add_argument("submission", type=Path)
    evaluating = sub.add_parser("eval")
    evaluating.add_argument("submission", type=Path)
    evaluating.add_argument("answers", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        result = run(args.data_dir, args.result_dir, args.config)
    elif args.command == "eval":
        result = score(list(read_records(args.submission)), list(read_records(args.answers)))
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
