# -*- coding: utf-8 -*-
"""Chuẩn hoá câu hỏi, bóc tách số tiền và tính khoảng thời gian (Việc 1 - Ngân).

Hàm chính:
  normalize_question(raw, as_of_date, calendar) -> dict
  normalize_text(text) -> (text_norm, text_ascii)
  parse_amounts(text) -> list[{span, value, unit}]
  resolve_time(text, as_of_date, calendar) -> list[{label, start, end, ...}]
  extract_flags(text) -> dict[str, bool]
"""
import re
import calendar as _cal
import datetime as dt
import unicodedata
from decimal import Decimal

# ───────────────────────── 1. TỪ ĐIỂN TEENCODE & CHUẨN HOÁ ─────────────────────────
TEENCODE_MAP = {
    "dthu": "doanh thu", "d thu": "doanh thu", "dt": "doanh thu",
    "bnhiu": "bao nhiêu", "bnhieu": "bao nhiêu", "bn": "bao nhiêu", "nhiu": "bao nhiêu", "bao nhiu": "bao nhiêu",
    "sp": "sản phẩm", "mh": "mặt hàng",
    "hqua": "hôm qua", "hom qua": "hôm qua", "bua qua": "hôm qua", "bữa qua": "hôm qua",
    "hnay": "hôm nay", "hom nay": "hôm nay", "hom ni": "hôm nay", "hôm ni": "hôm nay", "bua nay": "hôm nay", "bữa nay": "hôm nay",
    "dc": "được", "đc": "được",
    "ko": "không", "k": "không", "hok": "không", "hong": "không", "hem": "không",
    "mik": "mình", "mk": "mình", "shop mik": "shop mình",
    "nv": "nhân viên", "kh": "khách hàng", "hđ": "hóa đơn", "hd": "hóa đơn", "bill": "đơn hàng", "order": "đơn hàng",
    "sl": "số lượng", "slg": "số lượng", "đv": "đơn vị", "dvt": "đơn vị tính",
    "trc": "trước", "nhut": "nhất", "z": "vậy", "zay": "vậy", "z ha": "vậy hả",
    "amount": "tổng tiền", "total": "tổng tiền", "cash": "tiền mặt",
}

