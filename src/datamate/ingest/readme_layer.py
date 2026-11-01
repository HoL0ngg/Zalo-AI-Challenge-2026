"""README-driven canonical sales layer.

The official packages are POS exports with a different shape per business (flat file, order + line
files, one sheet per month, ...), but every README documents its columns as "- **<column>**: <meaning>"
with standardised meanings. This module reads those meanings, finds the table of sale lines (plus an
optional order table), and builds the same views the rest of the pipeline uses:
v_sales, v_orders, v_valid_orders, v_lines, v_products, v_customers.

Nothing here names a business, a file or a column: bindings come from the README of the package being
answered and from the regexes in configs/readme_columns.yaml.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb
import yaml

from datamate.ingest.canonical import (DATE_TYPES, NUMERIC_TYPES, CanonicalSchema, _create, _is, _number, _text,
                                       business_flags, weekday_sql)
from datamate.ingest.profiler import quote
from datamate.understanding.resources import repo_root

MIN_DOC_OVERLAP = 0.6      # share of a README file's documented columns that must exist in the table


@lru_cache(maxsize=1)
def _config(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_config(root: Path | None = None) -> dict[str, Any]:
    return _config(str((root or repo_root()) / "configs" / "readme_columns.yaml"))


# ------------------------------------------------------------------ README parsing

_SECTION = re.compile(r"^## Cột trong `([^`]+)`(?:, sheet `([^`]+)`)?", re.M)
_ITEM = re.compile(r"^- \*\*(.+?)\*\*: (.+)$")


def readme_columns(readme: str) -> dict[str, dict[str, str]]:
    """{file: {column: meaning (lowercase)}} from the "## Cột trong `file`" sections (sheets of one file merged)."""
    docs: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in (readme or "").splitlines():
        header = _SECTION.match(line)
        if header:
            current = f"{header.group(1)}#{header.group(2)}" if header.group(2) else header.group(1)
            docs.setdefault(current, {})
        elif line.startswith("## "):
            current = None
        elif current:
            item = _ITEM.match(line)
            if item:
                docs[current].setdefault(item.group(1).strip(), item.group(2).strip().lower())
    return {file: cols for file, cols in docs.items() if cols}


def concept_of(meaning: str, config: Mapping[str, Any]) -> str | None:
    for concept, patterns in (config.get("concepts") or {}).items():
        if any(re.search(pattern, meaning) for pattern in patterns):
            return concept
    return None


def bind_tables(profile: Mapping[str, Mapping[str, Any]], docs: Mapping[str, Mapping[str, str]],
                config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """{table: {concept: column}} for tables that match a documented file.

    A table matches the documented file whose columns it contains best (not by name: merged sheets and
    clashing names change table names). At least MIN_DOC_OVERLAP of the documented columns must exist.
    """
    bound: dict[str, dict[str, str]] = {}
    for table, info in profile.items():
        columns = [c["name"] for c in info["columns"]]
        best, best_key = None, (0.0, 0)
        for file in sorted(docs):
            present = [c for c in docs[file] if c in columns]
            share = len(present) / len(docs[file])
            if share >= MIN_DOC_OVERLAP and (share, len(present)) > best_key:
                best, best_key = file, (share, len(present))
        if best is None:
            continue
        concepts: dict[str, str] = {}
        for column in columns:
            meaning = docs[best].get(column)
            concept = concept_of(meaning, config) if meaning else None
            if concept and concept not in concepts:
                concepts[concept] = column
        bound[table] = concepts
    return bound


def choose_lines(bound: Mapping[str, Mapping[str, str]], profile: Mapping[str, Mapping[str, Any]]) -> str | None:
    """The table of sale lines: has an item, a quantity and an amount (or a unit price)."""
    best: tuple[int, int, str] | None = None
    for table, concepts in bound.items():
        has_item = "product_name" in concepts or "sku" in concepts
        has_qty = "qty" in concepts or "qty_base" in concepts
        has_money = "line_amount" in concepts or "unit_price" in concepts
        if not (has_item and has_qty and has_money):
            continue
        key = (len(concepts), int(profile[table].get("rows") or 0), table)
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2] if best else None


def choose_order_list(bound: Mapping[str, Mapping[str, str]], profile: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Packages that list only orders (no item lines): the order table with an id, a date and a goods total."""
    best: tuple[int, str] | None = None
    for table, concepts in bound.items():
        if not {"order_id", "date", "order_total"} <= set(concepts):
            continue
        key = (int(profile[table].get("rows") or 0), table)
        if best is None or key > best:
            best = key
    return best[1] if best else None


