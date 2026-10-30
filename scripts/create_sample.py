"""Create tiny hand-checkable fixtures, independent of the synthetic benchmark."""
import json
import sqlite3
from pathlib import Path

from openpyxl import Workbook


def main():
    root = Path("data/samples")
    directory = root / "data" / "shop"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sales.csv").write_text("product,amount,quantity\nCà phê,10000,2\nTrà,20000,3\n", encoding="utf-8")
    (directory / "README.md").write_text("Tiny shop. amount is VND; quantity is a count.\n", encoding="utf-8")
    (root / "rulebook.md").write_text("Use recorded amounts. Weeks start Monday.\n", encoding="utf-8")
    (root / "calendar.csv").write_text("date,lunar_date,is_tet\n2026-01-01,2025-11-13,false\n", encoding="utf-8")
    book = Workbook()
    sheet = book.active
    sheet.title = "inventory"
    sheet.append(["Inventory report"])
    sheet.append([])
    sheet.append(["product", "stock"])
    sheet.append(["Cà phê", 5])
    sheet.append(["Trà", 8])
    sheet.append(["Tổng cộng", 13])
    sheet = book.create_sheet("branches")
    sheet.append(["name", "active"])
    sheet.append(["Main", True])
    book.save(directory / "inventory.xlsx")
    database = directory / "customers.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS customers (name TEXT, visits INTEGER)")
        connection.execute("DELETE FROM customers")
        connection.executemany("INSERT INTO customers VALUES (?, ?)", [("An", 2), ("Bình", 4)])
    examples = [
        ("đếm sales", "number", 2), ("tổng amount trong sales", "number", 30000),
        ("avg quantity from sales", "number", 2.5), ("min product from sales", "string", "Cà phê"),
        ("danh sách product trong sales", "list", ["Cà phê", "Trà"]),
        ("bảng sales", "table", {"columns": ["product", "amount", "quantity"], "rows": [["Cà phê", 10000, 2], ["Trà", 20000, 3]]}),
        ("sum stock from inventory", "number", 13), ("max active from branches", "boolean", True),
        ("count customers", "number", 2), ("predict next year profit", "abstain", None),
    ]
    questions, answers = [], []
    for index, (question, kind, value) in enumerate(examples, 1):
        identifier = f"sample-{index}"
        questions.append(dict(id=identifier, business_id="shop", question=question, as_of_date="2026-01-01"))
        answer = dict(id=identifier, type=kind)
        if kind != "abstain":
            answer["answer"] = value
        answers.append(answer)
    for filename, records in [("questions.jsonl", questions), ("answers.jsonl", answers)]:
        (root / filename).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


if __name__ == "__main__":
    main()
