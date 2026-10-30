"""Canonical semantic layer: stable, typed, de-duplicated DuckDB views over messy business data.

Raw tables keep whatever names, types and quirks the data package has (three naming schemes,
mixed date formats, thousand-separated money strings, duplicated rows). This module detects the
*role* of each table and column from synonym tables in configs/schema_roles.yaml (plus README lines
such as "OrderID = ma_don"), then creates views with fixed names and clean types:

    v_products, v_customers, v_orders, v_lines, v_purchases, v_debts   (typed, de-duplicated)
    v_valid_orders, v_sales                                             (rulebook business rules)

Nothing is guessed: a role is bound only when all its required columns are found, and the
capabilities derived from the mapping are True / False / None (None = could not tell).
Views are created in the private temporary DuckDB, never in the read-only input package.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import duckdb

from datamate.ingest.consistency import check_consistency, issues
from datamate.ingest.profiler import quote
from datamate.understanding.resources import load_rule_defaults, load_schema_roles
from datamate.understanding.temporal import json_objects
from datamate.understanding.textutil import fold

ROLE_ORDER = ("products", "customers", "orders", "lines", "purchases", "debts")
NUMERIC_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UBIGINT", "UINTEGER", "USMALLINT",
                 "UTINYINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL")
DATE_TYPES = ("DATE", "TIMESTAMP")

VIEW_DOCS: dict[str, tuple[str, dict[str, str]]] = {
    "v_products": ("One row per product (de-duplicated by sku).",
                   {"sku": "product code", "name": "canonical product name", "category": "product group",
                    "unit": "unit of measure", "price": "list price", "cost": "list cost"}),
    "v_customers": ("One row per customer.",
                    {"customer_id": "customer code", "name": "customer name", "phone": "phone", "region": "area"}),
    "v_orders": ("One row per order, de-duplicated, ALL statuses (including cancelled).",
                 {"order_id": "order code", "order_date": "DATE of the order", "customer_id": "customer code",
                  "status": "raw status text", "voucher": "order-level voucher amount", "shipping": "shipping fee",
                  "vat": "VAT amount"}),
    "v_lines": ("One row per order line, de-duplicated by line id, ALL orders.",
                {"line_id": "line code", "order_id": "order code", "sku": "product code", "qty": "quantity sold",
                 "unit_price": "price per unit", "discount": "line discount amount", "returned": "BOOLEAN returned line",
                 "display_name": "product name as typed on the sale line"}),
    "v_purchases": ("One row per stock-in lot (de-duplicated by lot id).",
                    {"lot_id": "lot code", "purchase_date": "DATE received", "sku": "product code",
                     "qty": "quantity received", "expiry_date": "DATE of expiry (NULL when unknown)",
                     "unit_cost": "cost per unit (NULL when unknown)"}),
    "v_debts": ("Customer debt entries.",
                {"customer_id": "customer code", "amount": "amount owed", "debt_date": "DATE of the entry"}),
    "v_valid_orders": ("Orders that count for sales: not cancelled and, per rulebook, without any returned line.",
                       {"order_id": "order code", "order_date": "DATE", "customer_id": "customer code",
                        "voucher": "order voucher", "shipping": "shipping fee", "vat": "VAT"}),
    "v_sales": ("USE THIS for sales, quantity and revenue: valid lines of valid orders. `revenue` already "
                "follows the rulebook (line value, voucher / VAT / shipping handling).",
                {"line_id": "line code", "order_id": "order code", "sale_date": "DATE of the sale",
                 "customer_id": "customer code", "sku": "product code", "product_name": "canonical product name",
                 "category": "product group", "qty": "quantity sold", "unit_price": "price per unit",
                 "discount": "line discount", "line_revenue": "max(qty*unit_price-discount, 0)",
                 "revenue": "line revenue after rulebook adjustments"}),
}


# ------------------------------------------------------------------ identifier matching

def ident_tokens(name: str) -> list[str]:
    """Tokens of an identifier: camelCase / snake_case split, diacritics folded, lowercase."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name))
    return [t for t in re.split(r"[^a-z0-9]+", fold(spaced)) if t]


