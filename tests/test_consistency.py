"""Cross-table consistency facts (ingest) and the profit-needs-a-cost-per-product gate rule."""
from datetime import date

import duckdb
import pytest

from business_fixture import REVENUE_NO_VOUCHER, make_package
from datamate.core import Period, Question
from datamate.gate import UNCOSTED_REASON, gate
from datamate.ingest.consistency import check_consistency, issues
from datamate.ingest.loader import BusinessLoader
from datamate.linking import link
from datamate.linking.data_facts import uncosted_skus
from datamate.understanding import understand

CLEAN = {"lines_without_order": 0, "line_skus_not_in_products": 0, "order_customers_not_in_customers": 0,
         "orders_without_date": 0}
DIRTY = {"lines_without_order": 1, "line_skus_not_in_products": 1, "order_customers_not_in_customers": 1,
         "orders_without_date": 1}
STYLE_NAMES = ["csv", "xlsx", "sqlite"]


def load(tmp_path, style="csv", **kwargs):
    return BusinessLoader(make_package(tmp_path / "package", style, **kwargs), tmp_path / "work").load("shop")


def run(context, text, as_of="2026-05-10"):
    question = Question(id="q", business_id="shop", question=text, as_of_date=as_of)
    linked = link(understand(question, context), context)
    return linked, gate(linked)


def sales_totals(context):
    connection = duckdb.connect(str(context.database), read_only=True)
    try:
        return connection.execute("SELECT count(*), sum(revenue), sum(qty) FROM v_sales").fetchone()
    finally:
        connection.close()


# ----------------------------------------------------------------------- consistency facts

@pytest.mark.parametrize("style", STYLE_NAMES)
def test_clean_data_has_no_findings_and_adds_nothing_to_the_prompt(tmp_path, style):
    context = load(tmp_path, style)
    assert context.canonical.quality == CLEAN and issues(context.canonical.quality) == {}
    assert not [w for w in context.warnings if w.startswith("consistency:")]
    assert "data_quality" not in context.canonical.describe()    # a clean business keeps its prompt as it was


def test_findings_are_counted_logged_and_described(tmp_path):
    context = load(tmp_path, dirty=True)
    quality = context.canonical.quality
    assert quality == DIRTY
    assert [w for w in context.warnings if w.startswith("consistency:")] == [f"consistency:{k}=1" for k in DIRTY]
    assert context.canonical.describe()["data_quality"] == DIRTY


def test_findings_never_change_a_valid_sale(tmp_path):
    clean, dirty = load(tmp_path / "a"), load(tmp_path / "b", dirty=True)
    assert sales_totals(dirty) == sales_totals(clean)
    assert sales_totals(dirty)[1] == REVENUE_NO_VOUCHER
    assert run(dirty, "Doanh thu tháng này là bao nhiêu?")[1].allowed    # information only, never blocks


def test_consistency_is_deterministic(tmp_path):
    first, second = load(tmp_path / "a", dirty=True), load(tmp_path / "b", dirty=True)
    assert first.canonical.quality == second.canonical.quality


def test_a_check_is_unknown_not_zero_when_its_views_are_missing():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE v_orders AS SELECT * FROM (VALUES ('O1', DATE '2026-05-02', 'C1'), "
                       "('O2', NULL, NULL)) t(order_id, order_date, customer_id)")
    quality = check_consistency(connection, {"v_orders": []})
    assert quality == {"lines_without_order": None, "line_skus_not_in_products": None,
                       "order_customers_not_in_customers": None, "orders_without_date": 1}
    assert issues(quality) == {"orders_without_date": 1}


def test_a_blank_customer_is_not_a_finding():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE v_orders AS SELECT * FROM (VALUES ('O1', DATE '2026-05-02', NULL)) "
                       "t(order_id, order_date, customer_id)")
    connection.execute("CREATE TABLE v_customers AS SELECT * FROM (VALUES ('C1')) t(customer_id)")
    quality = check_consistency(connection, {"v_orders": [], "v_customers": []})
    assert quality["order_customers_not_in_customers"] == 0


# ----------------------------------------------------------------------- profit needs a cost per sold product

PROFIT_2_5 = "Lợi nhuận ngày 2/5 là bao nhiêu?"   # P1 and P2 are sold
PROFIT_5_5 = "Lợi nhuận ngày 5/5 là bao nhiêu?"   # only P2 is sold


def test_profit_is_answerable_when_every_sold_product_has_a_costed_lot(tmp_path):
    linked, decision = run(load(tmp_path, purchase_skus=("P1", "P2")), PROFIT_2_5)
    assert linked.flags["uncosted_skus"] == [] and decision.allowed


def test_profit_is_blocked_when_a_sold_product_has_no_costed_lot(tmp_path):
    context = load(tmp_path, purchase_skus=("P2",))
    linked, decision = run(context, PROFIT_2_5)
    assert linked.flags["uncosted_skus"] == ["P1"]
    assert not decision.allowed and decision.reason == UNCOSTED_REASON
    # the uncosted product is not sold on the 5th, so the same business can answer that day
    linked, decision = run(context, PROFIT_5_5)
    assert linked.flags["uncosted_skus"] == [] and decision.allowed


def test_only_profit_questions_look_at_costs(tmp_path):
    linked, decision = run(load(tmp_path, purchase_skus=("P2",)), "Doanh thu ngày 2/5 là bao nhiêu?")
    assert linked.flags["uncosted_skus"] is None and decision.allowed


def test_without_a_purchase_table_the_old_capability_rule_still_applies(tmp_path):
    linked, decision = run(load(tmp_path), PROFIT_2_5)
    assert linked.flags["missing_capability"] == ["cost"] and linked.flags["uncosted_skus"] is None
    assert not decision.allowed and decision.reason != UNCOSTED_REASON


def test_a_lot_received_after_as_of_does_not_cost_earlier_sales(tmp_path):
    context = load(tmp_path, purchase_skus=("P1", "P2"))
    period = Period("day", date(2026, 5, 2), date(2026, 5, 2), "primary", "ngay 2/5")
    assert uncosted_skus(context, period, date(2026, 5, 10)) == []
    assert uncosted_skus(context, period, date(2026, 4, 30)) == ["P1", "P2"]   # lots arrive on 05-01


def test_uncosted_check_is_unknown_without_the_purchase_view(tmp_path):
    period = Period("day", date(2026, 5, 2), date(2026, 5, 2), "primary", "ngay 2/5")
    assert uncosted_skus(load(tmp_path), period, date(2026, 5, 10)) is None


def test_profit_gate_is_deterministic(tmp_path):
    context = load(tmp_path, purchase_skus=("P2",))
    first, second = run(context, PROFIT_2_5), run(context, PROFIT_2_5)
    assert first[0].flags == second[0].flags and first[1].reason == second[1].reason
