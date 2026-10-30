"""Table-driven tests for the rule-based temporal resolver (no I/O, no LLM)."""
from datetime import date, timedelta

import pytest

from datamate.understanding.resources import load_rule_defaults
from datamate.understanding.temporal import (parse_rule_params, remove_mentions, resolve_periods,
                                             tet_windows)

DEFAULTS = load_rule_defaults()
TRAIN_RULEBOOK = '''# Rulebook
Tuần: Thứ hai–Chủ nhật.
```json
{"month_to_as_of": true, "tet_lunar_end": "01-10", "tet_lunar_start": "12-23", "week_start": "monday"}
```
'''
SUNDAY_RULEBOOK = TRAIN_RULEBOOK.replace('"monday"', '"sunday"')
TET_2025 = (date(2025, 1, 22), date(2025, 2, 7))
TET_2026 = (date(2026, 2, 10), date(2026, 2, 26))


def make_calendar(windows=(TET_2025, TET_2026), first=date(2024, 1, 1), last=date(2027, 12, 31),
                  flag="is_tet_window", lunar=False):
    rows = []
    day = first
    while day <= last:
        inside = any(a <= day <= b for a, b in windows)
        row = {"date": day.isoformat()}
        if lunar:
            window = next(((a, b) for a, b in windows if a <= day <= b), None)
            if window:
                offset = (day - window[0]).days
                row.update(lunar_month="12" if offset < 8 else "1", lunar_day=str(23 + offset if offset < 8 else offset - 7))
            else:
                row.update(lunar_month="6", lunar_day="15")
        else:
            row[flag] = "1" if inside else "0"
        rows.append(row)
        day += timedelta(days=1)
    return rows


CAL = make_calendar()


def params_for(rulebook=TRAIN_RULEBOOK):
    return parse_rule_params(rulebook, DEFAULTS)[0]


def resolve(text, as_of, rulebook=TRAIN_RULEBOOK, calendar=CAL, **override):
    params = {**params_for(rulebook), **override}
    return resolve_periods(text, as_of, params, calendar)


def first(text, as_of, **kwargs):
    periods, warnings = resolve(text, as_of, **kwargs)
    assert periods, (text, as_of, warnings)
    return periods[0], warnings


D = date


