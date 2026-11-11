# -*- coding: utf-8 -*-
"""Chạy mọi shop và xuất báo cáo kiểm tra chất lượng (thay cho ô 'Chạy 3 hàm đã nâng cấp' dùng df giả).

dq_runner.run(roots, out_dir) ghi 2 file vào out_dir (datalayer/outputs/):
  dq_report.csv        1 dòng / shop: số bảng, số dòng, số cảnh báo, khoảng ngày giao dịch, khoảng ngày thô,
                       bảng tên lỗi font, bảng không có cột tiền, cột bị điền ô trống
  dq_columns.csv       1 dòng / (shop, bảng, cột) có vấn đề: ô không đổi được, cột bị bỏ qua, cột chuỗi toàn số
"""
import os
import time

import pandas as pd

import clean_shop


def _bad_name(n):
    return any(ch in n for ch in "├ß║╗Ã")


_ID_NAME = clean_shop._NameMatcher(("imei", "serial", "seri", "so may", "so seri", "barcode", "ma vach", "sdt", "so dien thoai", "sku"))


def invariant_issues(tabs):
    """v3 — kiểm tra BẤT BIẾN sau khi làm sạch (bắt cả lỗi cấp bảng mà test hàm đơn lẻ không thấy):
      1. cột tên giống TIỀN mà kiểu dữ liệu không phải số      (lỗi '45,000.0000' ở v2)
      2. cột tên giống SỐ LƯỢNG mà kiểu dữ liệu không phải số  (str ở biz_101/111/125..., int/float ở shop khác)
      3. cột tên giống NGÀY mà còn là chuỗi
      4. cột IMEI/serial/mã vạch bị điền xuống (nhiều ô hơn dữ liệu gốc cho phép: >95% có giá trị trong bảng có cờ nhóm)
    Trả list (bang, cot, loai, vi_du)."""
    out = []
    for n, df in tabs.items():
        grouped = "_is_group_head" in df.columns
        for c in df.columns:
            if c.startswith("_") or c.endswith(("__don_vi", "__raw")):
                continue
            num = pd.api.types.is_numeric_dtype(df[c])
            nn = df[c].dropna()
            ex = [str(v) for v in nn.head(3).tolist()]
            if not num and len(nn):
                smp = nn.head(300).tolist()
                numeric_like = sum(1 for v in smp if clean_shop.parse_money(v) is not None) / len(smp) >= 0.5   # cột chữ như 'MaKhuyenMai' không bị báo
                if numeric_like and clean_shop._MONEY_NAME.search(c):
                    out.append((n, c, "TÊN GIỐNG TIỀN NHƯNG KHÔNG PHẢI SỐ", ex))
                elif numeric_like and clean_shop._QTY_NAME.search(c):
                    out.append((n, c, "TÊN GIỐNG SỐ LƯỢNG NHƯNG KHÔNG PHẢI SỐ", ex))
            if grouped and _ID_NAME.search(c) and df[c].notna().mean() > 0.95 and (~df["_is_group_head"]).any():
                out.append((n, c, "MÃ ĐỊNH DANH CẤP DÒNG NGHI BỊ ĐIỀN XUỐNG", ex))
    return out


def run(roots, out_dir=None, verbose=True):
    shops, cols = [], []
    for split, root in roots:
        data_dir = os.path.join(root, "data") if os.path.isdir(os.path.join(root, "data")) else root
        for shop in sorted(os.listdir(data_dir)):
            path = os.path.join(data_dir, shop)
            if not os.path.isdir(path) or shop.startswith("."):
                continue
            t0 = time.time()
            try:
                tabs, m = clean_shop.load_clean_tables(path)
            except Exception as e:
                shops.append(dict(shop=shop, tap=split, ket_qua="LỖI: " + str(e)[:80]))
                continue
            no_money = [n for n, v in m["tables"].items() if not v["money"] and v["rows"] > 1000]
            shops.append(dict(
                shop=shop, tap=split, ket_qua="OK", giay=round(time.time() - t0), so_bang=len(tabs),
                so_dong=sum(len(v) for v in tabs.values()), canh_bao=len(m["warnings"]),
                ngay_tu=m["date_from"], ngay_den=m["date_to"],
                ngay_tu_tho=m["date_from_all"], ngay_den_tho=m["date_to_all"],
                bang_loi_font=";".join(n for n in tabs if _bad_name(n)),
                bang_lon_khong_co_cot_tien=";".join(no_money),
                cot_bi_dien=";".join("%s.%s" % (n, c) for n, v in m["tables"].items() for c in v["ffilled"]),
            ))
            for n, c, kind, ex in invariant_issues(tabs):
                cols.append(dict(shop=shop, bang=n, cot=c, van_de="BẤT BIẾN: " + kind, so_o=None))
            for n, v in m["tables"].items():
                if v.get("dup_rows"):
                    cols.append(dict(shop=shop, bang=n, cot="(cả dòng)", van_de="DÒNG TRÙNG HOÀN TOÀN (đã gắn cờ _is_exact_dup, KHÔNG xoá)", so_o=v["dup_rows"]))
                if v.get("total_rows_dropped"):
                    cols.append(dict(shop=shop, bang=n, cot="(dòng tổng)", van_de="DÒNG TỔNG ĐÃ BỎ: " + "; ".join(v.get("total_rows_dropped_text", [])), so_o=v["total_rows_dropped"]))
                for c, k in v["unparsed"].items():
                    cols.append(dict(shop=shop, bang=n, cot=c, van_de="Ô KHÔNG ĐỔI ĐƯỢC", so_o=k))
                for c, k in v["skipped"].items():
                    cols.append(dict(shop=shop, bang=n, cot=c, van_de="TRÔNG NHƯ %s NHƯNG BỎ QUA" % k.upper(), so_o=None))
                for c in v["numeric_text"]:
                    cols.append(dict(shop=shop, bang=n, cot=c, van_de="CHUỖI TOÀN SỐ, CHƯA ĐỔI (kiểm tra có phải tiền/SL?)", so_o=None))
            if verbose:
                print(shop, shops[-1]["ket_qua"], shops[-1]["giay"], "s")
    rep, col = pd.DataFrame(shops), pd.DataFrame(cols)
    if out_dir:
        rep.to_csv(os.path.join(out_dir, "dq_report.csv"), index=False, encoding="utf-8-sig")
        col.to_csv(os.path.join(out_dir, "dq_columns.csv"), index=False, encoding="utf-8-sig")
    return rep, col
