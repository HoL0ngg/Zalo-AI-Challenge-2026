import json
import os
from pathlib import Path

from datamate.core import Answer
from datamate.formatting.schemas import ANSWER_SCHEMA


def append_json(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class SubmissionWriter:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.seen: set[str] = set()
        if path.exists():
            with path.open("rb+") as stream:
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line:
                        break
                    try:
                        record = ANSWER_SCHEMA.validate_json(line)
                    except ValueError:
                        if line.endswith(b"\n") or stream.read(1):
                            raise ValueError("Corrupt submission before final partial line")
                        stream.truncate(start)
                        stream.flush()
                        os.fsync(stream.fileno())
                        break
                    if record.id in self.seen:
                        raise ValueError("Duplicate submission ID")
                    self.seen.add(record.id)
                    if not line.endswith(b"\n"):
                        stream.write(b"\n")
                        stream.flush()
                        os.fsync(stream.fileno())

    def write(self, answer: Answer) -> None:
        if answer.id in self.seen:
            return
        record = answer.to_dict()
        ANSWER_SCHEMA.validate_python(record)
        append_json(self.path, record)
        self.seen.add(answer.id)
