import json

from datamate.core import LinkResult

SYSTEM_PROMPT = (
    "You are a careful data analyst who writes DuckDB SQL over the data of one small Vietnamese business.\n"
    "The user message gives rules, then a JSON object: schema, business notes, resolved periods, linked entities "
    "and an informal Vietnamese question (slang, typos, missing diacritics are possible).\n"
    "Reply with exactly one DuckDB SELECT statement inside <sql></sql> tags and nothing else: "
    "no explanation, no markdown, no second statement.\n"
    "Checklist:\n"
    "- Use only tables, views and columns that appear in the schema; never invent names.\n"
    "- Use the resolved period dates literally (inclusive, e.g. d BETWEEN DATE '2026-04-01' AND DATE '2026-04-30'); "
    "never compute relative dates yourself.\n"
    "- Follow the rulebook definitions of revenue, cancelled/returned orders and best-selling; "
    "do not invent business rules that are not given.\n"
    "- Quantity questions use quantity, revenue questions use money amounts; do not mix them up.\n"
    "- Beware of JOINs that multiply rows; aggregate before joining when needed.\n"
    "- Output shape: one row and one column for a single value (number, name, date, boolean); "
    "one column ordered as asked for a list or top-N; several columns only for a table.\n"
    "- For 'thứ mấy' questions select weekday_vi (already a Vietnamese name); never return a weekday number.\n"
    "- A percent answer is the number in percent units (growth = 100.0 * (current - previous) / previous).\n"
    "- Use exact names and ids from the linked entities.\n"
    "- Rank with a deterministic tie-break: the rulebook's tie order if it gives one, otherwise the product/customer "
    "code ascending; LIMIT only as many rows as asked.\n"
)
BASE = ("Return one read-only DuckDB SELECT, no explanation. Never guess numerical answers.\n"
        "Use the provided resolved periods (inclusive dates); do not compute relative dates yourself.\n")
CANONICAL = ("Query only the v_* views listed in `schema.views`: they are already typed, de-duplicated and follow the "
             "rulebook (use v_sales for sales, quantity and revenue; do not re-apply cancelled/returned/duplicate rules). "
             "Use `linked_entities` ids and names verbatim and match the answer type in `expected_answer`.\n")

# Caps (characters) so the prompt always leaves room for the answer inside max_model_len.
# Vietnamese is roughly 2-3 characters per token, so 16000 characters stay near 6-7k tokens.
README_CHARS = 2000
RULEBOOK_CHARS = 3000
PROMPT_CHARS = 16000


# Percent questions come in several kinds (see intent_keywords.percent_kind). Each has one standard SQL
# shape; the model fills in the table, measure and filter. <P>/<C> are the resolved primary/comparison dates.
PERCENT_SHAPES = {
    "growth": ("Percent change vs the comparison period = 100 * (primary - comparison) / comparison (a drop is "
               "negative). Use exactly this shape and fill the <...> parts:\n"
               "WITH cur AS (SELECT SUM(<measure>) AS v FROM <table> WHERE <date column> BETWEEN <P>),\n"
               "     prev AS (SELECT SUM(<measure>) AS v FROM <table> WHERE <date column> BETWEEN <C>)\n"
               "SELECT 100.0 * (cur.v - prev.v) / NULLIF(prev.v, 0) FROM cur, prev"),
    "price_effect": ("Change in units sold after a price change = 100 * (primary - comparison) / comparison, with "
                     "the two resolved windows (<P> after, <C> before) and the named product only. Same shape as a "
                     "growth query using SUM(quantity in the base unit):\n"
                     "WITH cur AS (SELECT SUM(<qty>) AS v FROM <table> WHERE <product filter> AND <date column> "
                     "BETWEEN <P>),\n     prev AS (SELECT SUM(<qty>) AS v FROM <table> WHERE <product filter> "
                     "AND <date column> BETWEEN <C>)\n"
                     "SELECT 100.0 * (cur.v - prev.v) / NULLIF(prev.v, 0) FROM cur, prev"),
    "share": ("Share = 100 * part / whole over the same period; the whole is everything of that kind in the "
              "period, not only the part. Shape:\n"
              "SELECT 100.0 * SUM(CASE WHEN <part condition> THEN <measure> ELSE 0 END) / NULLIF(SUM(<measure>), 0) "
              "FROM <table> WHERE <date column> BETWEEN <P>"),
    "proportion": ("Proportion of customers = 100 * customers meeting the condition / all customers who bought "
                   "in the period (count each customer once). Shape: WITH per AS (SELECT <customer>, "
                   "COUNT(DISTINCT <order>) AS n FROM <table> WHERE <date column> BETWEEN <P> GROUP BY 1) "
                   "SELECT 100.0 * COUNT(*) FILTER (WHERE <condition on n>) / NULLIF(COUNT(*), 0) FROM per"),
    "rate": ("Rate = 100 * matching orders / ALL orders placed in the period, whatever their status (cancelled, "
             "returned and in-delivery orders are all in the denominator). Use the table with every order, not "
             "the valid-orders view. Shape:\n"
             "SELECT 100.0 * COUNT(*) FILTER (WHERE <status is the asked one>) / NULLIF(COUNT(*), 0) "
             "FROM <orders table> WHERE <date column> BETWEEN <P>"),
    "shift_compare": ("Compare two parts of the same period (morning vs afternoon shift): "
                      "100 * (first - second) / second where the second is the reference named last "
                      "(\"ca chiều so với ca sáng\" = (afternoon - morning) / morning)."),
}


