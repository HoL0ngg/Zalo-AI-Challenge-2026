"""Tiny messy business packages in the three layouts used by the data (CSV, XLSX, SQLite).

Same facts in every layout, different table/column names, mixed date formats, thousand-separated
money strings, a duplicated sale line, a cancelled order and an order with a returned line.
"""
import sqlite3
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

TRAIN_RULEBOOK = '''# Rulebook
```json
{"deduplicate_by_record_id": true, "exclude_cancelled": true, "exclude_entire_order_if_any_return": true,
 "month_to_as_of": true, "revenue_include_shipping": false, "revenue_include_vat": false,
 "revenue_subtract_order_voucher": false, "week_start": "monday"}
```
'''
VOUCHER_RULEBOOK = TRAIN_RULEBOOK.replace('"revenue_subtract_order_voucher": false', '"revenue_subtract_order_voucher": true')

# role -> (table name per style, {concept: column name per style})
STYLES = {
    "csv": {"products": ("san_pham", dict(sku="ma_sp", name="ten_sp", category="danh_muc", price="gia_ban")),
            "customers": ("khach_hang", dict(customer_id="ma_kh", name="ten_kh", region="khu_vuc")),
            "orders": ("don_hang", dict(order_id="ma_don", order_date="ngay", customer_id="ma_kh", status="trang_thai",
                                        voucher="voucher_don")),
            "lines": ("chi_tiet_don", dict(line_id="dong_id", order_id="ma_don", sku="ma_sp", qty="so_luong",
                                           unit_price="don_gia", discount="giam_gia_dong", returned="tra_hang",
                                           display_name="ten_hien_thi")),
            "debts": ("cong_no", dict(customer_id="ma_kh", amount="so_tien_no", debt_date="ngay_no"))},
    "xlsx": {"products": ("Products", dict(sku="SKU", name="ProductName", category="Category", price="Price")),
             "customers": ("Customers", dict(customer_id="CustomerID", name="CustomerName", region="Region")),
             "orders": ("Orders", dict(order_id="OrderID", order_date="OrderDate", customer_id="CustomerID",
                                       status="Status", voucher="Voucher")),
             "lines": ("OrderLines", dict(line_id="LineID", order_id="OrderID", sku="SKU", qty="Qty",
                                          unit_price="UnitPrice", discount="LineDiscount", returned="Returned",
                                          display_name="DisplayName"))},
    "sqlite": {"products": ("HangHoa", dict(sku="MaSP", name="TenHang", category="NhomHang", price="GiaBan")),
               "customers": ("KhachHang", dict(customer_id="MaKH", name="TenKH", region="KhuVuc")),
               "orders": ("DonHang", dict(order_id="MaDon", order_date="NgayBan", customer_id="MaKH",
                                          status="TrangThai", voucher="VoucherDon")),
               "lines": ("ChiTietDon", dict(line_id="MaDong", order_id="MaDon", sku="MaSP", qty="SL",
                                            unit_price="DonGia", discount="GiamGia", returned="TraHang",
                                            display_name="TenHienThi")),
               "debts": ("CongNo", dict(customer_id="MaKH", amount="SoTienNo", debt_date="NgayNo"))},
}

DATA = {
    "products": [dict(sku="P1", name="Sting dâu 330ml", category="Đồ uống", price="15.000"),
                 dict(sku="P2", name="Bánh quy bơ", category="Bánh", price="20.000"),
                 dict(sku="P3", name="Nước suối 500ml", category="Đồ uống", price="5000")],
    "customers": [dict(customer_id="C1", name="Nguyễn An", region="Hà Nội"),
                  dict(customer_id="C2", name="Trần Bình", region="")],
    "orders": [dict(order_id="O1", order_date="2026-05-02", customer_id="C1", status="hoàn thành", voucher="10.000"),
               dict(order_id="O2", order_date="03/05/2026", customer_id="C2", status="hủy", voucher="0"),
               dict(order_id="O3", order_date="2026-05-04", customer_id="C1", status="hoàn thành", voucher="0"),
               dict(order_id="O4", order_date="05/05/2026", customer_id="C2", status="hoàn thành", voucher="0")],
    "lines": [dict(line_id="L1", order_id="O1", sku="P1", qty=2, unit_price="15.000", discount="0", returned=False,
                   display_name="STING DÂU 330ML"),
              dict(line_id="L2", order_id="O1", sku="P2", qty=1, unit_price="20,000", discount="5.000", returned=False,
                   display_name="banh quy bo "),
              dict(line_id="L2", order_id="O1", sku="P2", qty=1, unit_price="20,000", discount="5.000", returned=False,
                   display_name="banh quy bo "),  # duplicated export row
              dict(line_id="L3", order_id="O2", sku="P1", qty=1, unit_price="15.000", discount="0", returned=False,
                   display_name="Sting dâu 330ml"),
              dict(line_id="L4", order_id="O3", sku="P1", qty=1, unit_price="15.000", discount="0", returned=True,
                   display_name="Sting dâu 330ml"),
              dict(line_id="L5", order_id="O4", sku="P2", qty=3, unit_price="20.000", discount="0", returned=False,
                   display_name="Bánh quy bơ")],
    "debts": [dict(customer_id="C2", amount="1.500.000", debt_date="2026-05-06")],
}
# Opt-in extras (CSV layout only, kept out of STYLES so the default package is unchanged).
# Lots all predate the sales, so every SKU listed in `purchase_skus` is costed for the whole month.
PURCHASES_STYLE = ("phieu_nhap", dict(lot_id="lo_id", purchase_date="ngay_nhap", sku="ma_sp", qty="so_luong",
                                      unit_cost="gia_nhap"))
