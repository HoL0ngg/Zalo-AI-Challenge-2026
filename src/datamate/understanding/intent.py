"""Light keyword intent hints. Hints only; no final decisions are made here.

Patterns live in configs/rules_defaults.yaml (`intent_keywords`) and are matched against
the diacritic-free lowercase question. First match in declaration order wins, so the
result is deterministic.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from datamate.understanding.temporal import NUMBER_WORDS

_TOP_N = re.compile(r"(?<![a-z0-9])top\s*(\d{1,2})(?![a-z0-9])")
# "ngay" is deliberately absent: "30 ngay qua" is a time window, not a top-N request.
_NOUN_AFTER_N = (r"(?:mat hang|san pham|nhom hang|khach(?: hang)?|don hang|nhan vien|danh muc|sp)")
_WORD_N = re.compile(
    r"(?<![a-z0-9])(\d{1,2}|muoi\s+(?:mot|hai)|hai\s+muoi|mot|hai|ba|bon|sau|bay|tam|chin|muoi)\s+" + _NOUN_AFTER_N)


def _first(patterns: Mapping[str, list[str]], text: str) -> str | None:
    for name, expressions in patterns.items():
        for expression in expressions:
            if re.search(expression, text):
                return name
    return None


def intent_hints(normalized_ascii: str, keywords: Mapping[str, Any] | None) -> dict[str, Any]:
    """{"metric": ..., "operation": ..., "top_n": int | None} from folded question text."""
    keywords = keywords or {}
    text = normalized_ascii
    metric = _first(keywords.get("metric") or {}, text) or "none"
    operation = _first(keywords.get("operation") or {}, text)
    top_n: int | None = None
    ranking = bool(re.search(keywords.get("ranking_words", r"nhat|dung dau|cao|thap"), text))
    match = _TOP_N.search(text)
    if match:
        top_n = int(match.group(1))
    elif ranking:
        word = _WORD_N.search(text)
        if word:
            token = re.sub(r"\s+", " ", word.group(1))
            top_n = int(token) if token.isdigit() else NUMBER_WORDS.get(token)
    if top_n is not None and top_n > 1:
        operation = "topN"
    return {"metric": metric, "operation": operation or "none", "top_n": top_n}
