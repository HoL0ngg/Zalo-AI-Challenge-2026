"""Phase 4 / P0: chat prompt, strict SQL parsing, prompt caps, backend plumbing and the stage report."""
import json
from pathlib import Path

import pytest

from datamate.codegen.prompt_builder import PROMPT_CHARS, README_CHARS, SYSTEM_PROMPT, clip, compact_schema
from datamate.codegen.sql_parser import extract_sql
from datamate.core import Candidate
from datamate.eval.report import build_report, classify_error, question_outcome
from datamate.llm.vllm_backend import candidate_from_reply, render_chat

SAMPLE = Path("data/samples")


@pytest.mark.parametrize("raw,expected", [
    ("<sql>SELECT 1;</sql>", "SELECT 1"),
    ("Sure!\n<sql>\nSELECT a FROM v_sales\n</sql>\nDone", "SELECT a FROM v_sales"),
    ("<sql>SELECT 1", "SELECT 1"),                                   # truncated generation, tag never closed
    ("```sql\nSELECT 2;\n```", "SELECT 2"),
    ("```\nWITH x AS (SELECT 1) SELECT * FROM x\n```", "WITH x AS (SELECT 1) SELECT * FROM x"),
    ("Here is the query: select count(*) from t;", "select count(*) from t"),
    ("<think>plan it</think><sql>SELECT 3</sql>", "SELECT 3"),
    ("<think>SELECT 4 is wrong, keep thinking", ""),                 # cut inside the thinking block
    ("I cannot answer that.", ""),
    ("<sql>   </sql>\n```sql\nSELECT 5\n```", "SELECT 5"),          # empty tag falls through to the fence
])
def test_extract_sql(raw, expected):
    assert extract_sql(raw) == expected


def test_clip_cuts_on_line_boundary_and_marks_the_cut():
    text = "\n".join(f"line {i}" for i in range(100))
    clipped = clip(text, 50)
    assert clipped.endswith("\n...[truncated]") and len(clipped) <= 50 + len("\n...[truncated]")
    kept = clipped.splitlines()[:-1]
    assert kept == [f"line {i}" for i in range(len(kept))]            # whole lines only, in order
    assert clip("short", 50) == "short" and README_CHARS < PROMPT_CHARS


def test_compact_schema_drops_roles_and_flattens_columns():
    described = {"views": {"v_x": {"about": "doc", "columns": [{"name": "a", "type": "DATE", "meaning": "when"},
                                                              {"name": "b", "type": "DOUBLE", "meaning": ""}]}},
                 "capabilities": {"has_debts": False}, "roles": {"lines": {"table": "raw"}}, "rules": {"x": True}}
    assert compact_schema(described) == {
        "views": {"v_x": {"about": "doc", "columns": ["a DATE: when", "b DOUBLE"]}},
        "capabilities": {"has_debts": False}, "rules": {"x": True}}


def test_system_prompt_defers_to_the_rulebook_on_tie_breaks():
    assert "tie order" in SYSTEM_PROMPT and "<sql></sql>" in SYSTEM_PROMPT


class FakeTokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        assert tokenize is False and add_generation_prompt
        return json.dumps({"messages": messages, "thinking": enable_thinking})


def test_render_chat_uses_system_and_user_roles():
    rendered = json.loads(render_chat(FakeTokenizer(), "SYS", "USER"))
    assert rendered == {"messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}],
                        "thinking": False}
    assert json.loads(render_chat(FakeTokenizer(), "S", "U", True))["thinking"] is True


def test_candidate_from_reply_keeps_raw_text_and_usage():
    candidate = candidate_from_reply("<sql>SELECT 1", "length", 1234)
    assert candidate.code == "SELECT 1"
    assert candidate.meta == {"raw_output": "<sql>SELECT 1", "finish_reason": "length", "prompt_tokens": 1234}
    assert Candidate("SELECT 1").meta == {}


