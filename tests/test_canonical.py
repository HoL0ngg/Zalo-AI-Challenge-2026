"""Canonical semantic layer: role mapping, typed de-duplicated views, business rules, capabilities."""
from datetime import date

import duckdb
import pytest

from business_fixture import (REVENUE_NO_VOUCHER, REVENUE_VOUCHER, STYLES, TRAIN_RULEBOOK, VALID_ORDERS,
                              VOUCHER_RULEBOOK, make_package)
from datamate.core import Candidate
from datamate.execution.sandbox import execute
from datamate.ingest.canonical import (business_flags, ident_tokens, map_roles, readme_pairs, squash)
from datamate.ingest.loader import BusinessLoader
from datamate.understanding.resources import load_rule_defaults

STYLE_NAMES = ["csv", "xlsx", "sqlite"]


def load(tmp_path, style, **kwargs):
    root = make_package(tmp_path / "package", style, **kwargs)
    return BusinessLoader(root, tmp_path / "work").load("shop")


def rows(context, sql):
    connection = duckdb.connect(str(context.database), read_only=True)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


@pytest.mark.parametrize("name,tokens", [("MaSP", ["ma", "sp"]), ("ChiTietDon", ["chi", "tiet", "don"]),
                                         ("ten_hien_thi", ["ten", "hien", "thi"]), ("ThueVAT", ["thue", "vat"]),
                                         ("OrderID", ["order", "id"]), ("Đơn giá", ["don", "gia"]), ("SDT", ["sdt"])])
def test_identifier_tokens(name, tokens):
    assert ident_tokens(name) == tokens
    assert squash("OrderLines") == squash("order_lines") == "orderlines"


@pytest.mark.parametrize("style", STYLE_NAMES)
def test_roles_are_found_in_every_layout(tmp_path, style):
    context = load(tmp_path, style)
    canonical = context.canonical
    assert canonical.complete, canonical.warnings
    for role, (table, columns) in STYLES[style].items():
        binding = canonical.roles[role]
        assert binding.table == table
        for concept, column in columns.items():
            assert binding.columns[concept] == column, (role, concept)
    assert {"v_products", "v_customers", "v_orders", "v_lines", "v_valid_orders", "v_sales"} <= set(canonical.views)
    assert context.warnings == []


@pytest.mark.parametrize("style", STYLE_NAMES)
def test_views_are_typed_clean_and_deduplicated(tmp_path, style):
    context = load(tmp_path, style)
    orders = {r[0]: r for r in rows(context, "SELECT order_id, order_date, voucher, status FROM v_orders")}
    assert orders["O1"][1] == date(2026, 5, 2) and orders["O2"][1] == date(2026, 5, 3)  # ISO and DD/MM/YYYY
    assert orders["O4"][1] == date(2026, 5, 5)
    assert orders["O1"][2] == 10000.0                                   # "10.000" -> 10000
    lines = rows(context, "SELECT line_id, unit_price, discount, returned FROM v_lines ORDER BY line_id")
    assert [r[0] for r in lines] == ["L1", "L2", "L3", "L4", "L5"]      # duplicate L2 removed
    assert dict((r[0], r[1]) for r in lines)["L2"] == 20000.0           # "20,000" -> 20000
    assert dict((r[0], r[2]) for r in lines)["L2"] == 5000.0
    assert dict((r[0], r[3]) for r in lines) == {"L1": False, "L2": False, "L3": False, "L4": True, "L5": False}
    assert rows(context, "SELECT price FROM v_products WHERE sku = 'P1'") == [(15000.0,)]


@pytest.mark.parametrize("style", STYLE_NAMES)
def test_business_rules_follow_the_rulebook(tmp_path, style):
    context = load(tmp_path, style)
    valid = {r[0] for r in rows(context, "SELECT order_id FROM v_valid_orders")}
    assert valid == VALID_ORDERS                                         # cancelled O2 and returned-line O3 are out
    assert rows(context, "SELECT sum(revenue), sum(qty) FROM v_sales") == [(float(REVENUE_NO_VOUCHER), 6.0)]
    by_name = dict(rows(context, "SELECT product_name, sum(revenue) FROM v_sales GROUP BY 1"))
    assert by_name == {"Sting dâu 330ml": 30000.0, "Bánh quy bơ": 75000.0}

    with_voucher = load(tmp_path / "v", style, rulebook=VOUCHER_RULEBOOK)
    total = rows(with_voucher, "SELECT sum(revenue) FROM v_sales")[0][0]
    assert abs(total - REVENUE_VOUCHER) < 1e-6                           # voucher spread pro rata over valid lines
    share = dict(rows(with_voucher, "SELECT line_id, revenue FROM v_sales ORDER BY line_id"))
    assert abs(share["L1"] - (30000 - 10000 * 30000 / 45000)) < 1e-6 and share["L5"] == 60000.0


def test_flags_come_from_the_rulebook_of_the_split():
    flags = business_flags(VOUCHER_RULEBOOK)
    assert flags["revenue_subtract_order_voucher"] is True and flags["sources"]["revenue_subtract_order_voucher"] == "rulebook"
    assert flags["exclude_cancelled"] is True and flags["sources"]["revenue_include_vat"] == "rulebook"
    default = business_flags("no json here")
    assert default["revenue_subtract_order_voucher"] is False and set(default["sources"].values()) == {"default"}
    relaxed = business_flags('{"exclude_entire_order_if_any_return": false}')
    assert relaxed["exclude_entire_order_if_any_return"] is False
    assert "business" in load_rule_defaults()


