"""CLI: python -m src.cli generate | report | all [--output out]."""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
import pandas as pd
from .calendar import build_calendar
from .rulebook import write_rulebook, read_rulebook
from .generators import generate_business, LABELS
from .writers import write_business, read_business, layout
from .answers import Dataset, answer_question
from .questions import make_business_specs
from .noise import inject

ROOT = Path(__file__).resolve().parent.parent


def seed_for(base: int, text: str) -> int:
    value = hashlib.sha256(f'{base}:{text}'.encode('utf-8')).digest()
    return int.from_bytes(value[:8], 'big') % (2**32)


def json_line(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n'


def dump_jsonl(path: Path, items: list[dict]) -> None:
    with path.open('w', encoding='utf-8', newline='\n') as f:
        for item in items:
            f.write(json_line(item))


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def size_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def generate(config_path: Path = ROOT / 'config.yaml', output: Path = ROOT / 'out') -> None:
    start_time = time.perf_counter()
    cfg = json.loads(config_path.read_text(encoding='utf-8'))  # JSON is a YAML 1.2 subset; no PyYAML dependency.
    catalog = json.loads((ROOT / 'data/product_catalog_seed.json').read_text(encoding='utf-8'))
    teencode = json.loads((ROOT / 'data/teencode_dict.json').read_text(encoding='utf-8'))
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for split, group in cfg['splits'].items():
        base = output / split
        (base / 'data').mkdir(parents=True)
        debug = output / '.debug' / split
        debug.mkdir(parents=True)
        write_rulebook(base / 'rulebook.md', split)
        build_calendar(base / 'calendar.csv')
        rules = read_rulebook(base / 'rulebook.md')
        cal = pd.read_csv(base / 'calendar.csv')
        questions, answers, metadata = [], [], []
        for i, kind in enumerate(group['types'], 1):
            bid = f'{split}_{i:02}'
            business_seed = seed_for(group['seed'], bid)
            fmt = cfg['formats'][(i - 1 + (1 if split == 'dev' else 0)) % len(cfg['formats'])]
            tables, registry = generate_business(bid, kind, business_seed, cfg, catalog, layout(bid))
            business_dir = base / 'data' / bid
            quirks = [
                'ngày ở hai dạng ISO và DD/MM/YYYY', 'một số trường tiền là chuỗi có dấu phân cách hàng nghìn',
                'tên sản phẩm trên dòng bán có teencode/Unicode NFC-NFD',
                'bản ghi chi tiết cùng mã dòng có thể bị lặp',
                'một số ô thông tin khách hàng bỏ trống'
            ]
            if 'gia_von' not in tables['products']:
                quirks.append('không lưu giá vốn hay giá nhập')
            if 'debts' not in tables:
                quirks.append('không theo dõi công nợ')
            write_business(business_dir, bid, fmt, tables, LABELS[kind], quirks)
            # Golds strictly use newly reloaded CSV, XLSX, or SQLite, not generated memory.
            ds = Dataset(read_business(business_dir), rules, cal)
            cases = make_business_specs(ds, registry, seed_for(group['seed'], bid + ':q'), cfg['questions_per_business'])
            noise_rng = random.Random(seed_for(group['seed'], bid + ':noise'))
            noisy_indices = set(noise_rng.sample(range(len(cases)), round(len(cases) * cfg['noise_rate'])))
            (debug / f'{bid}_registry.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
            for j, (plain, spec, asof) in enumerate(cases, 1):
                qid = f'{bid}_q{j:03}'
                noisy, tags = inject(plain, teencode, noise_rng) if j - 1 in noisy_indices else (plain, [])
                questions.append({'id': qid, 'business_id': bid, 'question': noisy, 'as_of_date': asof})
                gold = {'id': qid, **answer_question(ds, spec, asof)}
                answers.append(gold)
                metadata.append({'id': qid, 'business_id': bid, 'spec': spec, 'noise_tags': tags,
                                 'original_question': plain})
        dump_jsonl(base / 'questions.jsonl', questions)
        dump_jsonl(debug / 'questions_meta.jsonl', metadata)
        if split == 'train':
            dump_jsonl(base / 'answers.jsonl', answers)
        else:
            # Dev gold is withheld from the public split but available for offline tests.
            dump_jsonl(debug / 'answers.jsonl', answers)
        print(f'  {split}: {len(group["types"])} businesses, {len(questions)} questions, '
              f'{sum(x["type"] == "unanswerable" for x in answers)} unanswerable')
    mb = size_bytes(output) / 1_000_000
    elapsed = time.perf_counter() - start_time
    if mb >= cfg['max_output_mb']:
        raise RuntimeError(f'Generated output {mb:.2f} MB exceeds {cfg["max_output_mb"]} MB.')
    if elapsed > 120:
        raise RuntimeError(f'Generation took {elapsed:.1f}s (>120s).')
    print(f'Generated at {output} | {mb:.2f} MB | {elapsed:.1f}s')


def report(output: Path = ROOT / 'out') -> dict:
    summary = {}
    for split in ('train', 'dev'):
        base = output / split
        answer_path = base / 'answers.jsonl' if split == 'train' else output / '.debug' / split / 'answers.jsonl'
        answers = load_jsonl(answer_path)
        meta = load_jsonl(output / '.debug' / split / 'questions_meta.jsonl')
        counts = dict(sorted(Counter(a['type'] for a in answers).items()))
        n = len(answers)
        summary[split] = {
            'total_questions': n, 'types': counts,
            'unanswerable_percent': round(100 * counts.get('unanswerable', 0) / n, 2),
            'noisy_percent': round(100 * sum(bool(m['noise_tags']) for m in meta) / n, 2)
        }
        print(f'[{split}] {n} questions | unanswerable {summary[split]["unanswerable_percent"]}% '
              f'| noisy {summary[split]["noisy_percent"]}%')
        for key, cnt in counts.items():
            print(f'  {key:<15} {cnt:3} ({100 * cnt/n:5.1f}%)')
    summary['total_output_mb'] = round(size_bytes(output) / 1_000_000, 3)
    (output / 'report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Output size: {summary["total_output_mb"]} MB')
    return summary


def main():
    parser = argparse.ArgumentParser(description='Synthetic, fully offline DataMate Vietnamese QA benchmark')
    parser.add_argument('action', choices=['generate', 'report', 'all'])
    parser.add_argument('--config', type=Path, default=ROOT / 'config.yaml')
    parser.add_argument('--output', type=Path, default=ROOT / 'out')
    args = parser.parse_args()
    if args.action in ('generate', 'all'):
        generate(args.config, args.output)
    if args.action in ('report', 'all'):
        report(args.output)
    if args.action == 'all':
        import pytest
        code = pytest.main(['-q', str(ROOT / 'tests'), '--out', str(args.output)])
        if code != 0:
            sys.exit(code)


if __name__ == '__main__':
    main()
