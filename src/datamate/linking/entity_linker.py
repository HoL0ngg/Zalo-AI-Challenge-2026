"""Entity linking: connect question mentions to values that really exist in the data.

Order of evidence (all deterministic, ties broken by score, kind order, then id):
 1. exact scan: longest n-gram whose accent-free key equals an indexed name, alias or id;
 2. glued codes ("KháchC0001"): letters directly before a digit run that equal an id;
 3. cue scan: text after "sản phẩm" / "khách" / ... that is not a function word is a mention;
    it is resolved with rapidfuzz plus guards (numbers and sizes must match exactly).
A mention that cannot be resolved is reported as missing only when it looks like a real name
(contains a digit or a word unknown to the Vietnamese lexicon), so generic phrases such as
"sản phẩm tồn kho" never produce a false `missing_entity`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from rapidfuzz import fuzz, process
from rapidfuzz.distance import DamerauLevenshtein

from datamate.core import Entity, Period
from datamate.linking.entity_index import KIND_ORDER, EntityIndex, entity_key
from datamate.understanding.textutil import fold

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
ACCEPT_SCORE = 0.85
AMBIGUOUS_SCORE = 0.70
MARGIN = 0.05
MAX_CUE_TOKENS = 8


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    raw: str
    key: str  # fold(raw)


@dataclass(frozen=True)
class LinkOutcome:
    entities: tuple[Entity, ...] = ()
    missing: tuple[dict, ...] = ()
    ambiguous: tuple[dict, ...] = ()


def _tokens(text: str) -> list[Token]:
    return [Token(m.start(), m.end(), m.group(), fold(m.group())) for m in WORD_RE.finditer(text)]


def _blocked(text: str, tokens: Sequence[Token], periods: Sequence[Period]) -> list[bool]:
    """Tokens inside resolved time mentions are not entity candidates."""
    folded = fold(text)
    mask = [False] * len(text)
    for period in periods:
        needle = fold(period.mention)
        position = folded.find(needle) if needle else -1
        while position != -1:
            for i in range(position, position + len(needle)):
                mask[i] = True
            position = folded.find(needle, position + len(needle))
    return [any(mask[t.start:t.end]) for t in tokens]


def _make_entity(index: EntityIndex, indices: Sequence[int], mention: str, score: float, match_type: str,
                 prefer_kind: str | None = None) -> Entity:
    ordered = sorted(indices, key=lambda i: (prefer_kind is not None and index.records[i].kind != prefer_kind,
                                             KIND_ORDER[index.records[i].kind], index.records[i].id))
    record = index.records[ordered[0]]
    alternatives = tuple((index.records[i].name, index.records[i].id, 1.0 if match_type != "fuzzy" else 0.0)
                         for i in ordered[1:5])
    names = sorted({record.name, record.id, *record.aliases})
    return Entity(mention, record.kind, record.id, record.name, round(score, 4), match_type, tuple(names), alternatives)


def _similar(a: str, b: str) -> float:
    """Token similarity in 0..1 that treats an adjacent-letter swap as a single edit."""
    return max(fuzz.ratio(a, b) / 100, DamerauLevenshtein.normalized_similarity(a, b))


def _is_match(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and _similar(a, b) >= 0.75) or (min(len(a), len(b)) < 4 and _similar(a, b) >= 0.8)


def _numbers(tokens: Sequence[str]) -> list[str]:
    return [t for t in tokens if any(c.isdigit() for c in t)]


def _fuzzy(mention: str, kind: str, index: EntityIndex) -> list[tuple[float, int]]:
    """Candidate records for a mention, best first: (score in 0..1, record index).

    Score = half string similarity + half token coverage in both directions (F1), so a short
    mention cannot match a long name just because it is a substring of it.
    """
    query = entity_key(mention)
    qtokens = query.split()
    if not qtokens:
        return []
    pool = index.choices(kind)
    if not pool:
        return []
    keys = [key for key, _ in pool]
    best: dict[int, float] = {}
    for key, _, position in process.extract(query, keys, scorer=fuzz.token_sort_ratio, limit=16, score_cutoff=45):
        ctokens = key.split()
        if any(n not in ctokens for n in _numbers(qtokens)):
            continue  # sizes and codes ("330ml", "d21") must match exactly
        base = max(_similar(query, key), fuzz.token_sort_ratio(query, key) / 100)
        precision = sum(1 for t in qtokens if any(_is_match(t, c) for c in ctokens)) / len(qtokens)
        recall = sum(1 for c in ctokens if any(_is_match(c, t) for t in qtokens)) / len(ctokens)
        coverage = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        score = 0.5 * base + 0.5 * coverage
        record = pool[position][1]
        best[record] = max(best.get(record, 0.0), score)
    return sorted(((s, r) for r, s in best.items()),
                  key=lambda item: (-item[0], KIND_ORDER[index.records[item[1]].kind], index.records[item[1]].id))


def _looks_like_name(tokens: Sequence[Token], is_known) -> bool:
    """A name-shaped mention: a size/code token (letters and digits) or a word nobody knows."""
    for t in tokens:
        has_digit, has_alpha = any(c.isdigit() for c in t.key), any(c.isalpha() for c in t.key)
        if has_digit and has_alpha:
            return True
        if not has_digit and not is_known(t.key):
            return True
    return False


def link_entities(text: str, periods: Sequence[Period], index: EntityIndex,
                  cues: Mapping[str, Sequence[str]], stopwords: frozenset[str], is_known) -> LinkOutcome:
    """Link mentions in `text`. `is_known(fold_token)` says whether a word is ordinary Vietnamese."""
    tokens = _tokens(text)
    if not tokens or not index.records:
        return LinkOutcome()
    blocked = _blocked(text, tokens, periods)
    covered = [False] * len(tokens)
    entities: list[Entity] = []
    ambiguous: list[dict] = []
    missing: list[dict] = []
    cue_list = sorted(((kind, tuple(phrase.split())) for kind, phrases in cues.items() for phrase in phrases),
                      key=lambda item: (-len(item[1]), item[0], item[1]))

    def starts_cue(i: int) -> bool:
        return any(tuple(t.key for t in tokens[i:i + len(phrase)]) == phrase for _, phrase in cue_list)

    def after_cue(i: int) -> str | None:
        for kind, phrase in cue_list:
            n = len(phrase)
            if i >= n and tuple(t.key for t in tokens[i - n:i]) == phrase:
                return kind
        return None

    # 1. exact scan, longest n-gram first
    for n in range(min(index.max_tokens, len(tokens)), 0, -1):
        for i in range(len(tokens) - n + 1):
            span = tokens[i:i + n]
            if any(blocked[i:i + n]) or any(covered[i:i + n]):
                continue
            key = " ".join(t.key for t in span)
            indices = index.exact.get(key)
            if not indices:
                continue
            cue_kind = after_cue(i)
            if n == 1 and not (key in index.id_keys and any(c.isdigit() for c in key)):
                # A single generic word is an entity only right after a cue of the same kind
                # ("sản phẩm Trà" must not match the category "Trà").
                indices = [i2 for i2 in indices if index.records[i2].kind == cue_kind] if cue_kind else []
                if not indices:
                    continue
            mention = text[span[0].start:span[-1].end]
            entity = _make_entity(index, indices, mention, 1.0, "exact", cue_kind)
            entities.append(entity)
            if len(indices) > 1 and len({index.records[j].id for j in indices}) > 1:
                ambiguous.append({"mention": mention, "candidates": [e[1] for e in entity.alternatives] + [entity.id]})
            for j in range(i, i + n):
                covered[j] = True

    # 2. codes glued to a word ("khachc0001")
    folded = fold(text)
    for run in re.finditer(r"\d{3,}", folded):
        run_start, run_end = run.span()
        if any(covered[j] or blocked[j] for j, t in enumerate(tokens) if t.start < run_end and t.end > run_start):
            continue
        for k in (3, 2, 1):
            start = run_start - k
            if start < 0 or not folded[start:run_start].isalpha():
                continue
            key = folded[start:run_end]
            indices = index.exact.get(key)
            if indices and key in index.id_keys:
                entities.append(_make_entity(index, indices, text[start:run_end], 0.98, "code"))
                for j, t in enumerate(tokens):
                    if t.start < run_end and t.end > start:
                        covered[j] = True
                break

    # 3. cue scan for mentions the exact scan did not resolve
    for kind, phrase in cue_list:
        n = len(phrase)
        for i in range(len(tokens) - n + 1):
            if tuple(t.key for t in tokens[i:i + n]) != phrase or any(blocked[i:i + n]):
                continue
            j = i + n
            while (j < len(tokens) and not blocked[j] and j - i - n < MAX_CUE_TOKENS
                   and (covered[j] or (tokens[j].key not in stopwords and not starts_cue(j)))):
                j += 1
            span = tokens[i + n:j]
            if not span or any(covered[i + n:j]):
                continue  # nothing there, or already resolved by exact/code evidence
            mention = text[span[0].start:span[-1].end]
            ranked = _fuzzy(mention, kind, index)
            if ranked and ranked[0][0] >= ACCEPT_SCORE and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= MARGIN):
                entities.append(_make_entity(index, [ranked[0][1]], mention, ranked[0][0], "fuzzy", kind))
            elif ranked and ranked[0][0] >= AMBIGUOUS_SCORE:
                entity = _make_entity(index, [r for _, r in ranked[:4]], mention, ranked[0][0], "fuzzy", kind)
                entities.append(entity)
                ambiguous.append({"mention": mention, "candidates": [entity.id] + [a[1] for a in entity.alternatives]})
            elif _looks_like_name(span, is_known):
                missing.append({"mention": mention, "kind": kind})
            else:
                continue  # a generic phrase, not an entity: neither linked nor missing
            for j2 in range(i + n, j):
                covered[j2] = True
    entities.sort(key=lambda e: (text.find(e.mention) if e.mention in text else len(text), e.id))
    return LinkOutcome(tuple(entities), tuple(missing), tuple(ambiguous))
