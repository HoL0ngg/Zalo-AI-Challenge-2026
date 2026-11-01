"""Raw (non-canonical) business packages: merged slices, compact prompt schema, identifier quoting.

Cases come from the first public_test run: 622/1000 prompts overflowed the context window and 238 SQL
statements failed with `Parser Error` because "Thành tiền" was written without double quotes.
"""
import json

import duckdb
import pandas as pd

from datamate.codegen.prompt_builder import compact_profile, needs_quotes
from datamate.execution.repair import quote_known_identifiers
from datamate.ingest.loader import BusinessLoader, merge_same_schema
from datamate.ingest.profiler import profile_table


def frame(rows, columns=("Ngày", "Thành tiền")):
    return pd.DataFrame(rows, columns=list(columns))


def test_sheets_of_one_workbook_become_one_table_with_a_sheet_column():
    entries = [("So_chi_tiet", "02.2025", frame([["01/02/2025", "10"]])),
               ("So_chi_tiet", "03.2025", frame([["01/03/2025", "20"]])),
               ("Khach", "Sheet1", frame([["a", "b"]], ("Mã", "Tên")))]
    merged = merge_same_schema(entries)
    assert [name for _, name, _ in merged] == ["So_chi_tiet", "Sheet1"]
    table = merged[0][2]
    assert len(table) == 2 and list(table["_sheet"]) == ["02.2025", "03.2025"]


def test_numbered_parts_merge_but_different_columns_do_not():
    same = [("HoaDonChiTiet_1", "Sheet1", frame([["x", "1"]])), ("HoaDonChiTiet_2", "Sheet1", frame([["y", "2"]]))]
    merged = merge_same_schema(same)
    assert [name for _, name, _ in merged] == ["HoaDonChiTiet"] and len(merged[0][2]) == 2
    assert list(merged[0][2]["_sheet"]) == ["HoaDonChiTiet_1", "HoaDonChiTiet_2"]
    different = [("HoaDon_1", "Sheet1", frame([["x", "1"]])), ("HoaDon_2", "Sheet1", frame([["y", "2"]], ("A", "B")))]
    assert [name for _, name, _ in merge_same_schema(different)] == ["Sheet1", "Sheet1"]


def test_loader_merges_monthly_sheets_end_to_end(tmp_path):
    package = tmp_path / "pkg"
    (package / "data" / "shop").mkdir(parents=True)
    (package / "rulebook.md").write_text("rules", encoding="utf-8")
    (package / "data" / "shop" / "README.md").write_text("shop", encoding="utf-8")
    with pd.ExcelWriter(package / "data" / "shop" / "So_ban_hang.xlsx") as writer:
        for month in ("02.2025", "03.2025", "04.2025"):
            frame([["01/" + month.replace(".", "/"), "5"], ["02/" + month.replace(".", "/"), "7"]]).to_excel(
                writer, sheet_name=month, index=False)
    context = BusinessLoader(package, tmp_path / "work").load("shop")
    assert list(context.profile) == ["So_ban_hang"]
    assert context.profile["So_ban_hang"]["rows"] == 6
    assert "_sheet" in [c["name"] for c in context.profile["So_ban_hang"]["columns"]]


def test_compact_profile_quotes_names_and_keeps_few_short_samples():
    connection = duckdb.connect()
    connection.execute("CREATE TABLE \"02.2025\" AS SELECT 'Bia Heineken 330ml thùng 24 lon rất dài rất dài' AS \"Tên hàng\", "
                       "'1,234,000' AS tien, 1 AS n")
    profile = {"02.2025": profile_table(connection, "02.2025")}
    compact = compact_profile(profile)
    assert list(compact) == ['"02.2025"']
    columns = compact['"02.2025"']["columns"]
    assert columns[0].startswith('"Tên hàng" VARCHAR e.g. Bia Heineken 330ml thùng 24') and len(columns[0]) < 80
    assert columns[1].startswith("tien VARCHAR")
    assert len(json.dumps(compact)) < len(json.dumps(profile, default=str)) / 2


def test_needs_quotes():
    assert needs_quotes("Thành tiền") and needs_quotes("02.2025") and needs_quotes("a-b")
    assert not needs_quotes("so_luong") and not needs_quotes("DonGia")


COLUMNS = {"So_chi_tiet_ban_hang": ["Ngày", "Thành tiền", "Tên hàng hóa", "so_luong"], "02.2025": ["Giờ bán"]}


def test_quote_known_identifiers_fixes_the_failing_statements_from_the_log():
    bare = ("SELECT SUM(CAST(REPLACE(SUBSTR(Thành tiền, 4), ',', '') AS DOUBLE)) FROM So_chi_tiet_ban_hang "
            "WHERE Ngày BETWEEN '2025-07-01' AND '2025-07-31' AND Tên hàng hóa = 'Bia Heineken 330ml'")
    fixed = quote_known_identifiers(bare, COLUMNS)
    assert '"Thành tiền"' in fixed and '"Ngày"' in fixed and '"Tên hàng hóa"' in fixed
    assert "So_chi_tiet_ban_hang" in fixed and "'Bia Heineken 330ml'" in fixed
    connection = duckdb.connect()
    connection.execute('CREATE TABLE So_chi_tiet_ban_hang ("Ngày" DATE, "Thành tiền" VARCHAR, "Tên hàng hóa" VARCHAR, so_luong INT)')
    connection.execute("INSERT INTO So_chi_tiet_ban_hang VALUES (DATE '2025-07-02', 'VND 1,000', 'Bia Heineken 330ml', 1)")
    assert connection.execute(fixed).fetchone() == (1000.0,)


def test_quote_known_identifiers_leaves_correct_sql_and_literals_alone():
    done = 'SELECT "Thành tiền" FROM So_chi_tiet_ban_hang WHERE "Tên hàng hóa" = \'Thành tiền\''
    assert quote_known_identifiers(done, COLUMNS) == done
    assert quote_known_identifiers("SELECT 'Ngày' AS x", COLUMNS) == "SELECT 'Ngày' AS x"
    assert quote_known_identifiers("SELECT so_luong FROM t", {"t": ["so_luong"]}) == "SELECT so_luong FROM t"
    assert quote_known_identifiers('SELECT "02.2025"."Giờ bán" FROM "02.2025"', COLUMNS) == \
        'SELECT "02.2025"."Giờ bán" FROM "02.2025"'
