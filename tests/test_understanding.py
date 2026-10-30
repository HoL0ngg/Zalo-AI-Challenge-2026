"""Tests for the understand() stage: determinism, fallback, intent hints, pipeline wiring."""
import ast
import json
from datetime import date
from pathlib import Path

import pytest

import datamate.understanding as understanding
from datamate.core import BusinessContext, Candidate, Question, ResolvedQuestion
from datamate.ingest.loader import BusinessLoader
from datamate.io.question_reader import read_records
from datamate.runtime.pipeline import Pipeline
from datamate.runtime.runner import run
from datamate.runtime.time_guard import TimeGuard
from datamate.understanding import protected_from_profile, understand, understand_stub
from datamate.understanding.intent import intent_hints
from datamate.understanding.resources import load_rule_defaults

SAMPLE = Path("data/samples")
RULEBOOK = '```json\n{"month_to_as_of": true, "week_start": "monday", "tet_lunar_start": "12-23", "tet_lunar_end": "01-10"}\n```'


def context(rulebook=RULEBOOK, calendar=None, profile=None):
    return BusinessContext(database=Path("unused.duckdb"), profile=profile or {}, readme="", rulebook=rulebook,
                           calendar=calendar if calendar is not None else [])


def question(text, as_of="2026-05-14"):
    return Question(id="q", business_id="b", question=text, as_of_date=as_of)


def test_understand_end_to_end_fields():
    resolved = understand(question("Thang nay doanh thu tăng trưởng bn % so voi thang truoc?"), context())
    assert resolved.question.question == "Thang nay doanh thu tăng trưởng bn % so voi thang truoc?"  # untouched
    assert resolved.normalized == "tháng này doanh thu tăng trưởng bao nhiêu phần trăm so với tháng trước?"
    assert resolved.normalized_ascii == "thang nay doanh thu tang truong bao nhieu phan tram so voi thang truoc?"
    assert [(p.label, p.role, p.start, p.end) for p in resolved.periods] == [
        ("this_month", "primary", date(2026, 5, 1), date(2026, 5, 14)),
        ("last_month", "comparison", date(2026, 4, 1), date(2026, 4, 30))]
    assert resolved.intent_hints["metric"] == "revenue"
    assert resolved.intent_hints["operation"] == "compare_percent"
    assert resolved.rule_params["week_start"] == "monday"
    assert resolved.rule_params["rule_sources"]["week_start"] == "rulebook"
    assert resolved.rule_params["rule_sources"]["this_week_mode"] == "default"
    assert resolved.warnings == []


def test_resolved_question_defaults_keep_old_call_sites_working():
    q = question("x")
    resolved = ResolvedQuestion(q)
    assert resolved.question is q and resolved.periods == [] and resolved.warnings == []
    assert resolved.normalized == "" and resolved.intent_hints == {} and resolved.rule_params == {}
    assert understand_stub(q, context()).normalized == "x"  # alias still works


def test_rulebook_of_the_split_wins():
    sunday = RULEBOOK.replace("monday", "sunday")
    monday_period = understand(question("tuần rồi", "2026-03-15"), context()).periods[0]
    sunday_period = understand(question("tuần rồi", "2026-03-15"), context(sunday)).periods[0]
    assert (monday_period.start, sunday_period.start) == (date(2026, 3, 2), date(2026, 3, 8))


def test_deterministic_across_runs():
    texts = ["THANG nay chot duoc bao nhieu don hop le?", "Cung kỳ nam ngoai san pham nao ban nhieu nhat",
             "Trong dịp Tết gần nhất, sản phẩm nào bán chạy nhất?", "30 ngay qua ban duoc bn, ko co gi"]
    for text in texts:
        results = [understand(question(text), context()) for _ in range(3)]
        assert results[0] == results[1] == results[2]
    dataset = Path("dataset/train/questions.jsonl")
    if dataset.exists():
        for line in dataset.read_text(encoding="utf-8").splitlines()[:60]:
            record = json.loads(line)
            q = Question.model_validate(record)
            assert understand(q, context()) == understand(q, context())


