# -*- coding: utf-8 -*-
"""Đổi giá trị lộn xộn trong sổ sách thành giá trị chuẩn. Không hiểu thì trả None (không đoán).

parse_money(x)            -> int VND | None
parse_qty(x)              -> (số, đơn vị) | None
parse_date(x, year_hint)  -> 'YYYY-MM-DD' | None
parse_datetime(x, year_hint) -> 'YYYY-MM-DD' hoặc 'YYYY-MM-DD HH:MM:SS' | None
"""
import datetime as dt
import math
import numbers
import re
from decimal import Decimal, ROUND_HALF_UP

_NBSP = "\u00a0"
_CUR = re.compile(r"(?:đồng|vnđ|vnd|đ|₫)$")
_CUR_PRE = re.compile(r"^(?:vnđ|vnd|₫)\s*")
_MAX_MONEY = 10 ** 13  # > 10 nghìn tỷ coi là rác, không đoán
_TR = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|trieu)\s*(\d+)?$")
_TY = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:tỷ|tỉ|ty)\s*(\d+)?$")
_K = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:k|nghìn|nghin|ngàn|ngan)$")


def _round_int(d):
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _is_number(x):
    return isinstance(x, numbers.Real) and not isinstance(x, bool)


def _scaled(m, scale):
    """'5tr520' -> 5.520 triệu ; '20,1tr' -> 20,1 triệu."""
    a, b = m.group(1), m.group(2) if m.lastindex and m.lastindex >= 2 else None
    if b and ("," in a or "." in a):
        return None
    if b:
        return Decimal(int(a)) * scale + Decimal("0." + b) * scale
    return Decimal(a.replace(",", ".")) * scale


def parse_money(value):
    """Tiền -> số nguyên VND. Ví dụ: '90k'->90000, '5tr520'->5520000, '1.500đ'->1500, '84,000'->84000."""
    if value is None or isinstance(value, bool):
        return None
    if _is_number(value):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        r = _round_int(Decimal(str(value)))
        return r if abs(r) <= _MAX_MONEY else None
    s = str(value).replace(_NBSP, " ").strip().lower()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s[:1] in "-−–":
        neg, s = True, s[1:].strip()
    s = _CUR.sub("", s).strip()
    s = _CUR_PRE.sub("", s).strip()          # 'VND 150.000', '₫250.000'
    if s[:1] == "+":
        s = s[1:].strip()
    if not s:
        return None

    val = None
    m = _TR.match(s)
    if m:
        val = _scaled(m, Decimal(10) ** 6)
    else:
        m = _TY.match(s)
        if m:
            val = _scaled(m, Decimal(10) ** 9)
        else:
            m = _K.match(s)
            if m:
                a = m.group(1)
                if re.fullmatch(r"\d{1,3}([.,]\d{3})+", a):  # '1.500k', '1,500k' = 1500k
                    a = a.replace(".", "").replace(",", "")
                val = Decimal(a.replace(",", ".")) * 1000
    if val is None:
        if re.fullmatch(r"\d{1,3}( \d{3})+", s):  # '16 076' hoặc '15 000 000'
            s = s.replace(" ", "")
        if not re.fullmatch(r"[\d.,]+", s):
            return None
        has_c, has_d = "," in s, "." in s
        if has_c and has_d:
            # Dấu đứng sau cùng là thập phân, phần trước bỏ hết dấu ngăn nghìn
            last = max(s.rfind(","), s.rfind("."))
            dec = s[last]
            thou = "," if dec == "." else "."
            ip, fp = s[:last], s[last + 1:]
            if not fp.isdigit():
                return None
            ip_clean = ip.replace(thou, "")
            if not ip_clean.isdigit():
                return None
            val = Decimal(ip_clean + "." + fp)
        elif has_c or has_d:
            sep = "," if has_c else "."
            parts = s.split(sep)
            if not all(p.isdigit() for p in parts):
                return None
            if len(parts) > 2:  # 294.770.300 hoặc 1.500.000
                if 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
                    val = Decimal("".join(parts))
                else:
                    return None
            else:
                a, b = parts
                if len(b) == 3 and 1 <= len(a) <= 3:  # 84,000 / 1.500
                    val = Decimal(a + b)
                elif set(b) == {"0"}:  # 45000.0 / 8000,00 / 1500000,00
                    val = Decimal(a)
                else:  # 1,5 -> mơ hồ, không đoán
                    return None
        else:
            if not s.isdigit():
                return None
            val = Decimal(s)
    out = _round_int(val)
    if out > _MAX_MONEY:
        return None
    return -out if neg else out


_QTY = re.compile(r"^(-?\s*\d+(?:[.,]\d+)*(?: \d{3})*)\s*([^\W\d_].*)?$")