@pytest.mark.parametrize("text,as_of,label,start,end", [
    # single days
    ("hôm nay", D(2026, 5, 14), "today", D(2026, 5, 14), D(2026, 5, 14)),
    ("Hôm qua doanh thu bao nhiêu?", D(2026, 8, 23), "yesterday", D(2026, 8, 22), D(2026, 8, 22)),
    ("hôm kia", D(2026, 3, 1), "day_before_yesterday", D(2026, 2, 27), D(2026, 2, 27)),
    ("hom qua", D(2026, 1, 1), "yesterday", D(2025, 12, 31), D(2025, 12, 31)),  # year boundary, no diacritics
    # weeks (Monday start): as_of Monday, Wednesday, Sunday
    ("tuần này", D(2026, 3, 9), "this_week", D(2026, 3, 9), D(2026, 3, 9)),
    ("tuần rồi", D(2026, 3, 9), "last_week", D(2026, 3, 2), D(2026, 3, 8)),
    ("Tuần rồi có bao nhiêu đơn", D(2026, 3, 11), "last_week", D(2026, 3, 2), D(2026, 3, 8)),
    ("tuần này", D(2026, 3, 15), "this_week", D(2026, 3, 9), D(2026, 3, 15)),
    ("tuần trước", D(2026, 3, 15), "last_week", D(2026, 3, 2), D(2026, 3, 8)),
    ("tuần vừa rồi", D(2026, 3, 15), "last_week", D(2026, 3, 2), D(2026, 3, 8)),
    ("tuần sau", D(2026, 3, 11), "next_week", D(2026, 3, 16), D(2026, 3, 22)),
    ("tuần rồi", D(2026, 1, 5), "last_week", D(2025, 12, 29), D(2026, 1, 4)),  # crosses the year
    # months
    ("tháng này", D(2026, 5, 14), "this_month", D(2026, 5, 1), D(2026, 5, 14)),
    ("tháng này", D(2026, 3, 1), "this_month", D(2026, 3, 1), D(2026, 3, 1)),
    ("tháng này", D(2026, 3, 31), "this_month", D(2026, 3, 1), D(2026, 3, 31)),
    ("tháng trước", D(2026, 3, 31), "last_month", D(2026, 2, 1), D(2026, 2, 28)),
    ("tháng rồi", D(2026, 5, 31), "last_month", D(2026, 4, 1), D(2026, 4, 30)),
    ("tháng trước", D(2026, 1, 15), "last_month", D(2025, 12, 1), D(2025, 12, 31)),
    ("tháng trước", D(2028, 3, 31), "last_month", D(2028, 2, 1), D(2028, 2, 29)),  # leap February
    ("tháng sau", D(2026, 12, 20), "next_month", D(2027, 1, 1), D(2027, 1, 31)),
    # quarters and years
    ("quý này", D(2026, 8, 19), "this_quarter", D(2026, 7, 1), D(2026, 8, 19)),
    ("quý trước", D(2026, 2, 1), "last_quarter", D(2025, 10, 1), D(2025, 12, 31)),
    ("quý trước", D(2026, 8, 19), "last_quarter", D(2026, 4, 1), D(2026, 6, 30)),
    ("năm nay", D(2026, 8, 1), "this_year", D(2026, 1, 1), D(2026, 8, 1)),
    ("năm ngoái", D(2026, 8, 1), "last_year", D(2025, 1, 1), D(2025, 12, 31)),
    ("năm trước", D(2026, 1, 1), "last_year", D(2025, 1, 1), D(2025, 12, 31)),
    # same period (rulebook: day 1 .. matching day last year, clamped to month end)
    ("cùng kỳ năm ngoái", D(2026, 3, 31), "same_period_last_year", D(2025, 3, 1), D(2025, 3, 31)),
    ("Cùng kỳ năm ngoái mặt hàng nào bán nhiều nhất?", D(2026, 6, 4), "same_period_last_year", D(2025, 6, 1), D(2025, 6, 4)),
    ("cùng kỳ năm ngoái", D(2028, 2, 29), "same_period_last_year", D(2027, 2, 1), D(2027, 2, 28)),  # 29/2 clamp
    ("cùng kỳ năm ngoái", D(2027, 2, 28), "same_period_last_year", D(2026, 2, 1), D(2026, 2, 28)),
    ("cùng kỳ tháng trước", D(2026, 3, 31), "same_period_last_month", D(2026, 2, 1), D(2026, 2, 28)),  # 31 -> 28
    ("cùng kỳ tháng trước", D(2026, 5, 15), "same_period_last_month", D(2026, 4, 1), D(2026, 4, 15)),
    ("cùng kỳ tháng trước", D(2026, 1, 20), "same_period_last_month", D(2025, 12, 1), D(2025, 12, 20)),
    ("cung ky nam ngoai", D(2026, 6, 26), "same_period_last_year", D(2025, 6, 1), D(2025, 6, 26)),
    # rolling windows (as_of inclusive)
    ("30 ngày qua", D(2026, 8, 19), "last_30_ngay", D(2026, 7, 21), D(2026, 8, 19)),
    ("7 ngày qua", D(2026, 3, 1), "last_7_ngay", D(2026, 2, 23), D(2026, 3, 1)),
    ("ba mươi ngày qua", D(2026, 8, 19), "last_30_ngay", D(2026, 7, 21), D(2026, 8, 19)),
    ("2 tuần qua", D(2026, 8, 1), "last_2_tuan", D(2026, 7, 19), D(2026, 8, 1)),
    ("2 tháng qua", D(2026, 8, 31), "last_2_thang", D(2026, 7, 1), D(2026, 8, 31)),
    ("3 tháng qua", D(2026, 3, 31), "last_3_thang", D(2026, 1, 1), D(2026, 3, 31)),
    ("30 ngày tới", D(2026, 8, 19), "next_30_ngay", D(2026, 8, 19), D(2026, 9, 18)),
    # explicit dates, ranges, months
    ("ngày 5 tháng 3", D(2026, 8, 1), "explicit_date", D(2026, 3, 5), D(2026, 3, 5)),
    ("ngày 5 tháng 3", D(2026, 2, 1), "explicit_date", D(2025, 3, 5), D(2025, 3, 5)),  # future -> last year
    ("ngày 5 tháng 3 năm 2024", D(2026, 2, 1), "explicit_date", D(2024, 3, 5), D(2024, 3, 5)),
    ("ngày 05/03/2026", D(2026, 8, 1), "explicit_date", D(2026, 3, 5), D(2026, 3, 5)),
    ("5/3", D(2026, 8, 1), "explicit_date", D(2026, 3, 5), D(2026, 3, 5)),
    ("từ ngày 1 đến ngày 15 tháng 3", D(2026, 5, 1), "explicit_range", D(2026, 3, 1), D(2026, 3, 15)),
    ("từ 01/03/2026 đến 15/03/2026", D(2026, 5, 1), "explicit_range", D(2026, 3, 1), D(2026, 3, 15)),
    ("từ 20/12 đến 5/1", D(2026, 1, 10), "explicit_range", D(2025, 12, 20), D(2026, 1, 5)),
    ("từ tháng 1 đến tháng 3", D(2026, 8, 1), "explicit_range", D(2026, 1, 1), D(2026, 3, 31)),
    ("từ ngày 1/3 đến hôm nay", D(2026, 3, 20), "explicit_range", D(2026, 3, 1), D(2026, 3, 20)),
    ("tháng 3", D(2026, 8, 1), "explicit_month", D(2026, 3, 1), D(2026, 3, 31)),
    ("tháng 10", D(2026, 8, 1), "explicit_month", D(2025, 10, 1), D(2025, 10, 31)),  # future -> last year
    ("tháng 8", D(2026, 8, 19), "explicit_month", D(2026, 8, 1), D(2026, 8, 19)),    # current month = to as_of
    ("tháng 5 năm 2025", D(2026, 8, 1), "explicit_month", D(2025, 5, 1), D(2025, 5, 31)),
    ("Doanh thu trong tháng 01/2023 là bao nhiêu?", D(2026, 8, 20), "explicit_month", D(2023, 1, 1), D(2023, 1, 31)),
    ("tháng 2 năm 2024", D(2026, 8, 1), "explicit_month", D(2024, 2, 1), D(2024, 2, 29)),
    ("quý 2", D(2026, 8, 1), "explicit_quarter", D(2026, 4, 1), D(2026, 6, 30)),
    ("quý 4/2025", D(2026, 8, 1), "explicit_quarter", D(2025, 10, 1), D(2025, 12, 31)),
    ("năm 2025", D(2026, 8, 1), "explicit_year", D(2025, 1, 1), D(2025, 12, 31)),
    # weekend (Saturday + Sunday, latest completed)
    ("cuối tuần", D(2026, 8, 19), "last_weekend", D(2026, 8, 15), D(2026, 8, 16)),
    ("cuối tuần", D(2026, 8, 16), "last_weekend", D(2026, 8, 15), D(2026, 8, 16)),  # as_of Sunday
    ("cuối tuần", D(2026, 8, 15), "last_weekend", D(2026, 8, 8), D(2026, 8, 9)),    # as_of Saturday
    ("cuối tuần rồi", D(2026, 8, 17), "last_weekend", D(2026, 8, 15), D(2026, 8, 16)),
    ("cuối tuần này", D(2026, 8, 19), "weekend_this_week", D(2026, 8, 22), D(2026, 8, 23)),
    # Tết: latest window that ended on or before as_of
    ("Trong dịp Tết gần nhất", D(2026, 4, 25), "tet", *TET_2026),
    ("tết", D(2026, 2, 26), "tet", *TET_2026),                  # ends exactly on as_of
    ("Tết", D(2026, 2, 25), "tet", *TET_2025),                  # inside a window -> previous one
    ("dip tet gan nhat", D(2026, 8, 20), "tet", *TET_2026),
    ("trước Tết", D(2026, 8, 1), "before_tet", D(2026, 2, 3), D(2026, 2, 9)),
    ("sau Tết", D(2026, 8, 1), "after_tet", D(2026, 2, 27), D(2026, 3, 5)),
])
def test_expressions(text, as_of, label, start, end):
    period, _ = first(text, as_of)
    assert (period.label, period.start, period.end) == (label, start, end)
    assert period.role == "primary"


