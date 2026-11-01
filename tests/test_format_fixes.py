"""Answer-shape rules found from the first real-LLM run: ranked lists, 'which customer', weekday names."""
from datetime import date
from pathlib import Path

import pytest

from datamate.core import Candidate, ExecResult, Question
from datamate.formatting.formatter import format_answer
from datamate.ingest.loader import BusinessLoader
from datamate.linking.schema_linker import expected_answer
from datamate.understanding.intent import intent_hints
from datamate.understanding.resources import load_rule_defaults
from datamate.understanding.textutil import fold

QUESTION = Question(id="q", business_id="b", question="x", as_of_date=date(2026, 1, 1))


def result(columns, rows, **candidate):
    return ExecResult(Candidate("SELECT 1", **candidate), columns, rows)


def test_ranked_list_keeps_first_column_and_order():
    answer = format_answer(QUESTION, result(["name", "qty"], [["B", 9], ["A", 9], ["C", 1]], answer_type="list"))
    assert (answer.type, answer.answer) == ("list", ["B", "A", "C"])


def test_single_entity_with_measure_column_is_a_string_only_when_a_string_was_expected():
    wide = dict(columns=["customer_name", "total"], rows=[["Lan", 5]])
    expected = format_answer(QUESTION, result(**wide, meta={"expected_type": "string"}))
    assert (expected.type, expected.answer) == ("string", "Lan")
    assert format_answer(QUESTION, result(**wide)).type == "table"  # no hint: unchanged behaviour
    several = format_answer(QUESTION, result(["n", "t"], [["a", 1], ["b", 2]], meta={"expected_type": "string"}))
    assert several.type == "table"  # several rows are ambiguous: never pick one


def test_scalar_number_is_not_turned_into_string():
    answer = format_answer(QUESTION, result(["revenue"], [[10.5]], meta={"expected_type": "string"}))
    assert (answer.type, answer.answer) == ("number", 10.5)


def hints(text):
    return intent_hints(fold(text), load_rule_defaults()["intent_keywords"])


@pytest.mark.parametrize("text,operation", [
    ("Khách hàng nào mua nhiều tiền nhất tháng trước?", "top1"),
    ("Tháng trước thứ mấy có nhiều đơn hàng hợp lệ nhất?", "top1"),
    ("Mặt hàng nào bán chạy nhất tháng này?", "top1"),
    ("Sản phẩm nào bán ít nhất tháng trước?", "bottom1"),
    ("Trong tháng trước, ngày nào có doanh thu cao nhất?", "date_of_max"),  # still wins over top1
])
def test_ranking_phrases_with_words_between(text, operation):
    assert hints(text)["operation"] == operation


def test_expected_answer_for_weekday_and_customer_questions():
    for text in ("Tháng trước thứ mấy có nhiều đơn hàng hợp lệ nhất?", "Khách hàng nào mua nhiều tiền nhất?"):
        ascii_text = fold(text)
        assert expected_answer(hints(text), ascii_text) == {"type": "string"}
    assert expected_answer({"operation": "none", "metric": "none"}, "thu may la ngay dep") == {"type": "string"}


DATASET = Path("dataset")


@pytest.mark.skipif(not (DATASET / "train" / "questions.jsonl").exists(), reason="dataset not present")
def test_weekday_column_in_views_uses_vietnamese_names(tmp_path):
    loader = BusinessLoader(DATASET / "train", tmp_path)
    context = loader.load("train_01")
    import duckdb
    with duckdb.connect(str(context.database), read_only=True) as connection:
        rows = connection.execute("SELECT order_date, weekday_vi FROM v_valid_orders LIMIT 50").fetchall()
        sales = connection.execute("SELECT DISTINCT sale_date, weekday_vi FROM v_sales LIMIT 50").fetchall()
    names = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"]
    assert rows and sales
    for day, name in rows + sales:
        assert name == names[day.weekday()]
