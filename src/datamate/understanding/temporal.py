"""Rule-based Vietnamese temporal resolver (pure functions, no I/O, no LLM).

Turns relative/explicit time expressions into inclusive date ranges from
as_of_date + the split's rulebook parameters + calendar rows. The rulebook of the
split being answered always wins over configs/rules_defaults.yaml.

Matching runs on fold(text) (lowercase, no diacritics, same length as the NFC text),
so it is robust to missing diacritics; mentions are sliced from the original text.
"""
from __future__ import annotations

import calendar as _cal
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Sequence

from datamate.core import Period
from datamate.understanding.textutil import fold

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "thu hai": 0, "thu ba": 1, "thu tu": 2, "thu nam": 3, "thu sau": 4, "thu bay": 5, "chu nhat": 6,
}
ENGLISH_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NUMBER_WORDS = {
    "mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5, "sau": 6, "bay": 7, "tam": 8, "chin": 9, "muoi": 10,
    "muoi mot": 11, "muoi hai": 12, "muoi lam": 15, "hai muoi": 20, "ba muoi": 30,
}
_BOOL_KEYS = ("month_to_as_of", "quarter_to_as_of", "year_to_as_of", "rolling_window_includes_as_of")
_INT_KEYS = ("pre_tet_days", "post_tet_days")
_ENUMS = {"this_week_mode": {"week_to_date", "full_week"}, "bare_cung_ky": {"year", "month"}}


# ------------------------------------------------------------------ date arithmetic

def month_end(year: int, month: int) -> date:
    return date(year, month, _cal.monthrange(year, month)[1])


def add_months(d: date, n: int) -> date:
    year, month0 = divmod(d.year * 12 + d.month - 1 + n, 12)
    month = month0 + 1
    return date(year, month, min(d.day, _cal.monthrange(year, month)[1]))


def week_begin(d: date, start_index: int) -> date:
    return d - timedelta(days=(d.weekday() - start_index) % 7)


def quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def quarter_end(d: date) -> date:
    first = quarter_start(d)
    return month_end(first.year, first.month + 2)


def _parse_iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


# ------------------------------------------------------------------ rule parameters

def json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(value, dict):
            objects.append(value)
        index = text.find("{", end)
    return objects


def _week_start_from_prose(rulebook: str) -> str | None:
    text = fold(unicodedata.normalize("NFC", rulebook))
    match = re.search(r"weeks?\s+start(?:s)?\s+(?:on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", text)
    if match:
        return match.group(1)
    match = re.search(r"tuan\s*:?\s*(thu hai|chu nhat)\b", text)
    if match:
        return "monday" if match.group(1) == "thu hai" else "sunday"
    return None


def _valid(key: str, value: Any, default: Any) -> Any:
    """Return the validated value or raise ValueError."""
    if key == "week_start":
        name = fold(str(value)).strip()
        if name in WEEKDAYS:
            return ENGLISH_DAYS[WEEKDAYS[name]]
        raise ValueError(key)
    if key in _BOOL_KEYS:
        if isinstance(value, bool):
            return value
        if str(value).lower() in {"true", "false"}:
            return str(value).lower() == "true"
        raise ValueError(key)
    if key in _INT_KEYS:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        raise ValueError(key)
    if key in _ENUMS:
        if value in _ENUMS[key]:
            return value
        raise ValueError(key)
    if key in ("tet_lunar_start", "tet_lunar_end"):
        if isinstance(value, str) and re.fullmatch(r"\d{1,2}-\d{1,2}", value):
            return value
        raise ValueError(key)
    raise ValueError(key)


