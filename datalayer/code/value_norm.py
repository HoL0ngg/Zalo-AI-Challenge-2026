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
        return _round_int(Decimal(str(value)))
    s = str(value).replace(_NBSP, " ").strip().lower()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s[:1] in "-−–":
        neg, s = True, s[1:].strip()
    s = _CUR.sub("", s).strip()
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
                if re.fullmatch(r"\d{1,3}(\.\d{3})+", a):  # '1.500k' = 1500k
                    a = a.replace(".", "")
                val = Decimal(a.replace(",", ".")) * 1000
    if val is None:
        if re.fullmatch(r"\d{1,3}( \d{3})+", s):  # '16 076'
            s = s.replace(" ", "")
        if not re.fullmatch(r"[\d.,]+", s):
            return None
        has_c, has_d = "," in s, "." in s
        if has_c and has_d:
            last = max(s.rfind(","), s.rfind("."))
            dec = s[last]
            thou = "," if dec == "." else "."
            ip, fp = s[:last], s[last + 1:]
            if not fp.isdigit() or not re.fullmatch(r"\d{1,3}(%s\d{3})*" % re.escape(thou), ip):
                return None
            val = Decimal(ip.replace(thou, "") + "." + fp)
        elif has_c or has_d:
            sep = "," if has_c else "."
            parts = s.split(sep)
            if not all(p.isdigit() for p in parts):
                return None
            if len(parts) > 2:  # 294.770.300
                if 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
                    val = Decimal("".join(parts))
                else:
                    return None
            else:
                a, b = parts
                if len(b) == 3 and 1 <= len(a) <= 3:  # 84,000 / 1.500
                    val = Decimal(a + b)
                elif set(b) == {"0"}:  # 45000.0 / 8000,00
                    val = Decimal(a)
                else:  # 1,5 -> mơ hồ, không đoán
                    return None
        else:
            if not s.isdigit():
                return None
            val = Decimal(s)
    out = _round_int(val)
    return -out if neg else out


_QTY = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(.*)$")


def _nice(x):
    return int(x) if float(x).is_integer() else float(x)


def parse_qty(value):
    """Số lượng -> (số, đơn vị). '2 cái'->(2,'cái'); '1,5 kg'->(1.5,'kg'); 12->(12,'')."""
    if value is None or isinstance(value, bool):
        return None
    if _is_number(value):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return (_nice(value), "")
    s = str(value).replace(_NBSP, " ").strip()
    if not s:
        return None
    m = _QTY.match(s)
    if not m:
        return None
    num, unit = m.groups()
    if re.fullmatch(r"-?\d{1,3}\.\d{3}", num):  # 1.500 = một nghìn rưỡi
        n = float(num.replace(".", ""))
    else:
        n = float(num.replace(",", "."))
    return (_nice(n), unit.strip())


# ───────────────────────── ngày tháng ─────────────────────────
_EPOCH = dt.date(1899, 12, 30)
_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?$")
_DMY = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_DM = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})$")
_THG = re.compile(r"^(?:ngày\s*)?(\d{1,2})\s*(?:thg|tháng|thang)\s*(\d{1,2})\s*,?\s*(?:năm|nam)?\s*(\d{4})?$")


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
        if math.isnan(n) or not (20000 <= n <= 80000):
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
    ("90k", 90000), ("105k", 105000), ("79k", 79000), ("270k", 270000), ("3000k", 3000000), ("1840k", 1840000),
    ("18400k", 18400000), ("90K", 90000), (" 90k ", 90000), ("1tr", 1000000), ("2,5tr", 2500000),
    ("5tr520", 5520000), ("12tr460", 12460000), ("1tr780", 1780000), ("19tr990", 19990000), ("20,1tr", 20100000),
    ("4,544tr", 4544000), ("294,7703tr", 294770300), ("294.770.300đ", 294770300), ("1.500đ", 1500),
    ("1.200.000đ", 1200000), ("569.000đ", 569000), ("112.000đ", 112000), ("-53.500đ", -53500), ("0đ", 0),
    ("84,000", 84000), ("32,000", 32000), ("15,044", 15044), ("878000", 878000), ("16 076", 16076),
    ("8,000.0000", 8000), ("45000", 45000), ("45000.0", 45000), (45000.0, 45000), (45000, 45000),
    ("", None), (None, None), ("N/A", None), ("#VALUE!", None), ("abc", None), ("-", None), ("1,5", None),
]
QTY_TESTS = [
    ("2 cái", (2, "cái")), ("5 viên", (5, "viên")), ("1 thùng", (1, "thùng")), ("2 cuộn", (2, "cuộn")),
    ("15 vỉ", (15, "vỉ")), ("10 hộp ", (10, "hộp")), ("12", (12, "")), (12.0, (12, "")),
    ("1,5 kg", (1.5, "kg")), ("0,5 lít", (0.5, "lít")), ("", None), (None, None),
]
DATE_TESTS = [  # (đầu vào, year_hint, mong đợi)
    ("2025-01-01 00:00:00", None, "2025-01-01"), ("01/01/2025", None, "2025-01-01"),
    ("30/07/2025", None, "2025-07-30"), ("2025-12-31", None, "2025-12-31"), ("1 thg 1 2025", None, "2025-01-01"),
    ("1 thg 5 2025", None, "2025-05-01"), ("1/1", 2025, "2025-01-01"), ("15/07", 2025, "2025-07-15"),
    ("1/1", 2026, "2026-01-01"), ("1/1", None, None), ("02/03/2025", None, "2025-03-02"),
    (45839, None, "2025-07-01"), (45841, None, "2025-07-03"), (46023, None, "2026-01-01"),
    ("31/02/2025", None, None), ("abc", None, None), ("", None, None), (dt.datetime(2025, 1, 1), None, "2025-01-01"),
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