@pytest.mark.parametrize("as_of,text,label,start,end", [
    (D(2026, 3, 15), "tuần này", "this_week", D(2026, 3, 15), D(2026, 3, 15)),   # Sunday starts a new week
    (D(2026, 3, 15), "tuần rồi", "last_week", D(2026, 3, 8), D(2026, 3, 14)),
    (D(2026, 3, 14), "tuần này", "this_week", D(2026, 3, 8), D(2026, 3, 14)),    # Saturday ends it
    (D(2026, 3, 14), "tuần rồi", "last_week", D(2026, 3, 1), D(2026, 3, 7)),
    (D(2026, 3, 11), "tuần trước", "last_week", D(2026, 3, 1), D(2026, 3, 7)),
])
def test_week_start_sunday_from_rulebook(as_of, text, label, start, end):
    period, _ = first(text, as_of, rulebook=SUNDAY_RULEBOOK)
    assert (period.label, period.start, period.end) == (label, start, end)


def test_week_start_prose_and_json_precedence():
    params, sources, warnings = parse_rule_params("Tuần: Chủ nhật–Thứ bảy.", DEFAULTS)
    assert params["week_start"] == "sunday" and sources["week_start"] == "rulebook_prose" and not warnings
    params, sources, _ = parse_rule_params("Use recorded amounts. Weeks start Monday.", DEFAULTS)
    assert params["week_start"] == "monday" and sources["week_start"] == "rulebook_prose"
    params, sources, _ = parse_rule_params(SUNDAY_RULEBOOK, DEFAULTS)
    assert params["week_start"] == "sunday" and sources["week_start"] == "rulebook"


