"""End-to-end, disk-backed integrity, reproduction and schema tests."""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
import pandas as pd
from src.cli import generate, load_jsonl, size_bytes, ROOT
from src.rulebook import read_rulebook
from src.writers import read_business
from src.answers import Dataset, answer_question


def all_files(root: Path):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def test_same_seed_byte_identical(output, tmp_path):
    second = tmp_path / 'regen'
    generate(ROOT / 'config.yaml', second)
    # CLI report.json is created after generation, so compare the data products.
    expected = all_files(output)
    expected.pop('report.json', None)
    assert expected == all_files(second)


def test_questions_answers_from_written_files(output):
    cfg = json.loads((ROOT / 'config.yaml').read_text(encoding='utf-8'))
    for split in ('train', 'dev'):
        expected_count = len(cfg['splits'][split]['types']) * cfg['questions_per_business']
        base = output / split
        questions = load_jsonl(base / 'questions.jsonl')
        answerfile = (base / 'answers.jsonl') if split == 'train' else (output / '.debug' / split / 'answers.jsonl')
        gold = {x['id']: x for x in load_jsonl(answerfile)}
        meta = {x['id']: x for x in load_jsonl(output / '.debug' / split / 'questions_meta.jsonl')}
        assert len(questions) == expected_count
        assert len(gold) == len(meta) == len(questions)
        assert not (base / 'answers.jsonl').exists() if split == 'dev' else (base / 'answers.jsonl').exists()
        rules = read_rulebook(base / 'rulebook.md')
        cal = pd.read_csv(base / 'calendar.csv')
        for bid in sorted({x['business_id'] for x in questions}):
            # Explicitly reload from one of CSV / XLSX / SQLite on disk.
            data_dir = base / 'data' / bid
            ds = Dataset(read_business(data_dir), rules, cal)
            first = min(ds.orders['day']); last = max(ds.orders['day'])
            for q in [q for q in questions if q['business_id'] == bid]:
                assert set(q) == {'id', 'business_id', 'question', 'as_of_date'}
                assert q['id'] in gold and q['id'] in meta
                assert first <= date.fromisoformat(q['as_of_date']) <= last
                assert q['question'].strip()
                assert answer_question(ds, meta[q['id']]['spec'], q['as_of_date']) == {
                    key: value for key, value in gold[q['id']].items() if key != 'id'
                }
                assert gold[q['id']]['type'] in ('number', 'percent', 'string', 'date', 'boolean', 'list', 'table', 'unanswerable')
                if gold[q['id']]['type'] == 'unanswerable':
                    assert gold[q['id']]['answer'] is None and isinstance(gold[q['id']].get('reason'), str)
                elif gold[q['id']]['type'] == 'percent':
                    v = gold[q['id']]['answer']; assert isinstance(v, (int, float)) and round(v, 2) == v
                elif gold[q['id']]['type'] == 'table':
                    table = gold[q['id']]['answer']
                    assert set(table) == {'columns', 'rows'}
                    assert all(len(row) == len(table['columns']) for row in table['rows'])
        ids = [q['id'] for q in questions]
        assert len(ids) == len(set(ids))


def test_distribution_calendar_and_size(output):
    assert size_bytes(output) < 50_000_000
    seen_formats = set()
    cfg = json.loads((ROOT / 'config.yaml').read_text(encoding='utf-8'))
    for split in ('train', 'dev'):
        root = output / split
        rules = read_rulebook(root / 'rulebook.md')
        assert rules['week_start'] == ('sunday' if split == 'dev' else 'monday')
        assert rules['revenue_subtract_order_voucher'] == (split == 'dev')
        calendar = pd.read_csv(root / 'calendar.csv')
        jan1 = calendar.loc[calendar['date'].eq('2026-02-17')].iloc[0]
        assert (jan1['lunar_day'], jan1['lunar_month'], jan1['is_tet_window']) == (1, 1, 1)
        ans = load_jsonl(root / 'answers.jsonl' if split == 'train' else output / '.debug' / split / 'answers.jsonl')
        metas = load_jsonl(output / '.debug' / split / 'questions_meta.jsonl')
        assert len(ans) == len(metas)
        nbiz = len(cfg['splits'][split]['types'])
        assert sum(x['type'] == 'unanswerable' for x in ans) == 4 * nbiz
        assert sum(bool(x['noise_tags']) for x in metas) == round(cfg['questions_per_business'] * cfg['noise_rate']) * nbiz
        for data_dir in (root / 'data').iterdir():
            exts = {p.suffix for p in data_dir.iterdir() if p.suffix in ('.xlsx', '.sqlite', '.csv')}
            assert len(exts) == 1
            seen_formats |= exts
            assert (data_dir / 'README.md').exists()
            loaded = read_business(data_dir)
            assert 500 <= len(loaded['order_lines']) <= 5000
            assert 30 <= len(loaded['products']) <= 150
            assert 20 <= len(loaded['customers']) <= 200
    assert seen_formats == {'.csv', '.sqlite', '.xlsx'}


def test_reference_dictionary():
    aliases = json.loads((ROOT / 'data' / 'teencode_dict.json').read_text(encoding='utf-8'))
    catalog = json.loads((ROOT / 'data' / 'product_catalog_seed.json').read_text(encoding='utf-8'))
    assert len(aliases) >= 80
    assert all(30 <= len(items) <= 60 for items in catalog.values())
    assert len(catalog) == 8


def test_dev_rules_affect_computation_and_date_edges(output):
    from datetime import timedelta
    from src.answers import as_int
    devbase = output / 'dev'
    rules_dev = read_rulebook(devbase / 'rulebook.md')
    cal = pd.read_csv(devbase / 'calendar.csv')
    ds = Dataset(read_business(devbase / 'data' / 'dev_03'), rules_dev, cal)
    baseline = dict(rules_dev, week_start='monday', revenue_subtract_order_voucher=False)
    without_dev_overrides = Dataset(read_business(devbase / 'data' / 'dev_03'), baseline, cal)
    asof = max(ds.orders['day'])
    # Real vouchers exist in dev data, so the voucher-inclusive amount must differ.
    day = date(asof.year, asof.month, 1)
    dev_total = ds.scoped('this_month', asof)[0]['revenue'].sum()
    normal_total = without_dev_overrides.scoped('this_month', asof)[0]['revenue'].sum()
    assert dev_total < normal_total
    # Sunday is the first day of a new week under dev, but the last day in train.
    sunday = asof - timedelta(days=(asof.weekday() - 6) % 7)
    assert ds.period('this_week', sunday)[0] == sunday
    assert without_dev_overrides.period('this_week', sunday)[0] == sunday - timedelta(days=6)
    for split in ('train', 'dev'):
        questions = load_jsonl(output / split / 'questions.jsonl')
        for bid in sorted(set(x['business_id'] for x in questions)):
            dates = [date.fromisoformat(x['as_of_date']) for x in questions if x['business_id'] == bid]
            assert 0 in {d.weekday() for d in dates}
            assert 6 in {d.weekday() for d in dates}
            import calendar as pycal
            assert any(d.day == pycal.monthrange(d.year, d.month)[1] for d in dates)
