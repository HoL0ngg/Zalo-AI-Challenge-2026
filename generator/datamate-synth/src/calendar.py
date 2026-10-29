"""Vietnamese lunar calendar (GMT+7); astronomical algorithm by Ho Ngoc Duc.

Calculation is self-contained, without internet or third-party astronomy packages.
The calendar supplies real lunar dates for Tết and Trung thu, not Gregorian guesses.
"""
from __future__ import annotations
import csv
import math
from datetime import date, timedelta
from pathlib import Path

PI = math.pi
TZ = 7


def jd_from_date(dd: int, mm: int, yy: int) -> int:
    a = (14 - mm) // 12
    y, m = yy + 4800 - a, mm + 12 * a - 3
    jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    if jd < 2299161:
        jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
    return jd


def new_moon(k: int) -> float:
    t = k / 1236.85
    t2, t3 = t * t, t * t * t
    dr = PI / 180
    jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * t2 - 0.000000155 * t3
    jd1 += 0.00033 * math.sin((166.56 + 132.87 * t - 0.009173 * t2) * dr)
    m = 359.2242 + 29.10535608 * k - 0.0000333 * t2 - 0.00000347 * t3
    mpr = 306.0253 + 385.81691806 * k + 0.0107306 * t2 + 0.00001236 * t3
    f = 21.2964 + 390.67050646 * k - 0.0016528 * t2 - 0.00000239 * t3
    c1 = (0.1734 - 0.000393 * t) * math.sin(m * dr) + 0.0021 * math.sin(2 * m * dr)
    c1 -= 0.4068 * math.sin(mpr * dr) + 0.0161 * math.sin(2 * mpr * dr)
    c1 -= 0.0004 * math.sin(3 * mpr * dr)
    c1 += 0.0104 * math.sin(2 * f * dr) - 0.0051 * math.sin((m + mpr) * dr)
    c1 -= 0.0074 * math.sin((m - mpr) * dr) + 0.0004 * math.sin((2 * f + m) * dr)
    c1 -= 0.0004 * math.sin((2 * f - m) * dr) - 0.0006 * math.sin((2 * f + mpr) * dr)
    c1 += 0.0010 * math.sin((2 * f - mpr) * dr) + 0.0005 * math.sin((2 * mpr + m) * dr)
    if t < -11:
        delta_t = 0.001 + 0.000839 * t + 0.0002261 * t2 - 0.00000845 * t3 - 0.000000081 * t * t3
    else:
        delta_t = -0.000278 + 0.000265 * t + 0.000262 * t2
    return jd1 + c1 - delta_t


def sun_longitude(jdn: float) -> float:
    t = (jdn - 2451545.0) / 36525
    t2 = t * t
    dr = PI / 180
    m = 357.52910 + 35999.05030 * t - 0.0001559 * t2 - 0.00000048 * t * t2
    l0 = 280.46645 + 36000.76983 * t + 0.0003032 * t2
    dl = (1.914600 - 0.004817 * t - 0.000014 * t2) * math.sin(dr * m)
    dl += (0.019993 - 0.000101 * t) * math.sin(2 * dr * m) + 0.000290 * math.sin(3 * dr * m)
    l = (l0 + dl) * dr
    return l - PI * 2 * math.floor(l / (PI * 2))


def new_moon_day(k: int) -> int:
    return math.floor(new_moon(k) + 0.5 + TZ / 24)


def get_sun_longitude(day: int) -> int:
    return math.floor(sun_longitude(day - 0.5 - TZ / 24) / PI * 6)


def lunar_month_11(year: int) -> int:
    off = jd_from_date(31, 12, year) - 2415021
    k = math.floor(off / 29.530588853)
    nm = new_moon_day(k)
    if get_sun_longitude(nm) >= 9:
        nm = new_moon_day(k - 1)
    return nm


def leap_month_offset(a11: int) -> int:
    k = math.floor(0.5 + (a11 - 2415021.076998695) / 29.530588853)
    last, i = 0, 1
    arc = get_sun_longitude(new_moon_day(k + i))
    while arc != last and i < 14:
        last = arc
        i += 1
        arc = get_sun_longitude(new_moon_day(k + i))
    return i - 1


def solar_to_lunar(day: date) -> tuple[int, int, int, bool]:
    jd = jd_from_date(day.day, day.month, day.year)
    k = math.floor((jd - 2415021.076998695) / 29.530588853)
    month_start = new_moon_day(k + 1)
    if month_start > jd:
        month_start = new_moon_day(k)
    a11 = lunar_month_11(day.year)
    b11 = a11
    if a11 >= month_start:
        lunar_year = day.year
        a11 = lunar_month_11(day.year - 1)
    else:
        lunar_year = day.year + 1
        b11 = lunar_month_11(day.year + 1)
    lunar_day = jd - month_start + 1
    diff = math.floor((month_start - a11) / 29)
    lunar_month = diff + 11
    leap = False
    if b11 - a11 > 365:
        leap_diff = leap_month_offset(a11)
        if diff >= leap_diff:
            lunar_month = diff + 10
            if diff == leap_diff:
                leap = True
    if lunar_month > 12:
        lunar_month -= 12
    if lunar_month >= 11 and diff < 4:
        lunar_year -= 1
    return int(lunar_day), int(lunar_month), int(lunar_year), leap


def build_calendar(path: Path, first: date = date(2024, 1, 1), last: date = date(2027, 12, 31)) -> None:
    days = []
    d = first
    while d <= last:
        ld, lm, _, _ = solar_to_lunar(d)
        days.append((d.isoformat(), d.weekday(), ld, lm, int((lm == 12 and ld >= 23) or (lm == 1 and ld <= 10))))
        d += timedelta(days=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        wr = csv.writer(f, lineterminator='\n')
        wr.writerow(['date', 'weekday', 'lunar_day', 'lunar_month', 'is_tet_window'])
        wr.writerows(days)


if __name__ == '__main__':
    for d in ['2025-01-29', '2026-02-17', '2027-02-06', '2026-02-10']:
        print(d, solar_to_lunar(date.fromisoformat(d)))
