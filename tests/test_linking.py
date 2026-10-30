"""Entity linking, schema linking, the rule gate and their wiring into prompt and pipeline."""
import json

import duckdb
import pytest

from business_fixture import VOUCHER_RULEBOOK, make_package
from datamate.codegen.prompt_builder import build_prompt
from datamate.core import Candidate, Question
from datamate.formatting.formatter import format_answer
from datamate.gate import EMPTY_PERIOD_REASON, ZERO_BASE_REASON, gate
from datamate.ingest.loader import BusinessLoader
from datamate.linking import link, link_to_log
from datamate.linking.entity_index import build_entity_index, entity_key
from datamate.linking.entity_linker import link_entities
from datamate.linking.schema_linker import expected_answer
from datamate.runtime.pipeline import Pipeline
from datamate.runtime.time_guard import TimeGuard
from datamate.understanding import understand
from datamate.core import ExecResult
from datamate.eval.scorer import matches


@pytest.fixture(scope="module")
def shop(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("shop")
    root = make_package(tmp / "package", "csv")
    return BusinessLoader(root, tmp / "work").load("shop")


def run(context, text, as_of="2026-05-06"):
    question = Question(id="q", business_id="shop", question=text, as_of_date=as_of)
    linked = link(understand(question, context), context)
    return linked, gate(linked)


def entity_ids(linked):
    return [(e.kind, e.id) for e in linked.entities]


def test_entity_index_gathers_names_aliases_and_categories(shop):
    index = shop.entities
    kinds = sorted((r.kind, r.id) for r in index.records)
    assert kinds == [("category", "Bánh"), ("category", "Đồ uống"), ("customer", "C1"), ("customer", "C2"),
                     ("product", "P1"), ("product", "P2"), ("product", "P3")]
    sting = next(r for r in index.records if r.id == "P1")
    assert sting.name == "Sting dâu 330ml" and "STING DÂU 330ML" in sting.aliases
    banh = next(r for r in index.records if r.id == "P2")
    assert "banh quy bo" in banh.aliases                      # trailing space cleaned, one entity not two
    assert index.exact[entity_key("STING DÂU 330ML")] == index.exact[entity_key("Sting dâu 330ml")]  # variants share one key
    assert "Sting dâu 330ml" in index.protected and "Nguyễn An" in index.protected
    assert shop.protected_values == index.protected
    assert entity_key("  Bánh  Quy-Bơ ") == "banh quy bo"


@pytest.mark.parametrize("text,expected", [
    ("Hôm qua có bán được sản phẩm Sting dâu 330ml không?", [("product", "P1")]),
    ("hom qua co ban duoc san pham STING DAU 330ML khong", [("product", "P1")]),          # no diacritics, caps
    ("Hôm qua có bán được sản phẩm P2 không?", [("product", "P2")]),                       # SKU
    ("Hôm qua có bán được sản phẩm banh quy bo không?", [("product", "P2")]),              # sale-line alias
    ("Hôm qua có bán được sản phẩm Sitng dâu 330ml không?", [("product", "P1")]),          # swapped letters
    ("Hôm qua có bán được sản phẩm Sting dâuu 330ml khônggg?", [("product", "P1")]),       # repeated letters
    ("Khách Nguyễn An hiện còn nợ cửa hàng bao nhiêu?", [("customer", "C1")]),
    ("khach nguyen an hien con no cua hang bao nhieu", [("customer", "C1")]),
    ("Khách C2 hiện còn nợ bao nhiêu?", [("customer", "C2")]),
    ("Khách Trần Bình hiện còn nợ cửa hàng bao nhiêu?", [("customer", "C2")]),
    ("Nhóm hàng Bánh bán thế nào tháng này?", [("category", "Bánh")]),
])
def test_existing_entities_are_linked(shop, text, expected):
    linked, decision = run(shop, text)
    assert entity_ids(linked) == expected, (text, linked.flags)
    assert decision.allowed and not linked.flags["missing_entity"]
    assert all(e.score >= 0.85 for e in linked.entities)


def test_entity_carries_in_data_values(shop):
    linked, _ = run(shop, "Hôm qua có bán được sản phẩm banh quy bo không?")
    entity = linked.entities[0]
    assert (entity.mention, entity.matched, entity.id, entity.match_type) == ("banh quy bo", "Bánh quy bơ", "P2", "exact")
    assert set(entity.aliases) >= {"Bánh quy bơ", "P2", "banh quy bo"}
    assert link_to_log(linked)["entities"][0]["matched"] == "Bánh quy bơ"
    json.dumps(link_to_log(linked))


@pytest.mark.parametrize("text", [
    "Hôm qua có bán được sản phẩm Nước thần ZZZ 999ml không?",
    "Sản phẩm Nước thần ZZZ 999ml tuần rồi bán được mấy cái?",
    "Hôm qua có bán được sản phẩm P9 không?",                    # unknown code
    "Hôm qua có bán được sản phẩm Sting dâu 500ml không?",       # right words, wrong size
    "Khách Lê Văn Zed hiện còn nợ cửa hàng bao nhiêu?",
])
def test_missing_entities_are_flagged_and_blocked(shop, text):
    linked, decision = run(shop, text)
    assert linked.flags["missing_entity"] and linked.flags["missing_mentions"], text
    assert not [e for e in linked.entities if e.score >= 0.85]
    assert not decision.allowed and "Không có" in decision.reason


@pytest.mark.parametrize("text", [
    "Sản phẩm nào bán chạy nhất tháng này?",
    "Khách hàng nào mua nhiều tiền nhất tháng trước?",
    "Mặt hàng nào bán nhiều nhất theo số lượng?",
    "Liệt kê hàng đang tồn kho dưới 15 đơn vị.",
    "Nhóm hàng nào đem lại doanh thu cao nhất tháng này?",
    "Sản phẩm tồn kho nhiều nhất là gì?",
    "Doanh thu tuần rồi tăng giảm bao nhiêu % so với tuần liền trước đó",
    "Sản phẩm nào còn tồn mà lô hàng sẽ hết hạn trong 30 ngày tới?",
    "Lập bảng các khách đang nợ tiền, kèm mã khách, tên và số tiền nợ.",
    "Hôm qua doanh thu bao nhiêu?",
])
def test_generic_questions_produce_no_entities_and_no_false_missing(shop, text):
    linked, decision = run(shop, text)
    assert linked.entities == [] and not linked.flags["missing_entity"], (text, linked.flags)
    # blocked only for a data reason, never a mention
    assert decision.allowed or "dữ liệu" in decision.reason or decision.reason in {EMPTY_PERIOD_REASON, ZERO_BASE_REASON}


def test_single_word_after_a_cue_must_match_the_cue_kind(shop):
    linked, decision = run(shop, "Hôm qua có bán được sản phẩm Bánh không?")
    assert [e for e in linked.entities if e.kind == "category"] == []  # "Bánh" is a category, not a product
    assert not linked.flags["missing_entity"]


def test_time_words_are_never_entities(shop):
    linked, _ = run(shop, "Tuần rồi bán được sản phẩm Sting dâu 330ml bao nhiêu?")
    assert entity_ids(linked) == [("product", "P1")] and linked.entities[0].mention == "Sting dâu 330ml"


def test_ambiguous_duplicates_pass_through_with_alternatives():
    connection = duckdb.connect()
    connection.execute("CREATE VIEW v_customers AS SELECT * FROM (VALUES ('C9', 'Nguyễn An'), ('C1', 'Nguyễn An'), "
                       "('C3', 'Lê Hoa')) t(customer_id, name)")
    index = build_entity_index(connection, ["v_customers"])
    cues = {"customer": ["khach"]}
    outcome = link_entities("Khách Nguyễn An hiện còn nợ", [], index, cues, frozenset({"hien", "con", "no"}), lambda k: True)
    assert [e.id for e in outcome.entities] == ["C1"]                       # tie broken by id, stable
    assert [a[1] for a in outcome.entities[0].alternatives] == ["C9"]
    assert outcome.ambiguous and not outcome.missing
    again = link_entities("Khách Nguyễn An hiện còn nợ", [], index, cues, frozenset({"hien", "con", "no"}), lambda k: True)
    assert again == outcome


def test_linking_is_deterministic(shop):
    texts = ["Hôm qua có bán được sản phẩm Sitng dâu 330ml không?", "Khách Nguyễnn An hiện còn nợ", "Doanh thu tháng này"]
    for text in texts:
        first, second = run(shop, text), run(shop, text)
        assert first[0].entities == second[0].entities and first[0].flags == second[0].flags


# ----------------------------------------------------------------------- schema linker and gate

@pytest.mark.parametrize("text,missing", [
    ("Nhân viên ca tối nào mang về doanh thu nhiều nhất tháng trước?", ["employee"]),
    ("Chi phí điện nước riêng của cửa hàng trong tháng trước là bao nhiêu?", ["utilities"]),
    ("Lợi nhuận gộp tháng trước dựa trên giá vốn bình quân nhập lô là bao nhiêu?", ["cost"]),
    ("Sản phẩm nào còn tồn mà lô hàng sẽ hết hạn trong 30 ngày tới?", ["expiry"]),
])
def test_missing_capabilities_block_with_a_reason(shop, text, missing):
    linked, decision = run(shop, text)
    assert linked.flags["missing_capability"] == missing and not decision.allowed
    assert decision.reason.startswith("Không có")


def test_debts_depend_on_the_data(tmp_path):
    with_debts = BusinessLoader(make_package(tmp_path / "a", "csv"), tmp_path / "wa").load("shop")
    without = BusinessLoader(make_package(tmp_path / "b", "csv", include_debts=False), tmp_path / "wb").load("shop")
    text = "Khách Trần Bình hiện còn nợ cửa hàng bao nhiêu?"
    assert run(with_debts, text)[1].allowed
    linked, decision = run(without, text)
    assert linked.flags["missing_capability"] == ["debt"] and not decision.allowed


def test_period_outside_the_data_range_is_flagged(shop):
    linked, decision = run(shop, "Doanh thu trong tháng 01/2023 là bao nhiêu?")
    assert linked.flags["period_outside_data"] == ["explicit_month"] and not decision.allowed
    assert decision.reason == "Khoảng thời gian được hỏi nằm ngoài dữ liệu của cơ sở."
    inside, allowed = run(shop, "Doanh thu tháng này là bao nhiêu?")
    assert inside.flags["period_outside_data"] == [] and allowed.allowed
    expiry, _ = run(shop, "Sản phẩm nào hết hạn trong 30 ngày tới?")
    assert expiry.flags["period_outside_data"] == []     # expiry uses another date column


@pytest.mark.parametrize("text,reason", [
    ("Doanh thu tháng này tăng trưởng bao nhiêu phần trăm so với tháng trước?", ZERO_BASE_REASON),   # April has no sales
    ("Mặt hàng nào bán chạy nhất ngày 03/05/2026?", EMPTY_PERIOD_REASON),   # inside the range, but only a cancelled order
    ("Giá trị đơn hàng trung bình ngày 03/05/2026 là bao nhiêu?", EMPTY_PERIOD_REASON),
    ("Mặt hàng nào bán chạy nhất ngày 04/05/2026?", EMPTY_PERIOD_REASON),   # the only order has a returned line
])
def test_empty_periods_block_questions_that_are_undefined_on_them(shop, text, reason):
    linked, decision = run(shop, text)
    assert linked.flags["period_outside_data"] == [] and linked.flags["period_stats"]
    assert not decision.allowed and decision.reason == reason


@pytest.mark.parametrize("text", [
    "Doanh thu ngày 5/5 tăng trưởng bao nhiêu phần trăm so với ngày 2/5?",   # both periods have sales
    "Mặt hàng nào bán chạy nhất ngày 05/05/2026?",
    "Cho mình top 3 sản phẩm bán nhiều nhất ngày 03/05/2026",    # topN on an empty period is []
    "Doanh thu ngày 03/05/2026 là bao nhiêu?",                    # a sum on an empty period is 0
    "Ngày 03/05/2026 có bao nhiêu đơn hàng?",
])
def test_empty_period_does_not_block_questions_that_have_a_defined_result(shop, text):
    assert run(shop, text)[1].allowed, text


def test_period_stats_count_valid_sales_only(shop):
    linked, _ = run(shop, "Doanh thu ngày 5/5 tăng trưởng bao nhiêu phần trăm so với ngày 03/05/2026?")
    by_label = {(s["role"], s["rows"] > 0) for s in linked.flags["period_stats"]}
    assert by_label == {("primary", True), ("comparison", False)}     # a cancelled order is not a sale


def test_period_stats_are_unknown_not_empty_without_the_canonical_layer(tmp_path):
    root = tmp_path / "package"
    directory = root / "data" / "shop"
    directory.mkdir(parents=True)
    (root / "rulebook.md").write_text("x", encoding="utf-8")
    (directory / "export.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")
    context = BusinessLoader(root, tmp_path / "work").load("shop")
    linked, decision = run(context, "Mặt hàng nào bán chạy nhất tháng này?")
    assert linked.flags["period_stats"] is None and decision.allowed


def test_unknown_business_is_never_blocked_on_capabilities(tmp_path):
    root = tmp_path / "package"
    directory = root / "data" / "shop"
    directory.mkdir(parents=True)
    (root / "rulebook.md").write_text("x", encoding="utf-8")
    (directory / "export.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")
    context = BusinessLoader(root, tmp_path / "work").load("shop")
    linked, decision = run(context, "Nhân viên nào bán nhiều nhất? Chi phí điện nước? Lợi nhuận tháng trước?")
    assert decision.allowed and linked.flags["missing_capability"] == [] and linked.schema["canonical"] is False


@pytest.mark.parametrize("text,expected", [
    ("Doanh thu tháng này tăng trưởng bao nhiêu phần trăm so với tháng trước?", {"type": "percent", "force_type": True}),
    ("Cho mình danh sách top 3 sản phẩm bán nhiều nhất tháng trước", {"type": "list", "force_type": True}),
    ("Liệt kê hàng đang tồn kho dưới 15 đơn vị", {"type": "list", "force_type": True}),
    ("Lập bảng các khách đang nợ tiền", {"type": "table", "force_type": True}),
    ("Hôm qua có bán được sản phẩm P1 không?", {"type": "boolean"}),
    ("Trong tháng trước, ngày nào có doanh thu cao nhất?", {"type": "date"}),
    ("Mặt hàng nào bán chạy nhất tháng này theo số lượng?", {"type": "string"}),
    ("Tháng trước có bao nhiêu đơn hàng bị hủy?", {"type": "number", "unit": "count"}),
    ("Giá trị đơn hàng trung bình tháng này là bao nhiêu?", {"type": "number"}),
    ("Doanh thu tuần rồi là bao nhiêu?", {"type": "number", "unit": "VND"}),
    ("Tổng số lượng sản phẩm bán ra tháng trước là bao nhiêu?", {"type": "number", "unit": "count"}),
])
def test_expected_answer(shop, text, expected):
    resolved = understand(Question(id="q", business_id="shop", question=text, as_of_date="2026-05-10"), shop)
    assert expected_answer(resolved.intent_hints, resolved.normalized_ascii) == expected, text


# ----------------------------------------------------------------------- prompt, formatter, pipeline

class SqlBackend:
    def __init__(self, sql):
        self.sql, self.prompts = sql, []

    def generate(self, prompt, linked):
        self.prompts.append(prompt)
        return Candidate(self.sql)


def answer(tmp_path, rulebook_text, question_text, sql, as_of="2026-05-10"):
    root = make_package(tmp_path / "package", "csv", rulebook=rulebook_text)
    backend = SqlBackend(sql)
    pipeline = Pipeline(BusinessLoader(root, tmp_path / "work"), backend, TimeGuard())
    record = {"id": "t", "business_id": "shop", "question": question_text, "as_of_date": as_of}
    return (*pipeline.answer(record), backend)


def test_pipeline_uses_canonical_prompt_and_rounds_money(tmp_path):
    sql = "SELECT sum(revenue) FROM v_sales WHERE sale_date BETWEEN DATE '2026-05-01' AND DATE '2026-05-10'"
    result, log, backend = answer(tmp_path, VOUCHER_RULEBOOK, "Doanh thu thang nay la bn?", sql)
    assert result.to_dict() == {"id": "t", "type": "number", "answer": 95000} and log["error"] is None
    assert log["linking"]["schema"]["expected"] == {"type": "number", "unit": "VND"}
    prompt = backend.prompts[0]
    assert "Query only the v_* views" in prompt and "as_of_date" in prompt and "rulebook" in prompt
    payload = json.loads(prompt.split("\n", 3)[3])
    assert "v_sales" in payload["schema"]["views"] and payload["schema"]["capabilities"]["has_debts"] is True
    assert payload["expected_answer"] == {"type": "number", "unit": "VND"} and payload["linked_entities"] == []
    assert payload["periods"][0]["label"] == "this_month"
    assert payload["schema"]["rules"]["revenue_subtract_order_voucher"] is True


def test_pipeline_passes_linked_entities_to_the_prompt(tmp_path):
    result, log, backend = answer(tmp_path, VOUCHER_RULEBOOK, "Hôm qua co ban duoc san pham banh quy bo khong?",
                                  "SELECT count(*) > 0 FROM v_sales WHERE sku = 'P2'", as_of="2026-05-06")
    payload = json.loads(backend.prompts[0].split("\n", 3)[3])
    assert payload["linked_entities"][0]["id"] == "P2" and payload["linked_entities"][0]["name"] == "Bánh quy bơ"
    assert result.type == "boolean" and result.answer is True


def test_pipeline_blocks_before_calling_the_model(tmp_path):
    result, log, backend = answer(tmp_path, VOUCHER_RULEBOOK, "Nhân viên ca tối nào bán nhiều nhất tháng trước?", "SELECT 1")
    assert result.to_dict() == {"id": "t", "type": "unanswerable", "reason": "Không có trường nhân viên hoặc ca làm việc trong dữ liệu của cơ sở."}
    assert backend.prompts == [] and log["linking"]["flags"]["missing_capability"] == ["employee"]


def test_percent_and_list_types_are_forced_from_the_question(tmp_path):
    result, _, _ = answer(tmp_path, VOUCHER_RULEBOOK,
                          "Doanh thu ngày 5/5 tăng trưởng bao nhiêu phần trăm so với ngày 2/5?", "SELECT 12.345")
    assert result.to_dict() == {"id": "t", "type": "percent", "answer": 12.35}
    result, _, _ = answer(tmp_path / "2", VOUCHER_RULEBOOK, "Liệt kê ba mặt hàng doanh thu cao nhất trong tháng này.",
                          "SELECT 'Bánh quy bơ'")
    assert result.to_dict() == {"id": "t", "type": "list", "answer": ["Bánh quy bơ"]}  # one row stays a list


def test_sum_over_an_empty_period_is_zero_for_money_and_counts():
    q = Question(id="q", business_id="b", question="x", as_of_date="2026-05-10")
    for unit in ("VND", "count"):
        empty = ExecResult(Candidate("SELECT sum(x)", unit=unit), ["s"], [[None]])
        assert format_answer(q, empty).to_dict() == {"id": "q", "type": "number", "answer": 0}
    with pytest.raises(ValueError):
        format_answer(q, ExecResult(Candidate("SELECT NULL"), ["s"], [[None]]))  # no unit: still an error


def test_scorer_reads_the_gold_alias_key():
    gold = {"id": "q", "type": "string", "answer": "Sting dâu 330ml", "alias": ["P0001", "STING DÂU 330ML"]}
    assert matches({"id": "q", "type": "string", "answer": "P0001"}, gold)
    assert matches({"id": "q", "type": "string", "answer": "sting dau 330ml".replace("dau", "dâu")}, gold)
    assert not matches({"id": "q", "type": "string", "answer": "Other"}, gold)
    assert matches({"id": "q", "type": "string", "answer": "X"}, {"id": "q", "type": "string", "answer": "x", "aliases": ["Y"]})


def test_prompt_without_canonical_layer_keeps_the_raw_schema(tmp_path):
    root = tmp_path / "package"
    directory = root / "data" / "shop"
    directory.mkdir(parents=True)
    (root / "rulebook.md").write_text("x", encoding="utf-8")
    (directory / "export.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")
    context = BusinessLoader(root, tmp_path / "work").load("shop")
    linked, _ = run(context, "tổng foo")
    prompt = build_prompt(linked)
    assert "Query only the v_* views" not in prompt and '"foo"' in prompt
