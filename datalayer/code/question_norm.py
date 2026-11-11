# -*- coding: utf-8 -*-
"""Chuẩn hoá câu hỏi (Việc 1) — phiên bản 2.

Hàm chính:
  normalize_question(raw, as_of_date, calendar=None) -> dict
      raw, as_of_date, text_norm, text_ascii, amounts, numbers, periods, flags, time_failed, time_cues

Các hàm thành phần:
  normalize_text(text)              -> (text_norm, text_ascii)   mở rộng viết tắt, giữ dấu câu
  parse_amounts(text)               -> [{span, value, unit}]      tiền / % (không nhầm 'trà', 'kg', 'trong'...)
  resolve_time(text, as_of, cal)    -> [{label, start, end, kind, ...}]  theo RULEBOOK
  extract_flags(text)               -> {cờ ý định}

Nguyên tắc: KHÔNG ĐOÁN. Có từ khoá thời gian mà không hiểu thì periods = [] và time_failed = True
(hệ thống phía sau nên bỏ qua câu đó thay vì trả bừa).
"""
import calendar as _cal
import datetime as dt
import json
import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher

# ═════════════════════════ 1. TỪ ĐIỂN VIẾT TẮT ═════════════════════════
# Cụm nhiều từ (so khớp chữ thường, đứng riêng) -> câu chuẩn
TEENCODE_PHRASES = {
    "so vs": "so với", "z ha": "vậy hả", "bao nhiu": "bao nhiêu", "bao nhieu": "bao nhiêu", "bao nhiêu": "bao nhiêu",
    "shop mik": "shop mình", "hom nay": "hôm nay", "hom qua": "hôm qua", "hom kia": "hôm kia",
    "bua nay": "hôm nay", "bữa nay": "hôm nay", "hom ni": "hôm nay", "hôm ni": "hôm nay",
    "bua qua": "hôm qua", "bữa qua": "hôm qua", "thang nay": "tháng này", "thang truoc": "tháng trước",
    "thang roi": "tháng rồi", "thang lien truoc": "tháng liền trước", "tuan nay": "tuần này",
    "tuan truoc": "tuần trước", "tuan roi": "tuần rồi", "nam nay": "năm nay", "nam ngoai": "năm ngoái",
    "nam truoc": "năm trước", "quy nay": "quý này", "quy truoc": "quý trước", "ca sang": "ca sáng",
    "ca chieu": "ca chiều", "gan nhat": "gần nhất", "cung ky": "cùng kỳ", "den het": "đến hết",
    "tu dau": "từ đầu", "ke tu": "kể từ", "doanh thu": "doanh thu", "d thu": "doanh thu",
}
# Từ đơn -> chuẩn
TEENCODE_WORDS = {
    "dthu": "doanh thu", "dthuu": "doanh thu", "bnhiu": "bao nhiêu", "bnhieu": "bao nhiêu", "bn": "bao nhiêu",
    "nhiu": "nhiêu", "nhìu": "nhiêu", "sp": "sản phẩm", "mh": "mặt hàng", "hqua": "hôm qua", "hnay": "hôm nay",
    "dc": "được", "đc": "được", "ko": "không", "hok": "không", "hong": "không", "hem": "không", "khong": "không",
    "mik": "mình", "mk": "mình", "nv": "nhân viên", "kh": "khách hàng", "hđ": "hóa đơn", "hd": "hóa đơn",
    "bill": "đơn hàng", "order": "đơn hàng", "sl": "số lượng", "slg": "số lượng", "đv": "đơn vị", "dvt": "đơn vị tính",
    "trc": "trước", "nhut": "nhất", "z": "vậy", "zay": "vậy", "vs": "so với", "amount": "tổng tiền",
    "total": "tổng", "cash": "tiền mặt", "revenue": "doanh thu", "thg": "tháng", "bít": "biết", "mún": "muốn", "trog": "trong",
}
# Từ mơ hồ: chỉ mở rộng khi ngữ cảnh rõ (xem _expand_ambiguous). 'dt' có thể là điện thoại, 'k' có thể là vitamin K.
# v3: phương ngữ 'ni' (= này) và tháng viết bằng chữ — trên public_test có >60 câu không ra kỳ nào vì các cách viết này
TEENCODE_PHRASES.update({
    "tháng ni": "tháng này", "thang ni": "tháng này", "tuần ni": "tuần này", "tuan ni": "tuần này",
    "quý ni": "quý này", "quy ni": "quý này", "năm ni": "năm này", "nam ni": "năm này",
    "bữa ni": "hôm nay", "bua ni": "hôm nay", "hôm ni": "hôm nay", "hom ni": "hôm nay",
    "tháng giêng": "tháng 1", "tháng một": "tháng 1", "tháng hai": "tháng 2", "tháng ba": "tháng 3",
    "tháng tư": "tháng 4", "tháng bốn": "tháng 4", "tháng năm": "tháng 5", "tháng sáu": "tháng 6",
    "tháng bảy": "tháng 7", "tháng tám": "tháng 8", "tháng chín": "tháng 9", "tháng mười một": "tháng 11",
    "tháng mười hai": "tháng 12", "tháng chạp": "tháng 12", "tháng mười": "tháng 10",
    "thang mot": "tháng 1", "thang hai": "tháng 2", "thang ba": "tháng 3", "thang bon": "tháng 4",
    "thang sau": "tháng 6", "thang bay": "tháng 7", "thang tam": "tháng 8", "thang chin": "tháng 9",
})
_AMBIG_DT_NEXT = {"thang", "tháng", "hom", "hôm", "hnay", "tuan", "tuần", "quy", "quý", "nam", "năm", "ngay", "ngày", "hqua"}
_AMBIG_K_NEXT = {"ban", "bán", "mua", "co", "có", "duoc", "được", "dc", "đc", "lan", "lần", "ai", "thay", "thấy", "con", "còn", "du", "đủ"}


def load_teencode(path_json):
    """Nạp thêm từ điển từ file JSON {"words": {...}, "phrases": {...}} (ví dụ configs/teencode_dict.json)."""
    with open(path_json, encoding="utf-8") as f:
        d = json.load(f)
    TEENCODE_WORDS.update({k.lower(): v for k, v in d.get("words", {}).items()})
    TEENCODE_PHRASES.update({k.lower(): v for k, v in d.get("phrases", {}).items()})


def export_teencode(path_json):
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump({"words": TEENCODE_WORDS, "phrases": TEENCODE_PHRASES}, f, ensure_ascii=False, indent=1, sort_keys=True)


