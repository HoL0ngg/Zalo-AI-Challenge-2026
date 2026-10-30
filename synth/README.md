# DataMate Synth — offline Vietnamese business QA benchmark

Generate a **deterministic, entirely synthetic** Vietnamese business-data benchmark.
No network, LLM, Faker, real personal data, or API keys. Python **3.10+** with
`pandas`, `numpy`, `openpyxl`, `pytest`; `sqlite3` is from the standard library.

## Quick start

```bash
python -m pip install pandas numpy openpyxl pytest
make all
```

Or, on **Windows PowerShell** (no Make required):

```powershell
py -3 -m pip install pandas numpy openpyxl pytest
py -3 -m src.cli generate
py -3 -m pytest -q tests
py -3 -m src.cli report
```

Or run `./run.sh` on macOS/Linux. Commands must run from the repository root.
Change output with `python -m src.cli generate --output /path/to/out`.

## Output

```text
out/
  train/
    data/train_01/{san_pham.csv,...,README.md}  # actual names vary by business
    data/train_02/{so_lieu.xlsx,README.md}
    data/train_03/{kinh_doanh.sqlite,README.md}
    ... (8 businesses)
    rulebook.md
    calendar.csv
    questions.jsonl
    answers.jsonl
  dev/
    data/dev_01/...                            # 3 businesses; 2 held-out types
    rulebook.md                                # Sunday week + deduct vouchers
    calendar.csv
    questions.jsonl                           # no public gold file
  .debug/
    train/questions_meta.jsonl                 # template params + noise_tags
    train/train_01_registry.json               # observed ground-truth aliases
    dev/questions_meta.jsonl
    dev/answers.jsonl                          # withheld dev gold, for local tests only
    dev/dev_01_registry.json
  report.json
```

**Do not distribute `.debug/` with a blind evaluation split.** The dev labels
are withheld from `dev/answers.jsonl` but are retained in `.debug/dev/answers.jsonl`
for deterministic local pytest validation. `questions.jsonl` contains only
`id`, `business_id`, `question`, `as_of_date`. Answers use the portal types:
`number`, `percent`, `string`, `date`, `boolean`, `list`, `table`, `unanswerable`.
No `abstain` examples are generated.

Each business uses **one** format: CSV tables, multi-sheet XLSX, or SQLite.
XLSX Orders header is on row 3 under a merged title; table and column names
vary (e.g. `don_hang`/`Orders`, `so_luong`/`Qty`/`SL`). Dates are mixed ISO
and DD/MM/YYYY. Numeric strings have `.`/`,` thousands separators. Real
customer names and phone numbers are **not** used.

## Answering semantics

`rulebook.md` is *executable*: a fenced JSON block is parsed by
`src.rulebook.read_rulebook`. Answer code reads that file for **each split**.
- Train: week Mon–Sun; **do not subtract** order vouchers from revenue.
- Dev: week Sun–Sat; **subtract** order vouchers allocated pro rata by eligible line value.
- Both: exclude VAT/shipping; cancelled orders; **entire** order with any returned line.
- Exact duplicate records share `dong_id` and are deduplicated before aggregation.
- Product rank ties sorted by `ma_sp`; calendar dates are derived from
  `as_of_date`, **not** the host clock.
- Costs are weighted averages of purchased lots up to `as_of_date`, with a
  missing-cost business unable to answer profit questions.
- Lunar dates use a local astronomical algorithm (GMT+7, see `src/calendar.py`).

The computation engine (`src/answers.py`) reads **written** files via
`src/writers.py`; source registries never provide numerical answers. Product
`alias` fields are reconstructed from observed product names and line names.

## Config & extensions

`config.yaml` uses **JSON syntax, valid as a YAML 1.2 document**. This avoids
requiring `PyYAML`. Change seeds, split business kinds, row sizes, months,
noise rates, costs, and formats there. Keep `rows_per_business` within
500–5000, product counts 30–150, 20–200 customers, 12–18 months and a
sufficiently long historical period for same-year-last-year questions.
The default is 11 businesses / 440 questions, ~70% noisy, ~10% unanswerable.

**Add a business type:** create a key in `src/generators.py:LABELS`, add
30–60 distinctive `name|category` strings under the same key in
`data/product_catalog_seed.json`, update price/unit methods if needed, and
append that type slug to `config.yaml` splits. Use a train-only or dev-only type
to simulate unseen classes.

**Add a question template:** add one `Template` to `src/questions.py:TEMPLATES`
with a natural-language form, dispatcher `answer_fn`, period, expected answer
type, and optional `needs` field. Implement its actual deterministic computation
in `src/answers.py:answer_question` (or reuse an existing dispatcher). The
test suite recomputes every answer after reloading written files.

**Edit teencode:** modify `data/teencode_dict.json` (131 editable mappings).
Noise tags live in `out/.debug/<split>/questions_meta.jsonl`, not the prompt.

## Design boundaries / assumptions

- Retail transaction quantities and VND prices are integer values; numeric
  formatting noise never changes an actual value.
- `as_of_date` is a *simulated* date within each business history, with
  deliberate Monday, Sunday, and month-end examples.
- There is no separate payments ledger; `debts` is an independent balance.
- Order-level vouchers are never larger than an order's valid line subtotal
  under the default sampling parameters; allocated amounts are capped at zero.
- Stock is purchases less quantities in eligible orders. Expiring lot
  quantities use FIFO allocation for a simple, deterministic snapshot.
- No item-level matching by fuzzy name is necessary for gold computation:
  line items carry a stable SKU, while generated questions can use a messy name.
- Byte-level reproducibility applies to all generated file bytes, including XLSX:
  archive member timestamps are normalized after `openpyxl` saves them.
