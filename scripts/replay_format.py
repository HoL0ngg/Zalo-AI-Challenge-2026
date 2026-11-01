"""Re-score a finished run with the CURRENT understanding/linking/formatting code, without an LLM.

Each logged question keeps the SQL the model produced and its result rows. This script re-links the
question (new intent/expected-type rules), re-attaches the expected type to the logged candidate and
runs the current formatter on the logged rows, then scores against the gold answers. It isolates the
effect of formatter / schema-linker changes; anything that changes the SQL itself (prompt, views) still
needs a real run.

    python scripts/replay_format.py kaggle_out/datamate_results/result/train dataset/train \
        --answers dataset/train/answers.jsonl [--meta synth/out/.debug/train/questions_meta.jsonl]
"""
import argparse
import json
import re
from datetime import date
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datamate.codegen.generator import apply_expected  # noqa: E402
from datamate.core import Answer, Candidate, ExecResult, Question  # noqa: E402
from datamate.eval.scorer import matches, score  # noqa: E402
from datamate.formatting.formatter import format_answer  # noqa: E402
from datamate.gate import gate  # noqa: E402
from datamate.ingest.loader import BusinessLoader  # noqa: E402
from datamate.io.question_reader import read_records  # noqa: E402
from datamate.linking import link  # noqa: E402
from datamate.understanding import understand  # noqa: E402


def replay(log: dict, loader: BusinessLoader) -> Answer:
    question = Question.model_validate(log["question"])
    context = loader.load(question.business_id)
    linked = link(understand(question, context), context)
    decision = gate(linked)
    if not decision.allowed:
        return Answer(question.id, "unanswerable", reason=decision.reason)
    good = [a for a in log["attempts"] if a.get("error") is None]
    if not good:
        return Answer(question.id, "abstain")
    attempt = good[-1]
    raw = attempt["candidate"]
    candidate = Candidate(raw["code"], None, None, dict(raw.get("meta") or {}))  # type/unit re-derived
    candidate = apply_expected(candidate, linked)
    rows = attempt["rows"]
    if (linked.schema.get("expected") or {}).get("type") == "date":
        # JSON logs store dates as text; the live run had real dates, so restore them for a faithful replay.
        rows = [[date.fromisoformat(v) if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else v
                 for v in row] for row in rows]
    try:
        return format_answer(question, ExecResult(candidate, attempt["columns"], rows))
    except Exception:  # noqa: BLE001  same policy as the pipeline: unformattable -> abstain
        return Answer(question.id, "abstain")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--meta", type=Path)
    args = parser.parse_args()
    logs = list(read_records(args.result_dir / "logs" / "questions.jsonl"))
    gold = list(read_records(args.answers))
    old = list(read_records(args.result_dir / "submission.jsonl"))
    with tempfile.TemporaryDirectory(prefix="replay-") as work:
        loader = BusinessLoader(args.data_dir, Path(work))
        new = [replay(log, loader).to_dict() for log in logs]
    before, after = score(old, gold), score(new, gold)
    total = len(gold)
    print(json.dumps({"total": total,
                      "before": {**{k: v for k, v in before.items() if k != "per_type"},
                                 "accuracy": round(before["correct"] / total, 4)},
                      "after": {**{k: v for k, v in after.items() if k != "per_type"},
                                "accuracy": round(after["correct"] / total, 4)}},
                     ensure_ascii=False, indent=1))
    if args.meta:
        templates = {m["id"]: m["spec"]["template"] for m in read_records(args.meta)}
        gold_by_id = {g["id"]: g for g in gold}
        old_by_id = {r["id"]: r for r in old}
        table = defaultdict(lambda: [0, 0, 0])
        for answer in new:
            one_gold = [gold_by_id[answer["id"]]]
            row = table[templates.get(answer["id"], "?")]
            row[0] += 1
            row[1] += matches(old_by_id.get(answer["id"], {"id": answer["id"], "type": "abstain"}), one_gold[0])
            row[2] += matches(answer, one_gold[0])
        print(f"{'template':18s} n  before after")
        for name, (n, b, a) in sorted(table.items(), key=lambda kv: kv[1][2] - kv[1][1], reverse=True):
            if a != b:
                print(f"{name:18s} {n:2d} {b:5d} {a:5d}")


if __name__ == "__main__":
    main()
