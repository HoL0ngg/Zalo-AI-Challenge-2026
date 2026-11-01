"""Comparison periods, percent kinds and the two-layer SQL repair (found with the official train data)."""
from datetime import date
from pathlib import Path

import pytest

from datamate.codegen.prompt_builder import percent_shape
from datamate.core import Candidate, ExecResult, Question
from datamate.execution.repair import diagnose, quick_fix, repair, repair_prompt
from datamate.ingest.loader import BusinessLoader
from datamate.io.question_reader import read_records
from datamate.runtime.pipeline import Pipeline
from datamate.runtime.time_guard import TimeGuard
from datamate.understanding import understand
from datamate.understanding.intent import intent_hints
from datamate.understanding.resources import load_rule_defaults
from datamate.understanding.textutil import fold
from test_understanding import context as make_context

SAMPLE = Path("data/samples")
SAME_DAYS_RULEBOOK = "| Tháng này | từ ngày 1 đến hết hôm nay. So với tháng trước thì lấy **cùng số ngày** của tháng trước |"


def periods(text, as_of, rulebook=""):
    resolved = understand(Question(id="q", business_id="b", question=text, as_of_date=as_of),
                          make_context(rulebook=rulebook))
    return [(p.role, p.start, p.end) for p in resolved.periods]


@pytest.mark.parametrize("text", [
    "doanh thu thang 3/2025 tang bao nhieu % so voi thang lien truoc",
    "doanh thu thang 3/2025 tang hay giam bao nhieu % so vs th truoc",
    "so vs th truoc do, doanh thu thang 3/2025 tang hay giam may %",   # comparison phrase before the primary
])
def test_comparison_is_the_month_before_the_primary_not_before_today(text):
    got = periods(text, "2026-09-14")
    assert sorted(got) == sorted([("primary", date(2025, 3, 1), date(2025, 3, 31)),
                                  ("comparison", date(2025, 2, 1), date(2025, 2, 28))])


def test_this_month_comparison_follows_the_rulebook():
    text = "thang nay so voi thang truoc doanh thu tang bao nhieu %"
    assert periods(text, "2026-07-17")[1] == ("comparison", date(2026, 6, 1), date(2026, 6, 30))  # default: full month
    assert periods(text, "2026-07-17", SAME_DAYS_RULEBOOK)[1] == ("comparison", date(2026, 6, 1), date(2026, 6, 17))
    # capped at the last day of a shorter previous month
    assert periods(text, "2026-03-31", SAME_DAYS_RULEBOOK)[1] == ("comparison", date(2026, 2, 1), date(2026, 2, 28))


def test_open_week_keeps_the_full_previous_week():
    got = periods("tuan nay so voi tuan truoc", "2026-07-17", SAME_DAYS_RULEBOOK)
    assert got == [("primary", date(2026, 7, 13), date(2026, 7, 17)),
                   ("comparison", date(2026, 7, 6), date(2026, 7, 12))]


def test_price_change_windows():
    text = ("pin aa doi gia tu 22.000d len 23.000d vao ngay 02/06/2026. 30 ngay ke tu ngay do ban duoc nhieu hay it hon "
            "30 ngay lien truoc bao nhieu %")
    assert periods(text, "2026-08-05") == [("primary", date(2026, 6, 2), date(2026, 7, 1)),
                                           ("comparison", date(2026, 5, 3), date(2026, 6, 1))]


def kind(text):
    return intent_hints(fold(text), load_rule_defaults()["intent_keywords"]).get("percent_kind")


@pytest.mark.parametrize("text,expected", [
    ("doanh thu thang 3/2025 tang hay giam bao nhieu % so vs th truoc", "growth"),
    ("thang 9/2025 cua hang co bnhiu % don bi huy", "rate"),
    ("ti le don huy thang 6/2025 la nhieu %", "rate"),
    ("nhom xi mang chiem bao nhieu % doanh thu thang 8/2025", "share"),
    ("trong so khach da mua hang thang 5/2026, bn phan tram mua tu 4 don tro len", "proportion"),
    ("pin aa doi gia tu 22.000d len 23.000d vao ngay 02/06/2026, so 7 ngay ke tu ngay do voi 7 ngay truoc, bao nhieu %",
     "price_effect"),
    ("thang 2/2026 ca chieu so voi ca sang thi so don chenh bao nhieu %", "shift_compare"),
])
def test_percent_kind(text, expected):
    assert kind(text) == expected


def test_non_percent_questions_have_no_percent_kind():
    assert "percent_kind" not in intent_hints(fold("doanh thu thang 3/2025 la bao nhieu"),
                                              load_rule_defaults()["intent_keywords"])


def test_percent_shape_fills_the_resolved_dates():
    text = percent_shape({"percent_kind": "growth"}, [
        {"role": "primary", "start": "2025-03-01", "end": "2025-03-31"},
        {"role": "comparison", "start": "2025-02-01", "end": "2025-02-28"}])
    assert "DATE '2025-03-01' AND DATE '2025-03-31'" in text and "DATE '2025-02-01' AND DATE '2025-02-28'" in text
    assert percent_shape({}, []) is None and percent_shape({"percent_kind": "unknown"}, []) is None