# ───────────────────────── 1b. SỬA LỖI GÕ TELEX ─────────────────────────
# Ví dụ: "hoom" -> "hôm", "gaanf" -> "gần", "dduwowcj" -> "được", "quys" -> "quý".
# Nguyên tắc an toàn (không sửa nhầm tên sản phẩm như Gas, Max, Strepsils):
#   (1) kết quả phải là MỘT ÂM TIẾT TIẾNG VIỆT HỢP LỆ (phụ âm đầu + vần + phụ âm cuối);
#   (2) từ chỉ có phím dấu ở cuối (vaof, quys...) phải có trong _VIET_VOCAB;
#   (3) không đụng các từ trong _TELEX_KEEP.
_VIET_VOCAB = set("""
biết buộc bà bàn bác bán bánh bên bình bò bó bóp băng bơ
bơm bươu bạc bạch bảng bảo bằm bằng bếp bị bỏ bổ bộ bột
bớt bữa chiên chiếm chiều chuyển chà cháo cháy chân châu chén chênh chưa
chạy chải chất chấu chậm chẵn chỉ chịu chống chở chức corbière cuối cuộn
cà cá các cái cánh cát cây còn có công cùng cúm cũ cơm
cường cạnh cả cảm cấp cần cắm cộng cụ củ của cửa dày dán
dây dùng dưa dương dầu dị dịch dịp dụng giá giò giòn gió giùm
giúp giảm giấy giặt giỏi gà gì gòn gói góp gạch gạo gần gỏi
gộp hiếu hiện hoàn hoàng hoá hoạt huyết huỳnh huỷ hà hàng hòa hôm
hông hùng hơn hướng hạ hạn hạnh hạt hả hải hảo hấp hấu hầm
hậu hằng hẳn hết họng hỏi hồ hồi hỗn hộp khiết khoáng khoản khác
khách khái kháng khánh khô không khổ kiềm kèm kém kê kẹo kẽm kết
kể kỳ liên liền liệt loại luôn luồn là làm lành lá lát lãi
lê lên lòng lóc lót lô lúc lưới lượng lượt lại lạnh lấp lấy
lần lẩu lẻ lễ lệ lệch lịch lọ lốc lốt lộ lớn lời lợi
miếng muối muống mà má máy mã mì mình món môn măng mũi mạ
mấy mắm mắt mặt mến mề mọi mỗi một mới mức mực nghiêm nghêu
nghề ngoài ngoái nguyên nguyễn ngày ngân ngư người ngậm ngọt nhiêu nhiều nhuận
nhà nhân nhìu nhóm nhôm nhất nhập nhỉ nhỏ nhồi những nào này não
nêm nên năm năng nước nướng nấm nằm nếp nền nồi nội nợ nữ
phiếu phát phân phép phê phí phùng phúc phương phải phần phẩm phế phộng
phở quá quách quán quân quý quảng quầy quẹt riêng ròng răng rạng rồi
rửa suối sài sáng sò súc sĩ sơn sườn sả sản sắt sặc sẽ
sỉ số sốt sụn sủi sữa thiết thiếu thiện thoại thuốc thuộc thành thái
tháng thân thép thêm thì thùng thúc thước thạch thảo thấm thất thấu thẻ
thịt thời thợ thủy thứ thực tiên tiêu tiếp tiền tiệm trà trân trét
trên trí trăm trưng trước trưởng trạng trả trần trị trọng trở trứng trừ
tuýp tuần tuổi tâm tã tính tô tôi tôm tôn tăng tươi tương tường
tại tấn tất tận tắc tế tết tỉ tỏi tố tồn tổng tới tục
từ từng tử tự tỷ uống viên việc và vàng vào ví võ vú
văn vũ vương vải vẫn vậy về vệ vỉ vị vốn với xoài xuất
xào xám xét xích xúc xỉu xịt âm é ép ê ích ít ó
ô ăn đ đang đau đc đen đinh điện đoàn đoạn đào đá đáng
đánh đáo đã đèn đó đóng đôi đông đĩa đơn đươc đường được đạt
đầu đậu đắt đằng đặc đặt đếm đến đồ đồng đổi độ đợt đức
ạ ế ếch ốc ống ổ ớt ở ứng
""".split())  # các âm tiết có dấu lấy từ câu hỏi TRAIN

_TELEX_KEEP = {"gas", "max", "air", "box", "mix", "lux", "tax", "car", "bar", "aa", "ee", "oo", "dd"}

_TONE_KEYS = {"s": 0, "f": 1, "r": 2, "x": 3, "j": 4}          # sắc, huyền, hỏi, ngã, nặng
_TONED = {  # nguyên âm -> (sắc, huyền, hỏi, ngã, nặng)
    "a": "áàảãạ", "ă": "ắằẳẵặ", "â": "ấầẩẫậ", "e": "éèẻẽẹ", "ê": "ếềểễệ", "i": "íìỉĩị",
    "o": "óòỏõọ", "ô": "ốồổỗộ", "ơ": "ớờởỡợ", "u": "úùủũụ", "ư": "ứừửữự", "y": "ýỳỷỹỵ",
}
_VOWELS = "aăâeêioôơuưy"
_ONSET = r"(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|b|c|d|đ|g|h|k|l|m|n|p|r|s|t|v|x)?"
_CODA = r"(?:ch|ng|nh|c|m|n|p|t)?"
_NUCLEI = {  # các vần nguyên âm hợp lệ (không kể phụ âm cuối)
    "a", "ă", "â", "e", "ê", "i", "o", "ô", "ơ", "u", "ư", "y",
    "ai", "ao", "au", "ay", "âu", "ây", "eo", "êu", "ia", "iê", "iu", "oa", "oă", "oe", "oi", "ôi",
    "ơi", "ua", "uâ", "uê", "ui", "uô", "uơ", "uy", "ưa", "ưi", "ưu", "ươ", "yê",
    "iêu", "yêu", "oai", "oay", "oeo", "uây", "uôi", "ươi", "ươu", "uyê", "uya",
}
_SYL = re.compile(r"^(%s)([%s]+)(%s)$" % (_ONSET, _VOWELS, _CODA))

