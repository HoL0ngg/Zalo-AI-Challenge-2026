"""Entity and schema linking stage. `link` never raises; failures are recorded in `flags`."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from rapidfuzz import fuzz, process

from datamate.core import BusinessContext, LinkResult, ResolvedQuestion
from datamate.linking.entity_linker import link_entities
from datamate.linking.schema_linker import link_schema
from datamate.understanding import build_lexicon_cached
from datamate.understanding.resources import load_homographs, load_lexicon, load_schema_roles

__all__ = ["link", "link_stub", "link_to_log"]


def _is_known_word(index):
    """Known = Vietnamese lexicon or in-domain word of this business, allowing a typo (ratio >= 82)."""
    lexicon = build_lexicon_cached(tuple(load_lexicon()), tuple(sorted(load_homographs())))
    words = sorted(lexicon.fold_keys | (index.vocabulary if index is not None else frozenset()))

    def known(key: str) -> bool:
        if key in lexicon.fold_keys or (index is not None and key in index.vocabulary):
            return True
        return len(key) >= 4 and process.extractOne(key, words, scorer=fuzz.ratio, score_cutoff=82) is not None
    return known


def link(resolved: ResolvedQuestion, context: BusinessContext) -> LinkResult:
    result = LinkResult(resolved, context)
    flags: dict[str, Any] = {"missing_entity": False, "ambiguous": False, "missing_mentions": [],
                             "ambiguous_mentions": [], "missing_capability": [], "period_outside_data": [],
                             "period_stats": None, "uncosted_skus": None, "errors": []}
    config = load_schema_roles()
    if context.entities is not None:
        try:
            cues = config.get("mention_cues", {})
            stopwords = frozenset(config.get("mention_stopwords", []))
            outcome = link_entities(resolved.normalized or resolved.question.question, resolved.periods,
                                    context.entities, cues, stopwords, _is_known_word(context.entities))
            result.entities = list(outcome.entities)
            flags.update(missing_entity=bool(outcome.missing), ambiguous=bool(outcome.ambiguous),
                         missing_mentions=list(outcome.missing), ambiguous_mentions=list(outcome.ambiguous))
        except Exception as error:  # noqa: BLE001 - never lose a question to linking
            flags["errors"].append(f"entity:{type(error).__name__}: {error}")
    try:
        schema, schema_flags = link_schema(resolved, context, config.get("concepts", {}), result.entities)
        result.schema = schema
        flags.update(schema_flags)
    except Exception as error:  # noqa: BLE001
        flags["errors"].append(f"schema:{type(error).__name__}: {error}")
    result.flags = flags
    return result


link_stub = link  # backward-compatible name


def link_to_log(linked: LinkResult) -> dict[str, Any]:
    return {"entities": [asdict(e) for e in linked.entities], "schema": linked.schema, "flags": linked.flags}
