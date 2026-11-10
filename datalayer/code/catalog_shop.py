# -*- coding: utf-8 -*-
"""Việc 3 — Bước 1: LIỆT KÊ cột của mọi bảng của mọi shop (dùng bảng đã làm sạch của việc 2).

catalog_shop(shop_dir, tap, shop)  -> (cột, bảng)    mỗi cột 1 dòng, mỗi bảng 1 dòng
unique_columns(cột)                -> mỗi tên cột chuẩn hoá 1 dòng (để điền VAI TRÒ)
Chỉ ĐỌC dữ liệu, không sửa gì. Cần value_parsers.py và clean_shop.py (việc 2) cùng thư mục / trong sys.path.
"""
import re
import unicodedata
from collections import Counter

import pandas as pd

from clean_shop import load_clean_tables

_ID = re.compile(r"^([A-Za-z]{1,8})[-_ ]?\d{2,}$")
_TABLE_HINTS = [
    ("nhaphang", "nhap_hang"), ("chiphi", "chi_phi"), ("congno", "cong_no"), ("tonkho", "ton_kho"), ("khachhang", "khach_hang"), ("quydoi", "quy_doi_don_vi"),
    ("banggia", "bang_gia"), ("giaohang", "giao_hang"), ("hanghoa", "danh_muc_hang"), ("sanpham", "danh_muc_hang"), ("danhmuc", "danh_muc_hang"),  # (từ khoá trong tên file/sheet đã bỏ dấu, gợi ý loại bảng)
    ("nhap", "nhap_hang"), ("the kho", "ton_kho"), ("thekho", "ton_kho"), ("ton", "ton_kho"), ("no", "cong_no"), ("khach", "khach_hang"), ("thu", "thanh_toan"),
    ("gia", "bang_gia"), ("quy doi", "quy_doi_don_vi"), ("quydoi", "quy_doi_don_vi"), ("ghi tat", "ten_tat"),
    ("chi phi", "chi_phi"), ("ca", "ca_lam"), ("giao", "giao_hang"), ("tho", "nhan_vien"), ("nhan vien", "nhan_vien"),
    ("san pham", "danh_muc_hang"), ("hang hoa", "danh_muc_hang"), ("danh muc", "danh_muc_hang"), ("thuoc", "danh_muc_hang"),
    ("lo", "lo_han_dung"), ("sua xe", "sua_chua"), ("may cu", "thu_may_cu"), ("hoa don", "ban_hang"), ("hoadon", "ban_hang"), ("ban hang", "ban_hang"), ("banhang", "ban_hang"),
    ("don hang", "ban_hang"), ("chi tiet", "ban_hang"),
]


def ascii_fold(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def table_hint(name, files):
    t = " " + ascii_fold(name + " " + " ".join(files)) + " "
    for k, v in _TABLE_HINTS:
        if " " + k + " " in t or (len(k) > 3 and " " not in k and k in t):
            return v
    return ""


def _kind(series, tm, col):
    """Loại giá trị của cột: tien | ngay | so_luong_kem_don_vi | ma | so_nguyen | so_thuc | nhom | chu | rong"""
    if col in tm.get("money", []):
        return "tien", ""
    if col in tm.get("date", []):
        return "ngay", ""
    if col in tm.get("qty", []):
        return "so_luong_kem_don_vi", ""
    vals = series.dropna()
    if vals.empty:
        return "rong", ""
    smp = vals.iloc[:: max(1, len(vals) // 2000)].head(2000)
    strs = [str(v).strip() for v in smp]
    m = [_ID.match(v) for v in strs]
    if sum(1 for x in m if x) / len(strs) >= 0.7:
        prefix = Counter(x.group(1).upper() for x in m if x).most_common(1)[0][0]
        return "ma", prefix
    nums = pd.to_numeric(pd.Series(strs), errors="coerce")
    if nums.notna().mean() >= 0.9:
        return ("so_nguyen" if (nums.dropna() % 1 == 0).all() else "so_thuc"), ""
    nun = len(set(strs))
    return ("nhom" if nun <= 25 and nun <= 0.05 * len(vals) + 3 else "chu"), ""


def catalog_shop(shop_dir, tap, shop):
    tables, meta = load_clean_tables(shop_dir)
    cols, tabs = [], []
    for tname, df in tables.items():
        tm = meta["tables"][tname]
        real = [c for c in df.columns if not c.startswith("_source") and c != "_sheet_year" and not c.endswith("__don_vi")]
        tabs.append({"tap": tap, "shop": shop, "bang": tname, "file": "; ".join(tm["files"]), "so_dong": len(df),
                     "so_cot": len(real), "goi_y_loai_bang": table_hint(tname, tm["files"]),
                     "cot_tien": "; ".join(tm["money"]), "cot_ngay": "; ".join(tm["date"]),
                     "cot_so_luong": "; ".join(tm["qty"]), "cot_dien_o_trong": "; ".join(tm["ffilled"])})
        for c in real:
            s = df[c]
            kind, prefix = _kind(s, tm, c)
            nn = s.dropna()
            ex = []
            for v in nn.head(300):
                t = str(v)[:28]
                if t not in ex:
                    ex.append(t)
                if len(ex) == 3:
                    break
            cols.append({"tap": tap, "shop": shop, "bang": tname, "cot": c, "cot_chuan": ascii_fold(c), "loai_gia_tri": kind,
                         "tien_to_ma": prefix, "ti_le_rong": round(float(s.isna().mean()), 3), "so_gia_tri_khac_nhau": int(nn.astype(str).nunique()),
                         "vi_du": " | ".join(ex)})
    return cols, tabs


def unique_columns(cols):
    """Gom theo tên cột chuẩn hoá: bao nhiêu shop dùng, loại giá trị phổ biến, ví dụ. Cột 'vai_tro' để người điền."""
    df = pd.DataFrame(cols)
    rows = []
    for name, g in df.groupby("cot_chuan"):
        rows.append({"cot_chuan": name, "so_shop_train": g[g.tap == "train"].shop.nunique(), "so_shop_public": g[g.tap == "public"].shop.nunique(),
                     "so_bang": len(g), "ten_goc_pho_bien": g.cot.value_counts().index[0],
                     "loai_gia_tri_pho_bien": g.loai_gia_tri.value_counts().index[0], "tien_to_ma": g[g.tien_to_ma != ""].tien_to_ma.value_counts().index[0] if (g.tien_to_ma != "").any() else "",
                     "vi_du": g.vi_du.iloc[0], "bang_vi_du": g.bang.iloc[0], "vai_tro": ""})
    out = pd.DataFrame(rows)
    out["so_shop"] = out.so_shop_train + out.so_shop_public
    return out.sort_values(["so_shop", "so_bang"], ascending=False).reset_index(drop=True)