def percent_shape(hints: dict, periods: list[dict]) -> str | None:
    """Shape instruction for a percent question, with the resolved dates filled in; None for other questions."""
    kind = (hints or {}).get("percent_kind")
    text = PERCENT_SHAPES.get(kind or "")
    if not text:
        return None
    by_role = {p["role"]: p for p in periods}
    for tag, role in (("<P>", "primary"), ("<C>", "comparison")):
        if role in by_role:
            text = text.replace(tag, f"DATE '{by_role[role]['start']}' AND DATE '{by_role[role]['end']}'")
    return text


def clip(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` characters on a line boundary, marking the cut."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if "\n" in cut:
        cut = cut[:cut.rindex("\n")]
    return cut + "\n...[truncated]"


def compact_schema(described: dict) -> dict:
    """Shrink `CanonicalSchema.describe()` for the prompt: one string per column ("name TYPE: meaning") and no
    `roles` (raw table/column names would only tempt the model to bypass the v_* views)."""
    views = {name: {"about": view["about"],
                    "columns": [f"{c['name']} {c['type']}" + (f": {c['meaning']}" if c.get("meaning") else "")
                                for c in view["columns"]]}
             for name, view in described["views"].items()}
    return {**{k: v for k, v in described.items() if k not in {"views", "roles"}}, "views": views}


def build_prompt(linked: LinkResult, caps: bool = True) -> str:
    """User prompt: rules + JSON. Stable parts come first so vLLM prefix caching can reuse them per business;
    the part that changes with every question comes last. With `caps=False` nothing is trimmed (measurement)."""
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
    readme, rulebook = context.readme, context.rulebook
    if caps:
        readme, rulebook = clip(readme, README_CHARS), clip(rulebook, RULEBOOK_CHARS)
    payload = {
        "schema": compact_schema(canonical.describe()) if canonical else context.profile,
        "readme": readme, "rulebook": rulebook, "as_of_date": question.as_of_date,
        "question": question.question,
        "original_question": question.question,
        "normalized_question": resolved.normalized or question.question,
        "periods": periods, "intent_hints": resolved.intent_hints,
    }
    shape = percent_shape(resolved.intent_hints, periods)
    if shape:
        payload["answer_shape"] = shape
    if canonical:
        payload["linked_entities"] = entities
        payload["expected_answer"] = expected
    head = BASE + (CANONICAL if canonical else "")
    text = head + json.dumps(payload, ensure_ascii=False, default=str)
    # Still too long: drop the free-text notes first (the schema, periods and question are never dropped).
    for key, keep in (("readme", 0), ("rulebook", RULEBOOK_CHARS // 3), ("rulebook", 0)):
        if not caps or len(text) <= PROMPT_CHARS:
            break
        payload[key] = clip(payload[key], keep) if keep else ""
        text = head + json.dumps(payload, ensure_ascii=False, default=str)
    return text