def squash(name: str) -> str:
    return "".join(ident_tokens(name))


def _match_score(column: str, synonyms: Sequence[str]) -> int:
    """3 = same words ignoring spacing/case, 2 = all words of a multi-word synonym present, 0 = none."""
    squashed, tokens = squash(column), set(ident_tokens(column))
    best = 0
    for synonym in synonyms:
        if squash(synonym) == squashed:
            return 3
        words = ident_tokens(synonym)
        if len(words) >= 2 and set(words) <= tokens:
            best = 2
    return best


def readme_pairs(readme: str) -> list[tuple[str, str]]:
    """`A` = `B` pairs documented in the README (e.g. `OrderID` = `ma_don`)."""
    return re.findall(r"`([\w ]+)`\s*=\s*`([\w ]+)`", readme or "")


def _extended_synonyms(roles: Mapping[str, Any], pairs: Sequence[tuple[str, str]]) -> dict[str, dict[str, list[str]]]:
    """concept synonyms per role, extended with README pairs (left name becomes a synonym of the right one)."""
    result: dict[str, dict[str, list[str]]] = {}
    for role, spec in roles.items():
        concepts = {c: list(v.get("names", [])) for c, v in spec.get("columns", {}).items()}
        for left, right in pairs:
            for concept, names in concepts.items():
                if any(squash(n) == squash(right) for n in names) and left not in names:
                    names.append(left)
        result[role] = concepts
    return result


@dataclass(frozen=True)
class RoleBinding:
    role: str
    table: str
    columns: Mapping[str, str]       # concept -> source column
    types: Mapping[str, str]         # concept -> DuckDB type of the source column
    score: float


def _bind_columns(role: str, spec: Mapping[str, Any], synonyms: Mapping[str, list[str]],
                  columns: Sequence[Mapping[str, Any]]) -> tuple[dict[str, str], dict[str, str], bool]:
    candidates = []
    for ci, (concept, info) in enumerate(spec["columns"].items()):
        for position, column in enumerate(columns):
            score = _match_score(column["name"], synonyms[concept])
            if score:
                candidates.append((-score, ci, position, concept, column))
    candidates.sort(key=lambda item: item[:3])
    bound: dict[str, str] = {}
    types: dict[str, str] = {}
    used: set[str] = set()
    for _, _, _, concept, column in candidates:
        if concept in bound or column["name"] in used:
            continue
        bound[concept] = column["name"]
        types[concept] = str(column.get("type", "VARCHAR"))
        used.add(column["name"])
    required = [c for c, info in spec["columns"].items() if info.get("required")]
    return bound, types, all(c in bound for c in required)


def map_roles(profile: Mapping[str, Mapping[str, Any]], readme: str = "",
              roles_config: Mapping[str, Any] | None = None) -> dict[str, RoleBinding]:
    """Bind each role to at most one table; each table serves at most one role."""
    config = (roles_config if roles_config is not None else load_schema_roles()).get("roles", {})
    synonyms = _extended_synonyms(config, readme_pairs(readme))
    options: list[tuple[float, int, str, RoleBinding]] = []
    for role in ROLE_ORDER:
        spec = config.get(role)
        if not spec:
            continue
        for table, info in profile.items():
            bound, types, ok = _bind_columns(role, spec, synonyms[role], info["columns"])
            if not ok:
                continue
            required = sum(1 for c, v in spec["columns"].items() if v.get("required"))
            name_score = _match_score(table, spec.get("table", []))
            score = 10 * required + (len(bound) - required) + name_score
            options.append((-score, ROLE_ORDER.index(role), table, RoleBinding(role, table, bound, types, score)))
    options.sort(key=lambda item: item[:3])
    chosen: dict[str, RoleBinding] = {}
    used_tables: set[str] = set()
    for _, _, table, binding in options:
        if binding.role in chosen or table in used_tables:
            continue
        chosen[binding.role] = binding
        used_tables.add(table)
    return chosen