def _nice(x):
    return int(x) if float(x).is_integer() else float(x)


def _qty_number(num):
    """'1.500'->1500 ; '1,5'->1.5 ; '0,500'->0.5 ; '1 000'->1000 ; '1.500,5'->1500.5. Không hiểu -> None."""
    num = num.replace(" ", "")
    neg = num.startswith("-")
    num = num.lstrip("-")
    if not num:
        return None
    if "," in num and "." in num:
        last = max(num.rfind(","), num.rfind("."))
        thou = "," if num[last] == "." else "."
        ip, fp = num[:last], num[last + 1:]
        ip = ip.replace(thou, "")
        if not (ip.isdigit() and fp.isdigit()):
            return None
        n = float(ip + "." + fp)
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", num) and not num.startswith("0"):
        n = float(num.replace(",", "").replace(".", ""))   # ngăn nghìn: 1,500 / 1.500
    elif re.fullmatch(r"\d+[.,]\d+", num):
        n = float(num.replace(",", "."))                  # thập phân (kể cả '0,500' = 0.5)
    elif num.isdigit():
        n = float(num)
    else:
        return None
    return -n if neg else n


def parse_qty(value):
    """Số lượng -> (số, đơn vị). '2 cái'->(2,'cái'); '2kg'->(2,'kg'); '1,5 kg'->(1.5,'kg'); '0,500 kg'->(0.5,'kg'); 12->(12,'')."""
    if value is None or isinstance(value, bool):
        return None
    if _is_number(value):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return (_nice(value), "")
    s = str(value).replace(_NBSP, " ").strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    m = _QTY.match(s)
    if not m:
        return None
    num, unit = m.group(1), (m.group(2) or "").strip().rstrip(".").strip()
    # Đơn vị: v3 nhận quy cách có số ('m3', '25kg') và cụm nhiều từ KHI có chữ số ('bao 25kg', 'hộp 30', 'xe 4m3').
    # Cụm nhiều từ không có số ('hộp to') vẫn không đoán. Quá dài / quá nhiều từ -> None.
    if unit:
        if len(unit) > 20 or len(unit.split()) > 3:
            return None
        if " " in unit and not re.search(r"\d", unit):
            return None
    n = _qty_number(num)
    if n is None:
        return None
    return (_nice(n), unit.lower())


# ───────────────────────── ngày tháng ─────────────────────────
_EPOCH = dt.date(1899, 12, 30)
_SERIAL_MIN, _SERIAL_MAX = 36526, 73415   # 2000-01-01 .. 2100-12-31 (cùng khoảng năm với _build)
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_TZ = re.compile(r"(?:z|[+-]\d{2}:?\d{2})$")
_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ tT](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?$")
_DMY = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:[ tT](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_DM = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})$")
# Mở rộng: cho phép "ngày/ngay", "tháng/thang/thg", "năm/nam", khoảng trắng linh hoạt
_THG = re.compile(
    r"^(?:ngày|ngay)?\s*(\d{1,2})\s*(?:thg|tháng|thang)\s*(\d{1,2})\s*"
    r"(?:,?\s*(?:năm|nam)?\s*(\d{4}))?$",
    re.IGNORECASE
)


def _build(y, m, d, hh=0, mm=0, ss=0):
    try:
        if not (1990 <= int(y) <= 2100):
            return None
        day = dt.date(int(y), int(m), int(d))
        t = dt.time(int(hh or 0), int(mm or 0), int(ss or 0))
    except (ValueError, TypeError):
        return None
    return (day, None if t == dt.time(0) else t)


def _year(h):
    try:
        return int(float(h))
    except (TypeError, ValueError):
        return None


