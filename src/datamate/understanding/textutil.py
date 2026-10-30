"""Small, pure text helpers shared by the normalizer and the temporal resolver."""
from __future__ import annotations

import unicodedata

_CONTROL_TO_SPACE = {"\t", "\n", "\r", "\x0b", "\x0c", "\x85", " ", " ", " "}


def fold_char(ch: str) -> str:
    """Lowercase base letter of one character, always exactly one character long."""
    if ch in "đĐ":
        return "d"
    base = unicodedata.normalize("NFD", ch)[0]
    lowered = base.lower()
    return lowered if len(lowered) == 1 else base


def fold(text: str) -> str:
    """Diacritic-free lowercase text with the same length as the NFC input.

    The length guarantee lets callers run regexes on the folded text and slice the
    original text with the same offsets.
    """
    return "".join(fold_char(ch) for ch in text)


def clean(text: str) -> str:
    """NFC, drop control/format characters, collapse whitespace."""
    out = []
    for ch in unicodedata.normalize("NFC", text):
        category = unicodedata.category(ch)
        if ch in _CONTROL_TO_SPACE or category == "Zs":
            out.append(" ")
        elif category in {"Cc", "Cf"}:
            continue
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def has_diacritics(text: str) -> bool:
    return text.lower() != fold(text)
