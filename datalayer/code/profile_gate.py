# -*- coding: utf-8 -*-
"""Việc 3 — HỒ SƠ SHOP (shop có gì, thiếu gì) và CÂU CHẶN (khi nào dữ liệu không đủ để trả lời).

profile_shop(tables, meta, cb)   -> dict hồ sơ
required_info(question_info)     -> danh sách thông tin câu hỏi CẦN ('khach_nu_nam', 'gia_von', ...)
gate(question_info, profile)     -> {"decision": "ok" | "unanswerable" | "abstain", "reason": str, "needs": [...]}

Rulebook: "Không có dữ liệu khác với bằng 0: kỳ nằm hoàn toàn ngoài khoảng ngày có dữ liệu của shop, hoặc shop không ghi loại thông tin
câu hỏi cần, thì không trả lời được." và "Thông tin file không ghi thì không suy ra từ cột khác".
Chặn sai (câu trả lời được mà báo unanswerable) cũng bị −1, nên luật cố tình HẸP: chỉ chặn khi chắc chắn.
"""
import re

import pandas as pd

import catalog_shop as cat
import role_draft as rd
import schema_build as sb


# ───────────────────────── HỒ SƠ SHOP ─────────────────────────
_NAME_PATTERNS = {
    "gioi_tinh": r"^(gioitinh|gt|gender|phai)$",
    "dia_chi": r"^(diachi.*|dchi|addr.*|diachigiaohang)$",
    "nhom_khach": r"^(nhomkhach(hang)?|nhomkh|loaikhach(hang)?|loaihinhkh.*|phanloaikh|hangthanhvien|hangkhach|doituongkh)$",
    "ly_do": r"^(lydo.*|lydohuy|lydotra)$",
    "nhom_hang": r"^(nhomhang|loaihang(hoa)?|nhomsp|phanloai|danhmuc|nhomhanghoa|loaisanpham|nhomsanpham)$",
    "tho": r"^(tho|thoxuly|nguoilam)$",
}
_ROLE_FLAGS = {  # cờ hồ sơ <- vai trò cột (role_draft)
    "has_customer_name": ("ten_khach",), "has_customer_id": ("ma_khach",), "has_employee": ("nhan_vien", "ma_nhan_vien"),
    "has_payment_method": ("phuong_thuc_tt",), "has_channel": ("kenh_ban",), "has_cost": ("gia_von",), "has_expiry": ("han_dung",),
    "has_ship_fee": ("phi_ship",), "has_order_discount": ("giam_gia",), "has_paid": ("da_tra",), "has_debt_col": ("cong_no",),
    "has_purchase_price": ("gia_nhap",), "has_stock_col": ("ton_kho",), "has_unit_conversion": ("quy_doi",),
}


_CH_RX = re.compile(r"store|zalo|phone|online|tai quay|tai cua hang|shopee|tiktok|facebook|website|mang ve|mua ve|grab|app|dien thoai|tai cho")
_PAY_RX = re.compile(r"cash|transfer|ewallet|cod|tien mat|chuyen khoan|vi dien tu|momo|the ngan hang|visa|qr|ghi no|debt")


def _fill_ok(series):
    return series.notna().mean() >= 0.3