PURCHASES = [dict(lot_id="B1", purchase_date="2026-05-01", sku="P1", qty=50, unit_cost="9.000"),
             dict(lot_id="B2", purchase_date="2026-05-01", sku="P2", qty=50, unit_cost="12.000"),
             dict(lot_id="B3", purchase_date="2026-05-01", sku="P3", qty=50, unit_cost="3.000")]
# `dirty=True`: a sale line whose order and product do not exist, an order of an unknown customer
# with an unreadable date. None of them may change a valid sale.
DIRTY = {"lines": [dict(line_id="L9", order_id="O99", sku="P9", qty=4, unit_price="10.000", discount="0",
                        returned=False, display_name="Hang la")],
         "orders": [dict(order_id="O5", order_date="khong ro", customer_id="C9", status="hoàn thành", voucher="0")]}
# Expected values the views must reproduce.
VALID_ORDERS = {"O1", "O4"}
REVENUE_NO_VOUCHER = 30000 + 15000 + 60000
REVENUE_VOUCHER = REVENUE_NO_VOUCHER - 10000


def _frame(style: str, role: str, include_debts: bool, dirty: bool = False,
           spec: tuple | None = None, rows: list | None = None) -> pd.DataFrame | None:
    spec = spec or STYLES[style].get(role)
    if spec is None or (role == "debts" and not include_debts):
        return None
    names = spec[1]
    rows = DATA[role] + (DIRTY.get(role, []) if dirty else []) if rows is None else rows
    frame = pd.DataFrame([{names[c]: v for c, v in row.items() if c in names} for row in rows])
    return frame[[names[c] for c in names if names[c] in frame.columns]]


def make_package(root: Path, style: str, rulebook: str = TRAIN_RULEBOOK, readme: str = "A shop.",
                 include_debts: bool = True, business: str = "shop", dirty: bool = False,
                 purchase_skus: tuple[str, ...] | None = None) -> Path:
    """Create root/{rulebook.md, calendar.csv, data/<business>/...} and return root.

    `dirty` and `purchase_skus` (SKUs that have a costed purchase lot; None = no purchase table) are
    opt-in and only supported by the CSV layout.
    """
    directory = root / "data" / business
    directory.mkdir(parents=True)
    (root / "rulebook.md").write_text(rulebook, encoding="utf-8")
    (root / "calendar.csv").write_text("date,is_tet_window\n2026-05-01,0\n", encoding="utf-8")
    (directory / "README.md").write_text(readme, encoding="utf-8")
    frames = {role: _frame(style, role, include_debts, dirty) for role in STYLES[style]}
    frames = {role: frame for role, frame in frames.items() if frame is not None}
    if style == "csv":
        for role, frame in frames.items():
            frame.to_csv(directory / f"{STYLES[style][role][0]}.csv", index=False, encoding="utf-8")
        if purchase_skus is not None:
            lots = [row for row in PURCHASES if row["sku"] in purchase_skus]
            _frame(style, "purchases", include_debts, spec=PURCHASES_STYLE, rows=lots).to_csv(
                directory / f"{PURCHASES_STYLE[0]}.csv", index=False, encoding="utf-8")
    elif style == "xlsx":
        book = Workbook()
        book.remove(book.active)
        for role, frame in frames.items():
            sheet = book.create_sheet(STYLES[style][role][0])
            if role == "orders":
                sheet.append(["BÁO CÁO GIAO DỊCH — shop"])  # merged-title style row before the header
                sheet.append([])
            sheet.append(list(frame.columns))
            for row in frame.itertuples(index=False):
                sheet.append([None if pd.isna(v) else v for v in row])
        book.save(directory / "so_lieu.xlsx")
    else:
        connection = sqlite3.connect(directory / "kinh_doanh.sqlite")
        for role, frame in frames.items():
            frame.to_sql(STYLES[style][role][0], connection, index=False)
        connection.commit()
        connection.close()
    return root
