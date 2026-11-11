# -*- coding: utf-8 -*-
"""Kiểm thử cho các bản vá v3 (chạy: python test_patches.py). Mỗi ca tái hiện một lỗi đã thấy trên dữ liệu thật."""
import warnings
import pandas as pd
warnings.filterwarnings("ignore")
import clean_shop as cs
import question_norm as qn
import value_parsers as vp

FAILS = []
def check(name, cond):
    if not cond:
        FAILS.append(name); print("SAI:", name)

# 1. cột tiền '45,000.0000' phải thành số (biz_112/115/116/118/130, dev_001)
df = pd.DataFrame({"Đơn giá": ["1,500.0000", "45,000.0000", "2,760,000.0000", "0.0000"] * 3,
                   "Thành tiền": ["3,000.0000", "45,000.0000", "2,760,000.0000", "0.0000"] * 3})
out, info = cs.clean_columns(df.copy(), 2025, [], "t")[:2] if isinstance(cs.clean_columns(df.copy(), 2025, [], "t"), tuple) else (None, None)
check("clean_columns trả (df, info)", out is not None)
if out is not None:
    check("Đơn giá thành số", pd.api.types.is_numeric_dtype(out["Đơn giá"]) and int(out["Đơn giá"].iloc[1]) == 45000)
    check("Thành tiền thành số", int(out["Thành tiền"].iloc[2]) == 2760000)

# 2. số lượng có quy cách
df = pd.DataFrame({"Số lượng": ["1 bao 25kg", "2 hộp 30", "1 xe 4m3", "2 m3", "5 thùng", "3", "1,5 kg", "2 cái"] * 2})
out, info = cs.clean_columns(df.copy(), 2025, [], "t")[:2]
check("SL: không còn ô trống", out["Số lượng"].notna().all())
check("SL: giữ đơn vị", out["Số lượng__don_vi"].iloc[0] == "bao 25kg" and out["Số lượng__don_vi"].iloc[3] == "m3")
check("SL: giữ chuỗi gốc", out["Số lượng__raw"].iloc[1] == "2 hộp 30")

# 3. SL thuần số phải cùng một kiểu số
df = pd.DataFrame({"so_luong": ["1", "2", "3", "10", "4", "7", "8"]})
out, info = cs.clean_columns(df.copy(), 2025, [], "t")[:2]
check("SL thuần số -> số", pd.api.types.is_numeric_dtype(out["so_luong"]))

# 4. điền ô trống: IMEI không làm khoá / không bị điền; STT làm khoá; tiền không bị điền
rows = []
for i in range(1, 9):
    rows.append([i, "Khách %d" % i, "Máy %d" % i, "35226465274%04d" % i, 100000, None])
    rows.append([None, None, "Ốp %d" % i, None, 20000, 5000])
df = pd.DataFrame(rows, columns=["STT", "Khách", "Hàng", "IMEI", "Thành tiền", "Bớt"])
out, filled = cs.fill_order_level(df.copy())
check("khoá là STT: Khách được điền", "Khách" in filled and out["Khách"].notna().all())
check("IMEI không bị điền", out["IMEI"].notna().sum() == 8)
check("tiền không bị điền", out["Bớt"].notna().sum() == 8)
check("có cờ dòng đầu nhóm", out["_is_group_head"].sum() == 8)

# 5. tên hàng không bị mở rộng viết tắt
check("HD 180mg giữ nguyên", "HD 180mg" in qn.normalize_text("tồn kho Telfast HD 180mg")[0])
check("T8 giữ nguyên", "T8 1.2m" in qn.normalize_text("bộ đèn led T8 1.2m 18W")[0])
check("hd thật vẫn mở rộng", "hóa đơn" in qn.normalize_text("so hd hom nay")[0])
check("protect tên hàng", "SP9" in qn.normalize_text("giá SP9 kh", protect=["SP9 kh"])[0])
# 6. phương ngữ / tháng bằng chữ / M-YYYY đứng một mình
import datetime as dt
for t, want in [("Thang ni doanh thu bao nhieu", True), ("Tháng ba quán có bao nhiêu đơn", True),
                ("6-2025 trung binh 1 don dem ve bao nhieu", True), ("Doanh thu bữa ni", True)]:
    r = qn.normalize_question(t, "2026-11-09")
    check("có kỳ: " + t, bool(r["periods"]) == want)
r = qn.normalize_question("12-2025 có mấy khách", "2026-11-09")
check("12-2025 = tháng 12/2025", r["periods"] and r["periods"][0]["start"] == "2025-12-01" and r["periods"][0]["end"] == "2025-12-31")

# 7. dòng tổng: không nhầm 'Tổng hợp vitamin' / 'Notebook A4'
rows = [["Mã", "Tên", "SL", "Tiền"]] + [["A%d" % i, "Hàng %d" % i, 1, 1000] for i in range(8)] + \
       [["Tổng hợp vitamin C", "Hộp", 2, 5000], ["Notebook A4", "Cuốn", 3, 9000], ["Tổng cộng", None, 13, 22000]]
df, info = cs.rows_to_frame(rows)
check("chỉ bỏ dòng 'Tổng cộng'", info["total_rows_dropped"] == 1 and len(df) == 10)

if FAILS:
    print("CÓ %d CA SAI" % len(FAILS)); raise SystemExit(1)
print("Tất cả ca kiểm thử v3 đạt; value_parsers:", vp.run_tests(False), "question_norm:", qn.run_tests(False))