def _place_tone(syl, tone):
    """Đặt dấu thanh vào đúng nguyên âm của một âm tiết đã có dấu mũ/móc."""
    m = _SYL.match(syl)
    if not m:
        return None
    onset, nuc, coda = m.groups()
    if nuc not in _NUCLEI:
        return None
    if tone is None:
        return syl
    marked = [i for i, c in enumerate(nuc) if c in "ăâêôơư"]
    if marked:                       # ưu tiên nguyên âm có mũ/móc (ươ -> đặt ở ơ)
        pos = marked[-1]
    elif coda or len(nuc) == 1:      # có phụ âm cuối -> nguyên âm cuối
        pos = len(nuc) - 1
    elif len(nuc) == 3:              # oai, uya -> nguyên âm giữa
        pos = 1
    else:                            # 2 nguyên âm: dấu ở âm đầu, trừ oa/oe/uy
        pos = 1 if nuc in ("oa", "oe", "uy") else 0
    nuc = nuc[:pos] + _TONED[nuc[pos]][tone] + nuc[pos + 1:]
    return onset + nuc + coda

def telex_fix(word):
    """Sửa một từ gõ Telex lỗi. Không chắc chắn thì trả về nguyên từ."""
    w = word.lower()
    if not re.fullmatch(r"[a-z]{2,8}", w) or w in _TELEX_KEEP:
        return word
    tone = None
    if w[-1] in _TONE_KEYS and re.search(r"[aeiouy]", w[:-1]):
        tone, w = _TONE_KEYS[w[-1]], w[:-1]
    has_mark = bool(re.search(r"dd|aa|aw|ee|oo|ow|uw", w))
    if tone is None and not has_mark:
        return word
    for a, b in (("dd", "đ"), ("uw", "ư"), ("ow", "ơ"), ("aw", "ă"), ("aa", "â"), ("ee", "ê"), ("oo", "ô")):
        w = w.replace(a, b)
    w = re.sub(r"uơ(?=[a-zđ])", "ươ", w)        # "uown" -> "ươn"
    out = _place_tone(w, tone)
    if out is None:
        return word
    if not has_mark and out not in _VIET_VOCAB:   # chỉ có phím dấu cuối -> phải có trong từ điển
        return word
    return out.capitalize() if word[0].isupper() else out

def to_ascii(text):
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def _split_punct(word):
    """Tách dấu câu dính cuối từ: "hnay?" -> ("hnay", "?"), "trc," -> ("trc", ",")."""
    m = re.match(r"^(.*?)([,.;:!?…]*)$", word)
    return m.group(1), m.group(2)

def normalize_text(text):
    if not text:
        return "", ""
    s = unicodedata.normalize("NFC", str(text)).strip()
    s = re.sub(r"(?i)\bth(\d{1,2})\b", r"tháng \1", s)
    s = re.sub(r"(?i)\bt(\d{1,2})\b", r"tháng \1", s)
    s = re.sub(r"(?i)\bthangs\b", "tháng", s)
    s = re.sub(r"(?i)\btuaan\b", "tuần", s)

    words = s.split()
    norm_words = []
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            # Tra cụm 2 từ: bỏ dấu câu dính ở từ thứ 2 khi tra, rồi gắn lại
            core2, punct2 = _split_punct(words[i+1])
            two = (telex_fix(words[i]) + " " + telex_fix(core2)).lower()
            if two in TEENCODE_MAP:
                norm_words.append(TEENCODE_MAP[two] + punct2)
                i += 2
                continue
        core, punct = _split_punct(words[i])
        core = telex_fix(core)                      # sửa lỗi gõ Telex trước khi tra teencode
        norm_words.append(TEENCODE_MAP.get(core.lower(), core) + punct)
        i += 1
    text_norm = re.sub(r"\s+", " ", " ".join(norm_words)).strip()
    return text_norm, to_ascii(text_norm)

# ───────────────────────── 2. BÓC TÁCH TIỀN & SỐ LƯỢNG ─────────────────────────
_TR_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|trieu)\s*(\d+)?", re.IGNORECASE)
_K_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:k|nghìn|nghin|ngàn|ngan)", re.IGNORECASE)
_NUM_VND = re.compile(r"(\d{1,3}(?:[.,]\d{3})+)\s*(?:đ|₫|đồng|dong|vnd)?", re.IGNORECASE)
_PCT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)

