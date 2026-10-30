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
    # Phase 3: canonical semantic layer, entity index and entity values to protect from normalization.
    canonical: Any = None            # datamate.ingest.canonical.CanonicalSchema | None
    entities: Any = None             # datamate.linking.entity_index.EntityIndex | None
    protected_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Period:
    """Inclusive date range resolved from a time expression in the question."""
    label: str
    start: date
    end: date
    role: str  # "primary" | "comparison"
    mention: str


@dataclass
class ResolvedQuestion:
    question: Question  # always the original, untouched question
    normalized: str = ""
    normalized_ascii: str = ""
    periods: list[Period] = field(default_factory=list)
    intent_hints: dict[str, Any] = field(default_factory=dict)
    rule_params: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Entity:
    """A question mention linked to a value that really exists in the business data."""
    mention: str
    kind: str                        # product | customer | category
    id: str
    matched: str                     # canonical in-data name
    score: float
    match_type: str                  # exact | code | fuzzy
    aliases: tuple[str, ...] = ()
    alternatives: tuple[tuple[str, str, float], ...] = ()   # (name, id, score)


@dataclass
class LinkResult:
    resolved: ResolvedQuestion
    context: BusinessContext
    entities: list[Entity] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)


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
