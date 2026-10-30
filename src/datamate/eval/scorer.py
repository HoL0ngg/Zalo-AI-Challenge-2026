import unicodedata
from collections import Counter, defaultdict

from datamate.formatting.formatter import clean
from datamate.formatting.schemas import ANSWER_SCHEMA


def normalize(value):
    if isinstance(value, str):
        text = unicodedata.normalize("NFC", value).lower()
        return " ".join("".join(c if c.isalnum() else " " for c in text).split())
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return value


def matches(prediction: dict, expected: dict) -> bool:
    try:
        ANSWER_SCHEMA.validate_python(prediction)
    except ValueError:
        return False
    kind = expected["type"]
    if prediction["type"] != kind:
        return False
    if kind in {"unanswerable", "abstain"}:
        return True
    actual, wanted = prediction["answer"], expected["answer"]
    if kind == "percent":
        return clean(actual) == clean(wanted)
    if kind == "string":
        return normalize(actual) in [normalize(v) for v in [wanted, *expected.get("alias", expected.get("aliases", []))]]
    if kind in {"list", "table"}:
        return normalize(actual) == normalize(wanted)
    return actual == wanted


def score(predictions: list[dict], expected: list[dict]) -> dict:
    by_id = {p["id"]: p for p in predictions}
    if len(by_id) != len(predictions):
        raise ValueError("Duplicate prediction IDs")
    counts = Counter(correct=0, wrong=0, abstain=0)
    types = defaultdict(lambda: Counter(correct=0, total=0))
    for gold in expected:
        prediction = by_id.get(gold["id"], {"id": gold["id"], "type": "abstain"})
        outcome = "abstain" if prediction["type"] == "abstain" else "correct" if matches(prediction, gold) else "wrong"
        counts[outcome] += 1
        types[gold["type"]]["total"] += 1
        types[gold["type"]]["correct"] += outcome == "correct"
    return {**counts, "per_type": {k: {**v, "accuracy": v["correct"] / v["total"]}
                                     for k, v in sorted(types.items())}}