def profile_shop(tables, meta, cb):
    """Hồ sơ 1 shop. tables/meta từ clean_shop.load_clean_tables, cb từ schema_build.build_canonical."""
    P = {"structure": cb["info"].get("structure"), "tables_used": cb["info"].get("tables_used"), "warnings": list(cb["info"].get("warnings", []))}
    vo, vl = cb["v_orders"], cb["v_lines"]
    P.update({"date_from": None, "date_to": None, "n_orders": 0, "n_lines": 0})
    if vo is not None and len(vo):
        d = sb._dates(vo["order_dt"]) if "order_dt" in vo else pd.Series(dtype="datetime64[ns]")
        d = d.dropna()
        P["n_orders"] = int(vo["order_id"].nunique())
        P["n_lines"] = int(len(vl)) if vl is not None else 0
        if len(d):
            P["date_from"], P["date_to"] = str(d.min())[:10], str(d.max())[:10]
        raw = vo["order_dt"].dropna().astype(str)
        P["has_time_of_day"] = bool((raw.str.len() > 10).mean() > 0.5) if len(raw) else False
        st = vo["status"] if "status" in vo else pd.Series(dtype=object)
        P["has_status"] = bool(st.notna().any())
        P["has_cancel"] = bool((st == "huy").any())
        P["has_return"] = bool((st == "tra_hang").any())
    # quét mọi bảng của shop
    has = {k: False for k in list(_ROLE_FLAGS) + ["has_gender", "has_address", "has_customer_group", "has_reason", "has_product_group", "has_service_staff"]}
    hint_tables = {"nhap_hang": False, "ton_kho": False, "cong_no": False, "chi_phi": False, "khach_hang": False}
    for tn, df in tables.items():
        tm = meta["tables"][tn]
        h = cat.table_hint(tn, tm.get("files", []))
        if h in hint_tables:
            hint_tables[h] = True
        for c in df.columns:
            if c.startswith("_") or c.endswith("__don_vi") or c.endswith("__raw"):
                continue
            s = df[c]
            if not _fill_ok(s):
                continue
            name = rd.squash(cat.ascii_fold(c))
            kind, prefix = cat._kind(s, tm, c)
            role, _ = rd.infer_role(cat.ascii_fold(c), kind, prefix)
            for flag, roles in _ROLE_FLAGS.items():
                if role in roles:
                    has[flag] = True
            for key, pat in _NAME_PATTERNS.items():
                if re.match(pat, name):
                    has[{"gioi_tinh": "has_gender", "dia_chi": "has_address", "nhom_khach": "has_customer_group", "ly_do": "has_reason",
                         "nhom_hang": "has_product_group", "tho": "has_service_staff"}[key]] = True
            if role == "ma_phieu_nhap":
                hint_tables["nhap_hang"] = True
            if h == "nhap_hang" and kind == "tien":
                has["has_purchase_price"] = True
            if kind in ("nhom", "chu") and s.nunique() <= 12:           # theo nội dung
                vals = [cat.ascii_fold(v) for v in s.dropna().astype(str).unique()]
                if len(vals) >= 2 and sum(bool(_CH_RX.search(v)) for v in vals) / len(vals) >= 0.7:
                    has["has_channel"] = True
                if len(vals) >= 2 and sum(bool(_PAY_RX.search(v)) for v in vals) / len(vals) >= 0.7:
                    has["has_payment_method"] = True
                if 2 <= len(vals) <= 4 and all(v in ("nam", "nu", "male", "female", "khac") for v in vals):
                    has["has_gender"] = True
    P.update(has)
    P["has_purchase"] = hint_tables["nhap_hang"] or has["has_purchase_price"]
    P["has_stock"] = hint_tables["ton_kho"] or has["has_stock_col"]
    P["has_stock_or_purchase"] = P["has_stock"] or P["has_purchase"]
    P["has_debt"] = hint_tables["cong_no"] or has["has_debt_col"] or has["has_paid"]
    P["has_expense"] = hint_tables["chi_phi"]
    P["has_customer"] = has["has_customer_name"] or has["has_customer_id"]
    return P


