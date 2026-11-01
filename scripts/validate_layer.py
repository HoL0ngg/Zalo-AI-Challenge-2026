"""Check the canonical layer against the official gold answers, without an LLM.

Takes the plain questions whose answer is one aggregate over one period ("doanh thu tháng 5/2025",
"tháng 3/2026 có bao nhiêu đơn"), computes that aggregate from the canonical views and compares it with
the gold. A mismatch means the views (dates, statuses, amounts, returns) are wrong for that business.

    python scripts/validate_layer.py official_dataset/train [--business biz_101 ...] [--show 3]
"""
import argparse
import collections
import re
import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datamate.core import Question  # noqa: E402
from datamate.ingest.loader import BusinessLoader  # noqa: E402
from datamate.io.question_reader import read_records  # noqa: E402
from datamate.linking import link  # noqa: E402
from datamate.understanding import understand  # noqa: E402

# Questions that add a condition this script does not model are skipped, never guessed.
EXTRA = re.compile(r"ca (?:sang|chieu|toi)|nhom|kenh|hinh thuc|khach|nhan vien|trung binh|moi |tung |cao nhat|thap nhat|"
                   r"lai|von|no |huy|tra |giao|ngay nao|thu may|%|phan tram|so voi|tang|giam|chenh|thuoc|ke don|"
                   r"don vi|cai|hop|chai|lon |kg|thung|loai|ban nhieu|ban it|mat hang|san pham|hang nao|"
                   r"≥|≤|tro len|tro xuong|dat |tu \d|tren \d|duoi \d|may ngay|so ngay|co dthu|co doanh thu|tien hang|"
                   r"quay|zalo|online|qua |tai |dien thoai|tieu chi|rieng")


def plain_question(resolved, linked) -> str | None:
    text = resolved.normalized_ascii or ""
    primaries = [p for p in resolved.periods if p.role == "primary"]
    if len(resolved.periods) != 1 or len(primaries) != 1 or linked.entities or EXTRA.search(text):
        return None
    if resolved.intent_hints.get("metric") == "revenue" and resolved.intent_hints.get("operation") in {"none", "sum"}:
        return "revenue"
    if re.search(r"bao nhieu don|may don|so don", text) and resolved.intent_hints.get("metric") in {"none", "revenue"}:
        return "orders"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--business", nargs="*")
    parser.add_argument("--show", type=int, default=2, help="mismatches to print per business")
    args = parser.parse_args()
    questions = list(read_records(args.data_dir / "questions.jsonl"))
    gold = {r["id"]: r for r in read_records(args.data_dir / "answers.jsonl")}
    businesses = sorted({q["business_id"] for q in questions})
    if args.business:
        businesses = [b for b in businesses if b in set(args.business)]
    total = collections.Counter()
    with tempfile.TemporaryDirectory(prefix="validate-") as work:
        loader = BusinessLoader(args.data_dir, Path(work))
        for business in businesses:
            try:
                context = loader.load(business)
            except Exception as error:  # noqa: BLE001
                print(f"{business}: LOAD FAILED {error}", flush=True)
                continue
            if not (context.canonical and context.canonical.complete):
                print(f"{business}: no canonical layer", flush=True)
                total["no_layer"] += 1
                continue
            connection = duckdb.connect(str(context.database), read_only=True)
            ok = bad = 0
            shown = []
            for record in (q for q in questions if q["business_id"] == business):
                question = Question.model_validate(record)
                resolved = understand(question, context)
                linked = link(resolved, context)
                kind = plain_question(resolved, linked)
                answer = gold[record["id"]]
                if kind is None or answer["type"] != "number" or answer.get("answer") is None:
                    continue
                period = next(p for p in resolved.periods if p.role == "primary")
                bounds = f"BETWEEN DATE '{period.start}' AND DATE '{period.end}'"
                sql = (f"SELECT SUM(revenue) FROM v_sales WHERE sale_date {bounds}" if kind == "revenue"
                       else f"SELECT count(*) FROM v_valid_orders WHERE order_date {bounds}")
                got = connection.execute(sql).fetchone()[0]
                got = 0 if got is None else round(got)
                if got == round(answer["answer"]):
                    ok += 1
                else:
                    bad += 1
                    if len(shown) < args.show:
                        shown.append((kind, record["question"][:70], answer["answer"], got))
            connection.close()
            total["ok"] += ok
            total["bad"] += bad
            tested = ok + bad
            print(f"{business}: {ok}/{tested} match" + ("" if not bad else f"  e.g. {shown}"), flush=True)
    print(dict(total), "| match rate", round(total["ok"] / max(1, total["ok"] + total["bad"]), 3))


if __name__ == "__main__":
    main()
