"""Evaluation of Phase 3: role mapping, entity linking and the rule gate.

  1. Role mapping: canonical roles/columns vs the generator's column maps (11 businesses, 3 layouts).
  2. Gate on dataset questions: precision/recall of `unanswerable` against train gold, and the questions
     blocked in dev (dev gold is withheld, so those are listed for review).
  3. Entity linking on synthetic questions: top-1 accuracy by noise type for existing entities (as name, SKU
     or sale-line alias) and the missing-entity rate for names that do not exist.

Reads the generator's naming maps and noise module as text/at script level only; src never imports synth.
Usage: python scripts/eval_linking.py [--per-business 10] [--seeds 3]
"""
from __future__ import annotations

import argparse
import ast
import json
import random
import sys
import tempfile
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True  # importing synth must not rewrite its tracked .pyc files
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datamate.core import Question  # noqa: E402
from datamate.gate import gate  # noqa: E402
from datamate.ingest.loader import BusinessLoader  # noqa: E402
from datamate.io.question_reader import read_records  # noqa: E402
from datamate.linking import link  # noqa: E402
from datamate.understanding import understand  # noqa: E402

ROLE_TO_SYNTH = {"products": "products", "customers": "customers", "orders": "orders", "lines": "order_lines",
                 "purchases": "purchases", "debts": "debts"}
CONCEPT_TO_SYNTH = {
    "products": {"sku": "ma_sp", "name": "ten_sp", "category": "danh_muc", "unit": "don_vi", "price": "gia_ban", "cost": "gia_von"},
    "customers": {"customer_id": "ma_kh", "name": "ten_kh", "phone": "sdt", "region": "khu_vuc"},
    "orders": {"order_id": "ma_don", "order_date": "ngay", "customer_id": "ma_kh", "status": "trang_thai",
               "voucher": "voucher_don", "shipping": "phi_ship", "vat": "vat"},
    "lines": {"line_id": "dong_id", "order_id": "ma_don", "sku": "ma_sp", "qty": "so_luong", "unit_price": "don_gia",
              "discount": "giam_gia_dong", "returned": "tra_hang", "display_name": "ten_hien_thi"},
    "purchases": {"lot_id": "lo_id", "purchase_date": "ngay_nhap", "sku": "ma_sp", "qty": "so_luong",
                  "expiry_date": "han_dung", "unit_cost": "gia_nhap"},
    "debts": {"customer_id": "ma_kh", "amount": "so_tien_no", "debt_date": "ngay_no"},
}