def test_return_rule_can_be_relaxed(tmp_path):
    rulebook = TRAIN_RULEBOOK.replace('"exclude_entire_order_if_any_return": true', '"exclude_entire_order_if_any_return": false')
    context = load(tmp_path, "csv", rulebook=rulebook)
    assert {r[0] for r in rows(context, "SELECT order_id FROM v_valid_orders")} == {"O1", "O3", "O4"}


def test_capabilities_and_date_range(tmp_path):
    with_debts = load(tmp_path / "a", "csv").canonical.capabilities
    assert with_debts == {"has_customers": True, "has_debts": True, "has_cost": False, "has_expiry": False,
                          "date_range": ["2026-05-02", "2026-05-05"]}
    without = load(tmp_path / "b", "csv", include_debts=False).canonical.capabilities
    assert without["has_debts"] is False and "v_debts" not in load(tmp_path / "c", "csv", include_debts=False).canonical.views


def test_unmappable_business_is_unknown_not_missing(tmp_path):
    root = tmp_path / "package"
    directory = root / "data" / "shop"
    directory.mkdir(parents=True)
    (root / "rulebook.md").write_text("Weeks start Monday.", encoding="utf-8")
    (directory / "README.md").write_text("flat export", encoding="utf-8")
    (directory / "export.csv").write_text("foo,bar,baz\n1,2,3\n4,5,6\n", encoding="utf-8")
    context = BusinessLoader(root, tmp_path / "work").load("shop")
    assert context.canonical.complete is False and context.entities is None
    assert context.canonical.capabilities["has_debts"] is None and context.canonical.capabilities["date_range"] is None
    assert context.protected_values == ()


def test_readme_pairs_add_synonyms(tmp_path):
    root = tmp_path / "package"
    directory = root / "data" / "shop"
    directory.mkdir(parents=True)
    (root / "rulebook.md").write_text("x", encoding="utf-8")
    (directory / "README.md").write_text("Fields: `Ref` = `ma_don`, `When` = `ngay`, `Item` = `ma_sp`, `Num` = `so_luong`, `Rate` = `don_gia`.", encoding="utf-8")
    (directory / "orders.csv").write_text("Ref,When,customer\nA1,2026-05-02,C1\n", encoding="utf-8")
    (directory / "lines.csv").write_text("Ref,Item,Num,Rate\nA1,P1,2,1000\n", encoding="utf-8")
    context = BusinessLoader(root, tmp_path / "work").load("shop")
    assert context.canonical.roles["orders"].columns["order_id"] == "Ref"
    assert context.canonical.roles["lines"].columns["qty"] == "Num"
    assert readme_pairs("`OrderID` = `ma_don`, `SKU` = `ma_sp`") == [("OrderID", "ma_don"), ("SKU", "ma_sp")]
    assert context.canonical.complete
    assert rows(context, "SELECT sum(revenue) FROM v_sales") == [(2000.0,)]


def test_month_first_slash_dates_are_detected(tmp_path):
    root = tmp_path / "package"
    directory = root / "data" / "shop"
    directory.mkdir(parents=True)
    (root / "rulebook.md").write_text("x", encoding="utf-8")
    (directory / "orders.csv").write_text("ma_don,ngay\nA1,05/13/2026\nA2,06/02/2026\n", encoding="utf-8")
    (directory / "lines.csv").write_text("ma_don,ma_sp,so_luong,don_gia\nA1,P1,1,10\nA2,P1,1,10\n", encoding="utf-8")
    context = BusinessLoader(root, tmp_path / "work").load("shop")
    assert rows(context, "SELECT order_date FROM v_orders ORDER BY order_id") == [(date(2026, 5, 13),), (date(2026, 6, 2),)]


def test_views_work_through_the_read_only_sandbox(tmp_path):
    context = load(tmp_path, "sqlite")
    result = execute(context, Candidate("SELECT sum(revenue) FROM v_sales WHERE sale_date BETWEEN DATE '2026-05-01' AND DATE '2026-05-31'"))
    assert result.error is None and result.rows == [[float(REVENUE_NO_VOUCHER)]]
    assert execute(context, Candidate("DROP VIEW v_sales")).error  # still SELECT only


def test_role_mapping_requires_all_required_columns():
    profile = {"things": {"rows": 1, "columns": [{"name": "ma_sp", "type": "VARCHAR"}, {"name": "x", "type": "VARCHAR"}]}}
    assert map_roles(profile) == {}  # only a sku: no role is bound by guessing
    profile = {"anything": {"rows": 1, "columns": [{"name": "ma_don", "type": "VARCHAR"}, {"name": "ngay", "type": "VARCHAR"}]},
               "ct": {"rows": 1, "columns": [{"name": c, "type": "VARCHAR"} for c in ("ma_don", "ma_sp", "so_luong", "don_gia")]}}
    roles = map_roles(profile)
    assert roles["orders"].table == "anything" and roles["lines"].table == "ct"  # columns decide, table name does not
