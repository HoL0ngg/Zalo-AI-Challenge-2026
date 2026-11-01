"""Compare a finished run with the canonical layer on the plain aggregate questions (no gold needed).

For public_test there are no answers, but for "doanh thu tháng X" / "số đơn tháng X" the canonical views
give a trustworthy value (validated against the official train, scripts/validate_layer.py). This lists how
often the model's answer disagrees with it, per business, with examples.

    python scripts/compare_run.py <result_dir> <data_dir> [--business dev_001 ...]
"""
import argparse
import collections
import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_layer import plain_question  # noqa: E402

from datamate.core import Question  # noqa: E402
from datamate.ingest.loader import BusinessLoader  # noqa: E402
from datamate.io.question_reader import read_records  # noqa: E402
from datamate.linking import link  # noqa: E402
from datamate.understanding import understand  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--business", nargs="*")
    parser.add_argument("--show", type=int, default=3)
    args = parser.parse_args()
    answers = {r["id"]: r for r in read_records(args.result_dir / "submission.jsonl")}
    questions = list(read_records(args.data_dir / "questions.jsonl"))
    businesses = sorted({q["business_id"] for q in questions})
    if args.business:
        businesses = [b for b in businesses if b in set(args.business)]
    total = collections.Counter()
    with tempfile.TemporaryDirectory(prefix="compare-") as work:
        loader = BusinessLoader(args.data_dir, Path(work))
        for business in businesses:
            context = loader.load(business)
            if not (context.canonical and context.canonical.complete):
                print(f"{business}: no canonical layer", flush=True)
                continue
            connection = duckdb.connect(str(context.database), read_only=True)
            count, shown = collections.Counter(), []
            for record in (q for q in questions if q["business_id"] == business):
                question = Question.model_validate(record)
                resolved = understand(question, context)
                kind = plain_question(resolved, link(resolved, context))
                if kind is None:
                    continue
                period = next(p for p in resolved.periods if p.role == "primary")
                bounds = f"BETWEEN DATE '{period.start}' AND DATE '{period.end}'"
                sql = (f"SELECT SUM(revenue) FROM v_sales WHERE sale_date {bounds}" if kind == "revenue"
                       else f"SELECT count(*) FROM v_valid_orders WHERE order_date {bounds}")
                truth = connection.execute(sql).fetchone()[0]
                truth = 0 if truth is None else round(truth)
                given = answers.get(record["id"], {"type": "abstain"})
                if given["type"] == "abstain":
                    count["abstain"] += 1
                elif given.get("answer") == truth:
                    count["same"] += 1
                else:
                    count["differ"] += 1
                    if len(shown) < args.show:
                        shown.append((kind, record["question"][:60], truth, given.get("answer")))
            connection.close()
            total.update(count)
            print(f"{business}: {dict(count)}" + (f"  e.g. {shown}" if shown else ""), flush=True)
    print(dict(total))


if __name__ == "__main__":
    main()
