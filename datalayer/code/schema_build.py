# -*- coding: utf-8 -*-
"""Việc 3 — SỔ CHUẨN (v16): đổi các bảng đã làm sạch của MỘT shop thành:
  v_lines, v_orders, v_purchases, v_inventory, v_debt, v_installments, v_expense, v_warranty, info.

Đầu vào : tables, meta = clean_shop.load_clean_tables(shop_dir)
Đầu ra  : build_canonical(tables, meta) -> dict(...)
"""
import re
import unicodedata

import pandas as pd

import catalog_shop as cat
import role_draft as rd
from value_parsers import parse_money

STATUS_VALUES = ("hoan_thanh", "huy", "tra_hang", "dang_giao")


def norm_status(v):
    """Giá trị trạng thái tự do -> 1 trong 4 trạng thái chuẩn (hoặc None nếu không nhận ra)."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    a = " " + cat.ascii_fold(v) + " "
    if re.search(r"\bhuy\b|cancel|khong giao duoc|giao khong thanh", a):
        return "huy"
    if re.search(r"tra hang|tra lai|tra ve|hoan tra|hoan hang|doi tra|return|khach tra", a):
        return "tra_hang"
    if re.search(r"\bdang\b|cho giao|shipping|van chuyen|xu ly|pending", a):
        return "dang_giao"
    if re.search(r"hoan thanh|\bxong\b|da lay|thanh cong|\bok\b|da giao|complete|received|da nhan", a):
        return "hoan_thanh"
    return None


# ───────────────────────── vai trò cột ─────────────────────────
_DATE_PREF = [r"dat|ban|giao dich|tao|lap|^ngay$|^thoi gian$|date", r"gio"]
_DATE_BAD = re.compile(r"giao hang|han|tra|nhap|sinh|dang ky|ap dung|thu|bao hanh|ngay giao")

_MONEY_ROLES = {"don_gia", "thanh_tien_dong", "tong_don", "tong_tien_hang", "giam_gia", "phi_ship", "gia_von", "gia_nhap", "da_tra", "cong_no", "gia_cu_moi"}


def _fix_excel_dt_series(s):
    if s is None:
        return s
    def _conv(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, (int, float)):
            iv = int(v)
            if 35000 <= iv <= 60000:
                return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=iv)).strftime("%Y-%m-%d")
        sv = str(v).strip()
        if sv in ("", "None", "nan", "NaT", "<NA>"):
            return None
        if re.fullmatch(r"\d{5}(?:\.0)?", sv):
            iv = int(float(sv))
            if 35000 <= iv <= 60000:
                return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=iv)).strftime("%Y-%m-%d")
        m_dmy = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", sv)
        if m_dmy:
            d, m, y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
            if 1 <= m <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{m:02d}-{d:02d}"
        return sv
    return s.map(_conv)


def _clean_customer_series(s):
    if s is None:
        return s
    def _c(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        sv = str(v).strip()
        if sv in ("", "None", "nan", "<NA>"):
            return None
        # Strip trailing phone numbers like 'Triệu Linh An - 0327 988 481' or 'Tăng Hương Thu 0914430525'
        sv2 = re.sub(r"(?:\s*[-–|]\s*|\s+)0\d[\d\s\.]{7,12}$", "", sv).strip()
        return sv2 if sv2 else sv
    return s.map(_c)


def column_roles(df, tm):
    """role -> danh sách (cột, kiểu, tỉ lệ có dữ liệu) cho 1 bảng. Nhận diện theo TÊN, rồi bổ sung theo NỘI DUNG."""
    out, used = {}, set()
    for c in df.columns:
        if c.startswith("_") or c.endswith("__don_vi") or c.endswith("__raw"):
            continue
        kind, prefix = cat._kind(df[c], tm, c)
        role, _ = rd.infer_role(cat.ascii_fold(c), kind, prefix)
        if role and role not in ("rong",):
            if role in _MONEY_ROLES and kind != "tien":
                smp = df[c].dropna().head(300)
                if len(smp) and sum(parse_money(v) is not None for v in smp) / len(smp) >= 0.9:
                    kind = "tien"
            out.setdefault(role, []).append((c, kind, float(df[c].notna().mean())))
            if role != "khong_dung":
                used.add(c)
    if "trang_thai" not in out:
        for c in df.columns:
            if c in used or c.startswith("_") or c.endswith("__raw"):
                continue
            smp = df[c].dropna().astype(str).head(1000)
            if len(smp) >= 20 and smp.nunique() <= 12 and smp.map(norm_status).notna().mean() >= 0.9:
                out["trang_thai"] = [(c, "nhom", float(df[c].notna().mean()))]
                used.add(c)
                break
    if "ten_hang" not in out and "ma_hang" not in out and "so_luong" in out:
        best, best_n = None, 0
        for c in df.columns:
            if c in used or c.startswith("_") or c.endswith("__raw") or c.endswith("__don_vi"):
                continue
            kind, _ = cat._kind(df[c], tm, c)
            n = df[c].dropna().astype(str).nunique()
            if kind in ("chu", "nhom") and 5 <= n and n > best_n and df[c].notna().mean() > 0.8:
                best, best_n = c, n
        if best:
            out["ten_hang"] = [(best, "chu", float(df[best].notna().mean()))]
    return out


def _best(cands, want_kind=None, prefer=None, avoid=None):
    if not cands:
        return None
    best, best_s = None, -1e9
    for c, kind, fill in cands:
        name = cat.ascii_fold(c)
        s = fill * 10
        if want_kind and kind in want_kind:
            s += 5
        if prefer and re.search(prefer, name):
            s += 3
        if avoid and re.search(avoid, name):
            s -= 6
        if s > best_s:
            best, best_s = c, s
    return best


def _pick(roles, role, **kw):
    return _best(roles.get(role, []), **kw)


def pick_line_amount(df, roles, qty_col, price_col):
    if not (qty_col and price_col):
        return None, 0.0
    smp = df.iloc[:: max(1, len(df) // 20000)]
    q = _num(smp[qty_col])
    qd_cols = [c for c, _, _ in roles.get("quy_doi", [])]
    p = _num(smp[price_col])
    prods = {"sl*gia": q * p}
    for c in qd_cols[:2]:
        prods["qd:" + c] = _num(smp[c]) * p
    best, best_r = None, 0.0
    skip = {price_col, qty_col} | set(qd_cols)
    money = {c for c in df.columns if not c.startswith("_") and not c.endswith("__don_vi") and c not in skip
             and _num(smp[c]).notna().mean() > 0.9}
    for c in money:
        v = _num(smp[c])
        for _, pr in prods.items():
            ok = ((v - pr).abs() <= (0.002 * v.abs()).clip(lower=1)) & v.notna() & pr.notna()
            r = float(ok.sum()) / max(1, int((v.notna() & pr.notna()).sum()))
            if r > best_r:
                best, best_r = c, r
    return (best, best_r) if best_r >= 0.5 else (None, best_r)


# ───────────────────────── phân loại bảng bán hàng ─────────────────────────
def classify_sales_table(name, roles, files=()):
    hint = cat.table_hint(name, files)
    has = lambda r: r in roles
    if has("ma_phieu_nhap") or hint in ("nhap_hang", "ton_kho", "ten_tat", "bang_gia", "quy_doi_don_vi", "danh_muc_hang", "khach_hang", "nhan_vien", "chi_phi"):
        if not (has("ma_don") and (has("thanh_tien_dong") or has("don_gia"))):
            return None
    if any(k in cat.ascii_fold(name) for k in ("tra gop", "bao hanh", "so no", "thu may cu", "khuyen mai")):
        return None
    item = has("ten_hang") or has("ma_hang")
    if not has("ma_don"):
        if item and has("so_luong") and (has("thanh_tien_dong") or has("don_gia") or has("tong_don")) and has("thoi_diem"):
            return "flat_noid"
        return None
    qty = has("so_luong")
    money_line = has("thanh_tien_dong") or has("don_gia")
    order_lvl = any(has(r) for r in ("thoi_diem", "trang_thai", "tong_don", "ten_khach", "ma_khach", "phuong_thuc_tt"))
    if item and qty and money_line:
        return "flat" if (has("thoi_diem") and (has("trang_thai") or has("tong_don") or has("ten_khach"))) else "lines"
    if order_lvl and (has("tong_don") or has("thoi_diem")) and not (item and qty):
        if hint in ("giao_hang", "cong_no", "thanh_toan") and not has("thoi_diem"):
            return None
        return "orders"
    return None


def _is_note(col):
    return re.sub(r"[^a-z0-9]", "", cat.ascii_fold(col)).startswith(("ghichu", "note"))


def _find_note(df):
    return next((c for c in df.columns if not c.startswith("_") and _is_note(c) and not c.endswith("__raw")), None)


def status_series(base, st_col):
    if st_col:
        out = base[st_col].map(norm_status)
        if _is_note(st_col):
            out = out.fillna("hoan_thanh")
        return out, ("ghi_chu" if _is_note(st_col) else "cot_trang_thai")
    note = _find_note(base)
    if note:
        return base[note].map(norm_status).fillna("hoan_thanh"), "ghi_chu"
    return pd.Series([None] * len(base), index=base.index), None


def _clean_id(s):
    return s.astype(str).str.strip().replace({"nan": None, "None": None, "": None, "<NA>": None})


def _num(s):
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    x = pd.to_numeric(s, errors="coerce")
    miss = x.isna() & s.notna()
    if miss.any():
        x = x.astype("float64")
        x[miss] = pd.to_numeric(s[miss].map(parse_money), errors="coerce")
    return x


def ledger_candidate(tables, tmeta):
    best = None
    for tn, df in tables.items():
        tm = tmeta[tn]
        if len(df) < 20 or not tm.get("money") or not tm.get("date"):
            continue
        if cat.table_hint(tn, tm.get("files", [])) in ("khach_hang", "nhan_vien", "bang_gia", "danh_muc_hang", "chi_phi", "nhap_hang", "ton_kho"):
            continue
        if any(k in cat.ascii_fold(tn) for k in ("tra gop", "bao hanh", "so no", "thu may cu", "bao cao ca")):
            continue
        d = max(tm["date"], key=lambda c: df[c].notna().mean())
        m = max(tm["money"], key=lambda c: df[c].notna().mean())
        if best is None or len(df) > best[3]:
            best = (tn, d, m, len(df))
    return best


def build_ledger(df, tm, led, info):
    _, dcol, mcol, _ = led
    base = df.copy()
    st, info["status_source"] = status_series(base, None)
    emp = next((c for c in base.columns if re.search(r"^(tho|nhan vien|nguoi lam|nguoi ban)", cat.ascii_fold(c))), None)
    what = next((c for c in base.columns if re.search(r"lam gi|noi dung|dich vu|cong viec|hang muc", cat.ascii_fold(c))), None)
    ids = ["R%d" % i for i in range(len(base))]
    vl = pd.DataFrame({"order_id": ids, "order_dt": _fix_excel_dt_series(base[dcol]).values, "line_amount": _num(base[mcol]).values})
    vl["line_total"] = vl["line_amount"]
    vl["status"] = st.fillna("hoan_thanh").values if st.notna().any() else pd.Series(["hoan_thanh"]*len(base)).values
    vl["product"] = base[what].values if what else None
    vl["product_name"] = vl["product"]
    vl["employee"] = base[emp].values if emp else None
    vl["customer"] = None
    vl["customer_id"] = None
    vl["qty"] = 1.0
    vl["quantity"] = 1.0
    vl["qty_base"] = 1.0
    vl["is_fee"] = 0
    vl["category"] = "dịch vụ"
    vo = pd.DataFrame({"order_id": ids, "order_dt": vl["order_dt"].values, "status": vl["status"].values, "employee": vl["employee"].values,
                       "customer": None, "customer_id": None,
                       "items_total": vl["line_amount"].values, "order_total": vl["line_amount"].values})
    info["structure"] = "ledger"
    info["tables_used"] = {"lines": led[0], "orders": None}
    info["warnings"].append("sổ ghi theo lần (mỗi dòng là một lượt/phiếu): doanh thu = cột tiền")
    return {"v_lines": vl, "v_orders": vo, "v_purchases": None, "v_inventory": None, "info": info}


def pick_order_table(tables, cls, orders, L):
    lroles = cls[L][1]
    lid = _pick(lroles, "ma_don")
    lids = set(_clean_id(tables[L][lid]).dropna().head(30000)) if lid else set()
    best, best_key = None, None
    for t in orders:
        roles = cls[t][1]
        oid = _pick(roles, "ma_don")
        if not oid:
            continue
        oids = set(_clean_id(tables[t][oid]).dropna())
        cover = len(lids & oids) / max(1, len(lids))
        key = (round(cover, 1), "trang_thai" in roles, "thoi_diem" in roles, len(tables[t]))
        if best_key is None or key > best_key:
            best, best_key = t, key
    return best or max(orders, key=lambda t: len(tables[t]))


def _enrich_from_catalogs(vl, tables, meta):
    """Bổ sung category, product, brand, hoat_chat, thuoc_ke_don, cost_amount, ghi_tat."""
    if vl is None or vl.empty:
        return vl
    # 1. Expand 'Ghi tắt' tables (dev_011, dev_014)
    for tn, df in tables.items():
        cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
        if "ghitat" in cols_sq and "tenhang" in cols_sq and "product" in vl.columns:
            gt_c = cols_sq["ghitat"]
            th_c = cols_sq["tenhang"]
            loai_c = cols_sq.get("loai")
            abbr_map = {}
            cat_map = {}
            for _, r in df.iterrows():
                k = str(r[gt_c]).strip() if pd.notna(r[gt_c]) else ""
                v = str(r[th_c]).strip() if pd.notna(r[th_c]) else ""
                if k and v:
                    abbr_map[k] = v
                    abbr_map[k.lower()] = v
                    if loai_c and pd.notna(r[loai_c]):
                        cat_map[v] = str(r[loai_c]).strip()
                        cat_map[k] = str(r[loai_c]).strip()
            if abbr_map:
                vl["product"] = vl["product"].map(lambda x: abbr_map.get(str(x).strip(), abbr_map.get(str(x).strip().lower(), x)) if pd.notna(x) else x)
                vl["product_name"] = vl["product"]
                if cat_map and ("category" not in vl.columns or vl["category"].isna().mean() > 0.5):
                    mapped_cat = vl["product"].map(lambda x: cat_map.get(str(x).strip()) if pd.notna(x) else None)
                    vl["category"] = vl["category"].where(vl["category"].notna(), mapped_cat) if "category" in vl.columns else mapped_cat

    for _loop in range(2):
        for tn, df in tables.items():
            tm = meta["tables"][tn]
            hint = cat.table_hint(tn, tm.get("files", []))
            is_cat = hint in ("danh_muc_hang", "bang_gia") or any(w in tn.lower() for w in ["sanpham", "danhmuc", "danh_muc", "thuoc", "hanghoa", "san_pham"])
            if not is_cat:
                continue
            prod_col, sku_col, cat_col, cost_col, ingr_col, presc_col, brand_col = None, None, None, None, None, None, None
            for c in df.columns:
                if c.startswith("_"): continue
                kind, prefix = cat._kind(df[c], tm, c)
                r, _ = rd.infer_role(cat.ascii_fold(c), kind, prefix)
                if r == "ten_hang" and not prod_col: prod_col = c
                elif r == "ma_hang" and not sku_col: sku_col = c
                elif r == "nhom_hang" and not cat_col: cat_col = c
                elif r == "gia_von" and not cost_col: cost_col = c
                elif r == "hoat_chat" and not ingr_col: ingr_col = c
                elif r == "thuoc_ke_don" and not presc_col: presc_col = c
                elif (r == "thuong_hieu" or c.strip().lower() == "hãng") and not brand_col: brand_col = c

            if not prod_col:
                for c in df.columns:
                    if not c.startswith("_") and rd.squash(cat.ascii_fold(c)) == "tengoi":
                        prod_col = c
                        break

            join_key, target_key = None, None
            if prod_col and "product" in vl.columns and vl["product"].notna().any():
                # Check if values overlap before picking product vs sku
                p_vals = set(df[prod_col].dropna().astype(str).head(500))
                v_vals = set(vl["product"].dropna().astype(str).head(500))
                if len(p_vals & v_vals) > 0 or not (sku_col and "sku" in vl.columns and vl["sku"].notna().any()):
                    join_key, target_key = prod_col, "product"
                else:
                    join_key, target_key = sku_col, "sku"
            elif sku_col and "sku" in vl.columns and vl["sku"].notna().any():
                join_key, target_key = sku_col, "sku"

            if not join_key:
                continue

            cols_to_pull = []
            rename_map = {join_key: target_key}
            if prod_col and ("product" not in vl.columns or vl["product"].isna().mean() > 0.5) and join_key != prod_col:
                cols_to_pull.append(prod_col)
                rename_map[prod_col] = "__prod_enrich"
            if sku_col and ("sku" not in vl.columns or vl["sku"].isna().mean() > 0.5) and join_key != sku_col:
                cols_to_pull.append(sku_col)
                rename_map[sku_col] = "__sku_enrich"
            if cat_col and (("category" not in vl.columns) or vl["category"].isna().mean() > 0.2):
                cols_to_pull.append(cat_col)
                rename_map[cat_col] = "__cat_enrich"
            if brand_col and (("brand" not in vl.columns) or vl["brand"].isna().mean() > 0.5):
                cols_to_pull.append(brand_col)
                rename_map[brand_col] = "__brand_enrich"
            if ingr_col and ("hoat_chat" not in vl.columns or vl["hoat_chat"].isna().mean() > 0.5):
                cols_to_pull.append(ingr_col)
                rename_map[ingr_col] = "__ingr_enrich"
            if presc_col and ("thuoc_ke_don" not in vl.columns or vl["thuoc_ke_don"].isna().mean() > 0.5):
                cols_to_pull.append(presc_col)
                rename_map[presc_col] = "__presc_enrich"
            if cost_col and ("cost_amount" not in vl.columns or vl["cost_amount"].isna().mean() > 0.5):
                cols_to_pull.append(cost_col)
                rename_map[cost_col] = "__cost_enrich"

            if cols_to_pull:
                sub = df.dropna(subset=[join_key]).drop_duplicates(subset=[join_key])[[join_key] + cols_to_pull].rename(columns=rename_map)
                vl = vl.merge(sub, on=target_key, how="left")
                if "__prod_enrich" in vl.columns:
                    vl["product"] = vl["product"].where(vl["product"].notna(), vl["__prod_enrich"]) if "product" in vl.columns else vl["__prod_enrich"]
                    vl["product_name"] = vl["product"]
                    vl.drop(columns=["__prod_enrich"], inplace=True)
                if "__sku_enrich" in vl.columns:
                    vl["sku"] = vl["sku"].where(vl["sku"].notna(), vl["__sku_enrich"]) if "sku" in vl.columns else vl["__sku_enrich"]
                    vl.drop(columns=["__sku_enrich"], inplace=True)
                if "__cat_enrich" in vl.columns:
                    vl["category"] = vl["category"].where(vl["category"].notna(), vl["__cat_enrich"]) if "category" in vl.columns else vl["__cat_enrich"]
                    vl.drop(columns=["__cat_enrich"], inplace=True)
                if "__brand_enrich" in vl.columns:
                    vl["brand"] = vl["brand"].where(vl["brand"].notna(), vl["__brand_enrich"]) if "brand" in vl.columns else vl["__brand_enrich"]
                    vl.drop(columns=["__brand_enrich"], inplace=True)
                if "__ingr_enrich" in vl.columns:
                    vl["hoat_chat"] = vl["hoat_chat"].where(vl["hoat_chat"].notna(), vl["__ingr_enrich"]) if "hoat_chat" in vl.columns else vl["__ingr_enrich"]
                    vl["active_ingredient"] = vl["hoat_chat"]
                    vl.drop(columns=["__ingr_enrich"], inplace=True)
                if "__presc_enrich" in vl.columns:
                    p_norm = vl["__presc_enrich"].astype(str).str.lower().map(lambda s: 1 if any(k in s for k in ("ke don", "kê đơn", "co", "có", "1", "true", "x", "t")) else 0)
                    vl["thuoc_ke_don"] = p_norm
                    vl["is_prescription"] = p_norm
                    vl.drop(columns=["__presc_enrich"], inplace=True)
                if "__cost_enrich" in vl.columns:
                    c_val = _num(vl["__cost_enrich"])
                    if "qty" in vl.columns:
                        vl["cost_amount"] = (vl["qty"] * c_val).fillna(0)
                    else:
                        vl["cost_amount"] = c_val.fillna(0)
                    vl.drop(columns=["__cost_enrich"], inplace=True)
    return vl


def _apply_unit_conversion(vl, tables, meta):
    """Tạo cột qty_base (số lượng quy đổi về đơn vị cơ bản)."""
    if vl is None or vl.empty:
        return vl
    if "qty_base" in vl.columns and vl["qty_base"].notna().mean() > 0.5:
        vl["qty_base"] = vl["qty_base"].fillna(vl["qty"])
        return vl

    # Build conversion dict: (product_lower, unit_lower) -> ratio
    conv_map = {}
    for tn, df in tables.items():
        cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
        # Pattern 1: DanhSachQuyDoi ('Tên sản phẩm', 'Đơn vị quy đổi', 'Tỉ lệ quy đổi', 'Đơn vị cơ bản')
        if "donviquydoi" in cols_sq and ("tilequydoi" in cols_sq or "tylequydoi" in cols_sq):
            p_c = cols_sq.get("tensanpham") or cols_sq.get("tenhang")
            u_c = cols_sq["donviquydoi"]
            r_c = cols_sq.get("tilequydoi") or cols_sq.get("tylequydoi")
            if p_c and u_c and r_c:
                for p, u, r in zip(df[p_c], df[u_c], _num(df[r_c])):
                    if pd.notna(p) and pd.notna(u) and pd.notna(r) and r > 0:
                        conv_map[(str(p).strip().lower(), str(u).strip().lower())] = float(r)
        # Pattern 2: DanhMuc ('Hàng', 'Hệ số', 'ĐV gốc', 'Loại ĐV') - dev_004
        elif "heso" in cols_sq and ("loaidv" in cols_sq or "donvi" in cols_sq):
            p_c = cols_sq.get("hang") or cols_sq.get("tenhang") or cols_sq.get("tensanpham")
            u_c = cols_sq.get("loaidv") or cols_sq.get("donvi")
            r_c = cols_sq["heso"]
            if p_c and u_c and r_c:
                for p, u, r in zip(df[p_c], df[u_c], _num(df[r_c])):
                    if pd.notna(p) and pd.notna(u) and pd.notna(r) and r > 0:
                        conv_map[(str(p).strip().lower(), str(u).strip().lower())] = float(r)
        # Pattern 3: pos__don_vi_sp ('MaHangHoa', 'DonViTinh', 'HeSoQuyDoi') - dev_006
        elif "hesoquydoi" in cols_sq and "donvitinh" in cols_sq:
            s_c = cols_sq.get("mahanghoa") or cols_sq.get("mahang")
            u_c = cols_sq["donvitinh"]
            r_c = cols_sq["hesoquydoi"]
            if s_c and u_c and r_c:
                for s, u, r in zip(df[s_c], df[u_c], _num(df[r_c])):
                    if pd.notna(s) and pd.notna(u) and pd.notna(r) and r > 0:
                        conv_map[(str(s).strip().lower(), str(u).strip().lower())] = float(r)

    if conv_map and "qty" in vl.columns and "unit" in vl.columns:
        p_key = vl["product"].fillna("").astype(str).str.strip().str.lower()
        s_key = vl["sku"].fillna("").astype(str).str.strip().str.lower() if "sku" in vl.columns else pd.Series([""] * len(vl))
        u_key = vl["unit"].fillna("").astype(str).str.strip().str.lower()
        ratios = []
        for pk, sk, uk in zip(p_key, s_key, u_key):
            r = conv_map.get((pk, uk)) or conv_map.get((sk, uk)) or 1.0
            ratios.append(r)
        vl["qty_base"] = (vl["qty"].astype(float) * pd.Series(ratios, index=vl.index)).round(4)
    else:
        vl["qty_base"] = vl["qty"] if "qty" in vl.columns else None
    return vl


def _build_purchases(tables, meta):
    """Trích xuất v_purchases (sổ nhập hàng) từ các bảng nhập (kể cả header + detail)."""
    header_df, detail_df = None, None
    single_candidates = []
    for tn, df in tables.items():
        tm = meta["tables"][tn]
        hint = cat.table_hint(tn, tm.get("files", []))
        af = cat.ascii_fold(tn)
        if hint == "nhap_hang" or any(w in af for w in ["nhap hang", "nhaphang", "phieu nhap", "phieunhap", "chi tiet nhap"]):
            if "chi tiet" in af or "chitiet" in af or ("ten_hang" in column_roles(df, tm) or "ma_hang" in column_roles(df, tm)):
                if "thoi_diem" in column_roles(df, tm):
                    single_candidates.append((tn, df, tm))
                else:
                    detail_df = (tn, df, tm)
            else:
                header_df = (tn, df, tm)

    ncc_map = {}
    for tn, df in tables.items():
        if "nha_cung_cap" in cat.ascii_fold(tn).replace(" ", "_") or "nhacungcap" in rd.squash(cat.ascii_fold(tn)):
            cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
            id_c = cols_sq.get("manhacungcap") or cols_sq.get("mancc")
            nm_c = cols_sq.get("tengoi") or cols_sq.get("tennhacungcap") or cols_sq.get("tenncc")
            if id_c and nm_c:
                for k, v in zip(df[id_c], df[nm_c]):
                    if pd.notna(k) and pd.notna(v):
                        ncc_map[str(k).strip()] = str(v).strip()

    chosen = None
    if single_candidates:
        tn, df, tm = max(single_candidates, key=lambda x: len(x[1]))
        chosen = (df, tm)
    elif detail_df and header_df:
        d_tn, d_df, d_tm = detail_df
        h_tn, h_df, h_tm = header_df
        d_roles = column_roles(d_df, d_tm)
        h_roles = column_roles(h_df, h_tm)
        d_id = _pick(d_roles, "ma_phieu_nhap") or _pick(d_roles, "ma_don")
        h_id = _pick(h_roles, "ma_phieu_nhap") or _pick(h_roles, "ma_don")
        if d_id and h_id:
            merged = d_df.merge(h_df.drop_duplicates(subset=[h_id]), left_on=d_id, right_on=h_id, how="left", suffixes=("", "_hdr"))
            chosen = (merged, d_tm)
    elif detail_df:
        chosen = (detail_df[1], detail_df[2])
    elif header_df:
        chosen = (header_df[1], header_df[2])

    if not chosen:
        return None
    df, tm = chosen
    roles = column_roles(df, tm)
    p_id = _pick(roles, "ma_phieu_nhap") or _pick(roles, "ma_don")
    p_dt = _pick(roles, "thoi_diem", want_kind=("ngay",))
    p_item = _pick(roles, "ten_hang")
    p_sku = _pick(roles, "ma_hang")
    p_qty = _pick(roles, "so_luong") or _pick(roles, "quy_doi")
    p_unit = _pick(roles, "don_vi")
    p_price = _pick(roles, "gia_nhap") or _pick(roles, "don_gia")
    p_amt = _pick(roles, "thanh_tien_dong") or _pick(roles, "tong_don")
    p_ncc = _pick(roles, "ma_ncc") or _pick(roles, "ten_khach")

    base = df.copy()
    if not p_id:
        base["__rowid"] = ["P%d" % i for i in range(len(base))]
        p_id = "__rowid"

    vp = pd.DataFrame({"order_id": _clean_id(base[p_id])})
    vp["receipt_id"] = vp["order_id"]
    vp["order_dt"] = _fix_excel_dt_series(base[p_dt]).values if p_dt else None
    vp["receipt_dt"] = vp["order_dt"]
    vp["product"] = base[p_item].values if p_item else None
    vp["product_name"] = vp["product"]
    vp["sku"] = base[p_sku].values if p_sku else None
    vp["qty"] = _num(base[p_qty]).values if p_qty else None
    vp["quantity"] = vp["qty"]
    vp["unit"] = base[p_unit].values if p_unit else None
    vp["unit_price"] = _num(base[p_price]).values if p_price else None
    vp["cost_price"] = vp["unit_price"]
    if p_amt:
        vp["line_amount"] = _num(base[p_amt]).values
    elif p_qty and p_price:
        vp["line_amount"] = (vp["qty"] * vp["unit_price"]).values
    else:
        vp["line_amount"] = None
    vp["total_amount"] = vp["line_amount"]
    vp["supplier"] = base[p_ncc].values if p_ncc else None
    if ncc_map and vp["supplier"].notna().any():
        vp["supplier"] = vp["supplier"].map(lambda x: ncc_map.get(str(x).strip(), x) if pd.notna(x) else x)
    if vp["product"].isna().all() and vp["sku"].notna().any():
        vp = _enrich_from_catalogs(vp, tables, meta)
    return vp


def _build_inventory(tables, meta):
    for tn, df in tables.items():
        tm = meta["tables"][tn]
        hint = cat.table_hint(tn, tm.get("files", []))
        if hint != "ton_kho" and not any(w in tn.lower() for w in ["tonkho", "ton_kho", "thekho", "the_kho"]):
            continue
        roles = column_roles(df, tm)
        p_item = _pick(roles, "ten_hang")
        p_sku = _pick(roles, "ma_hang")
        p_unit = _pick(roles, "don_vi") or _pick(roles, "quy_doi")
        p_stock = _pick(roles, "ton_kho")
        p_cost = _pick(roles, "gia_von") or _pick(roles, "gia_nhap")
        p_dt = _pick(roles, "thoi_diem", want_kind=("ngay",))

        base = df.copy()
        vi = pd.DataFrame()
        vi["product"] = base[p_item].values if p_item else None
        vi["product_name"] = vi["product"]
        vi["sku"] = base[p_sku].values if p_sku else None
        vi["unit"] = base[p_unit].values if p_unit else None
        vi["ending_stock"] = _num(base[p_stock]).values if p_stock else None
        vi["qty"] = vi["ending_stock"]
        vi["quantity"] = vi["ending_stock"]
        vi["cost_price"] = _num(base[p_cost]).values if p_cost else None
        vi["date"] = _fix_excel_dt_series(base[p_dt]).values if p_dt else None
        if vi["product"].isna().all() and vi["sku"].notna().any():
            vi = _enrich_from_catalogs(vi, tables, meta)
        if len(vi) > 500:
            if p_dt:
                vi = vi.sort_values("date", kind="stable")
            dedup_col = "product" if vi["product"].notna().any() else ("sku" if vi["sku"].notna().any() else None)
            if dedup_col:
                vi = vi.drop_duplicates(subset=[dedup_col], keep="last").reset_index(drop=True)
        return vi
    return None


def _build_debt(tables, meta, vo):
    """Tạo view v_debt (công nợ / thanh toán nợ) từ sổ nợ, phiếu thu hoặc v_orders."""
    rows = []
    for tn, df in tables.items():
        af = cat.ascii_fold(tn)
        if any(k in af for k in ("so no", "cong no", "han no", "sohan")):
            cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
            dt_c = cols_sq.get("ngay") or cols_sq.get("ngayphaitra")
            pay_dt_c = cols_sq.get("ngaytra") or cols_sq.get("ngayphaitra")
            cust_c = cols_sq.get("khach") or cols_sq.get("tenkhachhang") or cols_sq.get("khachhang")
            oid_c = cols_sq.get("madonhang") or cols_sq.get("madon")
            debt_c = cols_sq.get("no") or cols_sq.get("congno") or cols_sq.get("conno")
            paid_c = cols_sq.get("datra") or cols_sq.get("dathu")
            note_c = cols_sq.get("ghichu") or cols_sq.get("kyhan")
            d = pd.DataFrame({
                "order_id": _clean_id(df[oid_c]) if oid_c else None,
                "debt_dt": _fix_excel_dt_series(df[dt_c]) if dt_c else None,
                "paid_dt": _fix_excel_dt_series(df[pay_dt_c]) if pay_dt_c else None,
                "customer": _clean_customer_series(df[cust_c]) if cust_c else None,
                "debt_amount": _num(df[debt_c]) if debt_c else None,
                "paid_amount": _num(df[paid_c]) if paid_c else None,
                "note": df[note_c].values if note_c else None,
            })
            d["remaining_debt"] = (d["debt_amount"].fillna(0) - d["paid_amount"].fillna(0)).clip(lower=0)
            rows.append(d)
    if rows:
        return pd.concat(rows, ignore_index=True)
    # Fallback từ v_orders nếu có cột debt hoặc paid
    if vo is not None and not vo.empty and ("debt" in vo.columns and vo["debt"].notna().any()):
        sub = vo[vo["debt"].notna() | (vo["paid"].notna() if "paid" in vo.columns else False)].copy()
        if not sub.empty:
            return pd.DataFrame({
                "order_id": sub["order_id"].values,
                "debt_dt": sub["order_dt"].values if "order_dt" in sub else None,
                "paid_dt": sub["order_dt"].values if "order_dt" in sub else None,
                "customer": sub["customer"].values if "customer" in sub else None,
                "debt_amount": sub["order_total"].values if "order_total" in sub else None,
                "paid_amount": sub["paid"].values if "paid" in sub else None,
                "remaining_debt": sub["debt"].values,
                "note": None,
            })
    return None


def _build_installments(tables, meta):
    """Tạo view v_installments từ bảng Trả góp (dev_014)."""
    for tn, df in tables.items():
        if "tra gop" in cat.ascii_fold(tn):
            cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
            return pd.DataFrame({
                "start_dt": _fix_excel_dt_series(df[cols_sq["ngay"]]) if "ngay" in cols_sq else None,
                "stt": _num(df[cols_sq["stt"]]) if "stt" in cols_sq else None,
                "customer": _clean_customer_series(df[cols_sq["khach"]]) if "khach" in cols_sq else None,
                "product": df[cols_sq["may"]].values if "may" in cols_sq else None,
                "price": _num(df[cols_sq["gia"]]) if "gia" in cols_sq else None,
                "down_payment": _num(df[cols_sq["tratruoc"]]) if "tratruoc" in cols_sq else None,
                "total_terms": _num(df[cols_sq["soky"]]) if "soky" in cols_sq else None,
                "monthly_amount": _num(df[cols_sq["gopthang"]]) if "gopthang" in cols_sq else None,
                "due_day": _num(df[cols_sq["hangopngay"]]) if "hangopngay" in cols_sq else None,
                "pay_dt": _fix_excel_dt_series(df[cols_sq["ngaygop"]]) if "ngaygop" in cols_sq else None,
                "paid_amount": _num(df[cols_sq["dagop"]]) if "dagop" in cols_sq else None,
            })
    return None


def _build_expense(tables, meta):
    """Tạo view v_expense từ sổ chi phí (dev_003)."""
    for tn, df in tables.items():
        tm = meta["tables"][tn]
        hint = cat.table_hint(tn, tm.get("files", []))
        if hint == "chi_phi" or "chi phi" in cat.ascii_fold(tn) or "chiphi" in rd.squash(cat.ascii_fold(tn)):
            cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
            dt_c = next((c for k, c in cols_sq.items() if "ngay" in k), None)
            amt_c = next((c for k, c in cols_sq.items() if k in ("tienchi", "sotien", "chiphi", "tien")), None)
            cat_c = next((c for k, c in cols_sq.items() if k in ("nhom", "loai", "hangmuc", "danhmuc")), None)
            note_c = next((c for k, c in cols_sq.items() if k in ("luuy", "ghichu", "diengiai", "noidung")), None)
            return pd.DataFrame({
                "expense_dt": _fix_excel_dt_series(df[dt_c]) if dt_c else None,
                "category": df[cat_c].values if cat_c else None,
                "amount": _num(df[amt_c]) if amt_c else None,
                "note": df[note_c].values if note_c else None,
            })
    return None


def _build_warranty(tables, meta):
    """Tạo view v_warranty từ bảng Bảo hành (dev_014)."""
    for tn, df in tables.items():
        if "bao hanh" in cat.ascii_fold(tn):
            cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
            return pd.DataFrame({
                "receive_dt": _fix_excel_dt_series(df[cols_sq["ngaynhan"]]) if "ngaynhan" in cols_sq else None,
                "purchase_dt": _fix_excel_dt_series(df[cols_sq["ngaymua"]]) if "ngaymua" in cols_sq else None,
                "customer": _clean_customer_series(df[cols_sq["khach"]]) if "khach" in cols_sq else None,
                "product": df[cols_sq["may"]].values if "may" in cols_sq else None,
                "issue": df[cols_sq["loi"]].values if "loi" in cols_sq else None,
                "resolution": df[cols_sq["xuly"]].values if "xuly" in cols_sq else None,
            })
    return None


def build_canonical(tables, meta):
    info = {"warnings": [], "tables_used": {}, "structure": None}
    tmeta = meta["tables"]
    cls = {}
    for tn, df in tables.items():
        roles = column_roles(df, tmeta[tn])
        files = tmeta[tn].get("files", [])
        cls[tn] = (classify_sales_table(tn, roles, files), roles)

    flats = [t for t, (k, _) in cls.items() if k in ("flat", "flat_noid")]
    lines = [t for t, (k, _) in cls.items() if k == "lines"]
    orders = [t for t, (k, _) in cls.items() if k == "orders"]

    def biggest(ts):
        return max(ts, key=lambda t: len(tables[t])) if ts else None

    L = O = None
    if flats and not (lines and orders):
        L = biggest(flats)
        info["structure"] = "flat"
    elif lines and orders:
        L = biggest(lines)
        O = pick_order_table(tables, cls, orders, L)
        info["structure"] = "orders+lines"
    elif lines:
        L = biggest(lines)
        info["structure"] = "lines_only"
    elif orders:
        O = biggest(orders)
        info["structure"] = "orders_only"
    elif flats:
        L = biggest(flats)
        info["structure"] = "flat"
    if info["structure"] is None:
        led = ledger_candidate(tables, tmeta)
        if led is None:
            info["warnings"].append("không nhận ra bảng bán hàng")
            return {"v_lines": None, "v_orders": None, "v_purchases": None, "v_inventory": None,
                    "v_debt": None, "v_installments": None, "v_expense": None, "v_warranty": None, "info": info}
        res = build_ledger(tables[led[0]], tmeta[led[0]], led, info)
        # Map short mechanic names + commission rate from DanhSachTho (dev_012)
        for tn, df in tables.items():
            if "tho" in cat.ascii_fold(tn) and len(df) <= 50:
                cols_sq = {rd.squash(cat.ascii_fold(c)): c for c in df.columns if not c.startswith("_")}
                nm_c = cols_sq.get("hoten") or cols_sq.get("ten")
                comm_c = next((c for k, c in cols_sq.items() if "hoahong" in k), None)
                if nm_c and comm_c and res["v_lines"] is not None:
                    emp_comm = {}
                    short_to_full = {}
                    for nm, cm in zip(df[nm_c], _num(df[comm_c])):
                        if pd.notna(nm) and pd.notna(cm):
                            fnm = str(nm).strip()
                            emp_comm[fnm] = float(cm)
                            last = fnm.split()[-1].lower()
                            short_to_full[last] = fnm
                            short_to_full["a." + last] = fnm
                            short_to_full["anh " + last] = fnm
                    def _map_emp(e):
                        if pd.isna(e): return None
                        s = str(e).strip()
                        return short_to_full.get(s.lower(), s)
                    res["v_lines"]["employee"] = res["v_lines"]["employee"].map(_map_emp)
                    res["v_orders"]["employee"] = res["v_lines"]["employee"].values
                    res["v_lines"]["commission_rate"] = res["v_lines"]["employee"].map(lambda x: emp_comm.get(x, 0.0) if pd.notna(x) else 0.0)
                    res["v_lines"]["commission_amount"] = (res["v_lines"]["line_amount"].astype(float) * res["v_lines"]["commission_rate"] / 100.0).round(2)
        res["v_debt"] = _build_debt(tables, meta, res["v_orders"])
        res["v_installments"] = _build_installments(tables, meta)
        res["v_expense"] = _build_expense(tables, meta)
        res["v_warranty"] = _build_warranty(tables, meta)
        return res

    info["tables_used"] = {"lines": L, "orders": O}

    # ---- dòng hàng ----
    vl = None
    if L:
        df, roles = tables[L], cls[L][1]
        c = {r: _pick(roles, r) for r in ("ma_don", "ten_hang", "ma_hang", "so_luong", "quy_doi", "don_vi", "don_gia", "trang_thai", "ten_khach", "ma_khach", "nhom_khach", "nhan_vien", "ma_nhan_vien", "kenh_ban", "giam_gia", "nhom_hang", "thuong_hieu")}
        c["thoi_diem"] = _pick(roles, "thoi_diem", want_kind=("ngay",), prefer=_DATE_PREF[0], avoid=_DATE_BAD.pattern)
        amt, ratio = pick_line_amount(df, roles, c["so_luong"], c["don_gia"])
        c["thanh_tien_dong"] = amt or _pick(roles, "thanh_tien_dong", want_kind=("tien",))
        info["line_amount_match"] = round(ratio, 3)
        if not c["thanh_tien_dong"]:
            info["warnings"].append("bảng dòng hàng không có cột thành tiền: tính = số lượng × đơn giá")
        base = df.copy()
        if not c["ma_don"]:
            base["__rowid"] = ["R%d" % i for i in range(len(base))]
            c["ma_don"] = "__rowid"
            info["warnings"].append("bảng không có mã đơn: mỗi dòng tính là 1 đơn")
        real = [x for x in df.columns if not x.startswith("_")]
        before = len(base)
        if c["ma_don"] != "__rowid":
            base = base.drop_duplicates(subset=real)
        info["dup_lines_dropped"] = before - len(base)
        vl = pd.DataFrame({"order_id": _clean_id(base[c["ma_don"]])})
        if c["thoi_diem"]:
            vl["order_dt"] = base[c["thoi_diem"]].values
        st, info["status_source"] = status_series(base, c["trang_thai"])
        vl["status"] = st.fillna("hoan_thanh").values if st.notna().any() else "hoan_thanh"
        vl["product"] = base[c["ten_hang"]].values if c["ten_hang"] else None
        vl["product_name"] = vl["product"]
        vl["category"] = base[c["nhom_hang"]].values if c.get("nhom_hang") else None
        vl["brand"] = base[c["thuong_hieu"]].values if c.get("thuong_hieu") else None
        vl["sku"] = base[c["ma_hang"]].values if c["ma_hang"] else None
        vl["qty"] = _num(base[c["so_luong"]]).values if c["so_luong"] else None
        vl["quantity"] = vl["qty"]
        if c.get("quy_doi"):
            vl["qty_base"] = _num(base[c["quy_doi"]]).values
        vl["unit"] = base[c["don_vi"]].values if c["don_vi"] else None
        vl["unit_price"] = _num(base[c["don_gia"]]).values if c["don_gia"] else None
        if c["thanh_tien_dong"]:
            vl["line_amount"] = _num(base[c["thanh_tien_dong"]]).values
        else:
            vl["line_amount"] = (vl["qty"] * vl["unit_price"]).values
        vl["line_total"] = vl["line_amount"]
        vl["customer"] = base[c["ten_khach"] or c["ma_khach"]].values if (c["ten_khach"] or c["ma_khach"]) else None
        vl["customer_id"] = vl["customer"]
        vl["customer_group"] = base[c["nhom_khach"]].values if c.get("nhom_khach") else None
        emp_col = c.get("nhan_vien") or c.get("ma_nhan_vien")
        vl["employee"] = base[emp_col].values if emp_col else None
        vl["channel"] = base[c["kenh_ban"]].values if c["kenh_ban"] else None
        vl["_src_row"] = range(len(vl))
        vl = vl[vl.order_id.notna()].copy()

        # Forward-fill order-level fields within same order_id (fixes dev_013 BanHang_2026)
        if c["ma_don"] != "__rowid":
            for fcol in ("order_dt", "customer", "customer_group", "employee", "channel"):
                if fcol in vl.columns and vl[fcol].isna().any() and vl[fcol].notna().any():
                    vl[fcol] = vl.groupby("order_id", sort=False)[fcol].ffill().bfill()
            vl["customer_id"] = vl["customer"]

        info["lines_cols"] = {k: v for k, v in c.items() if v}

    # ---- đơn hàng ----
    vo = None
    if O:
        df, roles = tables[O], cls[O][1]
        c = {r: _pick(roles, r) for r in ("ma_don", "trang_thai", "ten_khach", "ma_khach", "nhom_khach", "tong_don", "tong_tien_hang", "giam_gia", "phi_ship", "da_tra", "cong_no", "phuong_thuc_tt", "kenh_ban", "nhan_vien", "ma_nhan_vien")}
        c["thoi_diem"] = _pick(roles, "thoi_diem", want_kind=("ngay",), prefer=_DATE_PREF[0], avoid=_DATE_BAD.pattern)
        base = df.drop_duplicates(subset=[x for x in df.columns if not x.startswith("_")])
        vo = pd.DataFrame({"order_id": _clean_id(base[c["ma_don"]])})
        vo["order_dt"] = base[c["thoi_diem"]].values if c["thoi_diem"] else None
        st, info["status_source"] = status_series(base, c["trang_thai"])
        vo["status"] = st.fillna("hoan_thanh").values if st.notna().any() else pd.Series(["hoan_thanh"]*len(vo)).values
        vo["customer"] = base[c["ten_khach"] or c["ma_khach"]].values if (c["ten_khach"] or c["ma_khach"]) else None
        vo["customer_id"] = vo["customer"]
        vo["customer_group"] = base[c["nhom_khach"]].values if c.get("nhom_khach") else None
        for src, dst in (("tong_tien_hang", "items_total"), ("phi_ship", "ship_fee"), ("giam_gia", "order_discount"), ("tong_don", "order_total"),
                         ("da_tra", "paid"), ("cong_no", "debt")):
            vo[dst] = _num(base[c[src]]).values if c[src] else None
        vo["payment_method"] = base[c["phuong_thuc_tt"]].values if c["phuong_thuc_tt"] else None
        vo["channel"] = base[c["kenh_ban"]].values if c["kenh_ban"] else None
        emp_col = c.get("nhan_vien") or c.get("ma_nhan_vien")
        vo["employee"] = base[emp_col].values if emp_col else None
        vo = vo[vo.order_id.notna()].drop_duplicates(subset=["order_id"])
        info["orders_cols"] = {k: v for k, v in c.items() if v}

    # ---- hợp nhất ----
    if info["structure"] in ("flat", "lines_only") and vl is not None:
        g = vl.groupby("order_id", sort=False)
        first = g.first()
        vo = pd.DataFrame({"order_id": first.index})
        vo["order_dt"] = first["order_dt"].values if "order_dt" in first else None
        vo["status"] = first["status"].values if "status" in first else "hoan_thanh"
        vo["customer"] = first["customer"].values
        vo["customer_id"] = vo["customer"]
        vo["customer_group"] = first["customer_group"].values if "customer_group" in first else None
        vo["employee"] = first["employee"].values
        vo["channel"] = first["channel"].values
        vo["items_total"] = g["line_amount"].sum().values
        if L and info["lines_cols"]["ma_don"] != "__rowid":
            roles = cls[L][1]
            t = tables[L].drop_duplicates(subset=[x for x in tables[L].columns if not x.startswith("_")])
            oid_col = info["lines_cols"]["ma_don"]
            tcol = _pick(roles, "tong_don", want_kind=("tien",))
            if tcol and tcol != info["lines_cols"].get("thanh_tien_dong"):
                tt = pd.DataFrame({"order_id": _clean_id(t[oid_col]), "order_total": _num(t[tcol])}).dropna().drop_duplicates("order_id")
                vo = vo.merge(tt, on="order_id", how="left")
            for role_k, dst_k in (("phi_ship", "ship_fee"), ("giam_gia", "order_discount"), ("da_tra", "paid"), ("cong_no", "debt")):
                ec = _pick(roles, role_k, want_kind=("tien",))
                if ec and ec != info["lines_cols"].get("thanh_tien_dong"):
                    et = pd.DataFrame({"order_id": _clean_id(t[oid_col]), dst_k: _num(t[ec])}).dropna().drop_duplicates("order_id")
                    vo = vo.merge(et, on="order_id", how="left")
    elif info["structure"] == "orders+lines" and vl is not None and vo is not None:
        for drop_c in ("order_dt", "status"):
            if drop_c in vl:
                vl = vl.drop(columns=[drop_c])
        m_cols = ["order_id", "order_dt", "status", "customer", "customer_group", "employee", "channel"]
        m_cols = [mc for mc in m_cols if mc in vo.columns]
        m = vo[m_cols].rename(columns={k: k + "_o" for k in m_cols if k != "order_id"})
        vl = vl.merge(m, on="order_id", how="left")
        for k in ("order_dt", "status", "customer", "customer_group", "employee", "channel"):
            ko = k + "_o"
            if ko in vl:
                vl[k] = vl[k].where(vl[k].notna(), vl[ko]) if k in vl else vl[ko]
                vl = vl.drop(columns=[ko])
        vl["customer_id"] = vl["customer"]
        s = vl.groupby("order_id")["line_amount"].sum().rename("items_total_lines").reset_index()
        vo = vo.merge(s, on="order_id", how="left")
        if vo["items_total"].isna().all() if "items_total" in vo else True:
            vo["items_total"] = vo["items_total_lines"]
    elif info["structure"] == "orders_only" and vo is not None and vl is None:
        amt = vo["items_total"] if "items_total" in vo and vo["items_total"].notna().any() else vo.get("order_total")
        vl = pd.DataFrame({
            "order_id": vo["order_id"].values,
            "order_dt": vo["order_dt"].values if "order_dt" in vo else None,
            "status": vo["status"].fillna("hoan_thanh").values if "status" in vo else pd.Series(["hoan_thanh"]*len(vo)).values,
            "line_amount": _num(amt).values if amt is not None else None,
            "line_total": _num(amt).values if amt is not None else None,
            "qty": 1.0,
            "quantity": 1.0,
            "qty_base": 1.0,
            "product": "Đơn hàng",
            "product_name": "Đơn hàng",
            "category": "Đơn hàng",
            "customer": vo["customer"].values if "customer" in vo else None,
            "customer_id": vo["customer_id"].values if "customer_id" in vo else None,
            "customer_group": vo["customer_group"].values if "customer_group" in vo else None,
            "employee": vo["employee"].values if "employee" in vo else None,
            "_src_row": range(len(vo))
        })
        info["warnings"].append("bảng đơn không có dòng hàng: tự tạo dòng tổng hợp để phục vụ query SQL")

    # ---- Bổ sung thông tin từ Catalog & Quy đổi đơn vị ----
    if vl is not None:
        vl = _enrich_from_catalogs(vl, tables, meta)
        vl = _apply_unit_conversion(vl, tables, meta)
        if "product_name" not in vl.columns and "product" in vl.columns:
            vl["product_name"] = vl["product"]
        if "line_total" not in vl.columns and "line_amount" in vl.columns:
            vl["line_total"] = vl["line_amount"]
        if "quantity" not in vl.columns and "qty" in vl.columns:
            vl["quantity"] = vl["qty"]
        if "category" not in vl.columns:
            vl["category"] = None
        if "brand" not in vl.columns:
            vl["brand"] = None
        if "hoat_chat" not in vl.columns:
            vl["hoat_chat"] = None
            vl["active_ingredient"] = None
        if "thuoc_ke_don" not in vl.columns:
            vl["thuoc_ke_don"] = 0
            vl["is_prescription"] = 0
        if "cost_amount" not in vl.columns:
            vl["cost_amount"] = None
        # Đánh dấu dòng phí/voucher/chiết khấu để không lọt vào top sản phẩm bán chạy
        if "product" in vl.columns:
            p_low = vl["product"].fillna("").astype(str).str.lower().str.strip()
            vl["is_fee"] = p_low.isin(["phí ship", "phi ship", "voucher", "chiết khấu", "chiet khau", "giảm giá", "giam gia", "phí giao hàng", "phi giao hang", "thu máy cũ", "thu may cu"]).astype(int)
        else:
            vl["is_fee"] = 0

    if vo is not None:
        if "order_total" not in vo.columns or vo["order_total"].isna().all():
            vo["order_total"] = vo["items_total"] if "items_total" in vo.columns else None
        if "status" not in vo.columns:
            vo["status"] = "hoan_thanh"
        else:
            vo["status"] = vo["status"].fillna("hoan_thanh")

    # ---- Hậu xử lý ngày, dòng tổng, mã KH->tên KH, mã NV->tên NV, SĐT dính tên KH, null_qty ----
    if vo is not None and not vo.empty:
        if "order_dt" in vo.columns:
            vo["order_dt"] = _fix_excel_dt_series(vo["order_dt"])
        if "order_id" in vo.columns and "order_dt" in vo.columns:
            bad_tot = vo["order_dt"].isna() & vo["order_id"].astype(str).str.lower().str.strip().str.startswith(("tổng", "tong", "total"))
            if bad_tot.any():
                bad_ids = set(vo.loc[bad_tot, "order_id"])
                vo = vo.loc[~bad_tot].reset_index(drop=True)
                if vl is not None and "order_id" in vl.columns:
                    vl = vl.loc[~vl["order_id"].isin(bad_ids)].reset_index(drop=True)

        # Map KH... -> Tên khách + Nhóm khách từ bảng khach_hang (dev_006, dev_007, dev_010)
        if "customer" in vo.columns:
            cust_map, grp_map = {}, {}
            for tn, cdf in tables.items():
                if "khach" in tn.lower():
                    id_c = next((c for c in cdf.columns if rd.squash(cat.ascii_fold(c)) in ("makhachhang", "makh", "makhach")), None)
                    nm_c = next((c for c in cdf.columns if rd.squash(cat.ascii_fold(c)) in ("tengoi", "tenkhachhang", "tenkh", "hoten")), None)
                    gp_c = next((c for c in cdf.columns if rd.squash(cat.ascii_fold(c)) in ("khachlesi", "loaikhachhang", "nhomkhachhang", "doituongkh")), None)
                    if id_c and nm_c:
                        for k, v in zip(cdf[id_c], cdf[nm_c]):
                            if pd.notna(k) and pd.notna(v):
                                cust_map[str(k).strip()] = str(v).strip()
                    if id_c and gp_c:
                        for k, v in zip(cdf[id_c], cdf[gp_c]):
                            if pd.notna(k) and pd.notna(v):
                                grp_map[str(k).strip()] = str(v).strip()
            if grp_map and ("customer_group" not in vo.columns or vo["customer_group"].isna().all()):
                vo["customer_group"] = vo["customer"].map(lambda x: grp_map.get(str(x).strip()) if pd.notna(x) else None)
                if vl is not None:
                    vl["customer_group"] = vl["customer"].map(lambda x: grp_map.get(str(x).strip()) if pd.notna(x) else None)
            if cust_map:
                vo["customer"] = vo["customer"].map(lambda x: cust_map.get(str(x).strip(), x) if pd.notna(x) else x)
                if vl is not None and "customer" in vl.columns:
                    vl["customer"] = vl["customer"].map(lambda x: cust_map.get(str(x).strip(), x) if pd.notna(x) else x)

            vo["customer"] = _clean_customer_series(vo["customer"])
            vo["customer_id"] = vo["customer"]
            if vl is not None and "customer" in vl.columns:
                vl["customer"] = _clean_customer_series(vl["customer"])
                vl["customer_id"] = vl["customer"]

        # Map NV... -> Tên nhân viên từ bảng nhan_vien (dev_006)
        if "employee" in vo.columns and vo["employee"].notna().any():
            emp_map = {}
            for tn, edf in tables.items():
                if "nhan_vien" in tn.lower() or "nhanvien" in tn.lower():
                    id_c = next((c for c in edf.columns if rd.squash(cat.ascii_fold(c)) in ("manhanvien", "manv")), None)
                    nm_c = next((c for c in edf.columns if rd.squash(cat.ascii_fold(c)) in ("tengoi", "tennhanvien", "hoten")), None)
                    if id_c and nm_c:
                        for k, v in zip(edf[id_c], edf[nm_c]):
                            if pd.notna(k) and pd.notna(v):
                                emp_map[str(k).strip()] = str(v).strip()
            if emp_map:
                vo["employee"] = vo["employee"].map(lambda x: emp_map.get(str(x).strip(), x) if pd.notna(x) else x)
                if vl is not None and "employee" in vl.columns:
                    vl["employee"] = vl["employee"].map(lambda x: emp_map.get(str(x).strip(), x) if pd.notna(x) else x)

    if vl is not None and not vl.empty:
        if "order_dt" in vl.columns:
            vl["order_dt"] = _fix_excel_dt_series(vl["order_dt"])
        if "qty" in vl.columns and "line_amount" in vl.columns and "unit_price" in vl.columns:
            need_qty = vl["qty"].isna() & vl["line_amount"].notna() & vl["unit_price"].notna() & (vl["unit_price"] > 0)
            if need_qty.any():
                vl.loc[need_qty, "qty"] = (vl.loc[need_qty, "line_amount"].astype(float) / vl.loc[need_qty, "unit_price"].astype(float)).round(4)
                vl["quantity"] = vl["qty"]
                if "qty_base" in vl.columns:
                    vl["qty_base"] = vl["qty_base"].fillna(vl["qty"])

    vp = _build_purchases(tables, meta)
    vi = _build_inventory(tables, meta)
    vd = _build_debt(tables, meta, vo)
    vins = _build_installments(tables, meta)
    vexp = _build_expense(tables, meta)
    vwar = _build_warranty(tables, meta)

    return {
        "v_lines": vl, "v_orders": vo, "v_purchases": vp, "v_inventory": vi,
        "v_debt": vd, "v_installments": vins, "v_expense": vexp, "v_warranty": vwar,
        "info": info,
    }


# ───────────────────────── tính số liệu từ sổ chuẩn ─────────────────────────
def _dates(s):
    return pd.to_datetime(s.astype(str).str[:10], errors="coerce")


def valid_orders(vo):
    if "status" not in vo or vo["status"].isna().all():
        return vo
    return vo[vo["status"].isin(["hoan_thanh", "dang_giao"]) | vo["status"].isna()]


def revenue(cb, start, end):
    vo, vl = cb["v_orders"], cb["v_lines"]
    d = _dates(vo["order_dt"])
    sel = vo[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]
    ok = valid_orders(sel)
    if vl is not None and len(vl):
        s = vl[vl.order_id.isin(set(ok.order_id))]["line_amount"].sum()
    else:
        col = "items_total" if "items_total" in ok and ok["items_total"].notna().any() else "order_total"
        s = ok[col].sum() if col in ok else float("nan")
    return float(s), int(ok.order_id.nunique())


def order_counts(cb, start, end):
    vo = cb["v_orders"]
    d = _dates(vo["order_dt"])
    sel = vo[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]
    return len(sel), int((sel["status"] == "huy").sum()) if "status" in sel else None