def test_failures_fall_back_without_crashing(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(understanding, "normalize", boom)
    resolved = understand(question("  Tháng này   doanh thu "), context())
    assert resolved.normalized == "Tháng này doanh thu"  # cleaned pass-through
    assert resolved.periods and resolved.periods[0].label == "this_month"  # temporal still works
    assert any(w.startswith("understanding_error:normalizer:RuntimeError") for w in resolved.warnings)
    monkeypatch.undo()

    monkeypatch.setattr(understanding, "resolve_periods", boom)
    resolved = understand(question("tháng này"), context())
    assert resolved.periods == [] and resolved.normalized == "tháng này"
    assert any(w.startswith("understanding_error:temporal:RuntimeError") for w in resolved.warnings)
    monkeypatch.undo()

    monkeypatch.setattr(understanding, "parse_rule_params", boom)
    resolved = understand(question("tháng này"), context())
    assert resolved.periods == [] and resolved.normalized == "tháng này"
    assert any(w.startswith("understanding_error:rule_params") for w in resolved.warnings)
    monkeypatch.undo()

    monkeypatch.setattr(understanding, "intent_hints", boom)
    assert understand(question("tháng này"), context()).intent_hints == {}


def test_missing_resources_degrade_with_warnings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAMATE_ROOT", str(tmp_path))
    understanding.resources._json.cache_clear()
    understanding.resources._lines.cache_clear()
    understanding.resources._rule_defaults.cache_clear()
    try:
        resolved = understand(question("Thang nay bn"), context())
        assert {"lexicon_missing", "teencode_dict_missing"} <= set(resolved.warnings)
        assert resolved.periods and resolved.periods[0].label == "this_month"  # builtin defaults, folded matching
    finally:
        monkeypatch.undo()
        understanding.resources._json.cache_clear()
        understanding.resources._lines.cache_clear()
        understanding.resources._rule_defaults.cache_clear()


def test_protected_values_come_from_profile_samples():
    profile = {"products": {"rows": 3, "columns": [
        {"name": "ten", "type": "VARCHAR", "samples": ["Nước ngọt Pepsi", "Cà phê sữa"]},
        {"name": "gia", "type": "INTEGER", "samples": [10, 20]}]}}
    assert protected_from_profile(profile) == ["Nước ngọt Pepsi", "Cà phê sữa"]
    assert protected_from_profile({}) == [] and protected_from_profile(None) == []
    resolved = understand(question("thang nay nuoc ngot pepsi ban bn"), context(profile=profile))
    assert resolved.normalized == "tháng này nuoc ngot pepsi ban bao nhiêu"  # "ban" is ambiguous: kept


@pytest.mark.parametrize("text,metric,operation,top_n", [
    ("Mặt hàng nào bán chạy nhất tháng này theo số lượng?", "quantity", "top1", None),
    ("Cho mình danh sách top 3 sản phẩm bán nhiều nhất tháng trước, đúng thứ tự.", "quantity", "topN", 3),
    ("Liệt kê ba mặt hàng doanh thu cao nhất trong tháng này.", "revenue", "topN", 3),
    ("Doanh thu tuần rồi tăng giảm bao nhiêu % so với tuần liền trước đó", "revenue", "compare_percent", None),
    ("Trong tháng trước, ngày nào có doanh thu cao nhất?", "revenue", "date_of_max", None),
    ("Hôm qua có bán được sản phẩm P0017 không?", "none", "exists", None),
    ("Lợi nhuận gộp tháng trước là bao nhiêu?", "profit", "none", None),
    ("Khách Nguyễn Văn An hiện còn nợ cửa hàng bao nhiêu?", "debt", "none", None),
    ("Tháng trước có bao nhiêu đơn hàng bị hủy?", "none", "count", None),
    ("Giá trị đơn hàng trung bình tháng này là bao nhiêu?", "revenue", "avg", None),
    ("Sản phẩm nào tồn ít nhất 70 cái mà 30 ngày qua chỉ bán tối đa 2 cái?", "stock", "bottom1", None),
    ("Sản phẩm nào còn tồn mà lô hàng sẽ hết hạn trong 30 ngày tới?", "expiry", "none", None),
    ("Tổng số lượng sản phẩm bán ra tháng trước là bao nhiêu?", "quantity", "sum", None),
    ("hello", "none", "none", None),
])
def test_intent_hints(text, metric, operation, top_n):
    resolved = understand(question(text), context())
    assert resolved.intent_hints == {"metric": metric, "operation": operation, "top_n": top_n}, text


def test_intent_without_keywords_is_neutral():
    assert intent_hints("doanh thu", None) == {"metric": "none", "operation": "none", "top_n": None}
    assert "intent_keywords" in load_rule_defaults()


class RecordingBackend:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, linked):
        self.prompts.append(prompt)
        return Candidate("select count(*) from sales")


def test_pipeline_logs_understanding_and_prompt_uses_periods(tmp_path):
    backend = RecordingBackend()
    pipeline = Pipeline(BusinessLoader(SAMPLE, tmp_path), backend, TimeGuard())
    record = {"id": "t1", "business_id": "shop", "question": "Tong amount thang truoc la bn?",
              "as_of_date": "2026-05-14"}
    answer, log = pipeline.answer(record)
    info = log["understanding"]
    assert info["normalized"] == "tổng amount tháng trước là bao nhiêu?"
    assert info["periods"] == [{"label": "last_month", "start": "2026-04-01", "end": "2026-04-30",
                                "role": "primary", "mention": "tháng trước"}]  # sliced from the normalized text
    assert info["intent_hints"]["operation"] in {"sum", "none"}
    assert "rule_sources" in info["rule_params"]
    json.dumps(log, default=str)  # the log stays serializable (dates are ISO strings)
    prompt = backend.prompts[0]
    assert "do not compute relative dates yourself" in prompt
    payload = json.loads(prompt.split("\n", 2)[2])
    assert payload["original_question"] == record["question"]
    assert payload["normalized_question"] == info["normalized"]
    assert payload["periods"] == [{"label": "last_month", "start": "2026-04-01", "end": "2026-04-30", "role": "primary"}]
    assert payload["intent_hints"] == info["intent_hints"]
    assert "as_of_date" in prompt and "rulebook" in prompt


def test_run_logs_contain_understanding_for_every_question(tmp_path):
    run(SAMPLE, tmp_path / "out")
    logs = list(read_records(tmp_path / "out/logs/questions.jsonl"))
    assert len(logs) == 10 and all("understanding" in entry for entry in logs)
    assert all(entry["understanding"]["warnings"] == [] for entry in logs)


def test_src_never_imports_synth():
    for path in Path("src/datamate").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            for name in names:
                assert name.split(".")[0] not in {"synth", "src"}, (path, name)