def parse_amounts(text):
    results = []
    if not text:
        return results
    for m in _TR_PATTERN.finditer(text):
        a, b = m.group(1), m.group(2)
        val = int(Decimal(a) * 1000000 + Decimal("0." + b) * 1000000) if b else int(Decimal(a.replace(",", ".")) * 1000000)
        results.append({"span": m.group(0), "value": val, "unit": "vnd"})
    for m in _K_PATTERN.finditer(text):
        if m.start() > 0 and text[m.start()-1].isalnum():
            continue
        try:
            val = int(float(m.group(1).replace(".", "").replace(",", ".")) * 1000)
            results.append({"span": m.group(0), "value": val, "unit": "vnd"})
        except ValueError:
            pass
    for m in _NUM_VND.finditer(text):
        try:
            val = int(m.group(1).replace(".", "").replace(",", ""))
            if not any(r["value"] == val for r in results):
                results.append({"span": m.group(0), "value": val, "unit": "vnd"})
        except ValueError:
            pass
    for m in _PCT_PATTERN.finditer(text):
        try:
            results.append({"span": m.group(0), "value": float(m.group(1).replace(",", ".")), "unit": "percent"})
        except ValueError:
            pass
    return results

# ───────────────────────── 3. TÍNH KHOẢNG THỜI GIAN THEO RULEBOOK ─────────────────────────
def _as_date(d):
    return d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])

def _find_tet_window(year, calendar):
    if not calendar:
        return None, None
    s_date, e_date = None, None
    y_prev, y_curr = str(year - 1), str(year)
    for row in calendar:
        if row.get("lunar_year") == y_prev and row.get("lunar_month") == "12" and row.get("lunar_day") == "23":
            s_date = row.get("date")
        if row.get("lunar_year") == y_curr and row.get("lunar_month") == "1" and row.get("lunar_day") == "10":
            e_date = row.get("date")
    return s_date, e_date

_UNTIL = re.compile(r"\b(tinh den|den het|den cuoi|cuoi ngay|het ngay|het hom nay|het bua nay|den hom nay)\b")

def resolve_time(text, as_of_date, calendar=None):
    """Rulebook: "đến hết ngày X", "tính đến hôm nay", "cuối ngày X" = tình trạng TỪ ĐẦU DỮ LIỆU đến hết X.
    Nếu câu có cụm đó (và không phải khoảng "từ ... đến hết ...") mà kết quả là 1 ngày,
    đổi kỳ thành kind="until", start=None (tức là từ đầu dữ liệu)."""
    periods = _resolve_time_core(text, as_of_date, calendar)
    _, s = normalize_text(text)
    m = _UNTIL.search(s)
    if m and not re.search(r"\btu\b", s[:m.start()]):
        for p in periods:
            if p["kind"] in ("date", "day") and p["start"] == p["end"]:
                p["start"], p["kind"] = None, "until"
    return periods

