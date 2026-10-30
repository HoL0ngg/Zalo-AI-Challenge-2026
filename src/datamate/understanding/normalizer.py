"""Deterministic Vietnamese normalizer: teencode, typos, repeated letters, diacritics.

Principle: fix less rather than fix wrong. A token is changed only when the result is
a known word (or an unambiguous restoration from the bundled lexicon). Protected spans
(entity values from the business data, product codes) are never modified.
Everything is pure and deterministic; the lexicon and teencode table are passed in.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from datamate.understanding.textutil import clean, fold

TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_TONE_KEYS = "sfrxjz"
_RUN3 = re.compile(r"(.)\1{2,}")
_RUN2 = re.compile(r"(.)\1+")

# Explicit slips that rules cannot derive safely. Values are final accented words.
TYPO_TABLE: dict[str, str] = {
    "thnags": "tháng", "thnag": "tháng", "thagn": "tháng", "thangs": "tháng",
    "tuaan": "tuần", "nawm": "năm", "namw": "năm",
}


@dataclass(frozen=True)
class Lexicon:
    known: frozenset[str]                       # every accented/lowercase word form
    fold_keys: frozenset[str]                   # fold() of known
    unigrams: Mapping[str, frozenset[str]]      # fold key -> candidate forms
    phrases: Mapping[tuple[str, ...], tuple[tuple[str, ...], ...]]
    homographs: frozenset[str]
    max_phrase_len: int


@dataclass(frozen=True)
class Teencode:
    table: Mapping[tuple[str, ...], str]        # lowercase variant tokens -> canonical phrase
    max_len: int


@dataclass(frozen=True)
class NormResult:
    normalized: str
    normalized_ascii: str
    changes: tuple[tuple[str, str, str], ...] = ()  # (kind, before, after)


@dataclass
class _Item:
    text: str
    sp: bool                  # whitespace before this token
    locked: bool = False      # already final, later passes must not touch it
    protected: bool = False


def _wordlike(text: str) -> bool:
    return text.isalpha()


def build_lexicon(entries: Iterable[str], homographs: Iterable[str] = ()) -> Lexicon:
    known: set[str] = set()
    phrases: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)
    longest = 1
    for entry in entries:
        words = tuple(w for w in entry.lower().split() if w)
        if not words or not all(_wordlike(w) for w in words):
            continue
        known.update(words)
        if len(words) > 1:
            phrases[tuple(fold(w) for w in words)].add(words)
            longest = max(longest, len(words))
    unigrams: dict[str, set[str]] = defaultdict(set)
    for word in known:
        unigrams[fold(word)].add(word)
    return Lexicon(
        known=frozenset(known),
        fold_keys=frozenset(fold(w) for w in known),
        unigrams={k: frozenset(v) for k, v in unigrams.items()},
        phrases={k: tuple(sorted(v)) for k, v in phrases.items()},
        homographs=frozenset(homographs),
        max_phrase_len=longest,
    )


def build_teencode(raw: Mapping[str, Sequence[str]]) -> Teencode:
    """Invert canonical->variants. Pure diacritic-stripped variants are left to the
    lexicon channel (they need the unambiguity check); clashing variants are dropped."""
    seen: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for canonical, variants in raw.items():
        canon_tokens = tuple(TOKEN_RE.findall(canonical.lower()))
        for variant in variants:
            lowered = variant.lower()
            tokens = tuple(TOKEN_RE.findall(lowered))
            if not tokens or tokens == canon_tokens:
                continue
            if fold(lowered) == fold(canonical.lower()) and lowered == fold(lowered):
                continue
            seen[tokens].add(canonical)
    table = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
    return Teencode(table, max((len(k) for k in table), default=1))


# --------------------------------------------------------------------------- passes

def _tokenize(text: str) -> list[_Item]:
    items: list[_Item] = []
    previous_end = 0
    for match in TOKEN_RE.finditer(text):
        items.append(_Item(match.group(), bool(items) and match.start() > previous_end))
        previous_end = match.end()
    return items


def _join(items: Sequence[_Item]) -> str:
    return "".join((" " if (i and it.sp) else "") + it.text for i, it in enumerate(items))


def _protected_index(values: Iterable[str]) -> dict[str, list[tuple[str, ...]]]:
    index: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for value in sorted(set(values)):
        tokens = tuple(TOKEN_RE.findall(fold(clean(value))))
        if not tokens or not any(t.isalpha() for t in tokens):
            continue
        if len(tokens) == 1 and len(tokens[0]) < 3:
            continue
        index[tokens[0]].append(tokens)
    for sequences in index.values():
        sequences.sort(key=len, reverse=True)
    return index


def _mark_protected(items: list[_Item], values: Iterable[str] | None) -> None:
    for item in items:
        if any(c.isdigit() for c in item.text) and any(c.isalpha() for c in item.text):
            item.protected = True  # product / order codes such as P0017
    if not values:
        return
    index = _protected_index(values)
    folds = [fold(it.text) for it in items]
    i = 0
    while i < len(items):
        for sequence in index.get(folds[i], ()):
            if tuple(folds[i:i + len(sequence)]) == sequence:
                for item in items[i:i + len(sequence)]:
                    item.protected = True
                i += len(sequence)
                break
        else:
            i += 1


def _free(item: _Item) -> bool:
    return not item.protected and not item.locked


def _apply_teencode(items: list[_Item], teencode: Teencode, changes: list) -> list[_Item]:
    out: list[_Item] = []
    i = 0
    while i < len(items):
        if not _free(items[i]):
            out.append(items[i])
            i += 1
            continue
        replaced = False
        for n in range(min(teencode.max_len, len(items) - i), 0, -1):
            segment = items[i:i + n]
            if not all(_free(s) for s in segment):
                continue
            key = tuple(s.text.lower() for s in segment)
            canonical = teencode.table.get(key)
            if canonical is None:
                continue
            if key == ("k",) and out and out[-1].text.isdigit():
                continue  # "5 k" is a thousand-suffix, not "không"
            if key == ("%",) and out and out[-1].text[-1:].isdigit() and not segment[0].sp:
                continue  # "10%" stays attached
            words = canonical.split()
            out.extend(_Item(w, segment[0].sp if j == 0 else True, locked=True)
                       for j, w in enumerate(words))
            changes.append(("teencode", " ".join(s.text for s in segment), canonical))
            i += n
            replaced = True
            break
        if not replaced:
            out.append(items[i])
            i += 1
    return out


def _known_form(word: str, lexicon: Lexicon) -> bool:
    return word in lexicon.known or fold(word) in lexicon.fold_keys


def _collapse_repeats(word: str, lexicon: Lexicon) -> str | None:
    c3 = _RUN3.sub(r"\1", word)
    c2 = _RUN2.sub(r"\1", word)
    for candidate in (c3, c2):
        if candidate != word and _known_form(candidate, lexicon):
            return candidate
    if c3 != word:
        return c3  # three or more equal letters are never legitimate
    return None


def _transposition_or_telex(word: str, lexicon: Lexicon) -> str | None:
    candidates: set[str] = set()
    bases = {word, _RUN2.sub(r"", word)}  # a swapped word may also carry a repeated last letter
    variants = set(bases)
    for base in bases:
        if len(base) >= 5:
            variants.update(base[:i] + base[i + 1] + base[i] + base[i + 2:] for i in range(len(base) - 1))
    for variant in variants:
        pool = {variant}
        if len(variant) >= 4 and variant[-1] in _TONE_KEYS:
            pool.add(variant[:-1])
        if "dd" in variant:
            pool.add(variant.replace("dd", "đ"))
        for candidate in pool:
            if candidate != word and len(candidate) >= 3 and _known_form(candidate, lexicon):
                candidates.add(candidate)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _split_glued(text: str, lexicon: Lexicon) -> tuple[str, str] | None:
    low = text.lower()
    splits = [(text[:i], text[i:]) for i in range(2, len(low) - 1)
              if fold(low[:i]) in lexicon.fold_keys and fold(low[i:]) in lexicon.fold_keys]
    return splits[0] if len(splits) == 1 else None


def _repair_tokens(items: list[_Item], lexicon: Lexicon, changes: list) -> list[_Item]:
    out: list[_Item] = []
    for item in items:
        if not _free(item) or not _wordlike(item.text):
            out.append(item)
            continue
        low = item.text.lower()
        if low in lexicon.known:
            out.append(item)
            continue
        typo = TYPO_TABLE.get(low)
        if typo is not None:
            words = typo.split()
            out.extend(_Item(w, item.sp if j == 0 else True, locked=True) for j, w in enumerate(words))
            changes.append(("typo", item.text, typo))
            continue
        current = low
        collapsed = _collapse_repeats(current, lexicon)
        if collapsed is not None:
            changes.append(("repeat", item.text, collapsed))
            current = collapsed
        if not _known_form(current, lexicon):
            fixed = _transposition_or_telex(current, lexicon)
            if fixed is not None:
                changes.append(("typo", current, fixed))
                current = fixed
        if not _known_form(current, lexicon) and len(current) >= 6:
            pieces = _split_glued(item.text if current == low else current, lexicon)
            if pieces is not None:
                left, right = pieces
                out.append(_Item(left, item.sp))
                out.append(_Item(right, True))
                changes.append(("split", item.text, f"{left} {right}"))
                continue
        out.append(_Item(item.text if current == low else current, item.sp))
    return out


def _compatible(entry: tuple[str, ...], lowered: Sequence[str]) -> bool:
    return all(low == word or low == fold(low) for word, low in zip(entry, lowered))


def _phrase_match(segment: Sequence[_Item], lexicon: Lexicon) -> tuple[str, ...] | None:
    """The single lexicon phrase compatible with this run of tokens, if unambiguous."""
    if not all(_free(s) and _wordlike(s.text) for s in segment):
        return None
    lowered = [s.text.lower() for s in segment]
    entries = lexicon.phrases.get(tuple(fold(w) for w in lowered))
    if not entries:
        return None
    matching = [e for e in entries if _compatible(e, lowered)]
    return matching[0] if len(matching) == 1 else None


def _restore_phrases(items: list[_Item], lexicon: Lexicon, changes: list) -> list[_Item]:
    """Cover the sentence with unambiguous phrases, maximizing covered tokens.

    A plain longest-first scan can let a long phrase swallow the start of the next one
    ("bao nhiêu đơn hợp" + "lệ"); the dynamic program picks the best segmentation instead.
    Ties prefer the longer first phrase, so the result is deterministic.
    """
    n = len(items)
    matches: dict[tuple[int, int], tuple[str, ...]] = {}
    for i in range(n):
        for length in range(2, min(lexicon.max_phrase_len, n - i) + 1):
            entry = _phrase_match(items[i:i + length], lexicon)
            if entry is not None:
                matches[(i, length)] = entry
    best = [0] * (n + 1)
    choice: list[int] = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        best[i], choice[i] = best[i + 1], 0
        for length in range(min(lexicon.max_phrase_len, n - i), 1, -1):
            if (i, length) in matches and length + best[i + length] > best[i]:
                best[i], choice[i] = length + best[i + length], length
    out: list[_Item] = []
    i = 0
    while i < n:
        length = choice[i]
        if length == 0:
            out.append(items[i])
            i += 1
            continue
        segment, entry = items[i:i + length], matches[(i, length)]
        if [s.text.lower() for s in segment] != list(entry):
            out.extend(_Item(w, segment[0].sp if j == 0 else True, locked=True) for j, w in enumerate(entry))
            changes.append(("phrase", " ".join(s.text for s in segment), " ".join(entry)))
        else:
            out.extend(segment)
        i += length
    return out


def _restore_unigrams(items: list[_Item], lexicon: Lexicon, changes: list) -> None:
    for item in items:
        if not _free(item) or not _wordlike(item.text) or len(item.text) < 2:
            continue
        low = item.text.lower()
        if low in lexicon.known:
            if item.text.isupper() and low != item.text:
                changes.append(("case", item.text, low))
                item.text = low
            continue
        key = fold(low)
        if low != key or key in lexicon.homographs:
            continue
        forms = lexicon.unigrams.get(key, frozenset())
        if len(forms) == 1:
            restored = next(iter(forms))
            changes.append(("diacritic", item.text, restored))
            item.text = restored
            item.locked = True


def _normalize_once(text: str, lexicon: Lexicon, teencode: Teencode,
                    protected_values: Iterable[str] | None) -> tuple[str, list]:
    changes: list[tuple[str, str, str]] = []
    items = _tokenize(text)
    _mark_protected(items, protected_values)
    items = _apply_teencode(items, teencode, changes)
    items = _repair_tokens(items, lexicon, changes)
    items = _restore_phrases(items, lexicon, changes)
    _restore_unigrams(items, lexicon, changes)
    return _join(items), changes


def normalize(text: str, lexicon: Lexicon, teencode: Teencode,
              protected_values: Iterable[str] | None = None, max_rounds: int = 4) -> NormResult:
    """Normalize to a fixed point so that normalize(normalize(x)) == normalize(x)."""
    protected = tuple(protected_values) if protected_values else ()
    current = clean(text)
    all_changes: list[tuple[str, str, str]] = []
    for _ in range(max_rounds):
        following, changes = _normalize_once(current, lexicon, teencode, protected)
        if following == current:
            break
        all_changes.extend(changes)
        current = following
    return NormResult(current, fold(current), tuple(all_changes))
