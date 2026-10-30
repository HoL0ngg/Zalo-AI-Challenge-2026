import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictFloat, StrictInt, StrictStr, TypeAdapter, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: StrictStr


class NumberAnswer(Record):
    type: Literal["number"]
    answer: StrictInt | StrictFloat


class PercentAnswer(Record):
    type: Literal["percent"]
    answer: StrictInt | StrictFloat


class StringAnswer(Record):
    type: Literal["string"]
    answer: StrictStr


class DateAnswer(Record):
    type: Literal["date"]
    answer: StrictStr

    @field_validator("answer")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", value):
            raise ValueError("Expected ISO date or month")
        date.fromisoformat(value + "-01" if len(value) == 7 else value)
        return value


class BooleanAnswer(Record):
    type: Literal["boolean"]
    answer: StrictBool


class ListAnswer(Record):
    type: Literal["list"]
    answer: list[JsonValue]


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    columns: list[StrictStr]
    rows: list[list[JsonValue]]

    @model_validator(mode="after")
    def rectangular(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Table row width mismatch")
        return self


class TableAnswer(Record):
    type: Literal["table"]
    answer: Table


class UnanswerableAnswer(Record):
    type: Literal["unanswerable"]
    reason: StrictStr | None = None


class AbstainAnswer(Record):
    type: Literal["abstain"]


ANSWER_SCHEMA = TypeAdapter(Annotated[
    NumberAnswer | PercentAnswer | StringAnswer | DateAnswer | BooleanAnswer |
    ListAnswer | TableAnswer | UnanswerableAnswer | AbstainAnswer, Field(discriminator="type")])
