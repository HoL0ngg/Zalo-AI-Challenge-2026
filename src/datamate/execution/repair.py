"""Self-repair of SQL that failed to execute.

Two layers, cheapest first:
1. `quick_fix`: deterministic rewrites for errors where the model tends to copy its own mistake back
   (a statement that names `v_sales.col` but has no FROM clause).
2. `repair`: ask the model again with the error, a diagnosis of that error class, the real columns of the
   tables involved and the earlier failed attempts, so it does not repeat itself.
"""
import re
from collections.abc import Sequence

import sqlglot
from rapidfuzz import fuzz
from sqlglot import exp

from datamate.codegen.generator import apply_expected
from datamate.codegen.prompt_builder import build_prompt
from datamate.core import Candidate, ExecResult, LinkResult
from datamate.llm.base import LLMBackend

_MISSING_TABLE = re.compile(r'Referenced table "([^"]+)" not found')
_MISSING_COLUMN = re.compile(r'(?:does not have a column named|Referenced column) "([^"]+)"')
_AMBIGUOUS = re.compile(r'Ambiguous reference to column name "([^"]+)"')
_NO_TABLE = re.compile(r'(?:Table|View) with name (\S+) does not exist')
MAX_COLUMNS = 40          # columns listed per table in the repair prompt
MAX_ERROR_CHARS = 400


def _squash(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip().rstrip(";").lower()


def available_columns(linked: LinkResult) -> dict[str, list[str]]:
    """Table/view -> column names the model may use (canonical views when mapped, else the raw profile)."""
    context = linked.context
    canonical = context.canonical
    if canonical is not None and canonical.complete:
        return {name: [c for c, _ in columns] for name, columns in canonical.views.items()}
    return {name: [c["name"] for c in table["columns"]] for name, table in (context.profile or {}).items()}


def _qualifiers(tree: exp.Expression) -> set[str]:
    return {column.table for column in tree.find_all(exp.Column) if column.table}


_PROTECTED = re.compile(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")")


def quote_known_identifiers(code: str, columns: dict[str, list[str]]) -> str:
    """Double-quote table/column names that need it ("Thành tiền", "02.2025") wherever the model left them bare.

    Only names that really exist in the schema are touched, longest first, outside string literals and
    already-quoted identifiers, so it cannot change what a correct statement means.
    """
    names = {n for table, cols in columns.items() for n in (table, *cols)}
    needy = sorted((n for n in names if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n)), key=lambda n: (-len(n), n))
    if not needy:
        return code
    parts = _PROTECTED.split(code)
    for i in range(0, len(parts), 2):          # even parts are outside quotes
        for name in needy:
            parts[i] = re.sub(rf"(?<![\w\"]){re.escape(name)}(?![\w\"])", '"' + name.replace('"', '""') + '"', parts[i])
    return "".join(parts)


def quick_fix(failed: ExecResult) -> Candidate | None:
    """`SELECT SUM(v_sales.x) ...` with no FROM: add `FROM v_sales` when exactly one table is qualified.

    Only the top-level SELECT is touched and only when it has no FROM at all; anything ambiguous goes to the
    model. The rewritten statement is executed like any other candidate, so a wrong guess just fails again.
    """
    match = _MISSING_TABLE.search(failed.error or "")
    if not match:
        return None
    try:
        tree = sqlglot.parse_one(failed.candidate.code, read="duckdb")
    except sqlglot.errors.SqlglotError:
        return None
    if not isinstance(tree, exp.Select) or tree.args.get("from"):
        return None
    names = _qualifiers(tree) - {cte.alias for cte in tree.find_all(exp.CTE)}
    if names != {match.group(1)}:
        return None
    tree.set("from", exp.From(this=exp.to_table(match.group(1))))
    fixed = Candidate(tree.sql(dialect="duckdb"), failed.candidate.answer_type, failed.candidate.unit,
                      dict(failed.candidate.meta))
    fixed.meta["repair"] = "deterministic:missing_from"
    return fixed