def _core(value, year_hint=None):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dt.datetime):
        if value != value:  # NaT
            return None
        t = value.time()
        return (value.date(), None if t == dt.time(0) else t)
    if isinstance(value, dt.date):
        return (value, None)
    if _is_number(value):
        n = float(value)
        if math.isnan(n) or not (_SERIAL_MIN <= n <= _SERIAL_MAX):
            return None
        days = int(n)
        frac = n - days
        day = _EPOCH + dt.timedelta(days=days)
        t = None
        if frac > 1e-9:
            secs = int(round(frac * 86400))
            t = (dt.datetime.min + dt.timedelta(seconds=secs)).time()
        return (day, t)
    s = str(value).replace(_NBSP, " ").strip().lower()
    if not s:
        return None
    if re.fullmatch(r"\d{5}(\.\d+)?", s):
        return _core(float(s))
    s = re.sub(r"^(?:ngày|ngay)\s+", "", s)           # 'ngày 1/2/2025'
    if re.search(r"\d[tT ]\d", s) and _TZ.search(s):   # bỏ múi giờ: ...Z / +07:00
        s = _TZ.sub("", s).strip()
    m = _COMPACT.match(s)
    if m:
        return _build(*m.groups())
    m = _ISO.match(s)
    if m:
        y, mo, d, hh, mi, ss = m.groups()
        return _build(y, mo, d, hh, mi, ss)
    m = _DMY.match(s)
    if m:
        a, b, y, hh, mi, ss = m.groups()
        y = int(y)
        if y < 100:
            y += 2000
        d, mo = int(a), int(b)
        if mo > 12 and d <= 12:  # kiểu tháng/ngày
            d, mo = mo, d
        return _build(y, mo, d, hh, mi, ss)
    m = _THG.match(s)
    if m:
        d, mo, y = m.groups()
        y = y or _year(year_hint)
        return _build(y, mo, d) if y else None
    m = _DM.match(s)
    if m:
        y = _year(year_hint)
        return _build(y, m.group(2), m.group(1)) if y else None
    return None


def parse_date(value, year_hint=None):
    r = _core(value, year_hint)
    return r[0].isoformat() if r else None


def parse_datetime(value, year_hint=None):
    r = _core(value, year_hint)
    if not r:
        return None
    return r[0].isoformat() if r[1] is None else "%s %s" % (r[0].isoformat(), r[1].strftime("%H:%M:%S"))


# ───────────────────────── bộ kiểm thử ─────────────────────────
MONEY_TESTS = [
    # --- cơ bản (đã qua) ---
    ("90k", 90000), ("105k", 105000), ("79k", 79000), ("270k", 270000),
    ("3000k", 3000000), ("1840k", 1840000), ("18400k", 18400000),
    ("90K", 90000), (" 90k ", 90000),
    ("1tr", 1000000), ("2,5tr", 2500000), ("5tr520", 5520000),
    ("12tr460", 12460000), ("1tr780", 1780000), ("19tr990", 19990000),
    ("20,1tr", 20100000), ("4,544tr", 4544000), ("294,7703tr", 294770300),
    ("294.770.300đ", 294770300), ("1.500đ", 1500), ("1.200.000đ", 1200000),
    ("569.000đ", 569000), ("112.000đ", 112000), ("-53.500đ", -53500), ("0đ", 0),
    ("84,000", 84000), ("32,000", 32000), ("15,044", 15044), ("878000", 878000),
    ("16 076", 16076), ("8,000.0000", 8000), ("45000", 45000), ("45000.0", 45000),
    (45000.0, 45000), (45000, 45000),
    ("", None), (None, None), ("N/A", None), ("#VALUE!", None),
    ("abc", None), ("-", None), ("1,5", None),

    # --- kế toán & khoảng trắng ---
    ("(150.000)", -150000),
    ("- 50.000 đ", -50000),
    ("  15 000 000  ", 15000000),

    # --- bẫy ngăn cách nghìn/thập phân ---
    ("1,500,000.00", 1500000),          # chuẩn quốc tế
    ("1.500.000,00 đ", 1500000),        # chuẩn Việt
    ("1500000,00", 1500000),            # chỉ thập phân phẩy
    ("1.2.3.4", None),                  # cấu trúc hỏng
    ("20k5", None),                     # lóng → không đoán

    # --- ký hiệu tiền tệ / số 0 ---
    ("VND 150.000", 150000),            # v2: ký hiệu tiền đứng trước vẫn đọc được
    ("0.00", 0),
    ("-0", 0),

    # --- v2: bug đã tái hiện được ở v1 ---
    ("1,500k", 1500000), ("1.500k", 1500000), ("- 50k", -50000),
    ("₫250.000", 250000), ("+50000", 50000),
    ("10 củ", None), (1e20, None), ("12345678901234567890", None),
]