def choose_orders(bound: Mapping[str, Mapping[str, str]], profile: Mapping[str, Mapping[str, Any]],
                  lines: str) -> str | None:
    """A separate table of orders, only when the line table lacks the date or the order id to join on."""
    own = bound[lines]
    if "order_id" not in own or "date" in own:
        return None
    best: tuple[int, str] | None = None
    for table, concepts in bound.items():
        if table == lines or "order_id" not in concepts or "date" not in concepts:
            continue
        if "product_name" in concepts or "sku" in concepts:
            continue
        key = (int(profile[table].get("rows") or 0), table)
        if best is None or key > best:
            best = key
    return best[1] if best else None


# ------------------------------------------------------------------ SQL expressions

def norm_sql(expr: str) -> str:
    """Lowercase, diacritic-free text for status/name matching."""
    return f"replace(strip_accents(lower(trim(CAST({expr} AS VARCHAR)))), 'đ', 'd')"


def date_sql(column: str, dtype: str, slash: str, year_hint: str | None) -> str:
    """Date from ISO / dd/mm/yyyy / dd-mm-yyyy / '1 thg 6 2025' text, native dates, Excel serial numbers and
    day/month without a year (year taken from the sheet name when there is one)."""
    q = quote(column)
    if _is(dtype, DATE_TYPES):
        return f"CAST({q} AS DATE)"
    s = f"trim(CAST({q} AS VARCHAR))"
    serial = f"TRY_CAST({s} AS DOUBLE)"
    parts = [f"CAST(TRY_STRPTIME(substr({s}, 1, 10), '%Y-%m-%d') AS DATE)",
             f"CAST(TRY_STRPTIME(substr({s}, 1, 10), '{slash}') AS DATE)",
             f"CAST(TRY_STRPTIME({s}, '%d-%m-%Y') AS DATE)", f"CAST(TRY_STRPTIME({s}, '%d.%m.%Y') AS DATE)",
             f"CAST(TRY_STRPTIME({s}, '%d thg %m %Y') AS DATE)",
             f"CASE WHEN {serial} BETWEEN 20000 AND 80000 THEN DATE '1899-12-30' + CAST(floor({serial}) AS INTEGER) END"]
    if year_hint:
        parts.append(f"CASE WHEN regexp_matches({s}, '^[0-9]{{1,2}}/[0-9]{{1,2}}$') THEN "
                     f"CAST(TRY_STRPTIME({s} || '/' || {year_hint}, '%d/%m/%Y') AS DATE) END")
    return "COALESCE(" + ", ".join(parts) + ")"


def qty_sql(column: str, dtype: str) -> str:
    """Quantity from numbers or text such as '5 kg', '3 thùng', '2,5'."""
    q = quote(column)
    if _is(dtype, NUMERIC_TYPES):
        return f"CAST({q} AS DOUBLE)"
    lead = f"regexp_extract(trim(CAST({q} AS VARCHAR)), '^-?[0-9]+(?:[.,][0-9]+)?', 0)"
    return f"COALESCE(TRY_CAST(replace({lead}, ',', '.') AS DOUBLE), {_number(column, dtype)})"


def _any(patterns: Sequence[str], expr: str) -> str:
    if not patterns:
        return "false"
    return "(" + " OR ".join(f"regexp_matches({expr}, '{p}')" for p in patterns) + ")"


# ------------------------------------------------------------------ the layer