# ───────────────────────── THÔNG TIN CÂU HỎI CẦN ─────────────────────────
# (tên thông tin cần, regex trên text_ascii đã bỏ dấu, cờ hồ sơ phải có; None = shop nào cũng KHÔNG ghi)
NEEDS = [
    ("kien_thuc_ngoai_du_lieu", r"\b(nen uong|lieu dung|tac dung phu|chong chi dinh|cong dung cua|uong moi lan|bao nhieu vien moi lan)\b", None),
    ("tinh_cach_nhan_vien", r"\b(quy men|yeu men|duoc khach men|khen|le phep|tan tam|chu dao|tay nghe|lanh nghe|than thien|thai do|hai long|nhiet tinh|chu dao|dang tin)\b", None),
    ("khach_nu_nam", r"\b(khach|nguoi mua|nguoi)\s*(nu|nam)\b|\bgioi tinh\b|\bnu gioi\b|\bnam gioi\b|\bphai nu\b", "has_gender"),
    ("dia_chi_khach", r"\b(dia chi|nha o duong|o duong|khach duong|khach o|o phuong|o quan|o huyen|o thanh pho|khu vuc)\b", "has_address"),
    ("ly_do_huy_tra", r"\b(huy vi|tra vi|ly do (huy|tra)|vi sao (huy|tra)|bi huy do|tra do)\b", "has_reason"),
    ("gia_von_loi_nhuan", r"\b(gia von|lai gop|lai rong|loi nhuan|tien lai|lai bao nhieu|bien loi nhuan|von hang|tien von)\b", "has_cost"),
    ("cong_no", r"\b(con no|cong no|ghi no|khach no|no cua|tuoi no|no qua han|chua thanh toan|con thieu|con phai thu|dang no)\b", "has_debt"),
    ("ton_kho", r"\b(ton kho|con ton|ton cuoi|ton dau|so luong ton|con hang trong kho|trong kho)\b|\bcuoi ngay\b.*\bcon\b|\bcon (bao nhieu|may) (cai|hop|chai|vi|goi|vien|lo|thung|cuon|bao|chiec|bo|ly|kg|tui|lon)\b", "has_stock_or_purchase"),
    ("gia_nhap_binh_quan", r"\bnhap\b.*\b(binh quan|trung binh|bao nhieu tien)\b|\bgia nhap\b", "has_purchase_price"),
    ("nhap_hang", r"\b(nhap hang|nhap vao|nha cung cap|\bncc\b|phieu nhap|lan nhap)\b", "has_purchase"),
    ("phuong_thuc_thanh_toan", r"\b(cod|tien mat|chuyen khoan|vi dien tu|the ngan hang|quet the|momo|zalopay|phuong thuc thanh toan|hinh thuc thanh toan|tra bang)\b", "has_payment_method"),
    ("kenh_ban", r"\b(kenh|zalo|facebook|shopee|tiktok|online|tai quay|qua dien thoai|tai cua hang|tai quan|mang di|mua ve|app)\b", "has_channel"),
    ("nhom_khach", r"\b(nhom khach|khach nhom|nhom than thiet|khach than thiet|khach vip|hang thanh vien|loai khach)\b", "has_customer_group"),
    ("han_dung", r"\b(han dung|het han|can date|\bhsd\b|sap het han)\b", "has_expiry"),
    ("chi_phi", r"\b(chi phi|tien thue mat bang|tien dien|tien nuoc|luong nhan vien)\b", "has_expense"),
    ("phi_giao_hang", r"\b(phi ship|phi giao hang|phi van chuyen|tien ship)\b", "has_ship_fee"),
    ("nhan_vien", r"\b(nhan vien|\bnv\b|thu ngan|nguoi ban|nhan vien ban)\b", "has_employee"),
    ("khach_hang", r"\b(khach hang|bao nhieu khach|so khach|khach moi|khach quen|khach nao|moi khach|ai la khach|ai mua|khach mua nhieu|khach mua nhin|nhieu lan nhat)\b", "has_customer"),
]
_NEEDS_RX = [(n, re.compile(p), f) for n, p, f in NEEDS]


def required_info(qi):
    """Danh sách (thông tin cần, cờ hồ sơ phải có) mà câu hỏi đòi hỏi."""
    t = qi["text_ascii"]
    return [(n, f) for n, rx, f in _NEEDS_RX if rx.search(t)]


def _outside(p, d0, d1):
    s, e = p.get("start"), p.get("end")
    if (s is None and e is None) or d0 is None:
        return False
    if s is None:                       # mốc 'đến hết ngày X'
        return e < d0
    return e < d0 or s > d1


_STATE_RX = re.compile(r"\b(tinh den|den het|cuoi ngay|qua han|chua gop|con lai|han gop|han tra|dang no|con no|con thieu)\b")


def is_state_question(qi):
    """Câu hỏi về TÌNH TRẠNG tại một ngày (nợ, tồn, hạn góp) chứ không phải số phát sinh trong kỳ."""
    return any(p.get("kind") == "snapshot" for p in qi.get("periods", [])) or bool(_STATE_RX.search(qi.get("text_ascii", "")))


def gate(qi, profile):
    """qi = question_norm.normalize_question(...). Trả {decision, reason, needs}."""
    if qi.get("time_failed"):
        return {"decision": "abstain", "reason": "câu có từ khoá thời gian nhưng chưa hiểu được kỳ", "needs": []}
    d0, d1 = profile.get("date_from"), profile.get("date_to")
    for p in qi.get("periods", []):
        if _outside(p, d0, d1):
            if d1 and p.get("start") and p["start"] > d1 and is_state_question(qi):
                # tình trạng tại ngày sau khi dữ liệu kết thúc: có thể suy ra từ lịch (nợ, hạn góp) -> không chắc, không dám khai unanswerable
                return {"decision": "abstain", "reason": "ngày hỏi sau khoảng dữ liệu, câu hỏi về tình trạng: không chắc", "needs": ["khoang_ngay"]}
            return {"decision": "unanswerable", "reason": "kỳ %s…%s nằm hoàn toàn ngoài khoảng dữ liệu %s…%s" % (p.get("start"), p.get("end"), d0, d1), "needs": ["khoang_ngay"]}
    for name, flag in required_info(qi):
        if flag is None or not profile.get(flag, False):
            return {"decision": "unanswerable", "reason": "shop không ghi thông tin '%s'" % name, "needs": [name]}
    return {"decision": "ok", "reason": "", "needs": []}