QTY_TESTS = [
    # --- cơ bản ---
    ("2 cái", (2, "cái")), ("5 viên", (5, "viên")), ("1 thùng", (1, "thùng")),
    ("2 cuộn", (2, "cuộn")), ("15 vỉ", (15, "vỉ")), ("10 hộp ", (10, "hộp")),
    ("12", (12, "")), (12.0, (12, "")),
    ("1,5 kg", (1.5, "kg")), ("0,5 lít", (0.5, "lít")),
    ("", None), (None, None),

    # --- khoảng trắng & dấu phẩy ---
    (" - 3   bịch ", (-3, "bịch")),
    ("1,500 cái", (1500, "cái")),       # 1,500 = một nghìn năm trăm
    ("1.500,5 kg", (1500.5, "kg")),     # kiểu VN có thập phân

    # --- bẫy chữ viết ---
    ("một cái", None),
    ("2 hộp to", None),                 # cụm nhiều từ không có số → None

    # --- v2: bug đã tái hiện được ở v1 ---
    ("2kg", (2, "kg")), ("3cái", (3, "cái")), ("1,5kg", (1.5, "kg")), ("2KG", (2, "kg")),
    ("0,500 kg", (0.5, "kg")),        # v1 trả 500 (sai gấp 1000 lần)
    ("0,250 kg", (0.25, "kg")),
    ("1 000", (1000, "")),             # v1 trả (1,'000')
    ("1 000 cái", (1000, "cái")),
    ("1 1/2", None),                    # v1 trả (1,'1/2')
    ("2 cái.", (2, "cái")),           # v1 giữ dấu chấm trong đơn vị
    ("2 Cái", (2, "cái")),            # chuẩn hoá chữ thường để group-by không bị tách đôi
    ("-5 cái", (-5, "cái")), ("1.5 kg", (1.5, "kg")), (" 2  hộp ", (2, "hộp")),

    # --- v3: đơn vị có quy cách / nhiều từ (trước đây bị xoá thành trống, mất ~5% dòng ở biz_114, biz_116) ---
    ("1 bao 25kg", (1, "bao 25kg")), ("2 hộp 30", (2, "hộp 30")), ("1 xe 4m3", (1, "xe 4m3")),
    ("2 m3", (2, "m3")), ("3 chai 500ml", (3, "chai 500ml")), ("10 thùng 24 lon", (10, "thùng 24 lon")),
    ("1 a b c d", None),
]

DATE_TESTS = [  # (đầu vào, year_hint, mong đợi)
    # --- cơ bản ---
    ("2025-01-01 00:00:00", None, "2025-01-01"),
    ("01/01/2025", None, "2025-01-01"),
    ("30/07/2025", None, "2025-07-30"),
    ("2025-12-31", None, "2025-12-31"),
    ("1 thg 1 2025", None, "2025-01-01"),
    ("1 thg 5 2025", None, "2025-05-01"),
    ("1/1", 2025, "2025-01-01"),
    ("15/07", 2025, "2025-07-15"),
    ("1/1", 2026, "2026-01-01"),
    ("1/1", None, None),
    ("02/03/2025", None, "2025-03-02"),
    (45839, None, "2025-07-01"),
    (45841, None, "2025-07-03"),
    (46023, None, "2026-01-01"),
    ("31/02/2025", None, None),
    ("abc", None, None),
    ("", None, None),
    (dt.datetime(2025, 1, 1), None, "2025-01-01"),

    # --- năm nhuận ---
    ("29/02/2024", None, "2024-02-29"),
    ("29/02/2025", None, None),

    # --- định dạng dấu khác & ISO ---
    ("15.07.2025", None, "2025-07-15"),
    ("2025/07/15", None, "2025-07-15"),
    ("2025-01-01T15:30:00", None, "2025-01-01"),

    # --- Excel serial có phần thập phân (giờ)gtrt
    ("45839.5", None, "2025-07-01"),
    (45839.99, None, "2025-07-01"),

    # --- văn xuôi ---
    ("ngày 2 tháng 3", 2025, "2025-03-02"),
    ("ngay 15 thang 8 nam 2025", None, "2025-08-15"),

    # --- v2 ---
    ("20250201", None, "2025-02-01"),
    ("ngày 1/2/2025", None, "2025-02-01"),
    ("2025-02-01T14:30:15Z", None, "2025-02-01"),
    ("2025-02-01T14:30:15+07:00", None, "2025-02-01"),
    (20000, None, None),               # trước đây ra 1954-10-03 -> chặn serial ngoài 2000-2100
    ("31/11/2025", None, None),
    ("02/01/2025", None, "2025-01-02"),
]


def run_tests(verbose=True):
    bad = 0
    for s, want in MONEY_TESTS:
        got = parse_money(s)
        if got != want:
            bad += 1
            print("SAI money", repr(s), "→", got, "(mong", want, ")")
    for s, want in QTY_TESTS:
        got = parse_qty(s)
        if got != want:
            bad += 1
            print("SAI qty", repr(s), "→", got, "(mong", want, ")")
    for s, hint, want in DATE_TESTS:
        got = parse_date(s, hint)
        if got != want:
            bad += 1
            print("SAI date", repr(s), "hint", hint, "→", got, "(mong", want, ")")
    total = len(MONEY_TESTS) + len(QTY_TESTS) + len(DATE_TESTS)
    if verbose:
        print("Đạt %d/%d ca kiểm thử" % (total - bad, total))
    return bad == 0