def _resolve_time_core(text, as_of_date, calendar=None):
    as_of = _as_date(as_of_date)
    norm, s = normalize_text(text)

    # 1. Từ đầu năm (Rulebook: từ 01/01 năm nay đến hết as_of)
    if "tu dau nam" in s:
        return [{"label": "ky_nay", "start": dt.date(as_of.year, 1, 1).isoformat(), "end": as_of.isoformat(), "kind": "year_to_date"}]

    # 2. N ngày gần nhất (Rulebook: N ngày kể cả hôm nay, ngày cuối là hôm nay)
    m_near = re.search(r"(\d+)\s*ngay\s*(?:gan nhat|qua|tro lai day)", s)
    if m_near:
        n = int(m_near.group(1))
        return [{"label": "ky_nay", "start": (as_of - dt.timedelta(days=n-1)).isoformat(), "end": as_of.isoformat(), "kind": "rolling_days"}]

    # 3. Quý (Quý theo dương lịch, mỗi quý 3 tháng)
    m_quy = re.search(r"quy\s*([1-4])\s*(?:nam|/)?\s*(\d{2,4})?", s)
    if m_quy:
        q_num = int(m_quy.group(1))
        y_str = m_quy.group(2)
        y = int(y_str) if y_str and len(y_str)==4 else (2000+int(y_str) if y_str else as_of.year)
        m_s, m_e = (q_num - 1) * 3 + 1, (q_num - 1) * 3 + 3
        if not y_str and dt.date(y, m_s, 1) > as_of:   # Rulebook: quý không ghi năm mà sau hôm nay -> năm trước
            y -= 1
        return [{"label": "ky_nay", "start": dt.date(y, m_s, 1).isoformat(), "end": dt.date(y, m_e, _cal.monthrange(y, m_e)[1]).isoformat(), "kind": "quarter"}]

    # 4. Tuần (Rulebook: Tuần bắt đầu thứ Hai)
    if "tuan nay" in s:
        mon = as_of - dt.timedelta(days=as_of.weekday())
        return [{"label": "ky_nay", "start": mon.isoformat(), "end": as_of.isoformat(), "kind": "week_to_date"}]
    if "tuan roi" in s or "tuan truoc" in s:
        mon_this = as_of - dt.timedelta(days=as_of.weekday())
        sun_prev = mon_this - dt.timedelta(days=1)
        return [{"label": "ky_nay", "start": (sun_prev - dt.timedelta(days=6)).isoformat(), "end": sun_prev.isoformat(), "kind": "prev_week"}]

    # 5. Tết âm lịch (Rulebook: 23 Chạp năm Y-1 -> mùng 10 Giêng năm Y)
    if "tet" in s:
        m_tet = re.search(r"tet\s*(?:am lich)?\s*(\d{4})?", s)
        t_year = int(m_tet.group(1)) if (m_tet and m_tet.group(1)) else as_of.year
        t_s, t_e = _find_tet_window(t_year, calendar)
        if t_s and t_e:
            res = [{"label": "ky_nay", "start": t_s, "end": t_e, "kind": "tet"}]
            m_pre = re.search(r"(\d+)\s*ngay\s*(?:truoc|ngay truoc)\s*tet", s)
            if m_pre:
                n_pre = int(m_pre.group(1))
                end_pre = dt.date.fromisoformat(t_s) - dt.timedelta(days=1)
                res.append({"label": "ky_truoc", "start": (end_pre - dt.timedelta(days=n_pre-1)).isoformat(), "end": end_pre.isoformat(), "kind": "pre_tet"})
            return res

    # 6. Tháng này (từ ngày 1 đến hết as_of; so tháng trước: cùng số ngày)
    if "thang nay" in s:
        res = [{"label": "ky_nay", "start": as_of.replace(day=1).isoformat(), "end": as_of.isoformat(), "kind": "month_to_date"}]
        if "thang truoc" in s or "cung ky" in s:
            p_m = 12 if as_of.month == 1 else as_of.month - 1
            p_y = as_of.year - 1 if as_of.month == 1 else as_of.year
            res.append({"label": "ky_truoc", "start": dt.date(p_y, p_m, 1).isoformat(), "end": dt.date(p_y, p_m, min(as_of.day, _cal.monthrange(p_y, p_m)[1])).isoformat(), "kind": "prev_month_same_days"})
        return res

    # 7. Tháng tường minh: tháng 5/2026, th6/2025...
    m_m = re.search(r"thang\s*(\d{1,2})\s*(?:nam|/)?\s*(\d{2,4})?", s)
    if m_m:
        month = int(m_m.group(1))
        y_str = m_m.group(2)
        year = int(y_str) if y_str and len(y_str)==4 else (2000+int(y_str) if y_str else (as_of.year if month<=as_of.month else as_of.year-1))
        if 1 <= month <= 12:
            return [{"label": "ky_nay", "start": dt.date(year, month, 1).isoformat(), "end": dt.date(year, month, _cal.monthrange(year, month)[1]).isoformat(), "kind": "explicit_month"}]

    # 8. Ngày cụ thể dd/mm/yyyy.
    #    Tìm trên câu GỐC (text), vì to_ascii đã xoá dấu "/" trong s.
    dates = []
    for d_, m_, y_ in re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
        try:
            dates.append(dt.date(int(y_), int(m_), int(d_)))
        except ValueError:
            pass
    if dates:
        d0 = dates[0]
        # 8a. "N ngày kể từ ngày X ... với N ngày (ngay/liền) trước đó"
        m_ke = re.search(r"(\d+)\s*ngay\s*ke tu", s)
        if m_ke:
            n = int(m_ke.group(1))
            res = [{"label": "ky_nay", "start": d0.isoformat(),
                    "end": (d0 + dt.timedelta(days=n-1)).isoformat(), "kind": "n_days_from"}]
            if "truoc" in s:
                res.append({"label": "ky_truoc", "start": (d0 - dt.timedelta(days=n)).isoformat(),
                            "end": (d0 - dt.timedelta(days=1)).isoformat(), "kind": "n_days_before"})
            return res
        # 8b. "từ dd/mm/yyyy đến (hết) dd/mm/yyyy"
        if len(dates) >= 2 and "den" in s:
            return [{"label": "ky_nay", "start": d0.isoformat(), "end": dates[1].isoformat(), "kind": "date_range"}]
        # 8c. Một ngày duy nhất
        return [{"label": "ky_nay", "start": d0.isoformat(), "end": d0.isoformat(), "kind": "date"}]

    # 9. Hôm qua & hôm nay
    if "hom qua" in s:
        yest = (as_of - dt.timedelta(days=1)).isoformat()
        return [{"label": "ky_nay", "start": yest, "end": yest, "kind": "day"}]
    if "hom nay" in s:
        return [{"label": "ky_nay", "start": as_of.isoformat(), "end": as_of.isoformat(), "kind": "day"}]

    return []

