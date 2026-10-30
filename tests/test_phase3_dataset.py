"""Regression on the real train/dev packages: capabilities, the rule gate, and canonical-view answers.

No question ids or business ids are used by the source code; they appear here only to describe data facts.
"""
from pathlib import Path

import pytest

from datamate.codegen.generator import apply_expected
from datamate.core import Candidate, Question
from datamate.eval.scorer import matches
from datamate.execution.sandbox import execute
from datamate.formatting.formatter import format_answer
from datamate.gate import gate
from datamate.ingest.loader import BusinessLoader
from datamate.io.question_reader import read_records
from datamate.linking import link
from datamate.understanding import understand

DATASET = Path("dataset")
pytestmark = pytest.mark.skipif(not (DATASET / "train" / "questions.jsonl").exists(), reason="dataset not present")


@pytest.fixture(scope="module")
def loaders(tmp_path_factory):
    work = tmp_path_factory.mktemp("work")
    return {split: BusinessLoader(DATASET / split, work / split) for split in ("train", "dev")}


def process(loader, record):
    context = loader.load(record["business_id"])
    question = Question.model_validate(record)
    resolved = understand(question, context)
    linked = link(resolved, context)
    return question, context, resolved, linked, gate(linked)


def test_capabilities_match_what_each_business_documents(loaders):
    expected = {  # facts from each README: missing debt tracking, cost fields, expiry dates
        ("train", "train_02"): dict(has_debts=False, has_cost=True), ("train", "train_03"): dict(has_debts=False),
        ("train", "train_04"): dict(has_debts=True, has_cost=False, has_expiry=False),
        ("train", "train_05"): dict(has_debts=True, has_expiry=False), ("train", "train_08"): dict(has_debts=False),
        ("dev", "dev_01"): dict(has_debts=False, has_cost=False), ("dev", "dev_02"): dict(has_debts=True, has_expiry=False),
    }
    for (split, business), caps in expected.items():
        canonical = loaders[split].load(business).canonical
        assert canonical.complete, (business, canonical.warnings)
        for key, value in caps.items():
            assert canonical.capabilities[key] is value, (business, key)
    for split in ("train", "dev"):
        for business in sorted(p.name for p in (DATASET / split / "data").iterdir()):
            context = loaders[split].load(business)
            assert context.canonical.complete and context.entities is not None and context.warnings == []


def test_gate_blocks_exactly_the_unanswerable_train_questions(loaders):
    gold = {r["id"]: r for r in read_records(DATASET / "train" / "answers.jsonl")}
    blocked, expected = set(), set()
    for record in read_records(DATASET / "train" / "questions.jsonl"):
        decision = process(loaders["train"], record)[4]
        if not decision.allowed:
            blocked.add(record["id"])
        if gold[record["id"]]["type"] == "unanswerable":
            expected.add(record["id"])
    assert expected and blocked == expected, (sorted(blocked - expected), sorted(expected - blocked))


def test_gate_blocks_every_dev_probe_and_nothing_else(loaders):
    blocked = []
    for record in read_records(DATASET / "dev" / "questions.jsonl"):
        decision = process(loaders["dev"], record)[4]
        if not decision.allowed:
            blocked.append(record["question"])
    # three dev businesses x four probes: unknown product, no employee, month outside history, no cost / no utilities
    assert len(blocked) == 12, blocked
    assert all(any(w in q.lower() for w in ("zzz", "nhân vi", "nhan vi", "01/2023", "lợi nhuận", "chi phí", "tinh theo", "điện"))
               for q in blocked), blocked


def test_canonical_views_reproduce_gold_for_revenue_and_valid_order_counts(loaders):
    gold = {r["id"]: r for r in read_records(DATASET / "train" / "answers.jsonl")}
    checked = {"revenue": 0, "orders": 0}
    for record in read_records(DATASET / "train" / "questions.jsonl"):
        question, context, resolved, linked, decision = process(loaders["train"], record)
        if not decision.allowed or len(resolved.periods) != 1:
            continue
        period, hints = resolved.periods[0], resolved.intent_hints
        where = f"BETWEEN DATE '{period.start}' AND DATE '{period.end}'"
        if hints["metric"] == "revenue" and hints["operation"] in ("none", "sum"):
            sql, kind = f"SELECT sum(revenue) FROM v_sales WHERE sale_date {where}", "revenue"
        elif "hop le" in resolved.normalized_ascii and hints["operation"] == "count":
            sql, kind = f"SELECT count(*) FROM v_valid_orders WHERE order_date {where}", "orders"
        else:
            continue
        result = execute(context, apply_expected(Candidate(sql), linked))
        assert result.error is None, (record["id"], result.error)
        answer = format_answer(question, result).to_dict()
        assert matches(answer, gold[record["id"]]), (record["id"], record["question"], answer, gold[record["id"]])
        checked[kind] += 1
    assert checked["revenue"] >= 40 and checked["orders"] >= 10, checked
