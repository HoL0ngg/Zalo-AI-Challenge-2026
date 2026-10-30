"""Coverage report for the Question Understanding stage (normalizer + temporal resolver).

Runs over dataset/train and dataset/dev (each split with its own rulebook and calendar) and prints:
  1. how many questions contain a detected time expression,
  2. the most frequent time-like tokens that no rule consumed (rule gaps),
  3. the normalizer change rate and 20 before/after samples,
  4. per-noise-type recovery rate, when the synthetic generator's noise module is importable.

The report is for finding rule gaps, never for tuning on question ids. The recovery numbers
are *in-sample*: the lexicon includes vocabulary from the same generator templates.

Usage: python scripts/eval_understanding.py [--splits train dev] [--samples 20] [--variants 20]
"""
from __future__ import annotations

import argparse
import ast
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True  # importing synth must not rewrite its tracked .pyc files
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datamate.core import BusinessContext, Question  # noqa: E402
from datamate.ingest.readers import read_calendar, read_text  # noqa: E402
from datamate.io.question_reader import read_records  # noqa: E402
from datamate.understanding import remove_mentions, understand  # noqa: E402
from datamate.understanding.normalizer import TOKEN_RE  # noqa: E402
from datamate.understanding.textutil import clean, fold  # noqa: E402

TIME_STEMS = ("tuan", "thang", "quy", "nam", "ngay", "tet", "hom", "cuoi", "cung")
# Bare words that are not time expressions on their own ("ngay nao", "nam" = male, ...).
NOT_TIME = {"nam", "quy", "ngay", "hom"}


def load_split(name: str) -> tuple[list[dict], str, list[dict]]:
    base = ROOT / "dataset" / name
    records = list(read_records(base / "questions.jsonl")) if (base / "questions.jsonl").exists() else []
    return records, read_text(base / "rulebook.md"), read_calendar(base / "calendar.csv")


def analyse(records, rulebook, calendar):
    rows = []
    for record in records:
        question = Question.model_validate(record)
        context = BusinessContext(Path("unused.duckdb"), {}, "", rulebook, calendar)
        resolved = understand(question, context)
        rows.append((record, resolved))
    return rows


def unmatched_time_tokens(rows) -> Counter:
    counter: Counter = Counter()
    for _, resolved in rows:
        rest = remove_mentions(resolved.normalized, resolved.periods)
        for token in TOKEN_RE.findall(fold(rest)):
            if token.isalpha() and token.startswith(TIME_STEMS) and token not in NOT_TIME:
                counter[token] += 1
    return counter


def clean_question_pool() -> list[str]:
    """Clean, entity-free question texts from the generator templates (read as text)."""
    path = ROOT / "synth" / "src" / "questions.py"
    if not path.exists():
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    texts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and " " in n.value and n.value.rstrip().endswith(("?", ".")) and any(ord(c) > 127 for c in n.value)]
    # Templates with an entity placeholder are skipped: noise inside entity names is not
    # recoverable by design (protected values keep names as typed).
    return sorted({text for text in texts if "{" not in text})


def recovery_report(variants: int) -> list[str]:
    synth = ROOT / "synth"
    sys.path.insert(0, str(synth))
    try:
        from src.noise import inject  # type: ignore  # synth/src/noise.py, stdlib only
    except Exception as error:  # noqa: BLE001
        return [f"(skipped: synth noise module not importable: {type(error).__name__})"]
    finally:
        sys.path.remove(str(synth))
    pool = clean_question_pool()
    dictionary = json.loads((synth / "data" / "teencode_dict.json").read_text(encoding="utf-8"))
    if not pool:
        return ["(skipped: no clean template questions found)"]

    def canon(text: str) -> str:
        return re.sub(r"\s+", " ", clean(text).casefold().rstrip("?!. "))

    from datamate.understanding import build_lexicon_cached, build_teencode_cached
    from datamate.understanding.normalizer import normalize
    from datamate.understanding.resources import load_homographs, load_lexicon, load_teencode
    lexicon = build_lexicon_cached(tuple(load_lexicon()), tuple(sorted(load_homographs())))
    teencode = build_teencode_cached(load_teencode())
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    overall = [0, 0]
    for index, clean_text in enumerate(pool):
        target = canon(normalize(clean_text, lexicon, teencode).normalized)
        for seed in range(variants):
            noisy, tags = inject(clean_text, dictionary, random.Random(index * 1000 + seed))
            recovered = canon(normalize(noisy, lexicon, teencode).normalized) == target
            overall[0] += recovered
            overall[1] += 1
            for tag in tags:
                stats[tag][0] += recovered
                stats[tag][1] += 1
    lines = [f"  {tag:<18} {hit:>5}/{total:<5} = {hit / total:6.1%}" for tag, (hit, total) in sorted(stats.items())]
    lines.append(f"  {'ALL (per sample)':<18} {overall[0]:>5}/{overall[1]:<5} = {overall[0] / overall[1]:6.1%}")
    return [f"{len(pool)} clean template questions x {variants} noisy variants (in-sample)"] + lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", nargs="+", default=["train", "dev"])
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--variants", type=int, default=20)
    args = parser.parse_args()

    all_rows = []
    print("== 1. Time expressions detected ==")
    for split in args.splits:
        records, rulebook, calendar = load_split(split)
        if not records:
            print(f"{split}: no questions found")
            continue
        rows = analyse(records, rulebook, calendar)
        all_rows.extend(rows)
        with_period = sum(1 for _, r in rows if r.periods)
        errors = sum(1 for _, r in rows if any(w.startswith("understanding_error") for w in r.warnings))
        labels = Counter(p.label for _, r in rows for p in r.periods)
        warnings = Counter(w.split(":")[0] for _, r in rows for w in r.warnings)
        print(f"{split}: {len(rows)} questions, {with_period} with a period ({with_period / len(rows):.1%}), "
              f"{errors} understanding errors")
        print("  labels:   " + ", ".join(f"{k}={v}" for k, v in labels.most_common()))
        print("  warnings: " + (", ".join(f"{k}={v}" for k, v in warnings.most_common()) or "none"))

    print("\n== 2. Top unmatched time-like tokens (rule gaps) ==")
    counter = unmatched_time_tokens(all_rows)
    for token, count in counter.most_common(25):
        print(f"  {count:>4}  {token}")
    if not counter:
        print("  none")

    print("\n== 3. Normalizer ==")
    changed = [(r.question.question, r.normalized, r.question.id) for _, r in all_rows
               if r.normalized != clean(r.question.question)]
    total = len(all_rows)
    print(f"change rate: {len(changed)}/{total} = {len(changed) / max(total, 1):.1%}")
    step = max(1, len(changed) // max(args.samples, 1))
    for before, after, _ in changed[::step][:args.samples]:
        print(f"  - {before}\n    {after}")

    print("\n== 4. Recovery by noise type ==")
    print("\n".join(recovery_report(args.variants)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