def test_rule_params_defaults_invalid_and_overrides():
    params, sources, warnings = parse_rule_params("no rules here", DEFAULTS)
    assert params["week_start"] == "monday" and params["month_to_as_of"] is True
    assert set(sources.values()) == {"default"} and not warnings
    bad = '```json\n{"week_start": "funday", "pre_tet_days": -3, "month_to_as_of": "maybe"}\n```'
    params, sources, warnings = parse_rule_params(bad, DEFAULTS)
    assert params["week_start"] == "monday" and params["pre_tet_days"] == 7
    assert sorted(warnings) == ["rulebook_param_invalid:month_to_as_of", "rulebook_param_invalid:pre_tet_days",
                                "rulebook_param_invalid:week_start"]
    params, _, warnings = parse_rule_params("```json\n{broken\n```", DEFAULTS)
    assert params["week_start"] == "monday" and warnings == ["rulebook_json_unreadable"]
    params, sources, _ = parse_rule_params('{"month_to_as_of": false, "tet_lunar_start": "12-20"}', DEFAULTS)
    assert params["month_to_as_of"] is False and params["tet_lunar_start"] == "12-20"
    assert sources["month_to_as_of"] == "rulebook" and sources["quarter_to_as_of"] == "default"


def test_named_parameters_change_behavior():
    period, _ = first("tháng này", D(2026, 5, 14), month_to_as_of=False)
    assert (period.start, period.end) == (D(2026, 5, 1), D(2026, 5, 31))
    period, _ = first("tuần này", D(2026, 3, 11), this_week_mode="full_week")
    assert (period.start, period.end) == (D(2026, 3, 9), D(2026, 3, 15))
    period, _ = first("quý này", D(2026, 8, 19), quarter_to_as_of=False)
    assert (period.start, period.end) == (D(2026, 7, 1), D(2026, 9, 30))
    period, _ = first("năm nay", D(2026, 8, 1), year_to_as_of=False)
    assert period.end == D(2026, 12, 31)
    period, _ = first("30 ngày qua", D(2026, 8, 19), rolling_window_includes_as_of=False)
    assert (period.start, period.end) == (D(2026, 7, 20), D(2026, 8, 18))
    period, _ = first("sau Tết", D(2026, 8, 1), post_tet_days=3)
    assert period.end == D(2026, 3, 1)
    period, warnings = first("cùng kỳ", D(2026, 5, 15), bare_cung_ky="month")
    assert period.label == "same_period_last_month" and "ambiguous_cung_ky_assumed_month" in warnings