def failed(code, error):
    return ExecResult(Candidate(code, "percent", None, {"raw_output": "x"}), error=error)


NO_FROM = ("SELECT 100.0 * (SUM(CASE WHEN v_sales.sale_date BETWEEN DATE '2026-05-01' AND DATE '2026-05-11' THEN "
           "v_sales.revenue ELSE 0 END) - 1) / 2 AS growth")
MISSING = 'Binder Error: Referenced table "v_sales" not found!'


def test_quick_fix_adds_the_missing_from():
    fixed = quick_fix(failed(NO_FROM, MISSING))
    assert fixed is not None and "FROM v_sales" in fixed.code and fixed.answer_type == "percent"
    assert fixed.meta["repair"] == "deterministic:missing_from"
    import duckdb
    connection = duckdb.connect()
    connection.execute("CREATE TABLE v_sales AS SELECT DATE '2026-05-02' AS sale_date, 10 AS revenue")
    assert connection.execute(fixed.code).fetchone() is not None


@pytest.mark.parametrize("code,error", [
    ("SELECT sum(a.x) + sum(b.y) AS t", 'Binder Error: Referenced table "a" not found!'),   # two tables: ambiguous
    ("SELECT sum(v_sales.x) FROM v_orders", MISSING),                                      # has FROM: not our case
    (NO_FROM, 'Binder Error: Referenced column "z" not found in FROM clause!'),             # other error class
    ("not sql at all", MISSING),
])
def test_quick_fix_declines_what_it_cannot_prove(code, error):
    assert quick_fix(failed(code, error)) is None


def test_diagnose_names_the_error_class_and_nearest_columns():
    columns = {"v_sales": ["sale_date", "revenue", "qty"], "v_orders": ["order_id", "order_date"]}
    assert "not in any FROM" in " ".join(diagnose(MISSING, NO_FROM, columns))
    hint = " ".join(diagnose('Binder Error: Referenced column "order_date" not found in FROM clause!', "", columns))
    assert "v_orders.order_date" in hint
    assert "alias" in " ".join(diagnose('Ambiguous reference to column name "customer_id" (use: "a.customer_id")',
                                        "", columns))
    assert "TRY_CAST" in " ".join(diagnose("Conversion Error: Could not convert string 'x'", "", columns))
    assert diagnose("something unknown", "", columns) == []


class Linked:
    """The few attributes repair reads: no canonical layer, a raw profile."""

    def __init__(self):
        self.schema = {}
        self.resolved = type("R", (), {
            "question": Question(id="q", business_id="b", question="x", as_of_date="2026-01-01"),
            "periods": [], "intent_hints": {}, "normalized": "x", "normalized_ascii": "x"})()
        self.context = type("C", (), {"canonical": None, "readme": "", "rulebook": "",
                                      "profile": {"sales": {"columns": [{"name": "amount"}, {"name": "qty"}]}}})()
        self.entities = []


def test_repair_prompt_carries_error_diagnosis_columns_and_history():
    first = failed("SELECT sales.amnt FROM sales", 'Binder Error: Referenced column "amnt" not found in FROM clause!')
    second = failed("SELECT amount2 FROM sales", 'Binder Error: Referenced column "amount2" not found in FROM clause!')
    prompt = repair_prompt(Linked(), second, [first, second])
    assert "Repair this SQL" in prompt and "amount2" in prompt and "sales.amount" in prompt
    assert "sales(amount, qty)" in prompt and "Earlier attempts" in prompt and "amnt" in prompt
    assert prompt.rstrip().endswith("<sql></sql> tags.")


def test_repair_asks_again_when_the_model_repeats_a_failed_statement():
    calls = []

    class Backend:
        def generate(self, prompt, linked):
            calls.append(prompt)
            return Candidate("SELECT 1" if len(calls) == 1 else "SELECT 2")

    fixed = repair(Linked(), failed("SELECT 1", "Binder Error: x"), Backend())
    assert fixed.code == "SELECT 2" and len(calls) == 2 and "repeated a failed statement" in calls[1]
    assert fixed.meta["repair"] == "llm"


def test_pipeline_uses_the_free_fix_before_calling_the_model(tmp_path):
    prompts = []

    class Backend:
        def generate(self, prompt, linked):
            prompts.append(prompt)
            return Candidate("SELECT sum(sales.amount) AS total")  # no FROM

    pipeline = Pipeline(BusinessLoader(SAMPLE, tmp_path), Backend(), TimeGuard(), repair_attempts=1)
    record = next(read_records(SAMPLE / "questions.jsonl"))
    answer, log = pipeline.answer(record)
    assert answer.type == "number" and len(prompts) == 1       # the model was asked only once
    assert [a.get("error") is None for a in log["attempts"]] == [False, True]
    assert log["attempts"][1]["candidate"]["meta"]["repair"] == "deterministic:missing_from"


def test_pipeline_repair_rounds_are_capped():
    class Backend:
        def generate(self, prompt, linked):
            return Candidate("SELECT 1")

    assert Pipeline(None, Backend(), TimeGuard(), repair_attempts=99).repair_attempts == 3
    assert Pipeline(None, Backend(), TimeGuard(), repair_attempts=-1).repair_attempts == 0
