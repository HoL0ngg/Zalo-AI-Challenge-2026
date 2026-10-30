"""Question Understanding stage: normalizer + temporal resolver + intent hints.

`understand` never raises: any failure is recorded in `warnings` and the question falls
back to a pass-through ResolvedQuestion, so a bad question can never crash the run.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, Mapping

from datamate.core import BusinessContext, Period, Question, ResolvedQuestion
from datamate.understanding.intent import intent_hints
from datamate.understanding.normalizer import build_lexicon, build_teencode, normalize
from datamate.understanding.resources import (load_homographs, load_lexicon, load_rule_defaults,
                                              load_teencode)
from datamate.understanding.temporal import parse_rule_params, remove_mentions, resolve_periods
from datamate.understanding.textutil import clean, fold

__all__ = ["understand", "understand_stub", "protected_from_profile", "remove_mentions", "periods_to_dicts"]

_MAX_PROTECTED = 5000


def protected_from_profile(profile: Mapping[str, Any] | None) -> list[str]:
    """Entity-like string values the profiler exposes (at most five samples per column).

    The full value dictionary arrives with entity linking; until then only these samples
    are protected from normalization.
    """
    values: list[str] = []
    for table in (profile or {}).values():
        for column in (table or {}).get("columns", []):
            for sample in column.get("samples") or []:
                if isinstance(sample, str) and len(values) < _MAX_PROTECTED:
                    values.append(sample)
    return values


def periods_to_dicts(periods: Iterable[Period]) -> list[dict[str, str]]:
    return [{"label": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(),
             "role": p.role, "mention": p.mention} for p in periods]


def understand(question: Question, context: BusinessContext,
               protected_values: Iterable[str] | None = None) -> ResolvedQuestion:
    warnings: list[str] = []
    text = question.question
    resolved = ResolvedQuestion(question, normalized=clean(text), normalized_ascii=fold(clean(text)))
    try:
        defaults = load_rule_defaults()
    except Exception as error:  # noqa: BLE001
        warnings.append(f"understanding_error:rule_defaults:{type(error).__name__}: {error}")
        defaults = {}

    try:
        params, sources, rule_warnings = parse_rule_params(context.rulebook, defaults)
        warnings.extend(rule_warnings)
        resolved.rule_params = {**params, "rule_sources": sources}
    except Exception as error:  # noqa: BLE001
        warnings.append(f"understanding_error:rule_params:{type(error).__name__}: {error}")
        params = None

    try:
        lexicon_entries, teencode_raw = load_lexicon(), load_teencode()
        if not lexicon_entries:
            warnings.append("lexicon_missing")
        if not teencode_raw:
            warnings.append("teencode_dict_missing")
        if protected_values is None:
            protected_values = context.protected_values or protected_from_profile(context.profile)
        result = normalize(text, build_lexicon_cached(tuple(lexicon_entries), tuple(sorted(load_homographs()))),
                           build_teencode_cached(teencode_raw), protected_values)
        resolved.normalized, resolved.normalized_ascii = result.normalized, result.normalized_ascii
    except Exception as error:  # noqa: BLE001
        warnings.append(f"understanding_error:normalizer:{type(error).__name__}: {error}")

    if params is not None:
        try:
            periods, time_warnings = resolve_periods(resolved.normalized, question.as_of_date, params,
                                                     context.calendar)
            resolved.periods = periods
            warnings.extend(time_warnings)
        except Exception as error:  # noqa: BLE001
            warnings.append(f"understanding_error:temporal:{type(error).__name__}: {error}")

    try:
        resolved.intent_hints = intent_hints(resolved.normalized_ascii, defaults.get("intent_keywords"))
    except Exception as error:  # noqa: BLE001
        warnings.append(f"understanding_error:intent:{type(error).__name__}: {error}")

    resolved.warnings = warnings
    return resolved


# Building the lexicon/teencode indexes is a pure function of the bundled files; cache it.
@lru_cache(maxsize=4)
def build_lexicon_cached(entries: tuple[str, ...], homographs: tuple[str, ...]):
    return build_lexicon(entries, homographs)


@lru_cache(maxsize=4)
def _teencode_cached(items: tuple[tuple[str, tuple[str, ...]], ...]):
    return build_teencode(dict(items))


def build_teencode_cached(raw: Mapping[str, tuple[str, ...]]):
    return _teencode_cached(tuple(sorted(raw.items())))


def understand_stub(question: Question, context: BusinessContext) -> ResolvedQuestion:
    """Backward-compatible alias; the stage is no longer a stub."""
    return understand(question, context)
