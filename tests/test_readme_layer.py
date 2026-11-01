"""README-driven canonical layer on a small package that reproduces the problems of the official data:
blank order codes on later lines, subtotal rows, mixed money / date / quantity formats and many status spellings."""
import csv

import duckdb
import pytest

from datamate.ingest.loader import BusinessLoader
from datamate.ingest.readme_layer import bind_tables, choose_lines, concept_of, load_config, readme_columns

README = """# Dữ liệu shop

## File
- `ban_hang.csv` (csv)

## Cột trong `ban_hang.csv`
- **Mã HD**: mã đơn
- **Ngày**: ngày bán
- **Kết quả**: trạng thái đơn
- **Khách**: tên khách (Khách lẻ nếu không lưu)
- **Hàng**: tên hàng
- **SL**: số lượng
- **Giá**: đơn giá
- **Tiền**: thành tiền sau giảm
- **Quy đổi**: số lượng đã đổi ra đơn vị cơ bản
"""

ROWS = [
    # order code only on the first line of an order; the status and customer repeat from it
    ("A1", "01/03/2025", "Xong", "Lan", "Trà", "2", "45k", "90k", "2"),
    ("", "", "", "", "Bánh", "1 cái", "10,000.0000", "10,000.0000", "1"),
    ("A2", "45720", "hủy đơn", "Khách lẻ", "Trà", "1", "45k", "45k", "1"),          # Excel serial 45720 = 2025-03-04
    ("A3", "5 thg 3 2025", "Đã trả hàng", "Hùng", "Trà", "1", "45k", "45k", "1"),
    ("A4", "2025-03-06 08:30:00", "Đang giao", "Khách lẻ", "Cà phê", "3 ly", "1tr440", "1tr440", "3"),
    ("", "", "", "", "TỔNG NGÀY 06/03", "", "", "1.500.000đ", ""),                  # subtotal row, no quantity
    ("A5", "07/03/2025", "ok", "Lan", "Trà", "1", "45k", "45k", "1"),
    ("A5", "07/03/2025", "ok", "Lan", "Trà", "1", "45k", "45k", "1"),                 # same line exported twice
]


@pytest.fixture()
def context(tmp_path):
    package = tmp_path / "pkg"
    shop = package / "data" / "shop"
    shop.mkdir(parents=True)
    (package / "rulebook.md").write_text("rules", encoding="utf-8")
    (shop / "README.md").write_text(README, encoding="utf-8")
    with (shop / "ban_hang.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Mã HD", "Ngày", "Kết quả", "Khách", "Hàng", "SL", "Giá", "Tiền", "Quy đổi"])
        writer.writerows(ROWS)
    return BusinessLoader(package, tmp_path / "work").load("shop")


def query(context, sql):
    connection = duckdb.connect(str(context.database), read_only=True)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_readme_meanings_become_concepts():
    docs = readme_columns(README)
    config = load_config()
    assert docs == {"ban_hang.csv": {"Mã HD": "mã đơn", "Ngày": "ngày bán", "Kết quả": "trạng thái đơn",
                                     "Khách": "tên khách (khách lẻ nếu không lưu)", "Hàng": "tên hàng", "SL": "số lượng",
                                     "Giá": "đơn giá", "Tiền": "thành tiền sau giảm",
                                     "Quy đổi": "số lượng đã đổi ra đơn vị cơ bản"}}
    assert [concept_of(m, config) for m in docs["ban_hang.csv"].values()] == [
        "order_id", "date", "status", "customer_name", "product_name", "qty", "unit_price", "line_amount", "qty_base"]
    assert concept_of("ngày giao", config) is None and concept_of("tiền nhập của cả dòng", config) is None


def test_table_is_matched_to_its_file_by_columns_not_by_name():
    profile = {"whatever_name": {"rows": 5, "columns": [{"name": c} for c in docs_columns()]},
               "other": {"rows": 9, "columns": [{"name": "x"}]}}
    bound = bind_tables(profile, readme_columns(README), load_config())
    assert list(bound) == ["whatever_name"] and choose_lines(bound, profile) == "whatever_name"


def docs_columns():
    return list(readme_columns(README)["ban_hang.csv"])


def test_layer_is_complete_and_blank_cells_follow_the_first_line_of_the_order(context):
    assert context.canonical.complete and "readme_layer:lines=ban_hang" in context.canonical.warnings
    orders = dict(query(context, "SELECT order_id, status_class FROM v_orders"))
    assert orders == {"A1": "completed", "A2": "cancelled", "A3": "returned", "A4": "shipping", "A5": "completed"}
    # the "Bánh" line has no order code of its own: it belongs to A1
    assert query(context, "SELECT count(*) FROM v_sales WHERE order_id = 'A1'") == [(2,)]
    assert query(context, "SELECT DISTINCT customer FROM v_sales WHERE order_id = 'A1'") == [("Lan",)]


def test_revenue_counts_valid_orders_only_and_ignores_subtotals_and_repeated_lines(context):
    # A1: 90k + 10k, A4 (shipping still counts): 1,440k, A5 once: 45k. Cancelled A2 and returned A3 are out,
    # the subtotal row has no quantity and the exported-twice line of A5 counts once.
    assert query(context, "SELECT SUM(revenue) FROM v_sales") == [(90_000 + 10_000 + 1_440_000 + 45_000,)]
    assert query(context, "SELECT count(*) FROM v_valid_orders") == [(3,)]


def test_dates_money_and_quantities_in_every_spelling(context):
    dates = dict(query(context, "SELECT order_id, order_date FROM v_orders"))
    assert str(dates["A1"]) == "2025-03-01" and str(dates["A2"]) == "2025-03-04"       # dd/mm/yyyy and Excel serial
    assert str(dates["A3"]) == "2025-03-05" and str(dates["A4"]) == "2025-03-06"       # "5 thg 3 2025" and ISO time
    qty = dict(query(context, "SELECT product_name, qty FROM v_sales WHERE order_id IN ('A1','A4') ORDER BY 1"))
    assert qty == {"Bánh": 1.0, "Cà phê": 3.0, "Trà": 2.0}


def test_walk_in_customers_are_not_customers_and_dates_carry_weekday_names(context):
    assert query(context, "SELECT count(*) FROM v_customers") == [(2,)]                  # Lan, Hùng; "Khách lẻ" excluded
    assert query(context, "SELECT DISTINCT weekday_vi FROM v_sales WHERE order_id = 'A1'") == [("Thứ bảy",)]
    assert query(context, "SELECT capabilities FROM (SELECT 1 AS capabilities)") == [(1,)]
    caps = context.canonical.capabilities
    assert caps["date_range"] == ["2025-03-01", "2025-03-07"] and caps["has_debts"] is None


def test_without_a_documented_line_table_the_layer_declines(tmp_path):
    package = tmp_path / "pkg"
    shop = package / "data" / "shop"
    shop.mkdir(parents=True)
    (package / "rulebook.md").write_text("rules", encoding="utf-8")
    (shop / "README.md").write_text("# no column documentation here\n", encoding="utf-8")
    (shop / "t.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    context = BusinessLoader(package, tmp_path / "work").load("shop")
    assert not (context.canonical and context.canonical.complete)
