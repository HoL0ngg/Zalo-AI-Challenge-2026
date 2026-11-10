# -*- coding: utf-8 -*-
"""Việc 3 — SỔ CHUẨN: đổi các bảng đã làm sạch của MỘT shop thành v_lines (mỗi dòng hàng) và v_orders (mỗi đơn).

Đầu vào : tables, meta = clean_shop.load_clean_tables(shop_dir)      (việc 2 của Nhi)
Đầu ra  : build_canonical(tables, meta) -> dict(v_lines, v_orders, info)

Luật (rulebook train):
  - trạng thái đơn chỉ có 4 giá trị: hoan_thanh | huy | tra_hang | dang_giao
  - doanh thu = tổng thành tiền các dòng hàng của đơn KHÔNG huỷ và KHÔNG trả hàng (đơn đang giao vẫn tính), theo NGÀY ĐẶT
  - hai dòng giống nhau ở mọi ô của CÙNG một đơn = lỗi xuất file, tính một lần
Nguyên tắc: không đoán. Không nhận diện được vai trò thì để trống và ghi vào info['warnings'].
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


def column_roles(df, tm):
    """role -> danh sách (cột, kiểu, tỉ lệ có dữ liệu) cho 1 bảng. Nhận diện theo TÊN, rồi bổ sung theo NỘI DUNG."""
    out, used = {}, set()
    for c in df.columns:
        if c.startswith("_") or c.endswith("__don_vi") or c.endswith("__raw"):
            continue
        kind, prefix = cat._kind(df[c], tm, c)
        role, _ = rd.infer_role(cat.ascii_fold(c), kind, prefix)
        if role and role not in ("rong",):
            if role in _MONEY_ROLES and kind != "tien":      # chuỗi tiền chưa được đổi ('45,000.0000')
                smp = df[c].dropna().head(300)
                if len(smp) and sum(parse_money(v) is not None for v in smp) / len(smp) >= 0.9:
                    kind = "tien"
            out.setdefault(role, []).append((c, kind, float(df[c].notna().mean())))
            if role != "khong_dung":
                used.add(c)
    # --- theo nội dung: cột trạng thái (≥90% giá trị đọc được thành 1 trong 4 trạng thái) ---
    if "trang_thai" not in out:
        for c in df.columns:
            if c in used or c.startswith("_") or c.endswith("__raw"):
                continue
            smp = df[c].dropna().astype(str).head(1000)
            if len(smp) >= 20 and smp.nunique() <= 12 and smp.map(norm_status).notna().mean() >= 0.9:
                out["trang_thai"] = [(c, "nhom", float(df[c].notna().mean()))]
                used.add(c)
                break
    # --- theo nội dung: cột tên hàng (chữ, nhiều giá trị khác nhau, chưa có vai trò) khi bảng có số lượng nhưng chưa có hàng ---
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
    """Chọn 1 cột trong danh sách (cột, kiểu, tỉ lệ có dữ liệu)."""
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
    """Cột thành tiền của DÒNG hàng = cột tiền khớp nhất với số lượng × đơn giá (có thể đang tên 'Tổng tiền'). Trả (cột hoặc None, tỉ lệ khớp)."""
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
    """Trả 'flat' (đơn + dòng cùng bảng) | 'lines' | 'orders' | None. Loại bảng nhập hàng, thanh toán, giao hàng, công nợ…"""
    hint = cat.table_hint(name, files)
    has = lambda r: r in roles
    if has("ma_phieu_nhap") or hint in ("nhap_hang", "ton_kho", "ten_tat", "bang_gia", "quy_doi_don_vi", "danh_muc_hang", "khach_hang", "nhan_vien", "chi_phi"):
        if not (has("ma_don") and (has("thanh_tien_dong") or has("don_gia"))):
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
    """Trạng thái chuẩn của từng dòng. Sổ KHÔNG có cột trạng thái: lấy từ cột Ghi chú, ghi chú không nhắc trạng thái = hoàn thành (rulebook public)."""
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
    return s.astype(str).str.strip().replace({"nan": None, "None": None, "": None})


def _num(s):
    """Chuyển cột sang số. Chuỗi như '45,000.0000' hay '1.500đ' mà bước làm sạch chưa đổi thì dùng parse_money."""
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    x = pd.to_numeric(s, errors="coerce")
    miss = x.isna() & s.notna()
    if miss.any():
        x = x.astype("float64")
        x[miss] = pd.to_numeric(s[miss].map(parse_money), errors="coerce")
    return x


def ledger_candidate(tables, tmeta):
    """Sổ ghi theo lần (vd sổ sửa xe): có ngày + tiền, không có mã đơn/hàng. Trả (tên bảng, cột ngày, cột tiền) hoặc None."""
    best = None
    for tn, df in tables.items():
        tm = tmeta[tn]
        if len(df) < 20 or not tm.get("money") or not tm.get("date"):
            continue
        if cat.table_hint(tn, tm.get("files", [])) in ("khach_hang", "nhan_vien", "bang_gia", "danh_muc_hang", "chi_phi", "nhap_hang", "ton_kho"):
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
    vl = pd.DataFrame({"order_id": ids, "order_dt": base[dcol].values, "line_amount": _num(base[mcol]).values})
    vl["status"] = st.values if st.notna().any() else None
    vl["product"] = base[what].values if what else None
    vl["employee"] = base[emp].values if emp else None
    vo = pd.DataFrame({"order_id": ids, "order_dt": base[dcol].values, "status": vl["status"].values, "employee": vl["employee"].values,
                       "items_total": vl["line_amount"].values})
    info["structure"] = "ledger"
    info["tables_used"] = {"lines": led[0], "orders": None}
    info["warnings"].append("sổ ghi theo lần (mỗi dòng là một lượt/phiếu): doanh thu = cột tiền")
    return {"v_lines": vl, "v_orders": vo, "info": info}


def pick_order_table(tables, cls, orders, L):
    """Bảng đơn tốt nhất = có cột trạng thái, phủ nhiều mã đơn của bảng dòng hàng nhất, rồi mới đến số dòng."""
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
            return {"v_lines": None, "v_orders": None, "info": info}
        return build_ledger(tables[led[0]], tmeta[led[0]], led, info)
    info["tables_used"] = {"lines": L, "orders": O}

    # ---- dòng hàng ----
    vl = None
    if L:
        df, roles = tables[L], cls[L][1]
        c = {r: _pick(roles, r) for r in ("ma_don", "ten_hang", "ma_hang", "so_luong", "don_vi", "don_gia", "trang_thai", "ten_khach", "ma_khach", "nhan_vien", "kenh_ban", "giam_gia")}
        c["thoi_diem"] = _pick(roles, "thoi_diem", want_kind=("ngay",), prefer=_DATE_PREF[0], avoid=_DATE_BAD.pattern)
        amt, ratio = pick_line_amount(df, roles, c["so_luong"], c["don_gia"])
        c["thanh_tien_dong"] = amt or _pick(roles, "thanh_tien_dong", want_kind=("tien",))
        info["line_amount_match"] = round(ratio, 3)
        if not c["thanh_tien_dong"]:
            info["warnings"].append("bảng dòng hàng không có cột thành tiền: tính = số lượng × đơn giá")
        base = df.copy()
        if not c["ma_don"]:                       # không có mã đơn: mỗi dòng là 1 đơn, KHÔNG gộp dòng trùng
            base["__rowid"] = ["R%d" % i for i in range(len(base))]
            c["ma_don"] = "__rowid"
            info["warnings"].append("bảng không có mã đơn: mỗi dòng tính là 1 đơn")
        real = [x for x in df.columns if not x.startswith("_")]
        # lỗi xuất file: 2 dòng giống hệt ở mọi ô và cùng đơn -> tính một lần
        before = len(base)
        if c["ma_don"] != "__rowid":
            base = base.drop_duplicates(subset=real)
        info["dup_lines_dropped"] = before - len(base)
        vl = pd.DataFrame({"order_id": _clean_id(base[c["ma_don"]])})
        if c["thoi_diem"]:
            vl["order_dt"] = base[c["thoi_diem"]].values
        st, info["status_source"] = status_series(base, c["trang_thai"])
        if st.notna().any():
            vl["status"] = st.values
        vl["product"] = base[c["ten_hang"]].values if c["ten_hang"] else None
        vl["sku"] = base[c["ma_hang"]].values if c["ma_hang"] else None
        vl["qty"] = _num(base[c["so_luong"]]).values if c["so_luong"] else None
        vl["unit"] = base[c["don_vi"]].values if c["don_vi"] else None
        vl["unit_price"] = _num(base[c["don_gia"]]).values if c["don_gia"] else None
        if c["thanh_tien_dong"]:
            vl["line_amount"] = _num(base[c["thanh_tien_dong"]]).values
        else:
            vl["line_amount"] = (vl["qty"] * vl["unit_price"]).values
        vl["customer"] = base[c["ten_khach"] or c["ma_khach"]].values if (c["ten_khach"] or c["ma_khach"]) else None
        vl["employee"] = base[c["nhan_vien"]].values if c["nhan_vien"] else None
        vl["channel"] = base[c["kenh_ban"]].values if c["kenh_ban"] else None
        vl["_src_row"] = range(len(vl))
        vl = vl[vl.order_id.notna()]
        info["lines_cols"] = {k: v for k, v in c.items() if v}

    # ---- đơn hàng ----
    vo = None
    if O:
        df, roles = tables[O], cls[O][1]
        c = {r: _pick(roles, r) for r in ("ma_don", "trang_thai", "ten_khach", "ma_khach", "tong_don", "tong_tien_hang", "giam_gia", "phi_ship", "da_tra", "cong_no", "phuong_thuc_tt", "kenh_ban", "nhan_vien", "ma_nhan_vien")}
        c["thoi_diem"] = _pick(roles, "thoi_diem", want_kind=("ngay",), prefer=_DATE_PREF[0], avoid=_DATE_BAD.pattern)
        base = df.drop_duplicates(subset=[x for x in df.columns if not x.startswith("_")])
        vo = pd.DataFrame({"order_id": _clean_id(base[c["ma_don"]])})
        vo["order_dt"] = base[c["thoi_diem"]].values if c["thoi_diem"] else None
        st, info["status_source"] = status_series(base, c["trang_thai"])
        vo["status"] = st.values if st.notna().any() else None
        vo["customer"] = base[c["ten_khach"] or c["ma_khach"]].values if (c["ten_khach"] or c["ma_khach"]) else None
        for src, dst in (("tong_tien_hang", "items_total"), ("phi_ship", "ship_fee"), ("giam_gia", "order_discount"), ("tong_don", "order_total"),
                         ("da_tra", "paid"), ("cong_no", "debt")):
            vo[dst] = _num(base[c[src]]).values if c[src] else None
        vo["payment_method"] = base[c["phuong_thuc_tt"]].values if c["phuong_thuc_tt"] else None
        vo["channel"] = base[c["kenh_ban"]].values if c["kenh_ban"] else None
        vo["employee"] = base[c["nhan_vien"] or c["ma_nhan_vien"]].values if (c["nhan_vien"] or c["ma_nhan_vien"]) else None
        vo = vo[vo.order_id.notna()].drop_duplicates(subset=["order_id"])
        info["orders_cols"] = {k: v for k, v in c.items() if v}

    # ---- hợp nhất ----
    if info["structure"] in ("flat", "lines_only") and vl is not None:
        g = vl.groupby("order_id", sort=False)
        first = g.first()
        vo = pd.DataFrame({"order_id": first.index})
        vo["order_dt"] = first["order_dt"].values if "order_dt" in first else None
        vo["status"] = first["status"].values if "status" in first else None
        vo["customer"] = first["customer"].values
        vo["employee"] = first["employee"].values
        vo["channel"] = first["channel"].values
        vo["items_total"] = g["line_amount"].sum().values
        # tổng đơn lặp ở từng dòng của bảng phẳng: lấy giá trị đầu
        if L and info["lines_cols"]["ma_don"] != "__rowid":
            roles = cls[L][1]
            tcol = _pick(roles, "tong_don", want_kind=("tien",))
            if tcol and tcol != info["lines_cols"].get("thanh_tien_dong"):
                t = tables[L].drop_duplicates(subset=[x for x in tables[L].columns if not x.startswith("_")])
                tt = pd.DataFrame({"order_id": _clean_id(t[info["lines_cols"]["ma_don"]]), "t": _num(t[tcol])}).dropna().drop_duplicates("order_id")
                vo = vo.merge(tt.rename(columns={"t": "order_total"}), on="order_id", how="left")
    elif info["structure"] == "orders+lines" and vl is not None and vo is not None:
        if "order_dt" in vl:
            vl = vl.drop(columns=["order_dt"])
        if "status" in vl:
            vl = vl.drop(columns=["status"])
        m = vo[["order_id", "order_dt", "status", "customer"]].rename(columns={"customer": "customer_o"})
        vl = vl.merge(m, on="order_id", how="left")
        if "customer_o" in vl:
            vl["customer"] = vl["customer"].where(vl["customer"].notna(), vl["customer_o"]) if "customer" in vl else vl["customer_o"]
            vl = vl.drop(columns=["customer_o"])
        s = vl.groupby("order_id")["line_amount"].sum().rename("items_total_lines").reset_index()
        vo = vo.merge(s, on="order_id", how="left")
        if vo["items_total"].isna().all() if "items_total" in vo else True:
            vo["items_total"] = vo["items_total_lines"]
    elif info["structure"] == "orders_only" and vo is not None:
        info["warnings"].append("chỉ có bảng đơn, không có dòng hàng: doanh thu lấy từ tổng đơn (không chắc đúng rulebook)")
    return {"v_lines": vl, "v_orders": vo, "info": info}


# ───────────────────────── tính số liệu từ sổ chuẩn (để kiểm chứng) ─────────────────────────
def _dates(s):
    return pd.to_datetime(s.astype(str).str[:10], errors="coerce")


def valid_orders(vo):
    """Đơn tính vào doanh thu / số đơn: không huỷ, không trả hàng (đang giao vẫn tính). Không có trạng thái -> coi mọi đơn là hợp lệ."""
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
    else:   # chỉ có bảng đơn: dùng TIỀN HÀNG (không trừ voucher cả đơn, không phí giao, không VAT)
        col = "items_total" if "items_total" in ok and ok["items_total"].notna().any() else "order_total"
        s = ok[col].sum() if col in ok else float("nan")
    return float(s), int(ok.order_id.nunique())


def order_counts(cb, start, end):
    vo = cb["v_orders"]
    d = _dates(vo["order_dt"])
    sel = vo[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]
    return len(sel), int((sel["status"] == "huy").sum()) if "status" in sel else None