def diagnose(error: str, code: str, columns: dict[str, list[str]]) -> list[str]:
    """Plain-language hints for the error classes seen in real runs."""
    hints: list[str] = []
    if match := _MISSING_TABLE.search(error):
        name = match.group(1)
        hints.append(f'`{name}.` is used but `{name}` is not in any FROM/JOIN of the statement. Every qualified '
                     "name must come from a table listed in FROM; a statement without FROM cannot read columns.")
    if match := _MISSING_COLUMN.search(error):
        wanted = match.group(1)
        near = sorted(((fuzz.WRatio(wanted, f"{t}.{c}"), t, c) for t, cs in columns.items() for c in cs),
                      key=lambda item: (-item[0], item[1], item[2]))[:3]
        if near:
            hints.append(f'Column "{wanted}" does not exist where you used it. Closest real columns: '
                         + ", ".join(f"{t}.{c}" for _, t, c in near)
                         + ". Join the table that owns the column instead of guessing a name.")
    if match := _AMBIGUOUS.search(error):
        hints.append(f'Column "{match.group(1)}" exists in several joined tables: prefix it with a table alias.')
    if "must appear in the GROUP BY" in error:
        hints.append("Every non-aggregated selected column must be in GROUP BY, or wrap it in an aggregate.")
    if match := _NO_TABLE.search(error):
        hints.append(f"Table {match.group(1)} does not exist. Use only: " + ", ".join(sorted(columns)) + ".")
    if "Conversion Error" in error or "Could not convert" in error:
        hints.append("A text column is being used as a number or date: use TRY_CAST(... AS DOUBLE/DATE).")
    return hints


def _schema_note(columns: dict[str, list[str]], code: str) -> str:
    """Columns of the tables named in the failed SQL (all tables if none is recognisable), capped."""
    used = [t for t in columns if re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", code)] or list(columns)
    lines = []
    for table in used[:8]:
        cols = columns[table]
        extra = f", ... (+{len(cols) - MAX_COLUMNS})" if len(cols) > MAX_COLUMNS else ""
        lines.append(f"{table}({', '.join(cols[:MAX_COLUMNS])}{extra})")
    return "\n".join(lines)


def repair_prompt(linked: LinkResult, failed: ExecResult, history: Sequence[ExecResult] = ()) -> str:
    columns = available_columns(linked)
    error = (failed.error or "")[:MAX_ERROR_CHARS]
    parts = [build_prompt(linked), f"\nRepair this SQL:\n{failed.candidate.code}\nError: {error}"]
    hints = diagnose(failed.error or "", failed.candidate.code, columns)
    if hints:
        parts.append("Diagnosis:\n" + "\n".join(f"- {hint}" for hint in hints))
    if columns:
        parts.append("Columns that really exist:\n" + _schema_note(columns, failed.candidate.code))
    earlier = [r for r in history if r is not failed]
    if earlier:
        parts.append("Earlier attempts that also failed (do not repeat them):\n"
                     + "\n".join(f"- {r.candidate.code.strip()[:300]} -> {(r.error or '')[:120]}" for r in earlier[-2:]))
    parts.append("Reply with the corrected statement inside <sql></sql> tags.")
    return "\n".join(parts)


def repair(linked: LinkResult, failed: ExecResult, backend: LLMBackend,
           history: Sequence[ExecResult] = ()) -> Candidate:
    prompt = repair_prompt(linked, failed, history)
    seen = {_squash(r.candidate.code) for r in (*history, failed)}
    candidate = apply_expected(backend.generate(prompt, linked), linked)
    if _squash(candidate.code) in seen:  # the model copied a failed statement: say so once and ask again
        prompt += "\nYour previous reply repeated a failed statement. Change it so the error above cannot happen."
        candidate = apply_expected(backend.generate(prompt, linked), linked)
    candidate.meta["repair"] = "llm"
    return candidate
