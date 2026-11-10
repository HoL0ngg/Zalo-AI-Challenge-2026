# -*- coding: utf-8 -*-
"""Việc 3 — KIỂM CHỨNG sổ chuẩn bằng đáp án train (không cần LLM): tái tạo các câu hỏi đơn giản bằng pandas thuần.

question_kind(q, r, a)        -> 'rev' | 'cnt' | 'cancel' | 'avg' | None   (r = question_norm.normalize_question(...), a = đáp án train)
check_shop(cb, items)         -> [{kind, start, end, got, expected, ok}]
evaluate_gate(rows, profiles) -> dict precision/recall/chặn nhầm
Mẫu câu: doanh thu 1 kỳ, số đơn 1 kỳ, tỉ lệ đơn huỷ 1 kỳ, giá trị trung bình mỗi đơn 1 kỳ — KHÔNG có bộ lọc khác (nhóm hàng, kênh, khách…).
"""
import re

import schema_build as sb
import profile_gate as pg

_BL = re.compile(r"so voi|nhat|top|moi|\bca\b|nhom|khach|nhan vien|\bnv\b|cod|tien mat|chuyen khoan|vi dien tu|ti trong|ty trong|phan tram|trung binh|theo|tung|ngay nao|thang nao|gio|tuan nao|\bmat hang|san pham|hang nao|tang|giam|chenh|%|quay|zalo|online|tai cua hang|shipper|voucher|giam gia|von|lai|nhieu|it nhat|thuoc|kenh|dien thoai|kho")
_BL2 = re.compile(r"so voi|nhom|khach|nhan vien|\bnv\b|cod|tien mat|chuyen khoan|vi dien tu|theo|tung|ngay nao|thang nao|\bca\b|gio|mat hang|san pham|hang nao|tang|giam|chenh|quay|zalo|online|voucher|top|nhat|lien tuc|thuoc|kenh|vi dien tu|nhieu nhat|it nhat")


def question_kind(q, r, a):
    t = r["text_ascii"]
    if len(r["periods"]) != 1 or r["amounts"] or r["periods"][0]["kind"] == "snapshot" or r["periods"][0].get("start") is None:
        return None
    if not _BL2.search(t):
        if re.search(r"ti le .*huy|huy.*phan tram", t) and a["type"] == "percent":
            return "cancel"
        if re.search(r"trung binh.*(mot|moi|1) don|trung binh don|gia tri trung binh", t) and re.search(r"doanh thu|tien", t) and a["type"] == "number":
            return "avg"
    if a["type"] == "number" and not _BL.search(t):
        if re.search(r"doanh thu", t):
            return "rev"
        if re.search(r"(so don|bao nhieu don|tong so don|dem so don)", t) and not re.search(r"huy|tra hang", t):
            return "cnt"
    return None


def check_shop(cb, items):
    """items: list (kind, q, r, a). Trả list kết quả từng câu."""
    out = []
    if cb.get("v_orders") is None:
        return [{"kind": k, "start": r["periods"][0]["start"], "end": r["periods"][0]["end"], "got": None, "expected": a["answer"], "ok": False} for k, q, r, a in items]
    for k, q, r, a in items:
        p = r["periods"][0]
        rev, n = sb.revenue(cb, p["start"], p["end"])
        if k == "rev":
            got = round(rev)
        elif k == "cnt":
            got = n
        elif k == "avg":
            got = round(rev / n) if n else None
        else:
            ntot, huy = sb.order_counts(cb, p["start"], p["end"])
            got = round(100 * huy / ntot, 2) if ntot else None
        ok = got is not None and abs(got - a["answer"]) <= (0.01 if k == "cancel" else 0.5)
        out.append({"kind": k, "start": p["start"], "end": p["end"], "got": got, "expected": a["answer"], "ok": bool(ok), "question": q["question"][:100]})
    return out


def evaluate_gate(rows, profiles):
    """rows: list (q, r, a) của các shop đã có hồ sơ. Đo cả tỉ lệ chặn nhầm."""
    tp = fp = fn = tn = ab = 0
    FP, FN = [], []
    for q, r, a in rows:
        prof = profiles.get(q["business_id"])
        if prof is None:
            continue
        g = pg.gate(r, prof)
        if g["decision"] == "abstain":
            ab += 1
        pred, act = g["decision"] == "unanswerable", a["type"] == "unanswerable"
        if pred and act:
            tp += 1
        elif pred and not act:
            fp += 1
            FP.append((q["business_id"], q["question"][:110], g["reason"][:70]))
        elif act:
            fn += 1
            FN.append((q["business_id"], q["question"][:120]))
        else:
            tn += 1
    return {"unanswerable_that": tp + fn, "bat_dung": tp, "bo_sot": fn, "chan_nham": fp, "tong_tra_loi_duoc": fp + tn,
            "ti_le_chan_nham": fp / max(1, fp + tn), "precision": tp / max(1, tp + fp), "recall": tp / max(1, tp + fn), "abstain": ab, "FP": FP, "FN": FN}
