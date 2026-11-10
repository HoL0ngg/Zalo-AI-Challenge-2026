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
            for n, v in m["tables"].items():
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
