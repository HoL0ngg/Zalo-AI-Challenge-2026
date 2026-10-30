"""Facts read from the data itself: how much valid sales activity each resolved period holds, and
whether the sold products can be costed.

Only facts are produced; the gate decides what they mean. `None` always means "unknown" (the
canonical layer is incomplete or the query failed) and never blocks a question.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Sequence, TypeVar

import duckdb

from datamate.core import BusinessContext, Period

T = TypeVar("T")
UNCOSTED_LIMIT = 5   # enough to explain the finding in a log, not a dump


def _read(context: BusinessContext, needed_views: Sequence[str], query: Callable[[duckdb.DuckDBPyConnection], T],
          what: str) -> T | None:
    """Run `query` on a read-only connection when the canonical layer has `needed_views`; None otherwise."""
    canonical = context.canonical
    if canonical is None or not canonical.complete or not all(view in canonical.views for view in needed_views):
        return None
    connection = None
    try:
        connection = duckdb.connect(str(context.database), read_only=True, config={
            "enable_external_access": "false", "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false", "threads": "1", "memory_limit": "512MB"})
        return query(connection)
    except Exception as error:  # noqa: BLE001 - facts are best effort, never lose a question
        logging.warning("%s unavailable: %s", what, error)
        return None
    finally:
        if connection is not None:
            connection.close()


def period_stats(context: BusinessContext, periods: Sequence[Period]) -> list[dict[str, Any]] | None:
    """One `{role, label, rows, revenue, qty}` per period, in mention order, over `v_sales`
    (inclusive date bounds, read-only connection)."""
    if not periods:
        return None

    def query(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        stats = []
        for period in periods:
            rows, revenue, qty = connection.execute(
                "SELECT count(*), COALESCE(sum(revenue), 0), COALESCE(sum(qty), 0) FROM v_sales "
                "WHERE sale_date BETWEEN ? AND ?", [period.start, period.end]).fetchone()
            stats.append({"role": period.role, "label": period.label, "rows": int(rows),
                          "revenue": float(revenue), "qty": float(qty)})
        return stats
    return _read(context, ("v_sales",), query, "period stats")


def uncosted_skus(context: BusinessContext, period: Period, as_of: date) -> list[str] | None:
    """SKUs sold in `period` that have no purchase lot with a known cost received on or before `as_of`
    (sorted, at most UNCOSTED_LIMIT). `[]` = every sold SKU can be costed; None = unknown."""
    def query(connection: duckdb.DuckDBPyConnection) -> list[str]:
        rows = connection.execute(
            "SELECT DISTINCT s.sku FROM v_sales s WHERE s.sale_date BETWEEN ? AND ? AND s.sku IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM v_purchases p WHERE p.sku = s.sku AND p.purchase_date <= ? "
            "AND p.qty > 0 AND p.unit_cost IS NOT NULL) ORDER BY s.sku LIMIT ?",
            [period.start, period.end, as_of, UNCOSTED_LIMIT]).fetchall()
        return [row[0] for row in rows]
    return _read(context, ("v_sales", "v_purchases"), query, "uncosted skus")