# ------------------------------------------------------------------ SQL expressions

def _is(dtype: str, kinds: Sequence[str]) -> bool:
    return str(dtype).upper().split("(")[0] in kinds


def _text(col: str) -> str:
    return f"NULLIF(trim(CAST({quote(col)} AS VARCHAR)), '')"


def _date(col: str, dtype: str, slash: str) -> str:
    if _is(dtype, DATE_TYPES):
        return f"CAST({quote(col)} AS DATE)"
    s = f"trim(CAST({quote(col)} AS VARCHAR))"
    return (f"CAST(COALESCE(TRY_STRPTIME(substr({s}, 1, 10), '%Y-%m-%d'), "
            f"TRY_STRPTIME(substr({s}, 1, 10), '{slash}'), TRY_STRPTIME({s}, '%d-%m-%Y'), "
            f"TRY_STRPTIME({s}, '%d.%m.%Y')) AS DATE)")


def _number(col: str, dtype: str) -> str:
    """Numbers from native columns or strings such as '1.558.000', '8,225,850', '12,5', '149000đ'."""
    if _is(dtype, NUMERIC_TYPES):
        return f"CAST({quote(col)} AS DOUBLE)"
    s = (f"replace(replace(regexp_replace(lower(trim(CAST({quote(col)} AS VARCHAR))), '(vnd|vnđ|₫|đ)$', ''), "
         f"' ', ''), chr(160), '')")
    return (f"CASE WHEN {s} = '' THEN NULL "
            f"WHEN regexp_matches({s}, '^-?[0-9]{{1,3}}([.,][0-9]{{3}})+$') "
            f"THEN TRY_CAST(replace(replace({s}, ',', ''), '.', '') AS DOUBLE) "
            f"WHEN regexp_matches({s}, '^-?[0-9]+[.,][0-9]{{1,2}}$') THEN TRY_CAST(replace({s}, ',', '.') AS DOUBLE) "
            f"ELSE TRY_CAST({s} AS DOUBLE) END")


def _bool(col: str, dtype: str) -> str:
    if str(dtype).upper() == "BOOLEAN":
        return f"COALESCE({quote(col)}, false)"
    if _is(dtype, NUMERIC_TYPES):
        return f"COALESCE({quote(col)} <> 0, false)"
    return (f"COALESCE(lower(trim(CAST({quote(col)} AS VARCHAR))) IN "
            f"('true', '1', '1.0', 'yes', 'y', 't', 'co', 'có', 'x'), false)")


def _slash_order(connection: duckdb.DuckDBPyConnection, date_columns: Sequence[tuple[str, str, str]]) -> str:
    """'%d/%m/%Y' (Vietnamese default) unless the data proves month-first."""
    first_big = second_big = 0
    for table, column, dtype in date_columns:
        if _is(dtype, DATE_TYPES):
            continue
        c = quote(column)
        row = connection.execute(
            f"SELECT count(*) FILTER (WHERE TRY_CAST(split_part(trim(CAST({c} AS VARCHAR)), '/', 1) AS INTEGER) > 12), "
            f"count(*) FILTER (WHERE TRY_CAST(split_part(trim(CAST({c} AS VARCHAR)), '/', 2) AS INTEGER) > 12) "
            f"FROM {quote(table)} WHERE CAST({c} AS VARCHAR) LIKE '%/%'").fetchone()
        first_big += row[0]
        second_big += row[1]
    return "%m/%d/%Y" if second_big and not first_big else "%d/%m/%Y"


# ------------------------------------------------------------------ business rules

BUSINESS_KEYS = ("deduplicate_by_record_id", "exclude_cancelled", "exclude_entire_order_if_any_return",
                 "revenue_subtract_order_voucher", "revenue_include_vat", "revenue_include_shipping")


