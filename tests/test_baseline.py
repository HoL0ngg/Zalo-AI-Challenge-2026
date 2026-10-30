import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from datamate.core import Answer, Candidate, ExecResult, Question
from datamate.eval.scorer import matches, score
from datamate.execution.sandbox import execute
from datamate.formatting.formatter import format_answer
from datamate.formatting.schemas import ANSWER_SCHEMA
from datamate.ingest.loader import BusinessLoader
from datamate.io.question_reader import read_records
from datamate.io.submission_writer import SubmissionWriter
from datamate.runtime.model_budget import check_model_budget
from datamate.runtime.runner import run
from datamate.runtime.time_guard import TimeGuard

SAMPLE = Path("data/samples")


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_end_to_end_resume_determinism_read_only(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "connect", lambda *a: pytest.fail("network access"), raising=False)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("network access"))
    before = digest(SAMPLE)
    first, second = tmp_path / "one", tmp_path / "two"
    run(SAMPLE, first)
    run(SAMPLE, second)
    submission = first / "submission.jsonl"
    assert submission.read_bytes() == (second / "submission.jsonl").read_bytes()
    records = list(read_records(submission))
    assert len(records) == 10
    for record in records:
        ANSWER_SCHEMA.validate_python(record)
    report = score(records, list(read_records(SAMPLE / "answers.jsonl")))
    assert (report["correct"], report["wrong"], report["abstain"]) == (9, 0, 1)
    logs = list(read_records(first / "logs/questions.jsonl"))
    assert len(logs) == 10
    assert all({"id", "final_answer", "elapsed_seconds", "attempts", "error"} <= log.keys() for log in logs)
    snapshot = digest(first)
    assert run(SAMPLE, first) == {"skipped": 10}
    assert digest(first) == snapshot
    assert digest(SAMPLE) == before


def test_incremental_fsync_and_resume_partial(tmp_path, monkeypatch):
    import os
    syncs = []
    real_sync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (syncs.append(fd), real_sync(fd)))
    path = tmp_path / "submission.jsonl"
    writer = SubmissionWriter(path)
    writer.write(Answer("a", "number", 3))
    assert len(syncs) == 1
    assert list(read_records(path)) == [{"id": "a", "type": "number", "answer": 3}]
    with path.open("ab") as stream:
        stream.write(b'{"id":')
    writer = SubmissionWriter(path)
    writer.write(Answer("a", "abstain"))
    writer.write(Answer("b", "abstain"))
    assert len(list(read_records(path))) == 2


def test_guard_and_per_question_failure(tmp_path):
    assert TimeGuard(0).exhausted
    config = yaml.safe_load(Path("configs/default.yaml").read_text())
    config["runtime"]["total_budget_seconds"] = 0
    config["models"] = str(Path("configs/models.yaml").resolve())
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    run(SAMPLE, tmp_path / "result", path)
    assert all(r["type"] == "abstain" for r in read_records(tmp_path / "result/submission.jsonl"))
    assert len(list(read_records(tmp_path / "result/logs/questions.jsonl"))) == 10


def test_model_budget(tmp_path):
    path = tmp_path / "models.yaml"
    for value in [15.1, -1, float("nan")]:
        path.write_text(yaml.safe_dump({"budget": {"max_parameters_billion": 15},
                                       "models": {"a": {"enabled": True, "parameters_billion": value}}}))
        with pytest.raises(ValueError):
            check_model_budget(path)
    assert check_model_budget(Path("configs/models.yaml"))


@pytest.mark.parametrize("kind,value,expected", [
    ("number", 2.345, 2.35), ("percent", -1.235, -1.24),
    ("string", "Ca\u0300 phê", "Cà phê"), ("date", date(2026, 1, 2), "2026-01-02"),
    ("boolean", True, True), ("list", ["B", "A"], ["B", "A"]),
    ("table", [["B", 2]], {"columns": ["name", "count"], "rows": [["B", 2]]}),
])
def test_formatter_and_scorer(kind, value, expected):
    question = Question(id="x", business_id="b", question="q", as_of_date="2026-01-01")
    columns = ["name", "count"] if kind == "table" else ["value"]
    rows = value if kind == "table" else [[v] for v in value] if kind == "list" else [[value]]
    answer = format_answer(question, ExecResult(Candidate("SELECT 1", kind), columns, rows)).to_dict()
    assert answer["answer"] == expected
    assert matches(answer, {"id": "x", "type": kind, "answer": expected})


def test_invalid_and_special_answers():
    for record in [{"id": "x", "type": "abstain", "answer": None},
                   {"id": "x", "type": "number", "answer": True},
                   {"id": "x", "type": "date", "answer": "2026-02-30"},
                   {"id": "x", "type": "number", "answer": float("nan")}]:
        with pytest.raises(ValueError):
            ANSWER_SCHEMA.validate_python(record)
    assert matches({"id": "x", "type": "unanswerable", "reason": "missing"}, {"type": "unanswerable"})
    assert matches({"id": "x", "type": "string", "answer": " CÀ--PHÊ "}, {"type": "string", "answer": "Cà phê"})
    assert not matches({"id": "x", "type": "list", "answer": [2, 1]}, {"type": "list", "answer": [1, 2]})
    assert score([], [{"id": "x", "type": "number", "answer": 1}])["abstain"] == 1