def synth_names() -> tuple[dict, dict]:
    tree = ast.parse((ROOT / "synth" / "src" / "writers.py").read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in {"TABLE_NAMES", "COLUMNS"}:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return found.get("TABLE_NAMES", {}), found.get("COLUMNS", {})


def layout_style(directory: Path) -> int:
    suffixes = {p.suffix.lower() for p in directory.iterdir()}
    return 0 if ".csv" in suffixes else 1 if ".xlsx" in suffixes else 2


def load_all(splits, work: Path):
    loaders = {s: BusinessLoader(ROOT / "dataset" / s, work / s) for s in splits}
    contexts = {}
    for split, loader in loaders.items():
        for business in sorted(p.name for p in (ROOT / "dataset" / split / "data").iterdir()):
            contexts[(split, business)] = loader.load(business)
    return contexts


def report_roles(contexts) -> None:
    print("== 1. Role mapping vs generator column maps ==")
    tables, columns = synth_names()
    if not tables:
        print("(skipped: synth writers not found)")
        return
    right = total = 0
    for (split, business), context in contexts.items():
        style = layout_style(ROOT / "dataset" / split / "data" / business)
        roles = context.canonical.roles if context.canonical else {}
        wrong = []
        for role, concepts in CONCEPT_TO_SYNTH.items():
            gold_table = tables[ROLE_TO_SYNTH[role]][style]
            present = gold_table in context.profile
            binding = roles.get(role)
            total += 1
            if (binding.table if binding else None) == (gold_table if present else None):
                right += 1
            else:
                wrong.append(f"{role}: got {binding.table if binding else None}, want {gold_table if present else None}")
                continue
            if not binding:
                continue
            existing = {c["name"] for c in context.profile[gold_table]["columns"]}
            for concept, synth_column in concepts.items():
                gold_column = columns[synth_column][style]
                total += 1
                got = binding.columns.get(concept)
                if got == (gold_column if gold_column in existing else None):
                    right += 1
                else:
                    wrong.append(f"{role}.{concept}: got {got}, want {gold_column if gold_column in existing else None}")
        caps = context.canonical.capabilities if context.canonical else {}
        print(f"{business}: {'OK' if not wrong else 'MISMATCH'}  complete={bool(context.canonical and context.canonical.complete)} "
              f"debts={caps.get('has_debts')} cost={caps.get('has_cost')} expiry={caps.get('has_expiry')}")
        for line in wrong:
            print("   ", line)
    print(f"role/column accuracy: {right}/{total} = {right / total:.1%}")


def run_question(context, record: dict):
    question = Question.model_validate(record)
    resolved = understand(question, context)
    linked = link(resolved, context)
    return linked, gate(linked)


def report_gate(contexts, splits) -> None:
    print("\n== 2. Rule gate on dataset questions ==")
    for split in splits:
        base = ROOT / "dataset" / split
        gold = {r["id"]: r for r in read_records(base / "answers.jsonl")} if (base / "answers.jsonl").exists() else {}
        blocked, tp, fp, fn, total = [], 0, 0, 0, 0
        for record in read_records(base / "questions.jsonl"):
            linked, decision = run_question(contexts[(split, record["business_id"])], record)
            total += 1
            is_blocked = not decision.allowed
            if gold:
                truth = gold[record["id"]]["type"] == "unanswerable"
                tp += is_blocked and truth
                fp += is_blocked and not truth
                fn += truth and not is_blocked
                if is_blocked != truth:
                    print(f"  {'FALSE BLOCK' if is_blocked else 'MISSED'} {record['id']}: {record['question']} "
                          f"-> {decision.reason or linked.flags}")
            if is_blocked:
                blocked.append((record["question"], decision.reason))
        if gold:
            precision = tp / (tp + fp) if tp + fp else 1.0
            recall = tp / (tp + fn) if tp + fn else 1.0
            print(f"{split}: {total} questions, blocked {tp + fp}, precision {precision:.1%}, recall {recall:.1%} "
                  f"(false blocks {fp}, missed {fn})")
        else:
            print(f"{split}: {total} questions, blocked {len(blocked)} (no gold; review below)")
            for text, reason in blocked:
                print(f"   - {text}  [{reason}]")


def report_entities(contexts, per_business: int, seeds: int) -> None:
    print("\n== 3. Entity linking on synthetic questions (in-sample noise) ==")
    synth = ROOT / "synth"
    sys.path.insert(0, str(synth))
    try:
        from src.noise import inject  # type: ignore
    except Exception as error:  # noqa: BLE001
        print(f"(skipped: synth noise module not importable: {type(error).__name__})")
        return
    finally:
        sys.path.remove(str(synth))
    dictionary = json.loads((synth / "data" / "teencode_dict.json").read_text(encoding="utf-8"))
    templates = {"product": "Hôm qua có bán được sản phẩm {} không?", "customer": "Khách {} hiện còn nợ cửa hàng bao nhiêu?"}
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    forms: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rng = random.Random(20261030)
    for (split, business), context in contexts.items():
        index = context.entities
        if index is None:
            continue
        for kind, template in templates.items():
            records = sorted((r for r in index.records if r.kind == kind), key=lambda r: r.id)
            for record in rng.sample(records, min(per_business, len(records))):
                labels = {"name": record.name, "id": record.id}
                if kind == "product" and record.aliases:
                    labels["alias"] = rng.choice(record.aliases)
                for form, label in labels.items():
                    for seed in range(seeds):
                        text, tags = inject(template.format(label), dictionary, random.Random(seed * 7919 + zlib.crc32(f"{record.id}/{form}".encode()) % 1000))
                        row = {"id": "x", "business_id": business, "question": text, "as_of_date": "2026-06-01"}
                        linked, _ = run_question(context, row)
                        hit = any(e.id == record.id and e.kind == kind for e in linked.entities)
                        for key in (tags or ["clean"]):
                            stats[key][0] += hit
                            stats[key][1] += 1
                        forms[f"{kind}/{form}"][0] += hit
                        forms[f"{kind}/{form}"][1] += 1
    for title, table in (("by noise type", stats), ("by entity form", forms)):
        print(f"top-1 accuracy {title}:")
        for key, (hit, total) in sorted(table.items()):
            print(f"  {key:<20} {hit:>5}/{total:<5} = {hit / total:6.1%}")
    unknown = ["Nước thần ZZZ 999ml", "Kem dưỡng da Hoàng Kim 50g", "Bánh quy Rồng Vàng 200g", "Sản phẩm Quantum X-900",
               "Trà ô long Atiso 1 lít", "Dầu gội Phượng Hoàng 650ml"]
    missing = total = 0
    for (split, business), context in contexts.items():
        for name in unknown:
            text, _ = inject(f"Sản phẩm {name} tuần rồi bán được mấy cái?", dictionary, random.Random(len(name)))
            linked, decision = run_question(context, {"id": "x", "business_id": business, "question": text,
                                                      "as_of_date": "2026-06-01"})
            missing += not decision.allowed
            total += 1
    print(f"non-existent products blocked as unanswerable: {missing}/{total} = {missing / total:.1%}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", nargs="+", default=["train", "dev"])
    parser.add_argument("--per-business", type=int, default=10)
    parser.add_argument("--seeds", type=int, default=3)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as work:
        contexts = load_all(args.splits, Path(work))
        report_roles(contexts)
        report_gate(contexts, args.splits)
        report_entities(contexts, args.per_business, args.seeds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
