"""Schema linking: which view/metric/date column a question needs, and what the data lacks.

Only facts are produced here. `flags` says what is provably missing (a concept the business
cannot provide, a period outside the data range); the gate decides what to do with it.
"unknown" is never "missing": when the canonical layer could not map the business (complete is
False) no capability flag is raised, so a mapping failure can never block a question.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping, Sequence

from datamate.core import BusinessContext, Entity, Period, ResolvedQuestion
from datamate.ingest.canonical import _match_score
from datamate.linking.data_facts import period_stats, uncosted_skus

METRIC_COLUMN = {
    "quantity": "v_sales.qty", "revenue": "v_sales.revenue", "profit": "v_sales.revenue - cost of goods",
    "debt": "v_debts.amount", "stock": "v_purchases.qty - sold qty", "expiry": "v_purchases.expiry_date",
}
DATE_COLUMN = {"expiry": "v_purchases.expiry_date", "debt": "v_debts.debt_date", "stock": "v_purchases.purchase_date"}
MONEY_METRICS = {"revenue", "profit", "debt"}
TABLE_RE = re.compile(r"(?:lap|ve|ke)\s+bang|bang\s+(?:cac|danh sach|thong ke|khach)|dang bang")
LIST_RE = re.compile(r"liet ke|danh sach")


def detect_needs(ascii_text: str, concepts: Mapping[str, Any]) -> list[str]:
    return [name for name, spec in concepts.items()
            if any(re.search(keyword, ascii_text) for keyword in spec.get("keywords", []))]


def _raw_provides(raw_columns: Sequence[str], names: Sequence[str]) -> bool:
    return any(_match_score(column, names) >= 2 for column in raw_columns)


def expected_answer(hints: Mapping[str, Any], ascii_text: str) -> dict[str, Any]:
    """Expected answer kind from intent. `force_type` is set only when the result shape alone
    cannot tell (percent, list, table); other types are inferred from the query result."""
    operation, metric = hints.get("operation", "none"), hints.get("metric", "none")
    expected: dict[str, Any] = {}
    if operation == "compare_percent":
        expected = {"type": "percent", "force_type": True}
    elif operation == "topN" or LIST_RE.search(ascii_text):
        expected = {"type": "list", "force_type": True}
    elif TABLE_RE.search(ascii_text):
        expected = {"type": "table", "force_type": True}
    elif operation == "exists":
        expected = {"type": "boolean"}
    elif operation == "date_of_max":
        expected = {"type": "date"}
    elif operation in {"top1", "bottom1"}:
        expected = {"type": "string"}
    elif operation == "count":
        expected = {"type": "number", "unit": "count"}
    elif operation == "avg":
        expected = {"type": "number"}
    elif metric in MONEY_METRICS:
        expected = {"type": "number", "unit": "VND"}
    elif metric == "quantity":
        expected = {"type": "number", "unit": "count"}
    if (expected.get("type") == "list" or expected.get("type") == "table") and "unit" in expected:
        expected.pop("unit")
    return expected


def link_schema(resolved: ResolvedQuestion, context: BusinessContext, concepts: Mapping[str, Any],
                entities: Sequence[Entity] = ()) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical = context.canonical
    complete = bool(canonical is not None and canonical.complete)
    capabilities = dict(canonical.capabilities) if complete else {}
    raw_columns = [c["name"] for table in context.profile.values() for c in table["columns"]]
    ascii_text = resolved.normalized_ascii or ""
    hints = resolved.intent_hints or {}

    needs = detect_needs(ascii_text, concepts)
    missing: list[str] = []
    reasons: dict[str, str] = {}
    if complete:
        for name in needs:
            spec = concepts[name]
            capability = spec.get("capability")
            if capability is not None:
                available = capabilities.get(capability)
                if available is None:
                    continue
            else:
                available = False
            if not available and not _raw_provides(raw_columns, spec.get("column_names", [])):
                missing.append(name)
                reasons[name] = spec.get("reason", "")

    metric = hints.get("metric", "none")
    uses_sales = metric not in {"debt", "expiry", "stock"} and not {"debt", "expiry"} & set(needs)
    outside: list[str] = []
    span = capabilities.get("date_range") if complete else None
    if span and uses_sales:
        low, high = date.fromisoformat(span[0]), date.fromisoformat(span[1])
        outside = [p.label for p in resolved.periods if p.role == "primary" and (p.end < low or p.start > high)]
    # Only ranking, average and growth questions can be undefined on an empty period, so only they pay for the query.
    needs_stats = hints.get("operation") in {"top1", "bottom1", "date_of_max", "avg", "compare_percent"}
    stats = period_stats(context, resolved.periods) if complete and uses_sales and needs_stats and not outside else None
    # Profit needs a cost for every product sold in the period; "some lot has a cost" (has_cost) is not enough.
    primary_period = next((p for p in resolved.periods if p.role == "primary"), None)
    uncosted = None
    if (complete and metric == "profit" and capabilities.get("has_cost") is True
            and primary_period is not None and not outside):
        uncosted = uncosted_skus(context, primary_period, resolved.question.as_of_date)

    views = sorted(canonical.views) if complete else []
    primary = metric if metric != "none" else None
    schema = {
        "canonical": complete,
        "views": views,
        "metric": METRIC_COLUMN.get(metric),
        "date_col": DATE_COLUMN.get(metric, "v_sales.sale_date" if complete else None),
        "tables": ([DATE_COLUMN[primary].split(".")[0]] if primary in DATE_COLUMN else (["v_sales"] if complete else [])),
        "needs": needs,
        "expected": expected_answer(hints, ascii_text),
    }
    flags = {"missing_capability": missing, "missing_capability_reasons": reasons, "period_outside_data": outside,
             "period_stats": stats, "uncosted_skus": uncosted}
    return schema, flags