def test_comparison_pairs():
    periods, warnings = resolve("Doanh thu tháng này tăng trưởng bao nhiêu phần trăm so với tháng trước?", D(2026, 8, 25))
    assert [(p.label, p.role, p.start, p.end) for p in periods] == [
        ("this_month", "primary", D(2026, 8, 1), D(2026, 8, 25)),
        ("last_month", "comparison", D(2026, 7, 1), D(2026, 7, 31))]
    assert not [w for w in warnings if w.startswith("multiple")]

    periods, _ = resolve("tuần này so với tuần trước", D(2026, 3, 11))
    assert [(p.label, p.role) for p in periods] == [("this_week", "primary"), ("last_week", "comparison")]

    periods, _ = resolve("Doanh thu tuần rồi tăng giảm bao nhiêu % so với tuần liền trước đó", D(2026, 7, 12))
    assert [(p.label, p.role, p.start, p.end) for p in periods] == [
        ("last_week", "primary", D(2026, 6, 29), D(2026, 7, 5)),
        ("previous_week", "comparison", D(2026, 6, 22), D(2026, 6, 28))]

    periods, _ = resolve("tháng này so với cùng kỳ năm ngoái", D(2026, 8, 25))
    assert [(p.label, p.role, p.start, p.end) for p in periods] == [
        ("this_month", "primary", D(2026, 8, 1), D(2026, 8, 25)),
        ("same_period_last_year", "comparison", D(2025, 8, 1), D(2025, 8, 25))]

    periods, _ = resolve("quý này so với quý trước đó", D(2026, 8, 19))
    assert periods[1].label == "previous_quarter" and (periods[1].start, periods[1].end) == (D(2026, 4, 1), D(2026, 6, 30))

    periods, _ = resolve("tháng này so với kỳ trước", D(2026, 8, 25))
    assert periods[1].label == "previous_period"
    assert (periods[1].start, periods[1].end) == (D(2026, 7, 7), D(2026, 7, 31))  # same length, directly before


def test_ambiguity_never_raises_and_warns():
    periods, warnings = resolve("doanh thu tháng này, tháng trước", D(2026, 8, 25))
    assert [p.role for p in periods] == ["primary", "comparison"]
    assert "multiple_periods_without_comparison_marker" in warnings

    period, warnings = first("cùng kỳ", D(2026, 5, 15))
    assert period.label == "same_period_last_year" and "ambiguous_cung_ky_assumed_year" in warnings

    period, warnings = first("tuần qua", D(2026, 8, 1))
    assert (period.start, period.end) == (D(2026, 7, 26), D(2026, 8, 1))
    assert "bare_rolling_window_assumes_one_unit" in warnings

    _, warnings = first("tháng sau", D(2026, 8, 1))
    assert "future_period:next_month" in warnings
    _, warnings = first("tháng 12", D(2026, 8, 1))
    assert "year_inferred_previous:explicit_month" in warnings
    _, warnings = first("trước Tết", D(2026, 8, 1))
    assert "pre_tet_window_is_assumption" in warnings
    _, warnings = first("Tết", D(2026, 2, 25))
    assert "as_of_inside_tet_window_using_previous" in warnings
    _, warnings = first("tháng 8", D(2026, 8, 19))
    assert "explicit_current_month_to_as_of" in warnings

    for junk in ["", "   ", "???", "ngày 31 tháng 2", "tháng 13", "32/13/2026", "từ ngày đến ngày", "ngày 29/2"]:
        resolve_periods(junk, D(2026, 3, 1), params_for(), CAL)  # must not raise
    periods, warnings = resolve("ngày 29/2", D(2026, 3, 1))
    assert periods == [] and "invalid_date" in warnings
    assert resolve("tháng 13", D(2026, 3, 1))[0] == []


