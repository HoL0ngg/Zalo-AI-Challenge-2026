import json

from datamate.core import LinkResult

BASE = ("Return one read-only DuckDB SELECT, no explanation. Never guess numerical answers.\n"
        "Use the provided resolved periods (inclusive dates); do not compute relative dates yourself.\n")
CANONICAL = ("Query only the v_* views listed in `schema.views`: they are already typed, de-duplicated and follow the "
             "rulebook (use v_sales for sales, quantity and revenue; do not re-apply cancelled/returned/duplicate rules). "
             "Use `linked_entities` ids and names verbatim and match the answer type in `expected_answer`.\n")


def build_prompt(linked: LinkResult) -> str:
    resolved = linked.resolved
    question = resolved.question
    context = linked.context
    canonical = context.canonical if (context.canonical is not None and context.canonical.complete) else None
    periods = [{"label": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(), "role": p.role}
               for p in resolved.periods]
    entities = [{"mention": e.mention, "kind": e.kind, "id": e.id, "name": e.matched, "score": e.score,
                 "alternatives": [{"name": n, "id": i} for n, i, _ in e.alternatives]}
                for e in linked.entities]
    expected = {k: v for k, v in ((linked.schema or {}).get("expected") or {}).items() if k != "force_type"}
    payload = {
        "schema": canonical.describe() if canonical else context.profile,
        "readme": context.readme, "rulebook": context.rulebook, "as_of_date": question.as_of_date,
        "question": question.question,
        "original_question": question.question,
        "normalized_question": resolved.normalized or question.question,
        "periods": periods, "intent_hints": resolved.intent_hints,
    }
    if canonical:
        payload["linked_entities"] = entities
        payload["expected_answer"] = expected
    return BASE + (CANONICAL if canonical else "") + json.dumps(payload, ensure_ascii=False, default=str)
