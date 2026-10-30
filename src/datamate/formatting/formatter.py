import math
import unicodedata
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from datamate.core import Answer, ExecResult, Question
from datamate.formatting.schemas import ANSWER_SCHEMA


def clean(value: Any, integer: bool = False) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        if not math.isfinite(value):
            raise ValueError("Non-finite number")
        rounded = Decimal(str(value)).quantize(Decimal("1" if integer else "0.01"), rounding=ROUND_HALF_UP)
        return int(rounded) if integer or rounded == rounded.to_integral_value() else float(rounded)
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (tuple, list)):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    raise ValueError(f"Unsupported result type {type(value)}")


def format_answer(question: Question, result: ExecResult) -> Answer:
    if result.error:
        raise ValueError(result.error)
    kind = result.candidate.answer_type
    if kind is None:
        if len(result.columns) > 1:
            kind = "table"
        elif len(result.rows) != 1:
            kind = "list"
        else:
            value = result.rows[0][0]
            kind = ("boolean" if isinstance(value, bool) else "date" if isinstance(value, date)
                    else "number" if isinstance(value, (int, float, Decimal)) else "string")
    if kind == "table":
        value = {"columns": result.columns, "rows": result.rows}
    elif kind == "list":
        if len(result.columns) != 1:
            raise ValueError("List requires one column")
        value = [row[0] for row in result.rows]
    else:
        if len(result.rows) != 1 or len(result.columns) != 1 or result.rows[0][0] is None:
            raise ValueError("Scalar requires one non-null cell")
        value = result.rows[0][0]
    answer = Answer(question.id, kind, clean(value, result.candidate.unit in {"VND", "count"}))
    ANSWER_SCHEMA.validate_python(answer.to_dict())
    return answer