# ═════════════════════════ 2. HÀM VĂN BẢN ═════════════════════════
def to_ascii(text):
    """Bỏ dấu + chỉ giữ chữ/số/khoảng trắng (dùng làm text_ascii)."""
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def fold(text):
    """Bỏ dấu, chữ thường, GIỮ các ký tự / . , % - : (cần cho ngày tháng, tiền, %)."""
    s = unicodedata.normalize("NFD", str(text).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    s = re.sub(r"[^a-z0-9/.,%\-:\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fold_aligned(text):
    """Giống fold() nhưng giữ NGUYÊN độ dài (mỗi ký tự -> 1 ký tự) để cắt đúng đoạn trong câu gốc."""
    out = []
    for ch in text:
        if ch in "đĐ":
            out.append("d")
            continue
        b = unicodedata.normalize("NFD", ch)[0].lower()
        out.append(b if re.match(r"[a-z0-9/.,%\-:]", b) else " ")
    return "".join(out)


# ═════════════════════════ 2b. GÕ TELEX SAI (không bật bộ gõ) ═════════════════════════
# Trong dữ liệu có nhiều chữ như 'tieenf' (tiền), 'dduwowcj' (được), 'laf' (là), 'bans' (bán).
# Giải mã chỉ được CHẤP NHẬN khi kết quả là một từ có dấu đã thấy trong VOCAB (xây từ câu train) -> không biến từ lạ/tên riêng thành từ sai.
VOCAB = set()
_VOWELS = set("aăâeêioôơuưy")
_TONE_MARK = {"s": "\u0301", "f": "\u0300", "r": "\u0309", "x": "\u0303", "j": "\u0323"}


def build_vocab(questions):
    """Tập các từ CÓ DẤU xuất hiện trong danh sách câu hỏi (dùng câu TRAIN)."""
    v = set()
    for q in questions:
        for w in re.findall(r"[^\W\d_]+", str(q["question"] if isinstance(q, dict) else q).lower()):
            if to_ascii(w).replace(" ", "") != w:
                v.add(unicodedata.normalize("NFC", w))
    return v


def load_vocab(path):
    global VOCAB
    with open(path, encoding="utf-8") as f:
        VOCAB = {l.strip() for l in f if l.strip()}
    return VOCAB


def _telex_candidates(w):
    """'tieenf' -> ['tiền'] ; trả list các cách đặt dấu có thể."""
    tone = None
    if len(w) >= 3 and w[-1] in _TONE_MARK and (w[-2] in "aeiouywd" + "".join(_VOWELS) or w[-2] in "ngchmpt"):
        tone, w = w[-1], w[:-1]
    x = w
    if x.startswith("dd"):
        x = "đ" + x[2:]
    for a, b in (("aa", "â"), ("ee", "ê"), ("oo", "ô"), ("aw", "ă"), ("uw", "ư"), ("ow", "ơ")):
        x = x.replace(a, b)
    if "w" in x:                      # còn chữ w lẻ: không phải Telex hợp lệ
        return []
    if x == w and tone is None:       # không có dấu hiệu Telex nào
        return []
    chars = list(x)
    idx = [i for i, c in enumerate(chars) if c in _VOWELS]
    if not idx:
        return []
    # nhóm nguyên âm liền nhau đầu tiên (bỏ 'u' trong 'qu', 'i' trong 'gi')
    start = idx[0]
    if start >= 1 and chars[start - 1] == "q" and chars[start] == "u" and len(idx) > 1:
        idx = idx[1:]
        start = idx[0]
    if start >= 1 and chars[start - 1] == "g" and chars[start] == "i" and len(idx) > 1 and idx[1] == start + 1:
        idx = idx[1:]
        start = idx[0]
    nucleus = [start]
    for i in idx[1:]:
        if i == nucleus[-1] + 1:
            nucleus.append(i)
        else:
            break
    out = []
    if tone is None:
        out.append("".join(chars))
    else:
        mod = [i for i in nucleus if chars[i] in "ăâêôơư"]
        if mod:
            pos = [mod[-1]]
        elif len(nucleus) == 1:
            pos = [nucleus[0]]
        elif len(nucleus) == 2:
            closed = nucleus[-1] < len(chars) - 1
            pos = [nucleus[1]] if closed else [nucleus[0], nucleus[1]]
        else:
            pos = [nucleus[1]]
        for p in pos:
            t = chars[:]
            t[p] = t[p] + _TONE_MARK[tone]
            out.append("".join(t))
    return [unicodedata.normalize("NFC", o) for o in out]


TELEX_PROTECT = {"max", "its", "mix", "pro", "ice", "plus", "ees", "ee", "set", "box", "size", "top", "hot", "new", "mini"}


def telex_decode(token, vocab=None, can_be_name=False):
    """Trả từ tiếng Việt có dấu nếu `token` là chữ gõ Telex sai VÀ kết quả nằm trong vocab; ngược lại trả None.
    can_be_name=True: token đứng giữa câu và viết hoa -> coi là tên riêng/thương hiệu, không giải mã."""
    v = VOCAB if vocab is None else vocab
    if not v:
        return None
    w = token.lower()
    if len(w) < 3 or w in v or w in TELEX_PROTECT or not w.isascii():
        return None
    if can_be_name and token[:1].isupper():
        return None
    for cand in _telex_candidates(w):
        if cand in v:
            return cand
    return None


def autoload_config(base_dir=None):
    """v3: tự nạp configs/teencode_dict.json + configs/vocab_vi_train.txt nếu có.
    v2 chỉ nạp khi gọi tay nên báo cáo câu hỏi chạy mà KHÔNG có từ điển: 'cuwar', 'tawng/giamr', 'soos', 'hoom', 'gias' không được sửa."""
    import os
    base = base_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "configs")
    tj, vt = os.path.join(base, "teencode_dict.json"), os.path.join(base, "vocab_vi_train.txt")
    if os.path.isfile(tj):
        load_teencode(tj)
    if os.path.isfile(vt) and not VOCAB:
        load_vocab(vt)
    return bool(VOCAB)


_PHRASE_CACHE = {}


def _phrase_regex():
    key = len(TEENCODE_PHRASES)
    if _PHRASE_CACHE.get("n") != key:
        items = sorted(TEENCODE_PHRASES.items(), key=lambda kv: -len(kv[0]))
        _PHRASE_CACHE["items"] = [(re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)", re.I), v) for k, v in items if k != v]
        _PHRASE_CACHE["n"] = key
    return _PHRASE_CACHE["items"]


# v3: viết tắt có nguy cơ trùng TÊN HÀNG ('Telfast HD 180mg', 'đèn led T8 1.2m'): không mở rộng khi
#   (a) đứng ngay trước quy cách (số + mg/ml/g/kg/w/v/m/cm/mm/l/iu/mcg/%) hoặc
#   (b) viết HOA trong câu có chữ thường ('HD', 'T8').
_RISKY_ABBR = re.compile(r"(?i)^(?:hd|hđ|t\d{1,2})$")
_SPEC_AFTER = re.compile(r"\s+\d+(?:[.,]\d+)?\s*(?:mg|mcg|ml|kg|g|iu|w|v|m|cm|mm|l|%|x)\b", re.I)


def _protected_spans(text, protect):
    spans = []
    for term in (protect or []):
        t = str(term).strip()
        if len(t) >= 3:
            for m in re.finditer(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text, re.I):
                spans.append((m.start(), m.end()))
    return spans


def normalize_text(text, protect=None):
    """Mở rộng viết tắt, đổi 'th5'->'tháng 5', giữ nguyên dấu câu và tên riêng. Trả về (text_norm, text_ascii).
    protect: danh sách tên hàng / tên riêng của shop (tuỳ chọn) — các đoạn trùng khớp không bị mở rộng viết tắt."""
    if not text:
        return "", ""
    if not VOCAB:
        autoload_config()
    s = unicodedata.normalize("NFC", str(text)).strip()
    s = re.sub(r"\s+", " ", s)
    # th5, thg 5, thang 5 -> tháng 5 ; 't5 2026' -> tháng 5 2026 ; 'th trước' -> tháng trước
    s = re.sub(r"(?i)(?<!\w)(?:th|thg|thang|tháng)\s*(\d{1,2})(?!\d)", r"tháng \1", s)
    s = re.sub(r"(?i)(?<!\w)t(\d{1,2})(?=\s*(?:/\s*)?(?:\d{4}|năm|nam)\b)", r"tháng \1", s)
    s = re.sub(r"(?i)(?<!\w)th(?=\s+(?:trước|truoc|trc|này|nay|rồi|roi)\b)", "tháng", s)
    for rx, rep in _phrase_regex():
        s = rx.sub(rep, s)

    pspans = _protected_spans(s, protect)
    has_lower = bool(re.search(r"[a-zà-ỹ]", s))

    def repl(m):
        w = m.group(0)
        lw = w.lower()
        if any(a <= m.start() < b for a, b in pspans):
            return w
        if _RISKY_ABBR.match(w) and (_SPEC_AFTER.match(m.string[m.end():]) or (w.isupper() and has_lower)):
            return w
        if lw == "dt":
            nxt = re.match(r"\s+(\w+)", m.string[m.end():])
            return "doanh thu" if nxt and nxt.group(1).lower() in _AMBIG_DT_NEXT else w
        if lw == "k":
            nxt = re.match(r"\s+(\w+)", m.string[m.end():])
            prev = re.search(r"(\w+)\s*$", m.string[:m.start()])
            if prev and prev.group(1).lower() in ("vitamin", "vit", "size", "loai", "hang", "nhom"):
                return w
            return "không" if nxt and nxt.group(1).lower() in _AMBIG_K_NEXT else w
        if lw in TEENCODE_WORDS:
            return TEENCODE_WORDS[lw]
        dec = telex_decode(w, can_be_name=m.start() > 0) if VOCAB else None
        return dec if dec else w

    s = re.sub(r"\w+", repl, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s, to_ascii(s)


# ═════════════════════════ 3. SỐ TIỀN / % / SỐ ĐẾM ═════════════════════════
_LB = r"(?<![\w/.,\-])"  # không đứng sau chữ/số/dấu ngày -> tránh bắt nhầm trong ngày tháng, mã hàng


def _dec(a):
    return Decimal(a.replace(",", "."))


def _parse_amounts_core(text):
    """Bóc tách tiền (vnd) và phần trăm. Mỗi phần tử: {span, value, unit[, maybe_money]}."""
    out, taken = [], []
    if not text:
        return out
    text = unicodedata.normalize("NFC", str(text))
    f = _fold_aligned(text)

    def free(a, b):
        return not any(a < y and x < b for x, y in taken)

    def add(m, value, unit, **extra):
        if free(m.start(), m.end()):
            taken.append((m.start(), m.end()))
            d = {"span": text[m.start():m.end()].strip(), "value": value, "unit": unit, "_pos": (m.start(), m.end())}
            d.update(extra)
            out.append((m.start(), d))

    # 3tr7, 3tr700, 1,5tr, 2 triệu   (đơn vị phải kết thúc ở ranh giới từ -> không bắt 'trà', 'trong', 'trang')
    for m in re.finditer(_LB + r"(\d+(?:[.,]\d+)?)\s*(?:tr|trieu)(?![a-z])(\d{1,3})?(\s*ruoi\b)?", f):   # [vá 3] "2 triệu rưỡi"
        a, b = m.group(1), m.group(2)
        if b and ("," in a or "." in a):
            continue
        val = Decimal(int(a)) * 10 ** 6 + Decimal("0." + b) * 10 ** 6 if b else _dec(a) * 10 ** 6
        if m.group(3):
            val += 500000
        add(m, int(val), "vnd")
    # [vá 3] tiếng lóng: củ/chai = 1 triệu, lít/xị = 100 nghìn, cá/cành = 1 nghìn (theo Việt), tỏi = 1 tỷ.
    # Các chữ này cũng là ĐƠN VỊ HÀNG THẬT (2 chai nước, 1 lít dầu, 3 củ gừng, 1kg tỏi) nên chỉ nhận là tiền khi
    # ngay trước có chữ chỉ tiền (giá, tiền, doanh thu...) hoặc toán tử (trên, dưới, từ... ; riêng chai/lít phải có chữ chỉ tiền).
    _SLANG = {"cu": 10 ** 6, "chai": 10 ** 6, "lit": 10 ** 5, "xi": 10 ** 5, "canh": 10 ** 3, "ca": 10 ** 3, "toi": 10 ** 9}
    _MONEY_W = r"(?:gia|tien|doanh thu|dthu|thu|chi|tri gia|gia tri|lai|no|tra|mat|het|ton)"
    _OP_W = r"(?:tren|duoi|hon|qua|tu|khoang|it nhat|toi da|khong qua|toi thieu|dat|la|bang|>|<|=)"
    for m in re.finditer(_LB + r"(nua|\d+(?:[.,]\d+)?)\s*(cu|chai|lit|xi|canh|ca|toi)(?![a-z])(?!\s*(?:ngay\s*)?\d)(\s*ruoi\b)?", f):   # "từ 15 tới 20" không phải 15 tỏi
        unit, before = m.group(2), f[max(0, m.start() - 30):m.start()]
        # [vá 7] chữ chỉ tiền phải là TỪ TRỌN ("thu" không khớp trong "thùng"); với chai/lít bỏ "tồn"/"hết"
        # vì "tồn kho còn 10 chai", "dùng hết 2 chai" là đếm hàng. Rulebook: "3 thùng 10 chai" là số lượng hàng.
        _MONEY_W_CL = r"(?:gia|tien|doanh thu|dthu|thu|chi|tri gia|gia tri|lai|no|tra|mat)"
        ctx = _MONEY_W_CL if unit in ("chai", "lit") else "(?:" + _MONEY_W + "|" + _OP_W + ")"
        if not re.search(r"\b" + ctx + r"\b\s*(?:\S+\s*){0,2}$", before):
            continue
        n = Decimal("0.5") if m.group(1) == "nua" else _dec(m.group(1))
        if m.group(3):
            n += Decimal("0.5")
        add(m, int(n * _SLANG[unit]), "vnd", slang=unit)
    for m in re.finditer(_LB + r"(\d+(?:[.,]\d+)?)\s*(?:ty|ti)(?![a-z])(?!\s*/\s*\d)", f):   # [vá] "2 tỷ/5ml" là hàm lượng
        add(m, int(_dec(m.group(1)) * 10 ** 9), "vnd")
    # 2k5 = 2500
    for m in re.finditer(_LB + r"(\d+)k(\d{1,3})\b", f):
        a, b = m.group(1), m.group(2)
        add(m, int(Decimal(int(a)) * 1000 + Decimal("0." + b) * 1000), "vnd")
    # 55k, 1,5k, 100 nghìn
    for m in re.finditer(_LB + r"(\d+(?:[.,]\d+)?)\s*(?:k|nghin|ngan)\b", f):
        a = m.group(1)
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", a):
            a = a.replace(".", "")
        add(m, int(_dec(a) * 1000), "vnd")
    # 290.000 đồng / 290000d / 290.000đ
    for m in re.finditer(_LB + r"(\d{1,3}(?:[.,]\d{3})+|\d{4,})\s*(?:d{1,2}(?:o{1,2}ng[fsrxj]?)?|vnd)\b", f):   # [vá] 23.000dd, 41.000 ddoongf
        add(m, int(re.sub(r"[.,]", "", m.group(1))), "vnd")
    # số có dấu ngăn nghìn nhưng không có đơn vị: có thể là tiền hoặc số lượng
    for m in re.finditer(_LB + r"(\d{1,3}(?:[.,]\d{3})+)(?![\d/])", f):
        add(m, int(re.sub(r"[.,]", "", m.group(1))), "number", maybe_money=True)
    # 15%, 12,5 phần trăm
    for m in re.finditer(_LB + r"(\d+(?:[.,]\d+)?)\s*(?:%|phan tram)", f):
        add(m, float(_dec(m.group(1))), "percent")
    out.sort(key=lambda t: t[0])
    return [d for _, d in out]


def _amt_window(text, start, end):
    """[vá] 3 từ trước và đoạn sau một con số, đã chuẩn hoá (teencode, Telex) và bỏ dấu."""
    before = fold(normalize_text(text[max(0, start - 25):start])[0]).split()[-3:]
    return " ".join(before), fold(normalize_text(text[end:end + 30])[0])


def _amt_op(text, start, end):
    """[vá] Rulebook: trên/hơn/quá/dưới N KHÔNG gồm N; từ N trở lên / ít nhất N gồm N."""
    sym = text[max(0, start - 3):start].strip()
    for k, v in (("≥", "gte"), (">=", "gte"), ("≤", "lte"), ("<=", "lte"), (">", "gt"), ("<", "lt")):
        if sym.endswith(k):
            return v
    before, after = _amt_window(text, start, end)
    if re.match(r"(?:\S+ ){0,3}?tro (?:len|di)\b", after) or re.search(r"\b(?:it nhat|toi thieu)$", before):
        return "gte"
    if re.match(r"(?:\S+ ){0,3}?tro (?:xuong|lai)\b", after) or re.search(r"\b(?:toi da|khong qua)$", before):
        return "lte"
    if re.search(r"\b(?:tren|hon|qua|vuot|vuot qua|lon hon|cao hon)$", before):
        return "gt"
    if re.search(r"\b(?:duoi|it hon|nho hon|thap hon)$", before):
        return "lt"
    return None


def parse_amounts(text):
    """Như bản cũ, thêm op (gte/gt/lte/lt/None) và role (new_price/old_price/None) cho mỗi số tiền.
    [vá] Bỏ % không có toán tử hay động từ đi kèm: "Otrivin 0,1%", "natri clorid 0,9%" là tên hàng."""
    out = []
    for d in _parse_amounts_core(text):
        a, b = d.pop("_pos")
        before, after = _amt_window(text, a, b)
        role = None
        if d["unit"] == "vnd":
            if re.search(r"\b(?:len|len gia|gia len|tang len)$", before):
                role = "new_price"
            elif re.search(r"\btu$", before) and re.match(r"len\b", after):
                role = "old_price"
        op = None if role else _amt_op(text, a, b)
        if d["unit"] == "percent" and op is None and not re.search(
                r"\b(?:tang|giam|chiem|dat|len|xuong|hon|kem|khoang|la|chiet khau|giam gia)$", before):
            continue
        d.update(op=op, role=role)
        out.append(d)
    return out


_COUNT_BLOCK = re.compile(r"^(?:thang|quy|tuan|ngay|nam|th|t)$")


def parse_numbers(text):
    """Các số đếm/ngưỡng chưa thuộc tiền hay ngày (ví dụ 'từ 187 đơn', 'top 3'). Trả {span, value, next}."""
    text = unicodedata.normalize("NFC", str(text))
    f = _fold_aligned(text)
    taken = [(m.start(), m.end()) for m in re.finditer(
        r"\d{1,2}\s*[/.\-]\s*\d{1,2}(?:\s*[/.\-]\s*\d{2,4})?|\d+(?:[.,]\d+)?\s*(?:tr|trieu|k|nghin|ngan|%|phan tram|dong|d|vnd)\b|\d{1,3}(?:[.,]\d{3})+", f)]
    out = []
    for m in re.finditer(r"(?<![\w/.,\-])(\d+)(?![\w/.,%])", f):
        if any(a <= m.start() < b for a, b in taken):
            continue
        prev = re.search(r"([a-z]+)\s*$", f[:m.start()])
        if prev and _COUNT_BLOCK.match(prev.group(1)):
            continue
        if 1990 <= int(m.group(1)) <= 2100 and prev and prev.group(1) in ("nam", "thang"):
            continue
        nxt = re.match(r"\s*([a-z]+)", f[m.end():])
        out.append({"span": text[m.start():m.end()], "value": int(m.group(1)), "next": nxt.group(1) if nxt else None})
    return out


# ═════════════════════════ 4. THỜI GIAN ═════════════════════════
_N_WORDS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4, "nam": 5, "sau": 6, "bay": 7, "tam": 8, "chin": 9, "muoi": 10}
_TIME_FUZZY = ["ngay", "thang", "tuan", "quy", "het", "hom", "truoc", "nhat", "gan"]
_TIME_PROTECT = {"thuoc", "thung", "than", "trang", "quay", "thuong", "truong", "thang", "thanh", "tuan", "tren", "tang", "tuoi", "gian", "gan", "ngan", "hon", "truong", "nhap", "nhan", "hop", "nay", "nao", "nam", "nghin", "thong", "ngay", "quy"}
_TYPO = {"trc": "truoc", "tr": "tr", "tryoc": "truoc", "thg": "thang", "thag": "thang", "hqua": "hom qua", "hnay": "hom nay"}
# 'M/YY' kiểu '8/26' = tháng 8 năm 2026. Kiểu viết này KHÔNG có trong train, chỉ thấy khi đo độ phủ trên public_test.
# Mặc định TẮT (câu đó sẽ báo time_failed -> hệ thống bỏ qua, không đoán). Chỉ bật nếu cả nhóm đồng ý (xem README mục 'Luật cuộc thi').
ENABLE_SHORT_MONTH_YEAR = True   # [vá 4] nhóm (Việt) đồng ý bật 05/11: '8/26' = tháng 8/2026, chỉ khi năm 20..40
CA_SANG = ("06:00:00", "13:59:59")
CA_CHIEU = ("14:00:00", "21:59:59")


def _collapse(w):
    return re.sub(r"(.)\1+", r"\1", w)


_TIME_EXACT = {"nay", "truoc", "roi", "qua", "ngay", "thang", "tuan", "quy", "nhat", "het", "hom", "gan", "den", "voi", "nam", "ngoai", "cung", "tet",
               "mot", "hai", "ba", "bon", "sau", "bay", "tam", "chin", "muoi", "dau", "cuoi", "nua", "mung"}   # [vá 3]


def _telex_clean(w):
    """'nayf' -> 'nay', 'truwowcs' -> 'truoc': bỏ chữ w thừa và dấu thanh Telex ở cuối (s f r x j z)."""
    for v in (w, w.replace("w", "")):
        for cand in (v, v[:-1] if len(v) > 3 and v[-1] in "sfrxjz" else v):
            if cand in _TIME_EXACT and cand != w:
                return cand
    return None


def _fix_word(w):
    if w in _TYPO:
        return _TYPO[w]
    t = _telex_clean(w)
    if t:
        return t
    if len(w) < 4 or w in _TIME_PROTECT or w in _TIME_FUZZY:
        return w
    for cand in _TIME_FUZZY:
        for v in (w, _collapse(w)):
            if v and v[0] == cand[0] and v != cand and len(cand) - 1 <= len(v) <= len(cand) + 2 \
                    and SequenceMatcher(None, v, cand).ratio() >= 0.8:
                return cand
    return w


def _time_text(norm_text):
    """Chuỗi dùng để tìm thời gian: bỏ dấu, giữ / . , -, sửa gõ sai từ khoá thời gian."""
    f = fold(re.sub(r"\s*[–—]\s*", " - ", norm_text))   # [vá] giữ gạch nối "01/02 – 15/02"
    f = re.sub(r"[a-z]+", lambda m: _fix_word(m.group(0)), f)
    f = re.sub(r"\b(?:ngay)\s+(?=ngay\b)", "", f)
    return f


def _date_ok(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _month_end(y, m):
    return dt.date(y, m, _cal.monthrange(y, m)[1])


def _add_months(y, m, k):
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def _clamp(y, m, d):
    return dt.date(y, m, min(d, _cal.monthrange(y, m)[1]))


def _ymd_not_after(as_of, y, m, d, month_start_rule=True):
    return dt.date(y, m, d) <= as_of


def _year_guess(as_of, month, day=1):
    """Tháng/ngày không ghi năm: năm nay nếu không sau hôm nay, ngược lại năm trước (rulebook)."""
    y = as_of.year
    try:
        if dt.date(y, month, day) > as_of:
            y -= 1
    except ValueError:
        pass
    return y


# -------- Tết --------
_CAL_IDX = {}


def _cal_index(calendar):
    k = id(calendar)
    if k not in _CAL_IDX:
        idx = {}
        for r in calendar or []:
            leap = str(r.get("lunar_leap", "")).lower() == "true"
            idx[(str(r.get("lunar_year")), str(r.get("lunar_month")), str(r.get("lunar_day")), leap)] = r.get("date")
        _CAL_IDX[k] = idx
    return _CAL_IDX[k]


def tet_window(year, calendar):
    """23 tháng Chạp (năm âm Y-1) -> hết mùng 10 tháng Giêng (năm âm Y), theo calendar.csv. Trả (start, end) hoặc None."""
    idx = _cal_index(calendar)
    s = idx.get((str(year - 1), "12", "23", False))
    e = idx.get((str(year), "1", "10", False))
    if s and e:
        return dt.date.fromisoformat(s[:10]), dt.date.fromisoformat(e[:10])
    return None


# -------- biểu thức thời gian --------
_D = r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{4}|\d{2}))?"
_NUMW = r"(\d+|mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi)"


def _nval(x):
    return int(x) if x.isdigit() else _N_WORDS.get(x)


def _mk(kind, start, end, **meta):
    return {"kind": kind, "start": start, "stop": end, "meta": meta}


def _date_from(m_d, m_m, m_y, as_of, ref_year=None):
    """Ngày d/m[/y]; thiếu năm: lấy năm ref_year nếu có, không thì theo rulebook (không sau hôm nay)."""
    if m_y:
        y = int(m_y)
        y = y + 2000 if y < 100 else y
    elif ref_year:
        y = ref_year
    else:
        y = _year_guess(as_of, int(m_m), int(m_d))
    return _date_ok(y, m_m, m_d)


def _extract(s, as_of, calendar):
    """Tìm mọi biểu thức thời gian trong chuỗi s (đã fold). Trả list dict theo thứ tự xuất hiện."""
    taken, exs = [], []

    def free(a, b):
        return not any(a < y and x < b for x, y in taken)

    def put(m, role, kind, start, end, **meta):
        if free(m.start(), m.end()):
            taken.append((m.start(), m.end()))
            e = _mk(kind, start, end, **meta)
            e.update({"pos": m.start(), "role": role, "span": m.group(0)})
            exs.append(e)
            return True
        return False

    ytd_start = dt.date(as_of.year, 1, 1)

    # --- N ngày kể từ D  /  N ngày ngay trước (đó | D)  (hiệu ứng tăng giá) ---
    for m in re.finditer(r"\b" + _NUMW + r"\s*ngay\s*ke\s*tu\s*(?:ngay\s*)?(?:" + _D + r")?", s):
        n = _nval(m.group(1))
        if not n:
            continue
        anchor = _date_from(m.group(2), m.group(3), m.group(4), as_of) if m.group(2) else None
        put(m, "abs", "fwd_window", anchor, None, n=n, needs_anchor=anchor is None)
    if re.search(r"\bke\s*tu\s*khi\b|\blen\s*gia\b|\btang\s*gia\b|\btu\s*khi\b[^,;?]*\blen\s*\d", s):  # '14 ngày đầu' sau khi tăng giá; [vá 8] "từ khi X lên 35.000đ"
        for m in re.finditer(r"\b" + _NUMW + r"\s*ngay\s*dau(?:\s*tien)?\b", s):
            n = _nval(m.group(1))
            if n:
                put(m, "abs", "fwd_window", None, None, n=n, needs_anchor=True)
    for m in re.finditer(r"\b" + _NUMW + r"\s*ngay\s*(?:ngay\s*)?(?:lien\s*)?truoc(?!\s*tet)\s*(?:do|ngay\s*do|ngay\s*tang(?:\s*gia)?|ngay\s*" + _D + r")?", s):
        n = _nval(m.group(1))
        if n:
            anchor = _date_from(m.group(2), m.group(3), m.group(4), as_of) if m.group(2) else None
            put(m, "back", "back_window", anchor, None, n=n)
    # --- [vá 3] nửa đầu / nửa cuối tháng: 1-15 và 16-cuối tháng ---
    for m in re.finditer(r"\bnua\s*(dau|cuoi|sau)\s*(?:cua\s*)?thang\s*(?:(\d{1,2})(?!\d)(?:\s*(?:/|nam)\s*(\d{4}))?|(nay|truoc|roi))", s):
        half, mo, y, rel = m.groups()
        if mo:
            mo = int(mo)
            if not 1 <= mo <= 12:
                continue
            y = int(y) if y else _year_guess(as_of, mo)
        else:
            y, mo = _add_months(as_of.year, as_of.month, 0 if rel == "nay" else -1)
        st, en = (dt.date(y, mo, 1), dt.date(y, mo, 15)) if half == "dau" else (dt.date(y, mo, 16), _month_end(y, mo))
        put(m, "abs", "range", st, en, semantics="within", note="nửa tháng: 1-15 / 16-cuối tháng")
    # --- [vá 3] từ ngày D1 tới D2 tháng (này | trước | M[/Y]) ---
    for m in re.finditer(r"\btu\s*(?:ngay\s*)?(\d{1,2})\s*(?:den|toi|-)\s*(?:het\s*)?(?:ngay\s*)?(\d{1,2})\s*thang\s*(?:(nay|truoc|roi)|(\d{1,2})(?!\d)(?:\s*(?:/|nam)\s*(\d{4}))?)", s):
        d1, d2, rel, mo, y = m.groups()
        if rel:
            y, mo = _add_months(as_of.year, as_of.month, 0 if rel == "nay" else -1)
        else:
            mo = int(mo)
            y = int(y) if y else _year_guess(as_of, mo) if 1 <= mo <= 12 else None
        a, b = (_date_ok(y, mo, d1), _date_ok(y, mo, d2)) if y else (None, None)
        if a and b and a <= b:
            put(m, "abs", "range", a, b, semantics="within")
    # --- [vá 3] thứ trong tuần: "từ thứ Hai tới giờ", "thứ Bảy tuần trước" ---
    _WD = r"(?:thu\s*(hai|ba|tu|nam|sau|bay|[2-7])|(chu\s*nhat|cn))"
    def _wd(g1, g2):
        return 6 if g2 else ({"hai": 0, "ba": 1, "tu": 2, "nam": 3, "sau": 4, "bay": 5}.get(g1, None) if not g1.isdigit() else int(g1) - 2)
    mon0 = as_of - dt.timedelta(days=as_of.weekday())
    for m in re.finditer(r"\btu\s*" + _WD + r"(?:\s*tuan\s*nay)?\s*(?:den|toi)\s*(?:gio|nay|hom\s*nay|bay\s*gio)\b", s):
        st = mon0 + dt.timedelta(days=_wd(m.group(1), m.group(2)))
        if st > as_of:
            st -= dt.timedelta(days=7)
        put(m, "abs", "range", st, as_of, semantics="within")
    for m in re.finditer(r"\b" + _WD + r"\s*tuan\s*(truoc|roi|nay)\b", s):
        d_ = mon0 + dt.timedelta(days=_wd(m.group(1), m.group(2)) - (0 if m.group(3) == "nay" else 7))
        if d_ <= as_of:
            put(m, "abs", "day", d_, d_, semantics="within")
    # --- [vá 3] "2 hôm nay", "3 bữa nay" = N ngày gần nhất (gồm hôm nay) ---
    for m in re.finditer(r"\b" + _NUMW + r"\s*(?:hom|bua|ngay)\s*nay\b", s):
        if m.group(1) in ("sau", "bay", "nam", "tam"):   # [vá 9] "sau hôm nay" là SAU chứ không phải SÁU; "bây", "năm", "tạm"
            continue
        n = _nval(m.group(1))
        if n and n >= 2:
            put(m, "abs", "rolling", as_of - dt.timedelta(days=n - 1), as_of, n=n, semantics="within")
    # --- [vá 3] "mùng 1 Tết", "mồng 3 Tết" = đúng ngày âm lịch đó (tra calendar.csv) ---
    for m in re.finditer(r"\b(?:mung|mong)\s*(\d{1,2})\s*tet\b(?:\s*(?:nam\s*)?(20\d\d))?", s):
        dd, yy = int(m.group(1)), m.group(2)
        idx = _cal_index(calendar)
        d_ = None
        for y in ([int(yy)] if yy else [as_of.year, as_of.year - 1]):
            iso = idx.get((str(y), "1", str(dd), False))
            if iso and dt.date.fromisoformat(iso[:10]) <= as_of:
                d_ = dt.date.fromisoformat(iso[:10])
                break
        if d_:
            put(m, "abs", "day", d_, d_, semantics="within")
        else:
            put(m, "abs", "unresolved", None, None, reason="mùng N Tết không có trong calendar")
    # --- [vá 3] cách nói KHÔNG có trong rulebook, nhiều nghĩa -> đánh dấu không hiểu (bỏ qua câu, 0 điểm) ---
    for rx, why in (
            (r"(?<!ca )\b(?:sang|trua|chieu|dem)\s*(?:nay|qua|hom\s*qua|hom\s*nay)\b|\btoi\s*(?:qua|hom\s*qua)\b", "buổi trong ngày"),
            (r"\b(?:tuan|quy|nam)\s*(?:sau|toi)\b(?!\s*(?:nay|gio|hom|bay|het|bua|ngay))|\bthang\s*toi\b(?!\s*(?:nay|gio|hom|bay|het|bua|ngay))|\bngay\s*mai\b", "kỳ tương lai"),
            (r"\bmay\s*(?:hom|bua|ngay)\s*(?:nay|qua)\b|\bdao\s*nay\b|(?<!ngay )(?<!tuan )\bgan\s*day\b|\bhoi\s*truoc\b", "khoảng mơ hồ"),
            (r"(?<!tu )\b(?:dau|cuoi|giua)\s*(?:thang|tuan|nam|quy)(?:\s*(?:nay|truoc|roi|\d{1,2}(?:\s*/\s*\d{4})?))?(?!\s*(?:den|toi))", "đầu/cuối/giữa kỳ"),
            (r"\b(?:tuan|ngay)\s*dau\s*tien\b|\bcuoi\s*tuan\b", "tuần đầu / cuối tuần")):
        for m in re.finditer(rx, s):
            put(m, "abs", "unresolved", None, None, reason=why)
    # --- N ngày trước Tết ---
    for m in re.finditer(r"\b" + _NUMW + r"\s*ngay\s*(?:ngay\s*)?truoc\s*tet\b", s):
        n = _nval(m.group(1))
        if n:
            put(m, "pre_tet", "pre_tet", None, None, n=n)
    # --- khoảng: từ D1 đến (hết) D2 | từ đầu tháng/năm/tuần (nay) đến hết hôm nay ---
    for m in re.finditer(r"\b(?:giai doan\s*)?tu\s*(?:ngay\s*)?(?:" + _D + r"|dau\s*(nam|thang|tuan)(?:\s*nay)?)(?:\s*nam\s*nay)?\s*(?:den|toi)\s*(?:het\s*)?(?:ngay\s*)?(?:" + r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{4}|\d{2}))?|(hom\s*nay|nay|hom\s*qua))", s):   # [vá 5] thêm "đến hết hôm qua"
        a_d, a_m, a_y, unit, b_d, b_m, b_y, today = m.groups()
        if unit:
            start = {"nam": ytd_start, "thang": as_of.replace(day=1), "tuan": as_of - dt.timedelta(days=as_of.weekday())}[unit]
            kind = {"nam": "ytd", "thang": "month_to_date", "tuan": "week_to_date"}[unit]
        else:
            start = _date_from(a_d, a_m, a_y, as_of, ref_year=as_of.year if not a_y else None)
            kind = "range"
        if today:
            end = as_of - dt.timedelta(days=1) if today.endswith("qua") else as_of
        else:
            end = _date_from(b_d, b_m, b_y, as_of, ref_year=(start.year if start else as_of.year) if not b_y else None)
        if start and end:
            if kind == "range" and end == as_of and start == ytd_start:
                kind = "ytd"
            if kind == "range" and end == as_of and start == as_of.replace(day=1):
                kind = "month_to_date"
            put(m, "abs", kind, start, end, semantics="within")
    # --- [vá] khoảng có gạch nối: 01/02/2026 - 15/02/2026 ---
    for m in re.finditer(r"(?<![\d/.])(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{4}|\d{2}))?\s*-\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{4}|\d{2}))?(?![\d/])", s):
        a_d, a_m, a_y, b_d, b_m, b_y = m.groups()
        end = _date_from(b_d, b_m, b_y, as_of)
        start = _date_from(a_d, a_m, a_y, as_of, ref_year=end.year if (end and not a_y) else None)
        if start and end and start <= end:
            put(m, "abs", "range", start, end, semantics="within")
    # --- [vá] từ nay / từ hôm nay đến (hết) ngày X  (hạn dùng sắp tới) ---
    for m in re.finditer(r"\btu\s*(?:hom\s*)?nay\s*(?:den|toi)\s*(?:het\s*)?(?:ngay\s*)?" + _D, s):
        end = _date_from(m.group(1), m.group(2), m.group(3), as_of, ref_year=as_of.year if not m.group(3) else None)
        if end and end >= as_of:
            put(m, "abs", "range", as_of, end, semantics="within")
    # --- đến hết ngày X / tính đến hôm nay / hết hôm nay (tình trạng lúc hết ngày) ---
    for m in re.finditer(r"\b(?:tinh\s*)?(?:den|toi)\s*het\s*(?:ngay\s*)?(?:" + _D + r"|(hom\s*nay|nay))|\bhet\s*(?:ngay\s*)?(?:" + _D + r"|(hom\s*nay))|\btinh\s*(?:den|toi)\s*(?:ngay\s*)?(?:" + _D + r"|(hom\s*nay))", s):
        g = m.groups()
        parts = [g[0:3], g[4:7], g[8:11]]
        today = g[3] or g[7] or g[11]
        d3 = next((p for p in parts if p[0]), None)
        end = as_of if today and not d3 else (_date_from(d3[0], d3[1], d3[2], as_of) if d3 else None)
        if end:
            put(m, "abs", "snapshot", None, end, semantics="snapshot_end")
    # --- N ngày gần nhất / qua / N tuần gần nhất ---
    for m in re.finditer(r"\b" + _NUMW + r"\s*(ngay|tuan)\s*(?:gan\s*nhat|gan\s*day|vua\s*qua|vua\s*roi|tro\s*lai\s*day|qua(?!\s*(?:han|tuoi)))", s):
        n = _nval(m.group(1))
        if n:
            days = n * (7 if m.group(2) == "tuan" else 1)
            put(m, "abs", "rolling", as_of - dt.timedelta(days=days - 1), as_of, n=days, semantics="within")
    for m in re.finditer(r"\b" + _NUMW + r"\s*thang\s*(?:gan\s*nhat|gan\s*day|vua\s*qua)", s):
        put(m, "abs", "unresolved", None, None, reason="N tháng gần nhất: rulebook không định nghĩa")
    # --- N ngày tới (hạn dùng, giao hàng tương lai) ---
    for m in re.finditer(r"\b" + _NUMW + r"\s*ngay\s*(?:toi|nua|sap\s*toi|tiep\s*theo|ke\s*tiep)\b", s):
        n = _nval(m.group(1))
        if n:
            put(m, "abs", "forward_days", as_of, as_of + dt.timedelta(days=n), n=n)
    # --- Tết ---
    for m in re.finditer(r"\btet\b(?:\s*am\s*lich)?(?:\s*(?:nam\s*)?(20\d\d|nay|ngoai|truoc))?", s):
        arg = m.group(1)
        put(m, "abs", "tet", None, None, arg=arg)
    # --- ngày d tháng m năm y (viết chữ) ---
    for m in re.finditer(r"\bngay\s*(\d{1,2})\s*thang\s*(\d{1,2})(?:\s*(?:nam|/)\s*(\d{4}))?", s):
        d_ = _date_from(m.group(1), m.group(2), m.group(3), as_of)
        if d_:
            put(m, "abs", "date", d_, d_, semantics="within")
    # --- quý ---
    for m in re.finditer(r"\bquy\s*(?:(\d)|(i{1,3}|iv))\s*(?:(?:nam|/|-)\s*(\d{4}|\d{2}))?(?!\d)", s):
        q = int(m.group(1)) if m.group(1) else {"i": 1, "ii": 2, "iii": 3, "iv": 4}[m.group(2)]
        if 1 <= q <= 4:
            if m.group(3):
                y = int(m.group(3))
                y = y + 2000 if y < 100 else y
            else:
                y = as_of.year if dt.date(as_of.year, 3 * (q - 1) + 1, 1) <= as_of else as_of.year - 1
            put(m, "abs", "quarter", dt.date(y, 3 * (q - 1) + 1, 1), _month_end(y, 3 * q), q=q, y=y, explicit_year=bool(m.group(3)))
    # --- tháng M/Y ; tháng M năm Y ; tháng M (không năm) ---
    for m in re.finditer(r"\bthang\s*(\d{1,2})(?!\d)(?:\s*(?:nam|/|-)\s*(\d{4}|\d{2})(?!\d))?", s):
        mo = int(m.group(1))
        if not 1 <= mo <= 12:
            continue
        if m.group(2):
            y = int(m.group(2))
            y = y + 2000 if y < 100 else y
        else:
            y = _year_guess(as_of, mo)
        put(m, "abs", "month", dt.date(y, mo, 1), _month_end(y, mo), explicit_year=bool(m.group(2)))
    for m in re.finditer(r"(?<![\d/.\-])(\d{1,2})\s*/\s*(20\d\d)(?![\d/])", s):  # '2/2025' không ghi chữ 'tháng'
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            put(m, "abs", "month", dt.date(y, mo, 1), _month_end(y, mo), explicit_year=True)
    if ENABLE_SHORT_MONTH_YEAR:  # '8/26', '10/25': tháng/năm 2 chữ số (năm phải >= 13 để không lẫn với ngày/tháng)
        for m in re.finditer(r"(?<![\d/.\-])(\d{1,2})\s*/\s*(\d{2})(?![\d/])", s):
            mo, yy = int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12 and 20 <= yy <= 40:
                y = 2000 + yy
                put(m, "abs", "month", dt.date(y, mo, 1), _month_end(y, mo), explicit_year=True)
    # --- ngày cụ thể ---
    for m in re.finditer(r"(?<![\d/.\-])(?:ngay\s*)?(\d{1,2})\s*/\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{4}|\d{2}))?(?![\d/])", s):
        d_ = _date_from(m.group(1), m.group(2), m.group(3), as_of)
        if d_:
            put(m, "abs", "date", d_, d_, semantics="within")
    for m in re.finditer(r"(?<![\d/.\-])(\d{1,2})\s*[\-.]\s*(\d{1,2})\s*[\-.]\s*(\d{4})(?![\d])", s):
        d_ = _date_from(m.group(1), m.group(2), m.group(3), as_of)
        if d_:
            put(m, "abs", "date", d_, d_, semantics="within")
    # --- [vá] "năm 2025" đứng riêng = cả năm (tháng/quý/Tết có năm đã được bắt ở trên) ---
    for m in re.finditer(r"\bnam\s*(20\d\d)\b", s):
        y = int(m.group(1))
        put(m, "abs", "year", dt.date(y, 1, 1), dt.date(y, 12, 31), semantics="within")
    # --- tham chiếu "kỳ trước" (dùng khi so sánh; nếu đứng một mình thì là kỳ chính tính từ hôm nay) ---
    for m in re.finditer(r"\bcung\s*(?:thang|quy|tuan|ngay)\s*(?:cua\s*)?nam\s*(?:truoc|ngoai|roi)\b", s):   # [vá]
        put(m, "prev_ref", "prev_ref", None, None, how="last_year", unit="nam", cung_ky=True)
    for m in re.finditer(r"\bcung\s*ky(?:\s*(thang|tuan|quy|nam)\s*(?:truoc|ngoai|roi))?", s):
        unit = m.group(1)
        how = "last_year" if unit == "nam" else "prev"
        put(m, "prev_ref", "prev_ref", None, None, how=how, unit=unit, cung_ky=True)
    for m in re.finditer(r"\b(ky\s*truoc|lien\s*truoc|truoc\s*do)\b", s):
        put(m, "prev_ref", "prev_ref", None, None, how="prev", unit=None)
    for m in re.finditer(r"\bthang\s*(?:truoc|roi|vua\s*roi|lien\s*truoc)\b(\s*nua\b)?", s):
        put(m, "prev_ref", "prev_ref", None, None, how="prev", unit="thang", nua=bool(m.group(1)))   # [vá] "trước nữa"
    for m in re.finditer(r"\btuan\s*(?:truoc|roi|vua\s*roi|lien\s*truoc)\b(\s*nua\b)?", s):
        put(m, "prev_ref", "prev_ref", None, None, how="prev", unit="tuan", nua=bool(m.group(1)))   # [vá] "trước nữa"
    for m in re.finditer(r"\bquy\s*(?:truoc|roi|vua\s*roi|lien\s*truoc)\b(\s*nua\b)?", s):
        put(m, "prev_ref", "prev_ref", None, None, how="prev", unit="quy", nua=bool(m.group(1)))   # [vá] "trước nữa"
    for m in re.finditer(r"\bnam\s*(?:ngoai|truoc|roi)\b", s):
        put(m, "prev_ref", "prev_ref", None, None, how="prev", unit="nam")
    # --- kỳ tính từ hôm nay ---
    for m in re.finditer(r"\bthang\s*nay\b", s):
        put(m, "now", "month_to_date", as_of.replace(day=1), as_of, semantics="within")
    for m in re.finditer(r"\btuan\s*nay\b", s):
        put(m, "now", "week_to_date", as_of - dt.timedelta(days=as_of.weekday()), as_of, semantics="within")
    for m in re.finditer(r"\bquy\s*nay\b", s):
        q0 = 3 * ((as_of.month - 1) // 3) + 1
        put(m, "now", "quarter_to_date", dt.date(as_of.year, q0, 1), as_of, semantics="within", note="giả định: quý này tính đến hết hôm nay (rulebook không nêu)")
    for m in re.finditer(r"\bnam\s*nay\b", s):
        put(m, "now", "ytd", ytd_start, as_of, semantics="within", note="giả định: năm nay tính từ 01/01 đến hết hôm nay")
    for m in re.finditer(r"\btu\s*dau\s*(nam|thang|tuan)\b", s):
        u = m.group(1)
        st = {"nam": ytd_start, "thang": as_of.replace(day=1), "tuan": as_of - dt.timedelta(days=as_of.weekday())}[u]
        put(m, "now", {"nam": "ytd", "thang": "month_to_date", "tuan": "week_to_date"}[u], st, as_of, semantics="within")
    for m in re.finditer(r"\bhom\s*(nay|qua|kia)\b", s):
        off = {"nay": 0, "qua": 1, "kia": 2}[m.group(1)]
        d_ = as_of - dt.timedelta(days=off)
        put(m, "now", "day", d_, d_, semantics="within")
    exs.sort(key=lambda e: e["pos"])
    return exs


def _tet_period(arg, as_of, calendar, rel_to=None):
    if arg and arg.isdigit():
        y = int(arg)
    elif arg in ("ngoai", "truoc"):
        y = (rel_to if rel_to else as_of.year) - 1 if rel_to else as_of.year - 1
    else:
        y = rel_to if rel_to else as_of.year
        w = tet_window(y, calendar)
        if not arg and w and w[0] > as_of:
            y -= 1
    w = tet_window(y, calendar)
    return (y, w) if w else (y, None)


def _shift(p, how, as_of, calendar=None):
    """Kỳ trước / cùng kỳ năm trước của p. Trả dict (kind, start, stop, meta) hoặc None."""
    k, s0, e0 = p["kind"], p["start"], p["stop"]
    meta = dict(p["meta"])
    if k in ("month", "month_to_date"):
        y, m = s0.year, s0.month
        if how == "last_year":
            ny, nm = y - 1, m
        else:
            ny, nm = _add_months(y, m, -1)
        end = _month_end(ny, nm) if k == "month" else _clamp(ny, nm, e0.day)
        return _mk(k, dt.date(ny, nm, 1), end, **meta)
    if k in ("quarter", "quarter_to_date"):
        q0 = s0.month
        if how == "last_year":
            ns = dt.date(s0.year - 1, q0, 1)
        else:
            ny, nm = _add_months(s0.year, q0, -3)
            ns = dt.date(ny, nm, 1)
        if k == "quarter":
            ny2, nm2 = _add_months(ns.year, ns.month, 2)
            return _mk(k, ns, _month_end(ny2, nm2), **meta)
        off = (e0 - s0).days
        ny2, nm2 = _add_months(ns.year, ns.month, 2)
        return _mk(k, ns, min(ns + dt.timedelta(days=off), _month_end(ny2, nm2)), **meta)
    if k in ("year", "ytd"):
        return _mk(k, dt.date(s0.year - 1, s0.month, s0.day), _clamp(e0.year - 1, e0.month, e0.day), **meta)
    if k in ("week", "week_to_date"):
        return _mk(k, s0 - dt.timedelta(days=7), e0 - dt.timedelta(days=7), **meta)
    if k in ("day", "date"):
        if how == "last_year":
            d_ = _clamp(s0.year - 1, s0.month, s0.day)
        else:
            d_ = s0 - dt.timedelta(days=1)
        return _mk("day", d_, d_, **meta)
    if k == "tet":
        y = meta.get("y")
        if y:
            w = tet_window(y - 1, calendar)
            if w:
                m2 = dict(meta)
                m2["y"] = y - 1
                return _mk("tet", w[0], w[1], **m2)
        return None
    if k in ("rolling", "range", "fwd_window"):
        L = (e0 - s0).days + 1
        if how == "last_year":
            return _mk(k, _clamp(s0.year - 1, s0.month, s0.day), _clamp(e0.year - 1, e0.month, e0.day), **meta)
        return _mk(k, s0 - dt.timedelta(days=L), s0 - dt.timedelta(days=1), **meta)
    return None


def _rel_primary(e, as_of):
    """Kỳ chính khi biểu thức 'tháng trước/tuần rồi/quý trước/năm ngoái' đứng một mình (tính từ hôm nay)."""
    u = e["meta"].get("unit")
    k = 2 if e["meta"].get("nua") else 1          # [vá] "tháng/tuần/quý trước nữa" lùi 2 kỳ
    if u == "thang":
        y, m = _add_months(as_of.year, as_of.month, -k)
        return _mk("month", dt.date(y, m, 1), _month_end(y, m))
    if u == "tuan":
        mon = as_of - dt.timedelta(days=as_of.weekday() + 7 * k)
        return _mk("week", mon, mon + dt.timedelta(days=6))
    if u == "quy":
        q0 = 3 * ((as_of.month - 1) // 3) + 1
        y, m = _add_months(as_of.year, q0, -3 * k)
        return _mk("quarter", dt.date(y, m, 1), _month_end(*_add_months(y, m, 2)))
    if u == "nam":
        return _mk("year", dt.date(as_of.year - 1, 1, 1), dt.date(as_of.year - 1, 12, 31))
    return None


_CMP_RE = re.compile(r"\bso\s*(?:voi|vs|cung|\d+\s*ngay|thang|tuan|quy|hom|tet|ca)\b|\bvs\b|\bcung\s*ky\b|\bhon\s*hay\s*kem\b|\bhon\s*kem\b|\btang\s*hay\s*giam\b")
_PCT_RE = re.compile(r"(?<!\d)(?<!\d )(?:%|phan\s*tram)|tang\s*truong|thay\s*doi\s*bao\s*nhieu|chenh\s*lech\s*bao\s*nhieu")
_GROWTH_RE = re.compile(r"\b(?:tang|giam(?!\s*dau)|thay\s*doi|chenh(?:\s*lech)?|tang\s*truong|hon|kem)\b")  # 'tỉ lệ … bao nhiêu phần trăm' KHÔNG phải so sánh kỳ
_CUE_RE = re.compile(
    r"\bthang\s*\d|\bthang\s*(?:nay|truoc|roi)|\btuan\s*(?:nay|truoc|roi)|\bquy\s*(?:\d|nay|truoc)|\bnam\s*(?:nay|ngoai|truoc|20\d\d)|"
    r"\bhom\s*(?:nay|qua|kia)|\btet\b|\bngay\s*\d|\d{1,2}/\d{1,2}|gan\s*nhat|den\s*het|\bhet\s*(?:ngay|hom)|\bdau\s*(?:thang|nam|tuan)|"
    r"ke\s*tu|\d+\s*ngay\s*dau|cung\s*ky|ky\s*truoc|gan\s*day|ngay\s*(?:qua|toi)|\d\s*(?:ngay|tuan)\s*(?:qua|toi)")


def _fmt(p, label, **extra):
    d = {"label": label, "start": p["start"].isoformat() if p["start"] else None,
         "end": p["stop"].isoformat() if p["stop"] else None, "kind": p["kind"]}
    for k in ("semantics", "note", "n", "needs_data", "reason"):
        if p["meta"].get(k) is not None:
            d[k] = p["meta"][k]
    d.update(extra)
    return d


# [vá 8] viết lại vài cách nói đồng nghĩa về dạng module đã hiểu (chỉ trên chuỗi thời gian, không đổi câu hỏi)
_RW8 = [
    # v3: 'M-YYYY' đứng một mình (không chữ 'tháng'): '6-2025 …', '12-2025', 'từ 2-2025 đến 4-2025' = tháng M/YYYY
    (r"(?<![\d\-/.])(?<!thang )(?<!thang)(?<!th )(?<!ngay )(\d{1,2})\s*-\s*(20\d{2})(?![\d\-/])", r"thang \1/\2"),
    # "chừ" (miền Trung) = "giờ"
    (r"\b(?:bay\s*)?chu\b(?=\s*(?:$|[,.?!]|quan|tiem|shop|cua|ban|duoc|thu|co|la|ro|vay|z|ha|a)\b|\s*$)", "gio"),
    # "từ mùng 1 (tháng này) tới (hết) hôm nay" = từ đầu tháng tới hết hôm nay
    (r"\btu\s*(?:mung|mong|ngay)\s*(?:1|mot)\b(?:\s*thang\s*nay)?(?=\s*(?:den|toi)\s*(?:het\s*)?(?:hom\s*nay|nay|gio)\b)", "tu dau thang"),
    # "đầu năm/tháng/tuần tới ..." thiếu chữ "từ" -> thêm "từ"; "từ đầu năm tới giờ" = từ đầu năm đến hết hôm nay
    (r"(?<!tu )\bdau\s*(nam|thang|tuan)(?=(?:\s*nay)?\s*(?:den|toi)\b)", r"tu dau \1"),
    (r"\btu\s*dau\s*(nam|thang|tuan)(?:\s*nay)?\s*(?:den|toi)\s*(?:het\s*)?(?:bay\s*gio|gio)\b", r"tu dau \1 den het hom nay"),
    # "tháng/năm/tuần/quý này tính tới (hết) hôm nay" = tháng/năm... này (đã là tới hôm nay)
    (r"(?<!\d )(?<!\d)(?<!dau )\b(thang|th|nam|tuan|quy)\s*nay\s*(?:tinh\s*)?(?:den|toi)\s*(?:het\s*)?(?:hom\s*nay|bay\s*gio|gio)\b", r"\1 nay"),
    # "cùng số ngày đầu tháng trước/rồi" = cùng kỳ tháng trước
    (r"\bcung\s*so\s*ngay\s*dau\s*(?:thang|th)\s*(?:truoc|roi|trc)\b", "cung ky thang truoc"),
    # "giữa tháng 1, tháng 2 và tháng 3" = trong các tháng (không phải giữa tháng)
    (r"\bgiua\s*(?=(?:thang|th)\s*\d{1,2}(?:\s*/\s*\d{2,4})?\s*(?:,|\bva\b|\bvoi\b)\s*(?:(?:thang|th)\s*)?\d)", "trong "),
    # "N ngày từ bữa/hôm đó" = N ngày kể từ ngày đó
    (r"\b(\d{1,3})\s*ngay\s*tu\s*(?:bua|hom|ngay)\s*(?:do|ay)\b", r"\1 ngay ke tu ngay do"),
    # "N tháng liền nhau tính tới (tháng) M-YYYY" = N tháng liền nhau kết thúc ở tháng M/YYYY
    (r"\b(thang\s*(?:lien\s*nhau|lien\s*tiep|lien))\s*(?:tinh\s*)?(?:den|toi)\s*(?:het\s*)?(?:thang\s*|th\s*)?(\d{1,2})\s*[/\-]\s*(\d{4})\b", r"\1 ket thuc o thang \2/\3"),
]


def _rewrite_time(s):
    for rx, rep in _RW8:
        s = re.sub(rx, rep, s)
    return s


def resolve_time_ex(text, as_of_date, calendar=None):
    """Như resolve_time nhưng trả thêm thông tin chẩn đoán: (periods, info)."""
    as_of = as_of_date if isinstance(as_of_date, dt.date) else dt.date.fromisoformat(str(as_of_date)[:10])
    norm, _ = normalize_text(text)
    s = _rewrite_time(_time_text(norm))     # [vá 8]
    cues = sorted(set(m.group(0).strip() for m in _CUE_RE.finditer(s)))
    exs = _extract(s, as_of, calendar)
    pct = bool(_PCT_RE.search(s)) and bool(_GROWTH_RE.search(s))
    cmp_ = bool(_CMP_RE.search(s))

    # ca sáng / ca chiều
    has_sang, has_chieu = bool(re.search(r"\bca\s*sang\b", s)), bool(re.search(r"\bca\s*chieu\b", s))

    non_ref = [e for e in exs if e["role"] in ("abs", "now")]
    refs = [e for e in exs if e["role"] == "prev_ref"]
    backs = [e for e in exs if e["role"] == "back"]
    pre_tets = [e for e in exs if e["role"] == "pre_tet"]

    # Tết: tính cửa sổ
    for e in non_ref:
        if e["kind"] == "tet":
            rel = None
            prev_tet = [x for x in non_ref if x["kind"] == "tet" and x["pos"] < e["pos"] and x["start"]]
            if e["meta"].get("arg") in ("ngoai", "truoc") and prev_tet:
                rel = prev_tet[-1]["meta"]["y"]
            y, w = _tet_period(e["meta"].get("arg"), as_of, calendar, rel_to=rel)
            e["meta"]["y"] = y
            if w:
                e["start"], e["stop"] = w
            else:
                e["kind"], e["meta"]["reason"] = "unresolved", "không tìm thấy Tết trong calendar.csv"

    # [vá] "cuối ngày hôm nay / cuối ngày X" (tồn kho, công nợ) = mốc cuối ngày, giống "đến hết ngày X"
    # Rulebook: mốc cuối ngày chỉ dùng cho câu hỏi SỐ CÒN LẠI (tồn, nợ, còn hàng); câu hỏi phát sinh (doanh thu, số đơn,
    # bán được, giá bán) thì vẫn là "trong ngày đó" dù có chữ "cuối ngày".
    _FLOW = r"\bdoanh\s*thu\b|\bdthu\b|\bso\s*don\b|\bban\s*(?:duoc|ra)\b|\bgia\s*ban\b|\bthu\s*duoc\b"
    if re.search(r"\bcuoi\s*(?:ngay|hom\s*nay)\b", s) and not re.search(r"\btu\s*(?:ngay\s*)?\d|\btu\s*dau\b", s) \
            and not re.search(_FLOW, s):
        for e in non_ref:
            if e["kind"] in ("day", "date") and e["start"] and e["start"] == e["stop"]:
                e["start"], e["kind"] = None, "snapshot"
                e["meta"]["semantics"] = "snapshot_end"

    # [vá 6] Việt chọn 05/11: câu hỏi SỐ CÒN LẠI (tồn kho, còn nợ, còn hàng) đi với một kỳ (tháng/quý/năm/tuần/Tết)
    # = mốc CUỐI kỳ, tính từ đầu dữ liệu (giống "đến hết ngày X"). Kỳ chưa hết (tháng này...) thì mốc là hôm nay.
    # Không áp khi câu có "từ ... đến ..." hoặc có hỏi phát sinh (bán, nhập, doanh thu).
    _STOCK = r"\bton\s*kho\b|\bcon\s*(?:ton|no|lai|hang|bao\s*nhieu|may)\b|\bcong\s*no\b|\bdang\s*no\b|\bhet\s*hang\b|\bcon\s*\S+\s*trong\s*kho\b"
    _FLOW2 = _FLOW + r"|\bnhap\b|\bban\b|\bxuat\b|\bthu\b|\bchi\b"
    if re.search(_STOCK, s) and not re.search(_FLOW2, s) and not re.search(r"\btu\s*(?:ngay\s*)?\d|\btu\s*dau\b", s):
        for e in non_ref:
            if e["kind"] in ("month", "quarter", "year", "week", "tet", "month_to_date", "quarter_to_date", "week_to_date", "ytd") and e["stop"]:
                e["stop"] = min(e["stop"], as_of)
                e["start"], e["kind"] = None, "snapshot"
                e["meta"]["semantics"] = "snapshot_end"
                e["meta"]["note"] = "số còn lại: mốc cuối kỳ (rulebook, Việt chốt)"

    # hiệu ứng tăng giá: N ngày kể từ ngày tăng giá -> kỳ chính; ngày đơn lẻ trong câu chính là mốc tăng giá
    fw = [e for e in non_ref if e["kind"] == "fwd_window"]
    if fw:
        dates = [e for e in non_ref if e["kind"] == "date" and e["start"]]
        for e in fw:
            if e["start"] is None and dates:
                e["start"] = dates[0]["start"]
            if e["start"] is None:
                e["meta"]["needs_data"] = "price_increase_date"
            else:
                e["stop"] = e["start"] + dt.timedelta(days=e["meta"]["n"] - 1)
        non_ref = fw + [e for e in non_ref if e["kind"] not in ("fwd_window", "date")]

    periods = []
    unresolved = [e for e in non_ref if e["kind"] == "unresolved"]
    non_ref = [e for e in non_ref if e["kind"] != "unresolved"]
    if backs and not fw and not any(e["kind"] == "fwd_window" for e in non_ref):   # [vá 3] "3 ngày trước" = 1 ngày hay 3 ngày?
        unresolved += [dict(b, meta=dict(b["meta"], reason="N ngày trước, không có mốc")) for b in backs if b["start"] is None]
    # [vá 5] câu hỏi PHÁT SINH (doanh thu, số đơn...) + "tính đến / đến hết X" mà không có "từ ...": rulebook chỉ định nghĩa
    # cho câu hỏi số còn lại; với phát sinh thì không rõ cộng dồn từ đầu dữ liệu hay chỉ ngày X -> bỏ qua (0 điểm), không đoán.
    if re.search(_FLOW, s) and re.search(r"\b(?:tinh\s*(?:den|toi)|(?:den|toi)\s*het)\b", s) \
            and not re.search(r"\btu\s*(?:ngay\s*)?\d|\btu\s*(?:dau|hom|nay|thu|thang|tuan|quy|nam)\b", s):
        unresolved.append({"meta": {"reason": "phát sinh + tính đến: không rõ cộng dồn hay 1 ngày"}})

    primary = non_ref[0] if non_ref else None
    if primary is None and refs:
        for r in refs:
            if r["meta"].get("cung_ky"):      # [vá 3] "cùng kỳ năm trước" chỉ là kỳ so sánh, không tự làm kỳ chính
                continue
            pp = _rel_primary(r, as_of)
            if pp:
                pp.update({"pos": r["pos"], "role": "now", "span": r["span"]})
                primary, refs = pp, [x for x in refs if x is not r]
                break

    if primary is not None:
        if primary["kind"] == "fwd_window" and primary["start"] is None:  # cần dữ liệu để biết ngày tăng giá
            p0 = _fmt(primary, "ky_nay", needs_data="price_increase_date", n=primary["meta"]["n"])
            periods.append(p0)
            if backs:
                periods.append({"label": "ky_truoc", "start": None, "end": None, "kind": "back_window",
                                "needs_data": "price_increase_date", "n": backs[0]["meta"]["n"]})
        else:
            periods.append(_fmt(primary, "ky_nay"))
            ref = None
            note = None
            second = [e for e in non_ref[1:] if e["role"] in ("abs", "now")]
            if primary["kind"] == "fwd_window" and backs:
                n = backs[0]["meta"]["n"]
                ref = _mk("back_window", primary["start"] - dt.timedelta(days=n), primary["start"] - dt.timedelta(days=1), n=n)
            elif pre_tets and primary["kind"] == "tet":
                n = pre_tets[0]["meta"]["n"]
                ref = _mk("pre_tet", primary["start"] - dt.timedelta(days=n), primary["start"] - dt.timedelta(days=1), n=n)
            elif second and (cmp_ or pct) and not (primary["kind"] == "tet" and second[0]["kind"] != "tet"):
                ref = second[0]
            elif refs:
                r = refs[0]
                how = r["meta"].get("how", "prev")
                ref = _shift(primary, how, as_of, calendar)
            elif pct and primary["kind"] not in ("snapshot", "fwd_window", "forward_days"):
                ref = _shift(primary, "prev", as_of, calendar)
                note = "ngầm hiểu: so với kỳ trước (rulebook)"
            if ref is not None:
                periods.append(_fmt(ref, "ky_truoc", **({"note": note} if note else {})))
            extra = [e for e in non_ref[1:] if ref is not e and e["role"] in ("abs", "now")]
            for e in extra:
                if not any(p["start"] == (e["start"].isoformat() if e["start"] else None) and p["end"] == (e["stop"].isoformat() if e["stop"] else None) for p in periods):
                    periods.append(_fmt(e, "ky_khac"))

    # [vá] "từ tháng X đến/tới tháng Y" = đủ các tháng ở giữa; "N tháng liền nhau kết thúc ở tháng X"
    months = [e for e in exs if e["kind"] == "month" and e["start"]]
    m_rng = re.search(r"\btu\s*thang\s*\d[^,;?]*?\b(?:den|toi)\s*(?:het\s*)?thang\s*\d", s)
    m_n = re.search(r"\b" + _NUMW + r"\s*thang\s*(?:lien\s*nhau|lien\s*tiep|lien)\s*(?:ket\s*thuc|cuoi\s*cung)\s*(?:o|vao|tai|la)?\s*thang\s*\d", s)
    chain = None
    if m_rng and len(months) >= 2:
        a, b = months[0]["start"], months[1]["start"]
        n = (b.year * 12 + b.month) - (a.year * 12 + a.month) + 1
        chain = (a.year, a.month, n)
    elif m_n:
        n, last = _nval(m_n.group(1)), [e for e in months if e["pos"] >= m_n.start()]
        if n and last:
            b = last[0]["start"]
            chain = _add_months(b.year, b.month, -(n - 1)) + (n,)
    if chain and 2 <= chain[2] <= 24:
        periods = []
        for k in range(chain[2]):
            y, mo = _add_months(chain[0], chain[1], k)
            periods.append({"label": "ky_%d" % (k + 1), "start": dt.date(y, mo, 1).isoformat(),
                            "end": _month_end(y, mo).isoformat(), "kind": "month_in_range"})

    # ca làm việc
    if periods and (has_sang or has_chieu):
        if has_sang and has_chieu:
            base = periods[0]
            ca_c = dict(base, time_start=CA_CHIEU[0], time_end=CA_CHIEU[1], label="ky_nay", note="ca chiều")
            ca_s = dict(base, time_start=CA_SANG[0], time_end=CA_SANG[1], label="ky_truoc", note="mốc là ca sáng (rulebook)")
            periods = [ca_c, ca_s] + [dict(p) for p in periods[1:] if p["label"] == "ky_khac"]
        else:
            ts, te = CA_SANG if has_sang else CA_CHIEU
            for p in periods:
                p["time_start"], p["time_end"] = ts, te

    if unresolved:          # [vá 3] có một cụm thời gian không hiểu -> bỏ qua cả câu, không trả kỳ nửa vời
        periods = []
    info = {"cues": cues, "unresolved": [e["meta"].get("reason") for e in unresolved], "text_time": s}
    resolved_any = bool(periods)
    info["time_failed"] = bool(cues or unresolved) and not resolved_any
    return periods, info


def resolve_time(text, as_of_date, calendar=None):
    return resolve_time_ex(text, as_of_date, calendar)[0]


# ═════════════════════════ 5. CỜ Ý ĐỊNH ═════════════════════════
def extract_flags(text):
    f = fold(normalize_text(text)[0])
    low = str(text).lower()
    pct = bool(re.search(r"%|phan\s*tram|\bmay\s*%|bao\s*nhieu\s*%", f + " " + low))
    f_nt = re.sub(r"\bgan\s*nhat\b", " ", f)  # 'gần nhất' là thời gian, không phải 'nhất' xếp hạng
    return {
        "so_sanh": bool(_CMP_RE.search(f)) or bool(re.search(r"\b(?:hon|kem|cao\s*hon|thap\s*hon|tang|giam)\b", f)),
        "tang_truong_pct": pct and bool(re.search(r"tang|giam|thay\s*doi|chenh|hon|kem|tang\s*truong|so\s*voi|so\s*vs|\bvs\b", f)),
        "top1": bool(re.search(r"\b(?:nhat|nhieu\s*nhat|cao\s*nhat|thap\s*nhat|lon\s*nhat|it\s*nhat)\b", f_nt)),
        "topk": bool(re.search(r"\btop\s*\d+|\b\d+\s*(?:mat\s*hang|san\s*pham|khach|mon|nhan\s*vien)\b.*\bnhat\b", f_nt)),
        "can_gia_von": bool(re.search(r"gia\s*von|lai\s*gop|lai\s*rong|loi\s*nhuan|\blai\b|bien\s*loi", f)),
        "ca_lam": bool(re.search(r"\bca\s*(?:sang|chieu)\b", f)),
        "no_cong_no": bool(re.search(r"\bno\b|con\s*no|cong\s*no|ghi\s*no|tuoi\s*no|tra\s*no|thu\s*no", f)),
        "ton_kho_han_dung": bool(re.search(r"ton\s*kho|con\s*ton|het\s*hang|han\s*dung|het\s*han|can\s*date|con\s*hang", f)),
        "ty_le_ty_trong": bool(re.search(r"ty\s*le|ty\s*trong|chiem\s*bao\s*nhieu", f)),
        "trung_binh": bool(re.search(r"trung\s*binh|binh\s*quan", f)),
        "gio_cao_diem": bool(re.search(r"gio\s*cao\s*diem|khung\s*gio|may\s*gio", f)),
    }


# ═════════════════════════ 6. HÀM CHÍNH ═════════════════════════
def normalize_question(raw_question, as_of_date, calendar=None, protect=None):
    text_norm, text_ascii = normalize_text(raw_question, protect=protect)
    periods, info = resolve_time_ex(raw_question, as_of_date, calendar)
    return {
        "raw": raw_question,
        "as_of_date": str(as_of_date)[:10],
        "text_norm": text_norm,
        "text_ascii": text_ascii,
        "amounts": parse_amounts(raw_question),
        "numbers": parse_numbers(raw_question),
        "periods": periods,
        "flags": extract_flags(raw_question),
        "time_failed": info["time_failed"],
        "time_cues": info["cues"],
    }


# ═════════════════════════ 7. ĐÁNH GIÁ & KIỂM THỬ ═════════════════════════
def _same_periods(got, exp):
    """exp: list [label, start, end] hoặc [label, start, end, time_start, time_end]. So đúng thứ tự."""
    if len(got) != len(exp):
        return False
    for g, e in zip(got, exp):
        if (g["label"], g["start"], g["end"]) != (e[0], e[1], e[2]):
            return False
        if len(e) >= 5 and (g.get("time_start"), g.get("time_end")) != (e[3], e[4]):
            return False
    return True


def evaluate_gold(gold, calendar=None):
    """gold: list [nhóm, câu hỏi, as_of, [kỳ mong đợi]]. Trả (bảng theo nhóm, danh sách sai)."""
    by_group, fails = {}, []
    for g in gold:
        group, q, as_of, exp = g[0], g[1], g[2], g[3]
        r = normalize_question(q, as_of, calendar)
        if group == "khong_hieu":      # câu có từ khoá thời gian mà luật chưa định nghĩa: phải báo time_failed
            ok = not r["periods"] and r["time_failed"]
        else:
            ok = _same_periods(r["periods"], exp) and not r["time_failed"]
        a = by_group.setdefault(group, [0, 0])
        a[1] += 1
        a[0] += int(ok)
        if not ok:
            fails.append({"nhom": group, "cau_hoi": q, "as_of": as_of, "mong_doi": exp,
                          "ra": [[p["label"], p["start"], p["end"]] for p in r["periods"]], "time_failed": r["time_failed"]})
    return by_group, fails


def time_cue_report(questions, calendar=None):
    """Mỗi câu 1 dòng: có từ khoá thời gian không, ra mấy kỳ, có bị time_failed không. questions: list dict {question, as_of_date[, id]}."""
    rows = []
    for q in questions:
        r = normalize_question(q["question"], q["as_of_date"], calendar)
        rows.append({
            "id": q.get("id"), "as_of": q["as_of_date"], "cau_hoi": q["question"], "co_tu_khoa_thoi_gian": bool(r["time_cues"]),
            "so_ky": len(r["periods"]), "time_failed": r["time_failed"],
            "cac_ky": " | ".join("%s %s→%s [%s]" % (p["label"], p["start"], p["end"], p["kind"]) for p in r["periods"]),
            "tu_khoa": ", ".join(r["time_cues"]),
        })
    return rows


_AMOUNT_TESTS = [
    ("lọc đơn từ 3tr7 trở lên", [("3tr7", 3700000, "vnd")]),
    ("đơn từ 290.000 đồng trở lên", [("290.000 đồng", 290000, "vnd")]),
    ("trên 55k", [("55k", 55000, "vnd")]),
    ("giá 1,5 triệu", [("1,5 triệu", 1500000, "vnd")]),
    ("2k5 một ly", [("2k5", 2500, "vnd")]),
    ("tăng 12,5%", [("12,5%", 12.5, "percent")]),
    ("bán được 2 trà sữa", []),
    ("top 5 trong số hàng bán chạy", []),
    ("bán 5kg gạo", []),
    ("hộp 500ml 10k", [("10k", 10000, "vnd")]),
    ("lên giá 103.000đ từ ngày 14/11/2025", [("103.000đ", 103000, "vnd")]),
    ("tháng 5/2026 có 30 đơn", []),
]
_TEXT_TESTS = [
    ("dthu hôm nay là bnhiu?", "doanh thu hôm nay là bao nhiêu?"),
    ("vitamin k bán được mấy hộp", "vitamin k bán được mấy hộp"),
    ("ko bán dc cái nào", "không bán được cái nào"),
    ("th5/2026 shop mik bn don", "tháng 5/2026 shop mình bao nhiêu don"),
    ("k bán dc cái nào", "không bán được cái nào"),
    ("bán điện thoại dt samsung", "bán điện thoại dt samsung"),
]


def run_tests(verbose=True):
    """Kiểm thử đơn vị + quét ngày (biên năm, tháng 2, năm nhuận). Trả True nếu đạt hết."""
    bad, total = 0, 0

    def check(name, got, want):
        nonlocal bad, total
        total += 1
        if got != want:
            bad += 1
            print("SAI", name, "→", got, "(mong", want, ")")

    for t, want in _AMOUNT_TESTS:
        got = [(a["span"], a["value"], a["unit"]) for a in parse_amounts(t) if a["unit"] != "number"]
        check("tiền: " + t, got, want)
    for t, want in _TEXT_TESTS:
        check("văn bản: " + t, normalize_text(t)[0], want)
    global ENABLE_SHORT_MONTH_YEAR
    old = ENABLE_SHORT_MONTH_YEAR
    ENABLE_SHORT_MONTH_YEAR = False            # [vá 4] test trạng thái tắt phải tự tắt trước
    check("M/YY tắt -> time_failed", resolve_time_ex("doanh thu 8/26", "2026-09-19")[1]["time_failed"], True)
    ENABLE_SHORT_MONTH_YEAR = True
    check("M/YY bật", [(p["start"], p["end"]) for p in resolve_time("doanh thu 8/26", "2026-09-19")], [("2026-08-01", "2026-08-31")])
    check("M/YY bật không nuốt ngày/tháng", [(p["start"], p["end"]) for p in resolve_time("bán ngày 3/12", "2026-09-19")], [("2025-12-03", "2025-12-03")])
    check("M/YY bật: th10/25", [(p["start"], p["end"]) for p in resolve_time("dthu th10/25 bn", "2026-09-19")], [("2025-10-01", "2025-10-31")])   # [vá 4]
    check("M/YY bật: 15/08 vẫn là ngày", [(p["start"], p["end"]) for p in resolve_time("bán ngày 15/08", "2026-09-19")], [("2026-08-15", "2026-08-15")])
    ENABLE_SHORT_MONTH_YEAR = old
    global VOCAB
    old_v = VOCAB
    VOCAB = {"tiền", "hàng", "là", "số", "đơn", "bán", "tháng", "được", "nhiêu", "hôm", "tôi", "tổng", "biết", "giùm", "nào", "vậy", "nhóm", "cửa", "khách"}
    for t, want in [("tieenf", "tiền"), ("hangf", "hàng"), ("laf", "là"), ("soos", "số"), ("ddown", "đơn"), ("bans", "bán"), ("thangs", "tháng"),
                    ("dduwowcj", "được"), ("nhieeu", "nhiêu"), ("hoom", "hôm"), ("tooi", "tôi"), ("toongr", "tổng"), ("bieets", "biết"),
                    ("giumf", "giùm"), ("naof", "nào"), ("vaayj", "vậy"), ("nhoms", "nhóm"), ("cuwar", "cửa"), ("khachs", "khách")]:
        check("telex " + t, telex_decode(t), want)
    check("telex không đoán từ lạ", telex_decode("redbull"), None)
    check("telex không đổi tên riêng 'Max'", normalize_text("bán Plusssz Max hộp")[0], "bán Plusssz Max hộp")
    check("telex không đổi từ đã đúng", telex_decode("tiền"), None)
    check("telex trong câu", normalize_text("tieenf hangf laf bao nhieeu")[0], "tiền hàng là bao nhiêu")
    VOCAB = old_v
    f = extract_flags("30 ngày gần nhất hàng nào bán chạy")
    check("cờ top1 không bật vì 'gần nhất'", f["top1"], False)
    check("cờ %", extract_flags("tăng bao nhiêu % so với tháng trước")["tang_truong_pct"], True)
    check("cờ top1", extract_flags("mặt hàng nào bán chạy nhất")["top1"], True)

    # [vá] kiểm thử cho các điểm chuyển từ bản Việt (as_of 2026-03-10 là thứ Ba)
    for q, a, want in [
        ("Tồn kho cuối ngày hôm nay còn bao nhiêu chai?", "2026-03-10", [(None, "2026-03-10")]),
        ("tồn kho Telfast cuối ngày 14/02/2026 là bao nhiêu", "2026-03-10", [(None, "2026-02-14")]),
        ("hnay kho còn tồn bnhiu hộp lúc cuối ngày", "2026-03-10", [(None, "2026-03-10")]),
        ("xem giúp tồn cuối bữa nay của amoxicillin là mấy vỉ", "2026-03-10", [(None, "2026-03-10")]),
        ("Đến cuối ngày 12/02/2026, shop có mấy mặt hàng đang hết hàng?", "2026-03-10", [(None, "2026-02-12")]),
        ("doanh thu cuối ngày hôm nay là bao nhiêu", "2026-03-10", [("2026-03-10", "2026-03-10")]),
        ("tính đến cuối ngày hôm qua bán được mấy đơn", "2026-03-10", []),          # [vá 5] Việt: không rõ -> bỏ qua
        # [vá 9] "sau hôm nay" không phải "sáu hôm nay"
        ("đơn bán chịu có hạn trả sau hôm nay", "2026-03-18", [("2026-03-18", "2026-03-18")]),
        ("6 hôm nay bán được bao nhiêu", "2026-03-18", [("2026-03-13", "2026-03-18")]),
        # [vá 8] cách nói đồng nghĩa (câu tự đặt, as_of 18/03/2026)
        ("năm nay tính tới hôm nay thu được bao nhiêu", "2026-03-18", [("2026-01-01", "2026-03-18")]),
        ("doanh thu quý này tính đến hôm nay", "2026-03-18", [("2026-01-01", "2026-03-18")]),
        ("tuần này tính tới hôm nay bán ra mấy đơn", "2026-03-18", [("2026-03-16", "2026-03-18")]),
        ("doanh thu từ mùng 1 đến hết hôm nay", "2026-03-18", [("2026-03-01", "2026-03-18")]),
        ("từ đầu tháng tới chừ được mấy đơn", "2026-03-18", [("2026-03-01", "2026-03-18")]),
        ("đầu năm tới giờ bán được bao nhiêu", "2026-03-18", [("2026-01-01", "2026-03-18")]),
        ("doanh thu tháng này so với cùng số ngày đầu tháng rồi tăng mấy %", "2026-03-18",
         [("2026-03-01", "2026-03-18"), ("2026-02-01", "2026-02-18")]),
        ("giữa tháng 9/2025, 10/2025 và 11/2025 tháng nào bán ít nhất", "2026-03-18",
         [("2025-09-01", "2025-09-30"), ("2025-10-01", "2025-10-31"), ("2025-11-01", "2025-11-30")]),
        ("doanh thu giữa tháng 3", "2026-03-18", []),
        ("cơm gà lên giá từ 20/12/2025, 14 ngày từ bữa đó so với 14 ngày trước đó", "2026-03-18",
         [("2025-12-20", "2026-01-02"), ("2025-12-06", "2025-12-19")]),
        ("doanh thu 3 tháng liền nhau tính tới 2-2026", "2026-03-18",
         [("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")]),
        ("từ khi trà đào lên 40.000 đồng/ly, 10 ngày đầu so với 10 ngày liền trước", "2026-03-18", [(None, None), (None, None)]),
        ("doanh thu đến hết ngày 28/02/2026 là bao nhiêu", "2026-03-10", []),
        # [vá 6] số còn lại + kỳ = mốc cuối kỳ
        ("tồn kho Panadol quý II năm 2025 còn bao nhiêu hộp", "2026-03-10", [(None, "2025-06-30")]),
        ("tháng 12/2025 có mấy khách còn nợ", "2026-03-10", [(None, "2025-12-31")]),
        ("tồn kho tháng này còn bao nhiêu chai", "2026-03-10", [(None, "2026-03-10")]),
        ("quý 1 còn bao nhiêu hộp trong kho", "2026-03-10", [(None, "2026-03-10")]),
        ("tháng 2 bán được mấy hộp, còn tồn bao nhiêu", "2026-03-10", [("2026-02-01", "2026-02-28")]),
        ("tồn kho từ đầu năm đến hết hôm nay còn bao nhiêu thùng", "2026-03-10", [("2026-01-01", "2026-03-10")]),
        ("từ 01/03 đến hết hôm qua bán được mấy đơn", "2026-03-10", [("2026-03-01", "2026-03-09")]),
        ("đến hết ngày 28/02/2026 có mấy khách còn nợ", "2026-03-10", [(None, "2026-02-28")]),
        ("trong tháng 5 năm 2025 bán mấy thùng gạch 60x60 thùng 4 viên", "2026-03-10", [("2025-05-01", "2025-05-31")]),
        ("Từ tháng 8/2025 tới tháng 10/2025, tháng nào bán nhiều nhất?", "2026-03-10",
         [("2025-08-01", "2025-08-31"), ("2025-09-01", "2025-09-30"), ("2025-10-01", "2025-10-31")]),
        ("tu thang 12/2025 toi thang 2/2026 thang nao ban nhieu nhat", "2026-03-10",
         [("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")]),
        ("dthu 3 tháng liền nhau kết thúc ở tháng 6/2025 là bao nhiêu mỗi tháng", "2026-03-10",
         [("2025-04-01", "2025-04-30"), ("2025-05-01", "2025-05-31"), ("2025-06-01", "2025-06-30")]),
        ("Từ tháng 2/2026 đến tháng 4/2026, doanh thu tháng sau có luôn cao hơn tháng trước không?", "2026-05-20",
         [("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-31"), ("2026-04-01", "2026-04-30")]),
        ("Doanh thu tuần trước nữa là bao nhiêu?", "2026-03-10", [("2026-02-23", "2026-03-01")]),
        ("Doanh thu tháng trước nữa?", "2026-03-10", [("2026-01-01", "2026-01-31")]),
        ("Doanh thu quý trước nữa?", "2026-03-10", [("2025-07-01", "2025-09-30")]),
        ("Doanh thu năm 2025?", "2026-03-10", [("2025-01-01", "2025-12-31")]),
        ("doanh thu tháng 5 năm 2025", "2026-03-10", [("2025-05-01", "2025-05-31")]),
        ("Doanh thu giai đoạn 01/02/2026 – 15/02/2026?", "2026-03-10", [("2026-02-01", "2026-02-15")]),
        ("so vs cung thang nam truoc, dthu thang 4 nam 2026 thay doi may %", "2026-06-16",
         [("2026-04-01", "2026-04-30"), ("2025-04-01", "2025-04-30")]),
        ("Tháng 2/2025 bán ra bao nhiêu tuýp Acyclovir Stella kem 5% tuýp 5g?", "2026-06-12", [("2025-02-01", "2025-02-28")]),
        ("tỉ trọng của nhóm giảm đau hạ sốt trong doanh thu tháng 2/2026 là bao nhiêu %", "2026-07-13", [("2026-02-01", "2026-02-28")]),
        ("Doanh thu tháng 11/2025 hơn hay kém tháng trước bao nhiêu phần trăm?", "2026-06-28",
         [("2025-11-01", "2025-11-30"), ("2025-10-01", "2025-10-31")]),
        # [vá 3] từ bảng chấm tay của Việt (as_of 10/03/2026, thứ Ba)
        ("doanh thu nửa đầu tháng 2 là bao nhiêu", "2026-03-10", [("2026-02-01", "2026-02-15")]),
        ("doanh thu nửa cuối tháng 2", "2026-03-10", [("2026-02-16", "2026-02-28")]),
        ("từ 15 tới 20 tháng này có bao nhiêu đơn", "2026-03-20", [("2026-03-15", "2026-03-20")]),
        ("từ 5 đến 10 tháng 2 bán được mấy ly", "2026-03-10", [("2026-02-05", "2026-02-10")]),
        ("từ thứ Hai tới giờ có mấy khách còn nợ", "2026-03-10", [("2026-03-09", "2026-03-10")]),
        ("doanh thu thứ Bảy tuần trước", "2026-03-10", [("2026-03-07", "2026-03-07")]),
        ("số đơn 2 hnay là bn", "2026-03-10", [("2026-03-09", "2026-03-10")]),
        ("tồn kho nước suối bayr ngày gần đây còn bao nhiêu", "2026-03-10", [("2026-03-04", "2026-03-10")]),
        ("số đơn mấy hnay là bn", "2026-03-10", []),
        ("đầu tháng 3 có bao nhiêu đơn", "2026-03-10", []),
        ("cuối tháng trước có bao nhiêu đơn", "2026-03-10", []),
        ("tuần đầu tiên của tháng 2 doanh thu bao nhiêu", "2026-03-10", []),
        ("doanh thu sáng nay", "2026-03-10", []),
        ("doanh thu ca sáng hôm qua", "2026-03-10", [("2026-03-09", "2026-03-09")]),
        ("số đơn từ đầu năm tới hết hôm nay", "2026-03-10", [("2026-01-01", "2026-03-10")]),
        ("doanh thu tối qua tăng hay giảm bao nhiêu % so với cùng kỳ năm trước", "2026-03-10", []),
        ("doanh thu 3 ngày trước là bao nhiêu", "2026-03-10", []),
        ("tuần sau có bao nhiêu đơn", "2026-03-10", []),
        ("gần đây bán được mấy chai", "2026-03-10", []),
        ("từ đầu tháng tới nay doanh thu bao nhiêu", "2026-03-10", [("2026-03-01", "2026-03-10")]),
        ("Từ tháng 2/2026 đến tháng 4/2026, doanh thu tháng sau có luôn cao hơn tháng trước không?", "2026-05-20",
         [("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-31"), ("2026-04-01", "2026-04-30")]),
    ]:
        check("vá thời gian: " + q, [(p["start"], p["end"]) for p in resolve_time(q, a)], want)
    for t, want in [
        ("đơn từ 270.000 ddoongf trở lên", [(270000, "vnd", "gte", None)]),
        ("tăng giá lên 23.000dd", [(23000, "vnd", None, "new_price")]),
        ("đổi giá từ 22.000đ lên 23.000đ", [(22000, "vnd", None, "old_price"), (23000, "vnd", None, "new_price")]),
        ("đơn trên 55k", [(55000, "vnd", "gt", None)]),
        ("đơn dưới 1tr", [(1000000, "vnd", "lt", None)]),
        ("đơn ≥ 500.000đ", [(500000, "vnd", "gte", None)]),
        ("Enterogermina 2 tỷ/5ml hộp 20 ống", []),
        ("Otrivin 0,1% chai 10ml bán mấy chai", []),
        ("tăng 12,5%", [(12.5, "percent", None, None)]),
        ("có bao nhiêu đơn trên 1,5 củ", [(1500000, "vnd", "gt", None)]),          # [vá 3]
        ("đơn từ 2 triệu rưỡi trở lên", [(2500000, "vnd", "gte", None)]),
        ("mua 2 củ gừng", []),
        ("điện thoại giá 5 củ", [(5000000, "vnd", None, None)]),
        ("đơn có tiền hàng trên 2 lít", [(200000, "vnd", "gt", None)]),
        ("bán được mấy chai nước suối 2 lít", []),
        ("đơn từ 2 chai trở lên", []),
        ("bán 3 thùng 10 chai nước suối", []),                                     # [vá 7]
        ("tồn kho còn 10 chai", []),
        ("dùng hết 2 chai nước rửa", []),
        ("doanh thu được 3 chai", [(3000000, "vnd", None, None)]),
        ("nhập 2 thùng 5 lít dầu", []),
        ("món này giá 5 cành", [(5000, "vnd", None, None)]),
        ("ly này giá 25 cá", [(25000, "vnd", None, None)]),
        ("bán được 2 cá lóc", []),
        ("tiền hàng nửa xị", [(50000, "vnd", None, None)]),
        ("doanh thu trên 1 tỏi", [(1000000000, "vnd", "gt", None)]),
        ("tháng 2 bán được mấy kg tỏi", []),
        ("từ 15 tới 20 tháng này có bao nhiêu đơn", []),
    ]:
        check("vá tiền: " + t, [(a["value"], a["unit"], a["op"], a["role"]) for a in parse_amounts(t) if a["unit"] != "number"], want)

    # quét ngày: so với công thức độc lập bằng datetime/calendar
    d = dt.date(2024, 1, 1)
    while d <= dt.date(2027, 12, 31):
        iso = d.isoformat()
        P = lambda q: resolve_time(q, iso, None)
        mon = d - dt.timedelta(days=d.weekday())
        py, pm = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
        pend = _cal.monthrange(py, pm)[1]
        exp_ref_end = dt.date(py, pm, min(d.day, pend))
        got = P("hôm qua")
        check("hôm qua %s" % iso, [(p["start"], p["end"]) for p in got], [((d - dt.timedelta(days=1)).isoformat(),) * 2])
        got = P("tuần này")
        check("tuần này %s" % iso, [(p["start"], p["end"]) for p in got], [(mon.isoformat(), iso)])
        got = P("tuần rồi")
        check("tuần rồi %s" % iso, [(p["start"], p["end"]) for p in got],
              [((mon - dt.timedelta(days=7)).isoformat(), (mon - dt.timedelta(days=1)).isoformat())])
        got = P("tháng này")
        check("tháng này %s" % iso, [(p["start"], p["end"]) for p in got], [(d.replace(day=1).isoformat(), iso)])
        got = P("tháng rồi")
        check("tháng rồi %s" % iso, [(p["start"], p["end"]) for p in got], [(dt.date(py, pm, 1).isoformat(), dt.date(py, pm, pend).isoformat())])
        got = P("so với tháng trước, doanh thu từ đầu tháng này đến hết hôm nay tăng bao nhiêu %")
        check("cùng số ngày %s" % iso, [(p["label"], p["start"], p["end"]) for p in got],
              [("ky_nay", d.replace(day=1).isoformat(), iso), ("ky_truoc", dt.date(py, pm, 1).isoformat(), exp_ref_end.isoformat())])
        got = P("7 ngày gần nhất")
        check("7 ngày %s" % iso, [(p["start"], p["end"]) for p in got], [((d - dt.timedelta(days=6)).isoformat(), iso)])
        d += dt.timedelta(days=13)  # bước 13 ngày để quét đủ thứ trong tuần/đầu-cuối tháng mà vẫn nhanh
    if verbose:
        print("Đạt %d/%d ca kiểm thử đơn vị" % (total - bad, total))
    return bad == 0


_SYL = re.compile(r"^(?:ngh|ng|nh|ph|th|tr|ch|kh|gh|gi|qu|[bcdghklmnpqrstvx])?[aeiouy]+(?:ng|nh|ch|[cmnpt])?$")


def find_unknown_tokens(questions, min_count=3, top=80):
    """Gợi ý từ viết tắt / gõ sai: các từ KHÔNG có cấu trúc âm tiết tiếng Việt (ví dụ 'dthu', 'bnhiu', 'hqua', 'trc'),
    chưa có trong từ điển và không giải mã Telex được. Người duyệt tay: giữ viết tắt thật, bỏ tên riêng/thương hiệu."""
    from collections import Counter
    cnt = Counter()
    for q in questions:
        for w in re.findall(r"[^\W\d_]+", str(q["question"]).lower()):
            cnt[w] += 1
    out = []
    for w, c in cnt.most_common():
        if c < min_count:
            break
        if w != to_ascii(w).replace(" ", "") or len(w) < 2 or w in TEENCODE_WORDS or _SYL.match(w):
            continue
        if VOCAB and telex_decode(w):
            continue
        out.append((w, c))
    return out[:top]
