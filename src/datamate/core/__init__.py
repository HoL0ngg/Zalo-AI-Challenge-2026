from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    business_id: str
    question: str
    as_of_date: date


@dataclass
class BusinessContext:
    database: Path
    profile: dict[str, Any]
    readme: str
    rulebook: str
    calendar: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ResolvedQuestion:
    question: Question


@dataclass
class LinkResult:
    resolved: ResolvedQuestion
    context: BusinessContext


@dataclass
class GateResult:
    linked: LinkResult
    allowed: bool = True
    reason: str | None = None


@dataclass
class Candidate:
    code: str
    answer_type: str | None = None
    unit: str | None = None


@dataclass
class ExecResult:
    candidate: Candidate
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class Answer:
    id: str
    type: str
    answer: Any = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"id": self.id, "type": self.type}
        if self.type not in {"abstain", "unanswerable"}:
            result["answer"] = self.answer
        elif self.type == "unanswerable" and self.reason:
            result["reason"] = self.reason
        return result