# ───────────────────────── 4. CỜ Ý ĐỊNH & HÀM CHÍNH ─────────────────────────
def extract_flags(text):
    _, s = normalize_text(text)
    return {
        "so_sanh": bool(re.search(r"\b(so voi|hon|kem|cao hon|thap hon|tang|giam|cung ky)\b", s)),
        "tang_truong_pct": bool(re.search(r"\b(may %|bao nhieu %|tang hay giam bao nhieu %)\b", s)),
        "top1": bool(re.search(r"\b(nhat|chay nhat|cao nhat|thap nhat|lon nhat|hot nhat)\b", s)),
        "can_gia_von": bool(re.search(r"\b(gia von|lai gop|lai rong|loi nhuan|loi nhat)\b", s)),
        "ca_lam": bool(re.search(r"\b(ca sang|ca chieu)\b", s)),
    }

def normalize_question(raw_question, as_of_date, calendar=None):
    text_norm, text_ascii = normalize_text(raw_question)
    amounts = parse_amounts(raw_question)
    periods = resolve_time(raw_question, as_of_date, calendar)
    flags = extract_flags(raw_question)

    if "ca sang" in text_ascii:
        for p in periods:
            p["time_start"], p["time_end"] = "06:00:00", "13:59:59"
    elif "ca chieu" in text_ascii:
        for p in periods:
            p["time_start"], p["time_end"] = "14:00:00", "21:59:59"

    return {
        "raw": raw_question,
        "as_of_date": str(as_of_date)[:10],
        "text_norm": text_norm,
        "text_ascii": text_ascii,
        "amounts": amounts,
        "periods": periods,
        "flags": flags,
    }