def parse_rule_params(rulebook: str, defaults: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Effective time parameters: rulebook of the current split over defaults.

    Returns (params, sources, warnings); sources[key] is "rulebook", "rulebook_prose" or "default".
    """
    params: dict[str, Any] = {"week_start": (defaults.get("week") or {}).get("starts_on", "monday")}
    params.update(defaults.get("time") or {})
    sources = {key: "default" for key in params}
    warnings: list[str] = []
    found = False
    for block in json_objects(rulebook or ""):
        for key, value in block.items():
            if key not in params:
                continue
            found = True
            try:
                params[key] = _valid(key, value, params[key])
                sources[key] = "rulebook"
            except ValueError:
                warnings.append(f"rulebook_param_invalid:{key}")
    if not found and "{" in (rulebook or "") and "json" in (rulebook or "").lower():
        warnings.append("rulebook_json_unreadable")
    if sources.get("week_start") != "rulebook":
        prose = _week_start_from_prose(rulebook or "")
        if prose:
            params["week_start"] = prose
            sources["week_start"] = "rulebook_prose"
    return params, sources, warnings


# ------------------------------------------------------------------ calendar / Tết

def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def tet_windows(calendar: Sequence[Mapping[str, str]], params: Mapping[str, Any]) -> list[tuple[date, date]]:
    """Tết windows as (start, end) from calendar flags or lunar columns, never hard-coded."""
    rows = [(d, row) for row in calendar if (d := _parse_iso(row.get("date"))) is not None]
    rows.sort(key=lambda pair: pair[0])
    flagged: list[date] = []
    if any(("is_tet_window" in row or "is_tet" in row) for _, row in rows):
        flagged = [d for d, row in rows if _truthy(row.get("is_tet_window", row.get("is_tet", "0")))]
    elif any(("lunar_month" in row and "lunar_day" in row) for _, row in rows):
        def pair(text: str) -> tuple[int, int]:
            month, day = text.split("-")
            return int(month), int(day)
        start, end = pair(str(params["tet_lunar_start"])), pair(str(params["tet_lunar_end"]))
        for d, row in rows:
            try:
                value = (int(row["lunar_month"]), int(row["lunar_day"]))
            except (KeyError, ValueError):
                continue
            inside = (value >= start or value <= end) if start > end else (start <= value <= end)
            if inside:
                flagged.append(d)
    windows: list[tuple[date, date]] = []
    for d in flagged:
        if windows and (d - windows[-1][1]).days == 1:
            windows[-1] = (windows[-1][0], d)
        else:
            windows.append((d, d))
    return windows


# ------------------------------------------------------------------ resolution core

@dataclass(frozen=True)
class _Spec:
    label: str
    start: date
    end: date
    relative: str | None = None   # "week"|"month"|"quarter"|"year"|"period": shift of the primary period


_CONSUME = object()  # matched but yields no period (e.g. "tính đến hôm nay")


class _Ctx:
    def __init__(self, as_of: date, params: Mapping[str, Any], tets: list[tuple[date, date]]):
        self.as_of, self.params, self.tets = as_of, params, tets
        self.warnings: list[str] = []
        self.week_index = WEEKDAYS.get(str(params.get("week_start", "monday")), 0)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def begin_of_week(self) -> date:
        return week_begin(self.as_of, self.week_index)


def _num(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(re.sub(r"\s+", " ", token))


def _month_span(ctx: _Ctx, month: int, year: int | None, label: str = "explicit_month") -> _Spec | None:
    if not 1 <= month <= 12:
        return None
    inferred = year is None
    y = ctx.as_of.year if inferred else year
    if inferred and date(y, month, 1) > ctx.as_of:
        y -= 1
        ctx.warn(f"year_inferred_previous:{label}")
    elif inferred:
        ctx.warn(f"year_inferred_current:{label}")
    end = month_end(y, month)
    if (y, month) == (ctx.as_of.year, ctx.as_of.month) and ctx.params["month_to_as_of"]:
        end = ctx.as_of
        ctx.warn("explicit_current_month_to_as_of")
    return _Spec(label, date(y, month, 1), end)


def _make_date(ctx: _Ctx, day: int, month: int, year: int | None) -> date | None:
    try:
        if year is not None:
            return date(year, month, day)
        value = date(ctx.as_of.year, month, day)
        if value > ctx.as_of:
            value = date(ctx.as_of.year - 1, month, day)
            ctx.warn("year_inferred_previous:explicit_date")
        else:
            ctx.warn("year_inferred_current:explicit_date")
        return value
    except ValueError:
        return None


_DAY = (r"(?:ngay\s*)?\d{1,2}(?:\s*[/\-.]\s*\d{1,2}(?:\s*[/\-.]\s*\d{2,4})?"
        r"|\s*thang\s*\d{1,2}(?:\s*nam\s*\d{4})?)?")
_MON = r"thang\s*\d{1,2}(?:\s*(?:/|-|nam)\s*\d{4})?"
_ATOM = rf"(?:{_MON}|{_DAY})"
_ATOM_MONTH = re.compile(r"^thang\s*(\d{1,2})(?:\s*(?:/|-|nam)\s*(\d{4}))?$")
_ATOM_DMY = re.compile(r"^(?:ngay\s*)?(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?$")
_ATOM_DM_WORDS = re.compile(r"^(?:ngay\s*)?(\d{1,2})\s*thang\s*(\d{1,2})(?:\s*nam\s*(\d{4}))?$")
_ATOM_DAY = re.compile(r"^(?:ngay\s*)?(\d{1,2})$")


def _parse_atom(text: str) -> tuple[str, int | None, int | None, int | None] | None:
    """(kind, day, month, year) with kind in {'month','day'}; day-only has month None."""
    text = text.strip()
    if m := _ATOM_MONTH.match(text):
        return "month", None, int(m.group(1)), int(m.group(2)) if m.group(2) else None
    for rx in (_ATOM_DMY, _ATOM_DM_WORDS):
        if m := rx.match(text):
            year = int(m.group(3)) if m.group(3) else None
            if year is not None and year < 100:
                year += 2000
            return "day", int(m.group(1)), int(m.group(2)), year
    if m := _ATOM_DAY.match(text):
        return "day", int(m.group(1)), None, None
    return None


def _handle_range(ctx: _Ctx, m: re.Match) -> Any:
    a, b = _parse_atom(m.group("a")), _parse_atom(m.group("b"))
    if a is None or b is None:
        return None
    (ka, da, ma, ya), (kb, db, mb, yb) = a, b
    if ka == "day" and kb == "day":
        ma = ma if ma is not None else mb
        mb = mb if mb is not None else ma
        if ma is None or mb is None:
            return None
        ya = ya if ya is not None else yb
        yb = yb if yb is not None else ya
        end = _make_date(ctx, db, mb, yb)
        if end is None:
            ctx.warn("invalid_date_in_range")
            return _CONSUME
        start = _make_date(ctx, da, ma, ya if ya is not None else end.year)
        if start is not None and ya is None and start > end:
            start = _make_date(ctx, da, ma, end.year - 1)
        if start is None:
            ctx.warn("invalid_date_in_range")
            return _CONSUME
    else:
        first = _month_span(ctx, ma, ya) if ka == "month" else None
        last = _month_span(ctx, mb, yb) if kb == "month" else None
        start = first.start if first else _make_date(ctx, da or 1, ma or 1, ya)
        end = last.end if last else _make_date(ctx, db or 1, mb or 1, yb)
        if start is None or end is None:
            ctx.warn("invalid_date_in_range")
            return _CONSUME
    if start > end:
        start, end = end, start
        ctx.warn("range_endpoints_swapped")
    return _Spec("explicit_range", start, end)


def _handle_range_to_today(ctx: _Ctx, m: re.Match) -> Any:
    atom = _parse_atom(m.group("a"))
    if atom is None:
        return None
    kind, day, month, year = atom
    if kind == "month":
        span = _month_span(ctx, month, year)
        start = span.start if span else None
    elif month is not None:
        start = _make_date(ctx, day, month, year)
    else:
        start = _make_date(ctx, day, ctx.as_of.month, ctx.as_of.year)
    if start is None:
        ctx.warn("invalid_date_in_range")
        return _CONSUME
    return _Spec("explicit_range", min(start, ctx.as_of), ctx.as_of)


def _handle_dmy(ctx: _Ctx, m: re.Match) -> Any:
    year = int(m.group("y")) if m.groupdict().get("y") else None
    value = _make_date(ctx, int(m.group("d")), int(m.group("m")), year)
    if value is None:
        if year is not None or int(m.group("m")) > 12 or int(m.group("d")) > 31:
            return None
        ctx.warn("invalid_date")
        return _CONSUME
    return _Spec("explicit_date", value, value)


def _handle_month_year(ctx: _Ctx, m: re.Match) -> Any:
    year = int(m.group("y")) if m.groupdict().get("y") else None
    return _month_span(ctx, int(m.group("m")), year)


def _handle_quarter_explicit(ctx: _Ctx, m: re.Match) -> Any:
    roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
    q = int(m.group("q")) if m.group("q").isdigit() else roman[m.group("q")]
    year = int(m.group("y")) if m.group("y") else None
    y = ctx.as_of.year if year is None else year
    start = date(y, 3 * (q - 1) + 1, 1)
    if year is None and start > ctx.as_of:
        y -= 1
        start = date(y, 3 * (q - 1) + 1, 1)
        ctx.warn("year_inferred_previous:explicit_quarter")
    end = month_end(y, start.month + 2)
    if year is None:
        ctx.warn("year_inferred_current:explicit_quarter") if y == ctx.as_of.year else None
    return _Spec("explicit_quarter", start, end)


def _handle_year_explicit(ctx: _Ctx, m: re.Match) -> Any:
    y = int(m.group("y"))
    end = date(y, 12, 31)
    if y == ctx.as_of.year and ctx.params["year_to_as_of"]:
        end = ctx.as_of
    return _Spec("explicit_year", date(y, 1, 1), end)


def _relative_unit(unit: str) -> str:
    return {"tuan": "week", "thang": "month", "quy": "quarter", "nam": "year", "ky": "period"}[unit]


def _handle_prior_of_primary(ctx: _Ctx, m: re.Match) -> Any:
    return _Spec("previous_" + _relative_unit(m.group("u")), ctx.as_of, ctx.as_of, relative=_relative_unit(m.group("u")))


def _same_period(mode: str) -> Callable[[_Ctx, re.Match], Any]:
    """mode: "year" | "month" | "bare" (bare falls back to params['bare_cung_ky'])."""
    def handler(ctx: _Ctx, m: re.Match) -> Any:
        as_of = ctx.as_of
        use_month = mode == "month" or (mode == "bare" and ctx.params["bare_cung_ky"] == "month")
        if mode == "bare":
            ctx.warn("ambiguous_cung_ky_assumed_" + ("month" if use_month else "year"))
        anchor = add_months(as_of.replace(day=1), -1) if use_month else date(as_of.year - 1, as_of.month, 1)
        end = date(anchor.year, anchor.month, min(as_of.day, _cal.monthrange(anchor.year, anchor.month)[1]))
        return _Spec("same_period_last_month" if use_month else "same_period_last_year", anchor, end)
    return handler


def _handle_tet(ctx: _Ctx, m: re.Match) -> Any:
    ended = [w for w in ctx.tets if w[1] <= ctx.as_of]
    if not ended:
        ctx.warn("tet_window_not_found")
        return _CONSUME
    if any(w[0] <= ctx.as_of < w[1] for w in ctx.tets):
        ctx.warn("as_of_inside_tet_window_using_previous")
    start, end = ended[-1]
    which = m.groupdict().get("w")
    if which == "truoc":
        days = int(ctx.params["pre_tet_days"])
        ctx.warn("pre_tet_window_is_assumption")
        return _Spec("before_tet", start - timedelta(days=days), start - timedelta(days=1))
    if which == "sau":
        days = int(ctx.params["post_tet_days"])
        ctx.warn("post_tet_window_is_assumption")
        return _Spec("after_tet", end + timedelta(days=1), min(end + timedelta(days=days), ctx.as_of))
    return _Spec("tet", start, end)


def _handle_rolling(ctx: _Ctx, m: re.Match) -> Any:
    n = _num(m.group("n")) if m.groupdict().get("n") else 1
    if not n:
        return None
    if not m.groupdict().get("n"):
        ctx.warn("bare_rolling_window_assumes_one_unit")
    unit = m.group("u")
    include = bool(ctx.params["rolling_window_includes_as_of"])
    as_of = ctx.as_of
    if unit == "ngay":
        start = as_of - timedelta(days=n - 1 if include else n)
    elif unit == "tuan":
        start = as_of - timedelta(days=7 * n - 1 if include else 7 * n)
    elif unit == "thang":
        start = add_months(as_of, -n) + (timedelta(days=1) if include else timedelta(0))
    else:
        start = add_months(as_of, -12 * n) + (timedelta(days=1) if include else timedelta(0))
    return _Spec(f"last_{n}_{unit}", start, as_of if include else as_of - timedelta(days=1))


def _handle_upcoming(ctx: _Ctx, m: re.Match) -> Any:
    n = _num(m.group("n"))
    if not n:
        return None
    unit = m.group("u")
    end = {"ngay": ctx.as_of + timedelta(days=n), "tuan": ctx.as_of + timedelta(days=7 * n),
           "thang": add_months(ctx.as_of, n)}[unit]
    return _Spec(f"next_{n}_{unit}", ctx.as_of, end)


def _single(label: str, offset: int) -> Callable[[_Ctx, re.Match], Any]:
    def handler(ctx: _Ctx, m: re.Match) -> Any:
        d = ctx.as_of + timedelta(days=offset)
        return _Spec(label, d, d)
    return handler


def _week(which: str) -> Callable[[_Ctx, re.Match], Any]:
    def handler(ctx: _Ctx, m: re.Match) -> Any:
        begin = ctx.begin_of_week
        if which == "this":
            if ctx.params["this_week_mode"] == "week_to_date":
                return _Spec("this_week", begin, ctx.as_of)
            return _Spec("this_week", begin, begin + timedelta(days=6))
        if which == "last":
            return _Spec("last_week", begin - timedelta(days=7), begin - timedelta(days=1))
        return _Spec("next_week", begin + timedelta(days=7), begin + timedelta(days=13))
    return handler


def _month(which: str) -> Callable[[_Ctx, re.Match], Any]:
    def handler(ctx: _Ctx, m: re.Match) -> Any:
        first = ctx.as_of.replace(day=1)
        if which == "this":
            end = ctx.as_of if ctx.params["month_to_as_of"] else month_end(first.year, first.month)
            return _Spec("this_month", first, end)
        other = add_months(first, -1 if which == "last" else 1)
        return _Spec(f"{which}_month", other, month_end(other.year, other.month))
    return handler


def _quarter(which: str) -> Callable[[_Ctx, re.Match], Any]:
    def handler(ctx: _Ctx, m: re.Match) -> Any:
        first = quarter_start(ctx.as_of)
        if which == "this":
            end = ctx.as_of if ctx.params["quarter_to_as_of"] else quarter_end(ctx.as_of)
            return _Spec("this_quarter", first, end)
        other = add_months(first, -3 if which == "last" else 3)
        return _Spec(f"{which}_quarter", other, quarter_end(other))
    return handler


def _year(which: str) -> Callable[[_Ctx, re.Match], Any]:
    def handler(ctx: _Ctx, m: re.Match) -> Any:
        y = ctx.as_of.year
        if which == "this":
            end = ctx.as_of if ctx.params["year_to_as_of"] else date(y, 12, 31)
            return _Spec("this_year", date(y, 1, 1), end)
        return _Spec("last_year", date(y - 1, 1, 1), date(y - 1, 12, 31))
    return handler


def _handle_weekend(ctx: _Ctx, m: re.Match) -> Any:
    which = m.groupdict().get("q") or ""
    if which == "nay":
        begin = ctx.begin_of_week
        saturday = begin + timedelta(days=(5 - ctx.week_index) % 7)
        ctx.warn("weekend_this_week_assumption")
        return _Spec("weekend_this_week", saturday, saturday + timedelta(days=1))
    saturday = ctx.as_of - timedelta(days=(ctx.as_of.weekday() - 5) % 7)
    if saturday + timedelta(days=1) > ctx.as_of:
        saturday -= timedelta(days=7)
    ctx.warn("weekend_is_latest_completed_saturday_sunday")
    return _Spec("last_weekend", saturday, saturday + timedelta(days=1))


_NUM = (r"(?P<n>\d{1,3}|muoi\s+(?:mot|hai|lam)|(?:hai|ba)\s+muoi|mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi)")
_B = r"(?<![a-z0-9])"
_E = r"(?![a-z0-9])"
_LAST = r"(?:roi|truoc|vua\s+roi|vua\s+qua|lien\s+truoc)"
_NEXT = r"(?:sau|toi|ke\s+tiep|tiep\s+theo)"

# Ordered specific -> general. Earlier patterns consume their span first.
_PATTERNS: list[tuple[str, re.Pattern, Callable[[_Ctx, re.Match], Any]]] = [
    ("range_to_today", re.compile(rf"{_B}tu\s+(?P<a>{_ATOM})\s+(?:den|toi)\s+(?:nay|hom\s+nay){_E}"), _handle_range_to_today),
    ("range", re.compile(rf"{_B}tu\s+(?P<a>{_ATOM})\s+(?:den|toi)\s+(?P<b>{_ATOM}){_E}"), _handle_range),
    ("until_today", re.compile(rf"{_B}(?:tinh\s+)?(?:cho\s+)?(?:den|toi)\s+(?:het\s+)?(?:ngay\s+)?(?:hom\s+)?nay{_E}"),
     lambda ctx, m: _CONSUME),
    ("prior_of_primary", re.compile(rf"{_B}(?P<u>tuan|thang|quy|nam)\s+(?:lien\s+)?truoc\s+do{_E}"), _handle_prior_of_primary),
    ("prior_period", re.compile(rf"{_B}(?P<u>ky)\s+truoc(?:\s+do)?{_E}"), _handle_prior_of_primary),
    ("same_period_month", re.compile(rf"{_B}cung\s+ky\s+thang\s+(?:truoc|roi|vua\s+roi){_E}"), _same_period("month")),
    ("same_period_year", re.compile(rf"{_B}cung\s+ky\s+(?:nam\s+)?(?:ngoai|truoc|roi){_E}"), _same_period("year")),
    ("same_period_bare", re.compile(rf"{_B}cung\s+ky{_E}"), _same_period("bare")),
    ("tet_relative", re.compile(rf"{_B}(?P<w>truoc|sau)\s+(?:dip\s+)?tet{_E}"), _handle_tet),
    ("tet", re.compile(rf"{_B}(?:dip\s+)?tet(?:\s+gan\s+nhat)?{_E}"), _handle_tet),
    ("rolling", re.compile(rf"{_B}{_NUM}\s*(?P<u>ngay|tuan|thang|nam)\s+(?:vua\s+)?(?:qua|gan\s+day|vua\s+roi){_E}"), _handle_rolling),
    ("upcoming", re.compile(rf"{_B}{_NUM}\s*(?P<u>ngay|tuan|thang)\s+(?:toi|nua|sau|sap\s+toi){_E}"), _handle_upcoming),
    ("rolling_bare", re.compile(rf"{_B}(?P<u>tuan|thang)\s+(?:vua\s+)?qua{_E}"), _handle_rolling),
    ("date_full", re.compile(rf"(?<![\d/\-.])(?:ngay\s*)?(?P<d>\d{{1,2}})\s*[/\-.]\s*(?P<m>\d{{1,2}})\s*[/\-.]\s*(?P<y>\d{{4}}){_E}"), _handle_dmy),
    ("date_words", re.compile(rf"{_B}ngay\s+(?P<d>\d{{1,2}})\s+thang\s+(?P<m>\d{{1,2}})(?:\s+nam\s+(?P<y>\d{{4}}))?(?![\d/])"), _handle_dmy),
    ("date_slash_ngay", re.compile(rf"{_B}ngay\s+(?P<d>\d{{1,2}})\s*[/\-.]\s*(?P<m>\d{{1,2}})(?![\d/\-.])"), _handle_dmy),
    ("month_year_slash", re.compile(rf"{_B}thang\s*(?P<m>\d{{1,2}})\s*[/\-]\s*(?P<y>\d{{4}}){_E}"), _handle_month_year),
    ("month_year_words", re.compile(rf"{_B}thang\s*(?P<m>\d{{1,2}})\s+nam\s+(?P<y>\d{{4}}){_E}"), _handle_month_year),
    ("month_number", re.compile(rf"{_B}thang\s*(?P<m>\d{{1,2}})(?![\d/])"), _handle_month_year),
    ("date_slash", re.compile(r"(?<![\d/\-.])(?P<d>\d{1,2})/(?P<m>\d{1,2})(?![\d/])"), _handle_dmy),
    ("quarter_explicit", re.compile(rf"{_B}quy\s*(?P<q>[1-4]|iv|iii|ii|i)(?:\s*(?:/|-|nam)\s*(?P<y>\d{{4}}))?{_E}"), _handle_quarter_explicit),
    ("year_explicit", re.compile(rf"{_B}nam\s+(?P<y>(?:19|20)\d{{2}})(?!\d)"), _handle_year_explicit),
    ("weekend", re.compile(rf"{_B}cuoi\s+tuan(?:\s+(?P<q>nay|roi|truoc|vua\s+roi))?{_E}"), _handle_weekend),
    ("today", re.compile(rf"{_B}(?:ngay\s+)?hom\s+nay{_E}"), _single("today", 0)),
    ("yesterday", re.compile(rf"{_B}(?:ngay\s+)?hom\s+qua{_E}"), _single("yesterday", -1)),
    ("day_before_yesterday", re.compile(rf"{_B}(?:ngay\s+)?hom\s+kia{_E}"), _single("day_before_yesterday", -2)),
    ("this_week", re.compile(rf"{_B}tuan\s+nay{_E}"), _week("this")),
    ("last_week", re.compile(rf"{_B}tuan\s+{_LAST}{_E}"), _week("last")),
    ("next_week", re.compile(rf"{_B}tuan\s+{_NEXT}{_E}"), _week("next")),
    ("this_month", re.compile(rf"{_B}thang\s+nay{_E}"), _month("this")),
    ("last_month", re.compile(rf"{_B}thang\s+{_LAST}{_E}"), _month("last")),
    ("next_month", re.compile(rf"{_B}thang\s+{_NEXT}{_E}"), _month("next")),
    ("this_quarter", re.compile(rf"{_B}quy\s+nay{_E}"), _quarter("this")),
    ("last_quarter", re.compile(rf"{_B}quy\s+{_LAST}{_E}"), _quarter("last")),
    ("next_quarter", re.compile(rf"{_B}quy\s+{_NEXT}{_E}"), _quarter("next")),
    ("this_year", re.compile(rf"{_B}nam\s+nay{_E}"), _year("this")),
    ("last_year", re.compile(rf"{_B}nam\s+(?:ngoai|truoc|roi|vua\s+roi){_E}"), _year("last")),
]

_MARKER = re.compile(r"(?:so\s+voi|so\s+sanh\s+voi|doi\s+chieu\s+voi|so\s+cung\s+voi)$")


def _shift_prior(base: Period | None, unit: str, ctx: _Ctx) -> tuple[date, date]:
    if base is None:
        ctx.warn("relative_period_without_primary")
        base_start = base_end = ctx.as_of
    else:
        base_start, base_end = base.start, base.end
    if unit == "week":
        return base_start - timedelta(days=7), base_end - timedelta(days=7)
    if unit == "month":
        first = add_months(base_start.replace(day=1), -1)
        return first, month_end(first.year, first.month)
    if unit == "quarter":
        first = add_months(quarter_start(base_start), -3)
        return first, quarter_end(first)
    if unit == "year":
        return date(base_start.year - 1, 1, 1), date(base_start.year - 1, 12, 31)
    length = (base_end - base_start).days + 1
    return base_start - timedelta(days=length), base_start - timedelta(days=1)


def resolve_periods(text: str, as_of: date, params: Mapping[str, Any],
                    calendar: Sequence[Mapping[str, str]] = ()) -> tuple[list[Period], list[str]]:
    """Resolve time expressions in `text` to inclusive Periods. Never raises."""
    text = unicodedata.normalize("NFC", text)
    folded = fold(text)
    ctx = _Ctx(as_of, params, tet_windows(calendar, params))
    consumed = [False] * len(folded)
    hits: list[tuple[int, int, _Spec]] = []
    for name, rx, handler in _PATTERNS:
        for match in rx.finditer(folded):
            start, end = match.span()
            if any(consumed[start:end]):
                continue
            try:
                spec = handler(ctx, match)
            except Exception as error:  # noqa: BLE001 - a bad expression must not lose the question
                ctx.warn(f"temporal_error:{name}:{type(error).__name__}")
                spec = _CONSUME
            if spec is None:
                continue
            for i in range(start, end):
                consumed[i] = True
            if spec is not _CONSUME:
                hits.append((start, end, spec))
    hits.sort(key=lambda hit: hit[0])

    periods: list[Period] = []
    primary: Period | None = None
    for start, end, spec in hits:
        mention = text[start:end]
        marker = bool(_MARKER.search(folded[:start].rstrip()))
        s, e = spec.start, spec.end
        if spec.relative:
            s, e = _shift_prior(primary, spec.relative, ctx)
            role = "comparison"
        elif primary is None and not marker:
            role = "primary"
        else:
            role = "comparison"
            if not marker and primary is not None:
                ctx.warn("multiple_periods_without_comparison_marker")
        period = Period(spec.label, s, e, role, mention)
        if role == "primary":
            primary = period
        periods.append(period)

    lows = [d for d in (_parse_iso(r.get("date")) for r in calendar) if d is not None]
    for period in periods:
        if period.end > as_of:
            ctx.warn(f"future_period:{period.label}")
        if lows and (period.start < min(lows) or period.end > max(lows)):
            ctx.warn(f"outside_calendar_range:{period.label}")
    return periods, ctx.warnings


def remove_mentions(text: str, periods: Sequence[Period]) -> str:
    """Text without the time words of the resolved periods (for entity detection)."""
    text = unicodedata.normalize("NFC", text)
    folded = fold(text)
    mask = [False] * len(text)
    for period in periods:
        needle = fold(period.mention)
        position = folded.find(needle) if needle else -1
        while position != -1:
            for i in range(position, position + len(needle)):
                mask[i] = True
            position = folded.find(needle, position + len(needle))
    kept = "".join(ch for ch, hidden in zip(text, mask) if not hidden)
    return " ".join(kept.split())