def test_outside_calendar_range_warning():
    _, warnings = first("tháng 01/2023", D(2026, 8, 20))
    assert "outside_calendar_range:explicit_month" in warnings
    _, warnings = first("tháng trước", D(2026, 8, 20))
    assert not [w for w in warnings if w.startswith("outside")]
    _, warnings = first("tháng trước", D(2026, 8, 20), calendar=[])
    assert not [w for w in warnings if w.startswith("outside")]  # no calendar, nothing to compare with


def test_tet_sources_and_missing_data():
    periods, warnings = resolve("Tết gần nhất", D(2026, 8, 1), calendar=[])
    assert periods == [] and "tet_window_not_found" in warnings
    periods, _ = resolve("Tết", D(2024, 1, 15))  # before any window in the calendar
    assert periods == []

    sample_schema = make_calendar(flag="is_tet")  # columns: date, is_tet
    assert resolve("Tết", D(2026, 8, 1), calendar=sample_schema)[0][0].start == TET_2026[0]

    lunar = make_calendar(lunar=True)  # no flag column, only lunar_month / lunar_day
    windows = tet_windows(lunar, params_for())
    assert windows == [TET_2025, TET_2026]
    assert resolve("Tết", D(2026, 8, 1), calendar=lunar)[0][0].end == TET_2026[1]

    shifted, _ = resolve("Tết", D(2026, 8, 1), calendar=make_calendar(windows=[(date(2026, 3, 1), date(2026, 3, 17))]))
    assert shifted[0].start == date(2026, 3, 1)  # nothing is hard-coded to Gregorian dates


def test_mentions_and_removal():
    text = "Doanh thu thang truoc cua hang A la bao nhieu"
    periods, _ = resolve(text, D(2026, 8, 20))
    assert [p.mention for p in periods] == ["thang truoc"]
    assert remove_mentions(text, periods) == "Doanh thu cua hang A la bao nhieu"

    text = "Trong dịp Tết gần nhất, sản phẩm nào bán chạy nhất?"
    periods, _ = resolve(text, D(2026, 8, 20))
    assert periods[0].mention == "dịp Tết gần nhất"
    assert "Tết" not in remove_mentions(text, periods)

    periods, _ = resolve("Tổng doanh thu tháng này tính đến hôm nay là bao nhiêu?", D(2026, 6, 10))
    assert [p.label for p in periods] == ["this_month"]  # "tính đến hôm nay" is a modifier, not a 2nd period


def test_deterministic_and_pure():
    for _ in range(3):
        a = resolve("tháng này so với cùng kỳ năm ngoái, 30 ngày qua, Tết", D(2026, 8, 25))
        b = resolve("tháng này so với cùng kỳ năm ngoái, 30 ngày qua, Tết", D(2026, 8, 25))
        assert a == b
    shuffled = resolve("30 ngày qua và tháng này", D(2026, 8, 25))[0]
    assert [p.label for p in shuffled] == ["last_30_ngay", "this_month"]  # mention order, not pattern order


def test_unaccented_and_noisy_forms():
    for text, label in [("thang nay", "this_month"), ("THANG TRUOC", "last_month"), ("tuan roi", "last_week"),
                        ("hom qua", "yesterday"), ("nam ngoai", "last_year"), ("quy nay", "this_quarter"),
                        ("Cuoi tuan", "last_weekend"), ("30 ngay qua", "last_30_ngay")]:
        assert first(text, D(2026, 8, 19))[0].label == label, text