# ───────────────────────── 5. BỘ TEST KIỂM THỬ ─────────────────────────
TESTS = [
    ("Cho tôi biết doanh thu tuần này.", "2025-11-16", "2025-11-10", "2025-11-16", 0),
    ("Tháng 5/2026 bán ra bao nhiêu cây Ống PVC?", "2026-06-10", "2026-05-01", "2026-05-31", 0),
    ("Rieng ngay hom nay doanh thu quan la bao nhieu?", "2025-03-04", "2025-03-04", "2025-03-04", 0),
    ("Tuần rồi trung bình mổi đơn quán bán được nhiêu tiền vậy?", "2026-08-18", "2026-08-10", "2026-08-16", 0),
    ("Cho tôi biết dthu 30 ngày gần nhất", "2026-05-20", "2026-04-21", "2026-05-20", 0),
    ("Doanh thu từ đầu năm tới hết hnay là bao nhiêu?", "2026-03-16", "2026-01-01", "2026-03-16", 0),
    ("th5/2026 shop mik bn don dthu dat tu 3tr7 tro len z ha", "2026-06-01", "2026-05-01", "2026-05-31", 1),
    ("bua qua dthu duoc bao nhieu", "2026-02-25", "2026-02-24", "2026-02-24", 0),
    # --- Ca bổ sung: ngày cụ thể dd/mm/yyyy (lấy từ TRAIN) ---
    ("Ngày 17/01/2026 cửa hàng bán Mực chiên nước mắm với đơn giá bao nhiêu một đĩa nhỉ?", "2026-01-20", "2026-01-17", "2026-01-17", 0),
    ("giai đoạn từ 17/02/2026 đến hết 23/02/2026, cửa hàng có mấy mặt hàng ees hẳn", "2026-03-01", "2026-02-17", "2026-02-23", 0),
    ("Từ ngày 25/12/2025, Xúc xích Vissan 5 cây tăng giá lên 26.000đ. So 7 ngày kể từ ngày 25/12/2025 với 7 ngày ngay trước đó", "2026-01-10", "2025-12-25", "2025-12-31", 1),
    # --- Ca bổ sung: dấu câu dính vào teencode ---
    ("Hết hnay, Amlodipin 5mg Domesco hộp 3 vỉ x 10 viên còn lại mấy viên trong kho", "2026-05-05", None, "2026-05-05", 0),  # rulebook: "hết hôm nay" = until
    ("coi gium tuan trc, doanh thu ca chieu tang hay giam bnhiu % so vs ca sang", "2026-08-18", "2026-08-10", "2026-08-16", 0),
    # --- Ca bổ sung: lỗi gõ Telex (lấy từ TRAIN) ---
    ("số đơn hoom nay là nhiêu", "2026-03-10", "2026-03-10", "2026-03-10", 0),
    ("số đơn quys 3/2025 là nhiêu", "2025-11-01", "2025-07-01", "2025-09-30", 0),
    ("30 ngày gaanf nhất cửa hangf bán được bao nhiêu tiền", "2026-05-20", "2026-04-21", "2026-05-20", 0),
    # --- Ca bổ sung theo rulebook ---
    ("số đơn quý 4 là bao nhiêu", "2026-03-10", "2025-10-01", "2025-12-31", 0),       # quý chưa tới -> năm trước
    ("số đơn quý 1 là bao nhiêu", "2026-03-10", "2026-01-01", "2026-03-31", 0),       # quý đang diễn ra -> năm nay
    ("Tính đến hết ngày 05/04/2025, tổng số tiền khách còn nợ là bao nhiêu?", "2025-04-10", None, "2025-04-05", 0),
    ("cuối ngày hôm nay bánh croissant còn mấy hộp", "2026-01-15", None, "2026-01-15", 0),
    ("Ngày 17/01/2026 cửa hàng bán Mực chiên với đơn giá bao nhiêu?", "2026-01-20", "2026-01-17", "2026-01-17", 0),  # trong ngày, KHÔNG phải until
    ("giai đoạn từ 17/02/2026 đến hết 23/02/2026 có mấy mặt hàng ế", "2026-03-01", "2026-02-17", "2026-02-23", 0),
]

TELEX_TESTS = [  # (đầu vào, mong đợi) - gồm cả ca KHÔNG được sửa
    ("hoom", "hôm"), ("gaanf", "gần"), ("dduwowcj", "được"), ("cuwar", "cửa"), ("quys", "quý"),
    ("nguwowif", "người"), ("thuoocj", "thuộc"), ("vaof", "vào"), ("huyr", "huỷ"), ("Thangs", "Tháng"),
    ("gas", "gas"), ("Max", "Max"), ("Strepsils", "Strepsils"), ("cool", "cool"), ("Tiger", "Tiger"),
    ("kids", "kids"), ("aa", "aa"), ("plus", "plus"), ("doanh", "doanh"), ("thu", "thu"),
]

def run_tests(verbose=True):
    passed = 0
    for w, want in TELEX_TESTS:
        got = telex_fix(w)
        if got != want:
            print(f"FAILED telex: {w} -> {got} (mong {want})")
    telex_ok = all(telex_fix(w) == want for w, want in TELEX_TESTS)
    for q, as_of, exp_s, exp_e, exp_amt in TESTS:
        res = normalize_question(q, as_of)
        ps = res["periods"]
        if len(ps) > 0 and ps[0]["start"] == exp_s and ps[0]["end"] == exp_e and len(res["amounts"]) >= exp_amt:
            passed += 1
        elif verbose:
            print(f"FAILED: {q} -> got {ps}")
    if verbose:
        print(f"Đạt {passed}/{len(TESTS)} ca kiểm thử chuẩn hoá!")
        print(f"Telex: {sum(telex_fix(w) == want for w, want in TELEX_TESTS)}/{len(TELEX_TESTS)} ca")
    return passed == len(TESTS) and telex_ok