def business_flags(rulebook: str, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Business rule flags: the rulebook JSON block of the split wins over configs/rules_defaults.yaml."""
    base = dict((defaults if defaults is not None else load_rule_defaults()).get("business") or {})
    flags = {k: base.get(k, v) for k, v in {
        "deduplicate_by_record_id": True, "exclude_cancelled": True, "exclude_entire_order_if_any_return": True,
        "revenue_subtract_order_voucher": False, "revenue_include_vat": False,
        "revenue_include_shipping": False}.items()}
    sources = {k: "default" for k in flags}
    for block in json_objects(rulebook or ""):
        for key in BUSINESS_KEYS:
            if isinstance(block.get(key), bool):
                flags[key] = block[key]
                sources[key] = "rulebook"
    flags["sources"] = sources
    return flags


# ------------------------------------------------------------------ views

@dataclass
class CanonicalSchema:
    roles: dict[str, RoleBinding] = field(default_factory=dict)
    views: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    complete: bool = False
    capabilities: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, int | None] = field(default_factory=dict)   # cross-table consistency counts, see consistency.py
    flags: dict[str, Any] = field(default_factory=dict)
    raw_columns: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> dict[str, Any]:
        """Compact, JSON-friendly description for prompts and logs."""
        views = {}
        for name, columns in self.views.items():
            doc, column_docs = VIEW_DOCS.get(name, ("", {}))
            views[name] = {"about": doc, "columns": [{"name": c, "type": t, "meaning": column_docs.get(c, "")}
                                                     for c, t in columns]}
        described = {"views": views, "capabilities": self.capabilities,
                     "roles": {r: {"table": b.table, "columns": dict(b.columns)} for r, b in self.roles.items()},
                     "rules": {k: v for k, v in self.flags.items() if k != "sources"}}
        found = issues(self.quality)
        if found:   # clean data adds nothing, so its prompt is unchanged
            described["data_quality"] = found
        return described


def _select_all(role: RoleBinding, wanted: Sequence[tuple[str, str]], slash: str,
                with_rowid: str | None = None) -> str:
    """SELECT list: (concept, kind) with kind in text/date/number/bool/zero; missing optional -> NULL."""
    parts = []
    for concept, kind in wanted:
        source = role.columns.get(concept)
        dtype = role.types.get(concept, "VARCHAR")
        if source is None:
            null = {"text": "VARCHAR", "date": "DATE", "number": "DOUBLE", "bool": "BOOLEAN"}.get(kind, "VARCHAR")
            expression = {"zero": "0.0", "bool": "false"}.get(kind, f"CAST(NULL AS {null})")
        elif kind == "text":
            expression = _text(source)
        elif kind == "date":
            expression = _date(source, dtype, slash)
        elif kind == "number":
            expression = _number(source, dtype)
        elif kind == "zero":
            expression = f"COALESCE({_number(source, dtype)}, 0.0)"
        else:
            expression = _bool(source, dtype)
        parts.append(f"{expression} AS {concept}")
    return ", ".join(parts)


def _dedup_view(name: str, role: RoleBinding, wanted: Sequence[tuple[str, str]], key: str | None,
                slash: str, dedupe: bool, require_key: bool = True) -> str:
    inner = _select_all(role, wanted, slash)
    table = quote(role.table)
    names = ", ".join(c for c, _ in wanted)
    if key and dedupe and key in role.columns:
        windowed = (f"SELECT {inner}, row_number() OVER (PARTITION BY {_text(role.columns[key])} "
                    f"ORDER BY rowid) AS _rn FROM {table}")
        condition = "_rn = 1" + (f" AND {key} IS NOT NULL" if require_key else "")
        return f"CREATE OR REPLACE VIEW {name} AS SELECT {names} FROM ({windowed}) WHERE {condition}"
    return f"CREATE OR REPLACE VIEW {name} AS SELECT {names} FROM (SELECT {inner} FROM {table})"


def _create(connection: duckdb.DuckDBPyConnection, schema: CanonicalSchema, name: str, sql: str) -> bool:
    try:
        connection.execute(sql)
        schema.views[name] = [(row[0], str(row[1])) for row in connection.execute(f"DESCRIBE {name}").fetchall()]
        return True
    except Exception as error:  # noqa: BLE001 - one broken view must not break ingest
        schema.warnings.append(f"canonical:{name}:{type(error).__name__}: {str(error)[:120]}")
        logging.warning("Canonical view %s failed: %s", name, error)
        return False


def build_canonical(connection: duckdb.DuckDBPyConnection, profile: Mapping[str, Mapping[str, Any]],
                    readme: str, rulebook: str) -> CanonicalSchema:
    """Detect roles and create the canonical views on an open (writable, temporary) connection."""
    schema = CanonicalSchema(raw_columns=tuple(sorted({c["name"] for t in profile.values() for c in t["columns"]})))
    try:
        schema.flags = business_flags(rulebook)
        schema.roles = map_roles(profile, readme)
        roles = schema.roles
        date_columns = [(roles[r].table, roles[r].columns[c], roles[r].types[c])
                        for r, c in (("orders", "order_date"), ("purchases", "purchase_date"),
                                     ("purchases", "expiry_date"), ("debts", "debt_date")) if r in roles and c in roles[r].columns]
        slash = _slash_order(connection, date_columns)
        dedupe = bool(schema.flags["deduplicate_by_record_id"])

        specs = {
            "products": ("v_products", [("sku", "text"), ("name", "text"), ("category", "text"), ("unit", "text"),
                                        ("price", "number"), ("cost", "number")], "sku"),
            "customers": ("v_customers", [("customer_id", "text"), ("name", "text"), ("phone", "text"),
                                          ("region", "text")], "customer_id"),
            "orders": ("v_orders", [("order_id", "text"), ("order_date", "date"), ("customer_id", "text"),
                                    ("status", "text"), ("voucher", "zero"), ("shipping", "zero"), ("vat", "zero")],
                       "order_id"),
            "lines": ("v_lines", [("line_id", "text"), ("order_id", "text"), ("sku", "text"), ("qty", "number"),
                                  ("unit_price", "number"), ("discount", "zero"), ("returned", "bool"),
                                  ("display_name", "text")], "line_id"),
            "purchases": ("v_purchases", [("lot_id", "text"), ("purchase_date", "date"), ("sku", "text"),
                                          ("qty", "number"), ("expiry_date", "date"), ("unit_cost", "number")],
                          "lot_id"),
            "debts": ("v_debts", [("customer_id", "text"), ("amount", "number"), ("debt_date", "date")], None),
        }
        for role, (view, wanted, key) in specs.items():
            if role in roles:
                _create(connection, schema, view, _dedup_view(view, roles[role], wanted, key, slash, dedupe,
                                                              require_key=role != "lines"))
        flags = schema.flags
        if "v_orders" in schema.views and "v_lines" in schema.views:
            invalid = ["lower(replace(strip_accents(COALESCE(status, '')), 'đ', 'd')) LIKE '%huy%'",
                       "lower(replace(strip_accents(COALESCE(status, '')), 'đ', 'd')) LIKE '%cancel%'"] \
                if flags["exclude_cancelled"] else []
            cancelled = f"({' OR '.join(invalid)})" if invalid else "false"
            returned = "order_id IN (SELECT order_id FROM v_lines WHERE returned)" \
                if flags["exclude_entire_order_if_any_return"] else "false"
            _create(connection, schema, "v_valid_orders",
                    f"CREATE OR REPLACE VIEW v_valid_orders AS SELECT order_id, order_date, customer_id, voucher, "
                    f"shipping, vat FROM v_orders WHERE NOT {cancelled} AND NOT ({returned})")
            if "v_valid_orders" in schema.views:
                revenue = "line_revenue"
                share = "line_revenue / NULLIF(order_total, 0)"
                if flags["revenue_subtract_order_voucher"]:
                    revenue = f"GREATEST({revenue} - COALESCE(voucher * {share}, 0), 0)"
                if flags["revenue_include_vat"]:
                    revenue += f" + COALESCE(vat * {share}, 0)"
                if flags["revenue_include_shipping"]:
                    revenue += f" + COALESCE(shipping * {share}, 0)"
                product_name = "COALESCE(p.name, l.sku)" if "v_products" in schema.views else "l.sku"
                category = "p.category" if "v_products" in schema.views else "CAST(NULL AS VARCHAR)"
                join_products = "LEFT JOIN v_products p ON l.sku = p.sku" if "v_products" in schema.views else ""
                _create(connection, schema, "v_sales",
                        "CREATE OR REPLACE VIEW v_sales AS WITH base AS (SELECT l.line_id, l.order_id, "
                        f"o.order_date AS sale_date, o.customer_id, l.sku, {product_name} AS product_name, "
                        f"{category} AS category, l.qty, l.unit_price, l.discount, "
                        "GREATEST(l.qty * l.unit_price - l.discount, 0) AS line_revenue, o.voucher, o.shipping, o.vat "
                        f"FROM v_lines l JOIN v_valid_orders o ON l.order_id = o.order_id {join_products}), "
                        "tot AS (SELECT *, SUM(line_revenue) OVER (PARTITION BY order_id) AS order_total FROM base) "
                        "SELECT line_id, order_id, sale_date, customer_id, sku, product_name, category, qty, "
                        f"unit_price, discount, line_revenue, {revenue} AS revenue FROM tot")
        schema.complete = "v_sales" in schema.views
        schema.capabilities = _capabilities(connection, schema)
        schema.quality = check_consistency(connection, schema.views)
        schema.warnings.extend(f"consistency:{name}={count}" for name, count in issues(schema.quality).items())
    except Exception as error:  # noqa: BLE001
        schema.warnings.append(f"canonical:{type(error).__name__}: {str(error)[:160]}")
        logging.warning("Canonical layer failed: %s", error)
        schema.complete = False
    return schema


def _count(connection: duckdb.DuckDBPyConnection, sql: str) -> int | None:
    try:
        return int(connection.execute(sql).fetchone()[0])
    except Exception:  # noqa: BLE001
        return None


def _capabilities(connection: duckdb.DuckDBPyConnection, schema: CanonicalSchema) -> dict[str, Any]:
    """True / False / None (None = the layer could not tell, so nothing may be blocked on it)."""
    if not schema.complete:
        return {"has_customers": None, "has_debts": None, "has_cost": None, "has_expiry": None,
                "date_range": None}
    views, roles = schema.views, schema.roles
    caps: dict[str, Any] = {"has_customers": "v_customers" in views}
    caps["has_debts"] = bool("v_debts" in views and (_count(connection, "SELECT count(*) FROM v_debts") or 0) > 0)
    caps["has_cost"] = bool("v_purchases" in views and "unit_cost" in roles.get("purchases", RoleBinding("", "", {}, {}, 0)).columns
                            and (_count(connection, "SELECT count(*) FROM v_purchases WHERE unit_cost IS NOT NULL") or 0) > 0)
    caps["has_expiry"] = bool("v_purchases" in views and "expiry_date" in roles.get("purchases", RoleBinding("", "", {}, {}, 0)).columns
                              and (_count(connection, "SELECT count(*) FROM v_purchases WHERE expiry_date IS NOT NULL") or 0) > 0)
    try:
        low, high = connection.execute("SELECT min(order_date), max(order_date) FROM v_orders").fetchone()
        caps["date_range"] = [low.isoformat(), high.isoformat()] if low and high else None
    except Exception:  # noqa: BLE001
        caps["date_range"] = None
    return caps
