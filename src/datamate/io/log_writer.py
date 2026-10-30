from pathlib import Path
import math

from datamate.io.submission_writer import append_json


class LogWriter:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "questions.jsonl"

    def write(self, record: dict) -> None:
        append_json(self.path, safe_log(record))


def safe_log(value):
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: safe_log(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_log(item) for item in value]
    return value