def test_ingest_cache_and_sandbox(tmp_path):
    loader = BusinessLoader(SAMPLE, tmp_path)
    context = loader.load("shop")
    assert loader.load("shop") is context
    assert set(context.profile) == {"sales", "inventory", "branches", "customers"}
    assert context.profile["inventory"]["rows"] == 2
    assert context.rulebook and context.calendar and context.readme
    for sql in ["DROP TABLE sales", "SELECT 1; SELECT 2", "SELECT * FROM read_csv_auto('https://example.com/a.csv')",
                "COPY sales TO 'stolen.csv'", "SELECT * FROM read_csv_auto('README.md')"]:
        assert execute(context, Candidate(sql)).error
    assert execute(context, Candidate("SELECT sum(i) FROM range(100000000000) t(i)"), .01).error
    assert execute(context, Candidate("SELECT count(*) FROM sales")).rows == [[2]]
    with pytest.raises(ValueError):
        loader.load("../../outside")
    with pytest.raises(ValueError):
        run(SAMPLE, SAMPLE / "bad-result")


def test_no_hardcoding():
    for path in Path("src/datamate").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r'(?:question\.id|business_id)\s*==\s*[\'\"]', source)
        assert not re.search(r'sample-\d|train_\d|dev_\d', source)


def test_single_repair_and_exception_continuation(tmp_path):
    from datamate.runtime.pipeline import Pipeline

    class RepairBackend:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt, linked):
            self.prompts.append(prompt)
            return Candidate("SELECT count(*) FROM sales" if "Repair this SQL" in prompt else "SELECT missing FROM sales")

    backend = RepairBackend()
    pipeline = Pipeline(BusinessLoader(SAMPLE, tmp_path), backend, TimeGuard())
    record = next(read_records(SAMPLE / "questions.jsonl"))
    answer, log = pipeline.answer(record)
    assert answer.answer == 2 and len(log["attempts"]) == 2
    assert "as_of_date" in backend.prompts[0] and "rulebook" in backend.prompts[0]
    answer, log = pipeline.answer({**record, "as_of_date": "bad date"})
    assert answer.type == "abstain" and log["error"]
    answer, log = pipeline.answer(record)
    assert answer.answer == 2


def test_csv_header_encoding_and_input_write_denial(tmp_path, monkeypatch):
    import builtins
    from datamate.ingest.loader import read_tables

    csv_path = tmp_path / "offset.csv"
    csv_path.write_text("Report\n\nname;amount\na;4\nb;6\n", encoding="cp1258")
    name, frame = next(read_tables(csv_path))
    assert list(frame.columns) == ["name", "amount"] and frame.amount.sum() == 10
    original = builtins.open
    original_path_open = Path.open

    def check(file, mode):
        if isinstance(file, (str, Path)) and Path(file).resolve().is_relative_to(SAMPLE.resolve()):
            assert not any(flag in mode for flag in "wax+"), "Input data write attempted"

    def guarded_open(file, mode="r", *args, **kwargs):
        check(file, mode)
        return original(file, mode, *args, **kwargs)

    def guarded_path_open(file, mode="r", *args, **kwargs):
        check(file, mode)
        return original_path_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    run(SAMPLE, tmp_path / "readonly-result")
    assert len(list(read_records(tmp_path / "readonly-result/submission.jsonl"))) == 10


def test_nonfinite_execution_is_logged_and_abstains(tmp_path):
    from datamate.io.log_writer import LogWriter
    from datamate.runtime.pipeline import Pipeline

    class NanBackend:
        def generate(self, prompt, linked):
            return Candidate("SELECT 'NaN'::DOUBLE")

    pipeline = Pipeline(BusinessLoader(SAMPLE, tmp_path / "db"), NanBackend(), TimeGuard())
    answer, log = pipeline.answer(next(read_records(SAMPLE / "questions.jsonl")))
    assert answer.type == "abstain"
    LogWriter(tmp_path / "logs").write(log)
    assert list(read_records(tmp_path / "logs/questions.jsonl"))[0]["error"]


def test_failed_ingest_does_not_reuse_another_business_database(tmp_path, monkeypatch):
    import datamate.ingest.loader as module
    original = module.profile_table
    loader = BusinessLoader(SAMPLE, tmp_path)
    monkeypatch.setattr(module, "profile_table", lambda *a: (_ for _ in ()).throw(ValueError("broken profile")))
    with pytest.raises(ValueError):
        loader.load("shop")
    monkeypatch.setattr(module, "profile_table", original)
    context = loader.load("shop")
    assert set(context.profile) == {"sales", "inventory", "branches", "customers"}
