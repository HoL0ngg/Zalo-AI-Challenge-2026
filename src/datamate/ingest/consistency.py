"""Cross-table consistency facts over the canonical views.

Only counts are produced, for logs and prompts; none of them blocks a question. Each check is
`None` (unknown) when the views it needs are missing or the query fails, and `0` when clean.
Counts are over the de-duplicated canonical views, so they are deterministic.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

import duckdb

CHECKS: dict[str, tuple[tuple[str, ...], str]] = {
    # Silently dropped from v_sales (it joins on valid orders).
    "lines_without_order": (("v_lines", "v_orders"),
                            "SELECT count(*) FROM v_lines l WHERE l.order_id IS NULL OR NOT EXISTS "
                            "(SELECT 1 FROM v_orders o WHERE o.order_id = l.order_id)"),
    "line_skus_not_in_products": (("v_lines", "v_products"),
                                  "SELECT count(DISTINCT l.sku) FROM v_lines l WHERE l.sku IS NOT NULL AND NOT EXISTS "
                                  "(SELECT 1 FROM v_products p WHERE p.sku = l.sku)"),
    # A blank customer (walk-in) is normal, only an id that points nowhere is a finding.
    "order_customers_not_in_customers": (("v_orders", "v_customers"),
                                         "SELECT count(*) FROM v_orders o WHERE o.customer_id IS NOT NULL AND NOT EXISTS "
                                         "(SELECT 1 FROM v_customers c WHERE c.customer_id = o.customer_id)"),
    # An unreadable date makes the order vanish from every query over a period.
    "orders_without_date": (("v_orders",), "SELECT count(*) FROM v_orders WHERE order_date IS NULL"),
}


def check_consistency(connection: duckdb.DuckDBPyConnection, views: Mapping[str, Any]) -> dict[str, int | None]:
    quality: dict[str, int | None] = {}
    for name, (needed, sql) in CHECKS.items():
        if not all(view in views for view in needed):
            quality[name] = None
            continue
        try:
            quality[name] = int(connection.execute(sql).fetchone()[0])
        except Exception as error:  # noqa: BLE001 - a check must never break ingest
            logging.warning("Consistency check %s failed: %s", name, error)
            quality[name] = None
    return quality


def issues(quality: Mapping[str, int | None]) -> dict[str, int]:
    """Only the findings (count > 0), in a stable order."""
    return {name: count for name, count in quality.items() if count}