def test_pipeline_logs_candidate_meta(tmp_path):
    from datamate.ingest.loader import BusinessLoader
    from datamate.io.question_reader import read_records
    from datamate.runtime.pipeline import Pipeline
    from datamate.runtime.time_guard import TimeGuard

    class MetaBackend:
        def generate(self, prompt, linked):
            return candidate_from_reply("<sql>SELECT count(*) FROM sales</sql>", "stop", 99)

    pipeline = Pipeline(BusinessLoader(SAMPLE, tmp_path), MetaBackend(), TimeGuard())
    answer, log = pipeline.answer(next(read_records(SAMPLE / "questions.jsonl")))
    assert answer.answer == 2
    meta = log["attempts"][0]["candidate"]["meta"]
    assert meta["finish_reason"] == "stop" and meta["prompt_tokens"] == 99 and "SELECT" in meta["raw_output"]


def test_classify_error():
    assert classify_error('Binder Error: Referenced column "x" not found') == "binder"
    assert classify_error("Parser Error: syntax error at or near") == "syntax"
    assert classify_error("Catalog Error: Table with name t does not exist") == "catalog"
    assert classify_error("SQL timeout") == "timeout" and classify_error(None) == "other"


def attempt(code, error=None, **meta):
    return {"candidate": {"code": code, "meta": meta}, "error": error}


def test_stage_report_groups_failures_and_templates():
    gold = [{"id": "ok", "type": "number", "answer": 5}, {"id": "bad", "type": "number", "answer": 5},
            {"id": "typ", "type": "number", "answer": 5}, {"id": "err", "type": "number", "answer": 5},
            {"id": "nosql", "type": "string", "answer": "a"}, {"id": "un", "type": "unanswerable"},
            {"id": "blocked", "type": "number", "answer": 1}, {"id": "missing", "type": "number", "answer": 1}]
    submission = [{"id": "ok", "type": "number", "answer": 5}, {"id": "bad", "type": "number", "answer": 6},
                  {"id": "typ", "type": "string", "answer": "5"}, {"id": "err", "type": "abstain"},
                  {"id": "nosql", "type": "abstain"}, {"id": "un", "type": "unanswerable"},
                  {"id": "blocked", "type": "unanswerable"}]
    logs = [{"id": "ok", "attempts": [attempt("SELECT 1", prompt_tokens=100, finish_reason="stop")], "elapsed_seconds": 1},
            {"id": "bad", "attempts": [attempt("SELECT 2")], "elapsed_seconds": 3},
            {"id": "typ", "attempts": [attempt("SELECT 3")], "elapsed_seconds": 2},
            {"id": "err", "attempts": [attempt("SELECT x", "Binder Error: no column"), attempt("SELECT y", "Binder Error")],
             "elapsed_seconds": 4},
            {"id": "nosql", "attempts": [attempt("", None, finish_reason="length")], "elapsed_seconds": 1}]
    templates = {"ok": "revenue", "bad": "revenue", "typ": "aov"}
    report = build_report(submission, logs, gold, templates)
    assert report["total"] == 8 and report["accuracy"] == 0.25
    assert report["stages"] == {"gated": 2, "generated": 5, "sql_extracted": 4, "exec_ok": 3, "repaired_ok": 0,
                                "answered": 3, "correct": 2}
    assert report["failures"] == {"wrong_value": 1, "wrong_type": 1, "abstain:exec_binder": 1,
                                  "abstain:no_sql_in_reply": 1, "wrongly_blocked": 1, "abstain:no_attempt": 1}
    assert report["exec_errors"] == {"binder": 2}
    assert report["per_template"] == {"aov": {"correct": 0, "total": 1, "accuracy": 0.0},
                                      "revenue": {"correct": 1, "total": 2, "accuracy": 0.5}}
    assert report["per_type"]["unanswerable"]["accuracy"] == 1.0
    assert report["precision_when_answered"] == 0.3333
    assert report["prompt_tokens"] == {"mean": 100, "max": 100}
    assert report["finish_reasons"] == {"stop": 1, "length": 1}
    assert report["latency_seconds"]["mean"] == 2.2


def test_question_outcome_marks_repaired_success():
    outcome = question_outcome({"id": "x", "type": "number", "answer": 1}, {"id": "x", "type": "number", "answer": 1},
                               {"attempts": [attempt("SELECT x", "Binder Error"), attempt("SELECT 1")]})
    assert outcome["repaired_ok"] and outcome["correct"] and outcome["failure"] is None