def build_readme_layer(connection: duckdb.DuckDBPyConnection, profile: Mapping[str, Mapping[str, Any]],
                       readme: str, rulebook: str, schema: CanonicalSchema,
                       config: Mapping[str, Any] | None = None) -> bool:
    """Create the canonical views from the README bindings; returns True and marks `schema` complete on success.

    Leaves `schema` untouched when the README documents no usable line table or a view fails.
    """
    config = config if config is not None else load_config()
    docs = readme_columns(readme)
    if not docs:
        return False
    bound = bind_tables(profile, docs, config)
    lines = choose_lines(bound, profile)
    order_list = False
    if lines is None:
        lines = choose_order_list(bound, profile)
        order_list = lines is not None
    if lines is None:
        return False
    orders = None if order_list else choose_orders(bound, profile, lines)
    types = {t: {c["name"]: str(c["type"]) for c in profile[t]["columns"]} for t in (lines, orders) if t}
    own = bound[lines]

    def column(table: str, concept: str) -> str | None:
        return bound[table].get(concept)

    sheet = "_sheet" if "_sheet" in types[lines] else None
    year_hint = f"regexp_extract(CAST({quote(sheet)} AS VARCHAR), '(20[0-9]{{2}})', 1)" if sheet else None
    slash = _slash(connection, [(t, column(t, "date"), types[t][column(t, "date")]) for t in (lines, orders)
                                if t and column(t, "date")])

    def order_level(table: str) -> dict[str, str]:
        out = {}
        for concept, kind in (("date", "date"), ("status", "text"), ("customer_name", "text"), ("customer_id", "text")):
            source = column(table, concept)
            if source is None:
                continue
            dtype = types[table][source]
            out[concept] = (date_sql(source, dtype, slash, year_hint if table == lines else None)
                            if kind == "date" else _text(source))
        return out

    q_lines = quote(lines)
    order_id = _text(own["order_id"]) if "order_id" in own else "'L' || CAST(rowid AS VARCHAR)"
    qty_line = qty_sql(own["qty"], types[lines][own["qty"]]) if "qty" in own else ("1.0" if order_list else None)
    qty_base = qty_sql(own["qty_base"], types[lines][own["qty_base"]]) if "qty_base" in own else None
    qty = f"COALESCE({qty_base}, {qty_line})" if qty_base and qty_line else (qty_base or qty_line)
    price = _number(own["unit_price"], types[lines][own["unit_price"]]) if "unit_price" in own else "CAST(NULL AS DOUBLE)"
    discount = _number(own["discount"], types[lines][own["discount"]]) if "discount" in own else "CAST(NULL AS DOUBLE)"
    computed = f"{qty_line or qty} * {price} - COALESCE({discount}, 0)"
    total_column = own.get("order_total")
    # An empty amount cell stays empty (counts as 0); only a filled but unreadable cell falls back to qty * price.
    if order_list:   # one "line" per order whose amount is the order's goods total
        amount = _number(total_column, types[lines][total_column])
    else:
        amount = (f"CASE WHEN {_text(own['line_amount'])} IS NULL THEN CAST(NULL AS DOUBLE) ELSE "
                  f"COALESCE({_number(own['line_amount'], types[lines][own['line_amount']])}, {computed}) END"
                  if "line_amount" in own else computed)
    name = _text(own["product_name"]) if "product_name" in own else "CAST(NULL AS VARCHAR)"
    sku = _text(own["sku"]) if "sku" in own else "CAST(NULL AS VARCHAR)"
    category = _text(own["category"]) if "category" in own else "CAST(NULL AS VARCHAR)"
    unit = _text(own["unit"]) if "unit" in own else "CAST(NULL AS VARCHAR)"
    mine = order_level(lines)
    null = {"date": "CAST(NULL AS DATE)"}
    alias = {"date": "odate"}   # `date` is also a type name: keep it out of generated SQL
    select_order = ", ".join(f"{mine.get(c, null.get(c, 'CAST(NULL AS VARCHAR)'))} AS {alias.get(c, c)}"
                             for c in ("date", "status", "customer_name", "customer_id"))

    join = ""
    if orders:
        theirs = order_level(orders)
        agg = ", ".join(f"first({theirs[c]}) FILTER (WHERE {theirs[c]} IS NOT NULL) AS o_{alias.get(c, c)}"
                        for c in theirs)
        join = (f"LEFT JOIN (SELECT {_text(column(orders, 'order_id'))} AS oid, {agg} FROM {quote(orders)} "
                f"GROUP BY 1) o ON o.oid = r.order_id")

        def pick(c: str) -> str:
            a = alias.get(c, c)
            return f"COALESCE(r.{a}, o.o_{a})" if c in theirs else f"r.{a}"
    else:
        def pick(c: str) -> str:
            return f"r.{alias.get(c, c)}"

    status_patterns = config.get("status_patterns") or {}
    n_status = norm_sql("status")
    status_class = (f"CASE WHEN {_any(status_patterns.get('cancelled', []), n_status)} THEN 'cancelled' "
                    f"WHEN {_any(status_patterns.get('returned', []), n_status)} OR has_negative THEN 'returned' "
                    f"WHEN {_any(status_patterns.get('shipping', []), n_status)} THEN 'shipping' ELSE 'completed' END")
    walk_in = _any(config.get("walk_in_patterns") or [], norm_sql("customer_name"))
    fee = _any(config.get("service_fee_patterns") or [], norm_sql("product_name"))

    carry = ("oid0" if order_list else
             "last_value(oid0 IGNORE NULLS) OVER (ORDER BY _ln ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)")
    helper = (
        "CREATE OR REPLACE VIEW _readme_lines AS "
        f"WITH src AS (SELECT rowid AS _ln, {order_id} AS oid0, {select_order}, "
        f"{sku} AS sku, {name} AS product_name, {category} AS category, {unit} AS unit, "
        f"{qty} AS qty, {price} AS unit_price, {discount} AS discount, {amount} AS line_amount FROM {q_lines}), "
        # Rulebook section 8: a blank cell on a later line of an order repeats the first line of the order,
        # the order code included, so carry the last order code down the file.
        # Rows without an item or a quantity are subtotal rows ("TỔNG NGÀY 02/04"), not sale lines: drop them (after the
        # order code is carried down, so they cannot be mistaken for a line of the previous order).
        # In an order list every row is one order: a row without a code is a total row, never a continuation.
        f"raw AS (SELECT * FROM (SELECT * EXCLUDE (oid0), {carry} AS order_id FROM src) "
        f"WHERE (sku IS NOT NULL OR product_name IS NOT NULL OR {str(order_list).lower()}) AND qty IS NOT NULL AND order_id IS NOT NULL), "
        "dedup AS (SELECT * FROM raw QUALIFY row_number() OVER (PARTITION BY order_id, sku, product_name, qty, "
        "unit_price, line_amount, odate, status, customer_name ORDER BY _ln) = 1), "
        "joined AS (SELECT r.order_id, r._ln, "
        f"first_value({pick('date')} IGNORE NULLS) OVER w AS odate, "
        f"first_value({pick('status')} IGNORE NULLS) OVER w AS status, "
        f"first_value({pick('customer_name')} IGNORE NULLS) OVER w AS customer_name, "
        f"first_value({pick('customer_id')} IGNORE NULLS) OVER w AS customer_id, "
        "r.sku, r.product_name, r.category, r.unit, r.qty, r.unit_price, r.discount, r.line_amount "
        f"FROM dedup r {join} WINDOW w AS (PARTITION BY r.order_id ORDER BY r._ln "
        "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)) "
        "SELECT * FROM joined")
    orders_sql = (
        "CREATE OR REPLACE VIEW _readme_orders AS WITH per AS (SELECT order_id, min(odate) AS order_date, "
        "max(customer_id) AS customer_id, max(customer_name) AS customer_name, max(status) AS status, "
        "bool_or(COALESCE(qty, 0) < 0) AS has_negative FROM _readme_lines GROUP BY order_id) "
        f"SELECT order_id, order_date, customer_id, customer_name, status, has_negative, {status_class} AS status_class "
        "FROM per")
    try:
        for sql in (helper, orders_sql):
            connection.execute(sql)
        for stale in list(schema.views):
            connection.execute(f"DROP VIEW IF EXISTS {stale}")
        schema.views.clear()
        schema.roles.clear()
        keep = f"NOT ({walk_in})"
        public = [
            ("v_orders", "CREATE OR REPLACE VIEW v_orders AS SELECT order_id, order_date, "
                         f"CASE WHEN {keep} THEN COALESCE(customer_id, customer_name) END AS customer_id, "
                         f"CASE WHEN {keep} THEN customer_name END AS customer, status, status_class "
                         "FROM _readme_orders"),
            ("v_valid_orders", "CREATE OR REPLACE VIEW v_valid_orders AS SELECT order_id, order_date, customer_id, "
                               f"customer, {weekday_sql('order_date')} AS weekday_vi FROM v_orders "
                               "WHERE status_class IN ('completed', 'shipping')"),
            ("v_lines", "CREATE OR REPLACE VIEW v_lines AS SELECT CAST(_ln AS VARCHAR) AS line_id, order_id, "
                        "COALESCE(sku, product_name) AS sku, qty, unit_price, line_amount, "
                        "product_name AS display_name FROM _readme_lines"),
            ("v_sales", "CREATE OR REPLACE VIEW v_sales AS SELECT CAST(l._ln AS VARCHAR) AS line_id, l.order_id, "
                        "o.order_date AS sale_date, o.customer_id, o.customer, COALESCE(l.sku, l.product_name) AS sku, "
                        "l.product_name, l.category, l.unit, l.qty, l.unit_price, "
                        "COALESCE(l.line_amount, 0) AS line_revenue, COALESCE(l.line_amount, 0) AS revenue, "
                        f"NOT ({fee.replace('product_name', 'l.product_name')}) AS is_item, "
                        f"{weekday_sql('o.order_date')} AS weekday_vi "
                        "FROM _readme_lines l JOIN v_valid_orders o ON o.order_id = l.order_id"),
            ("v_products", "CREATE OR REPLACE VIEW v_products AS SELECT COALESCE(sku, product_name) AS sku, "
                           "any_value(product_name) AS name, any_value(category) AS category, any_value(unit) AS unit "
                           f"FROM _readme_lines WHERE product_name IS NOT NULL AND NOT ({fee}) GROUP BY 1"),
            ("v_customers", "CREATE OR REPLACE VIEW v_customers AS SELECT customer_id, any_value(customer) AS name "
                            "FROM v_orders WHERE customer_id IS NOT NULL GROUP BY 1"),
        ]
        for view, sql in public:
            if not _create(connection, schema, view, sql):
                raise RuntimeError(f"view {view} failed")
        schema.flags = business_flags(rulebook)
        schema.complete = True
        low, high = connection.execute("SELECT min(order_date), max(order_date) FROM v_orders").fetchone()
        has_customers = (connection.execute("SELECT count(*) FROM v_customers").fetchone()[0] or 0) > 0
        schema.capabilities = {"has_customers": has_customers, "has_debts": None, "has_cost": None,
                               "has_expiry": None,
                               "date_range": [low.isoformat(), high.isoformat()] if low and high else None}
        schema.warnings.append(f"readme_layer:{'order_list' if order_list else 'lines'}={lines}"
                               + (f",orders={orders}" if orders else ""))
        return True
    except Exception as error:  # noqa: BLE001 - leave the raw schema in place
        schema.complete = False
        schema.views.clear()
        schema.warnings.append(f"readme_layer:{type(error).__name__}: {str(error)[:160]}")
        logging.warning("README layer failed: %s", error)
        return False


def _slash(connection: duckdb.DuckDBPyConnection, date_columns: Sequence[tuple[str, str, str]]) -> str:
    from datamate.ingest.canonical import _slash_order
    return _slash_order(connection, date_columns)
