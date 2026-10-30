import tempfile
from collections import Counter
from pathlib import Path

import yaml

from datamate.ingest.loader import BusinessLoader
from datamate.io.log_writer import LogWriter
from datamate.io.question_reader import read_records
from datamate.io.submission_writer import SubmissionWriter
from datamate.llm.mock_backend import MockBackend
from datamate.runtime.model_budget import check_model_budget
from datamate.runtime.pipeline import Pipeline
from datamate.runtime.seeding import seed_everything
from datamate.runtime.time_guard import TimeGuard


def run(data_dir: Path, result_dir: Path, config_path: Path = Path("configs/default.yaml"),
        backend=None) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    runtime = config["runtime"]
    guard = TimeGuard(min(float(runtime["total_budget_seconds"]), 21600), runtime.get("reserve_seconds", 60))
    root = config_path.resolve().parent.parent
    models = check_model_budget(root / config["models"])
    seed_everything(runtime["seed"])
    data_dir, result_dir = data_dir.resolve(), result_dir.resolve()
    if result_dir.is_relative_to(data_dir):
        raise ValueError("Output must be outside read-only input package")
    writer = SubmissionWriter(result_dir / "submission.jsonl")
    logs = LogWriter(result_dir / "logs")
    if backend is None:
        if runtime["backend"] == "mock" or guard.exhausted:
            backend = MockBackend()
        elif runtime["backend"] == "vllm":
            from datamate.llm.vllm_backend import VLLMBackend
            model = dict(models["models"]["code_generation"])
            model["local_path"] = str(root / model["local_path"])
            backend = VLLMBackend(model, runtime["seed"])
        else:
            raise ValueError("Unknown backend")
    counts = Counter()
    with tempfile.TemporaryDirectory(prefix="datamate-") as temporary:
        pipeline = Pipeline(BusinessLoader(data_dir, Path(temporary)), backend, guard,
                            runtime["max_question_seconds"], config["pipeline"]["max_repair_attempts"])
        for record in read_records(data_dir / "questions.jsonl"):
            if not isinstance(record.get("id"), str):
                raise ValueError("Each input record needs a string ID")
            if record["id"] in writer.seen:
                counts["skipped"] += 1
                continue
            answer, log = pipeline.answer(record)
            # Persist audit evidence before committing the resumable answer.
            logs.write(log)
            writer.write(answer)
            counts[answer.type] += 1
    return dict(counts)
