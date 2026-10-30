# Baseline plumbing

Implemented pipeline: ingest (canonical views since Phase 3) -> understanding (real since Phase 2) -> linking (real since Phase 3) -> rule gate ->
one SQL candidate -> read-only execution -> optional single repair -> first valid
result stub -> Pydantic formatter -> durable logs and submission.

## Run

Install once before going offline: `python -m pip install -e ".[test]"`.
Then `make test`, `make run-sample`, `make eval-sample`.
`make test` covers the baseline under `tests/`. The independent synthetic-generator
suite can be run with `python -m pytest synth/tests`; its stored output snapshots
may depend on the Python/library versions used to create them.
The Makefile accepts `PYTHON=/path/to/python`. Windows GNU Make can be invoked
as `mingw32-make PYTHON=.venv/Scripts/python.exe test`.
Direct equivalents are `python -m pytest`,
`python -m datamate.cli run --data-dir data/samples --result-dir result/sample`,
and `python -m datamate.cli eval result/sample/submission.jsonl data/samples/answers.jsonl`.
Validate with `python -m datamate.cli validate result/sample/submission.jsonl`.

Input layout is `split/{questions.jsonl,rulebook.md,calendar.csv,data/<business_id>/}`.
Each business contains README.md and CSV/XLSX/SQLite files. IDs must be strings;
questions must contain id, business_id, question, as_of_date (ISO date).
Invalid records with usable IDs become abstain. Invalid JSON or absent IDs are
input-contract errors: no valid output ID can be invented.

## Boundaries

* Original files are only read. Temporary DuckDB databases live in the system
  temporary directory, outside the input tree, and are deleted at run completion.
  SQL connects read-only, disables external access and automatic extensions,
  accepts one SELECT only, uses one thread and 512 MB, and interrupts on timeout.
  Results larger than 10,000 rows fail instead of silently truncating.
* XLSX reads all sheets; the earliest densest text row in the first ten rows is
  treated as the header. Explicit final total rows are excluded. CSV delimiter
  and UTF-8/BOM or cp1258 encoding are detected. SQLite uses a read-only immutable
  connection and includes views. Closed SQLite packages must include checkpointed
  data; active WAL databases are not supported.
* Table names are CSV stems, worksheet names, or SQLite table/view names. Collisions
  get a file-stem prefix. Profiling includes types, row counts, null ratios,
  distinct counts, min/max and five ordered examples. Broken sources are logged.
* Rulebook text and calendar come from the current split. Rule extraction,
  locale-dependent numeric/date cleanup, relationship discovery and full value
  dictionaries are deferred. No training-split rules are substituted.
* Mock grammar: `count TABLE` / `đếm TABLE`, `sum|tổng|avg|min|max COLUMN from|trong TABLE`,
  `list|danh sách COLUMN from|trong TABLE`, `table|bảng TABLE`. Names are literal
  identifiers, and all answers come from SQL execution. Unsupported questions abstain.
* Phase 2 added real question understanding (normalizer, temporal resolver, intent hints; see
  `docs/03_question_understanding.md` and `docs/14_phase2.md`). Phase 3 added the canonical views, entity/schema linking and a
  rule gate (`docs/15_phase3.md`); multi-candidate voting is still not implemented.
  The gate blocks only on provable evidence (missing entity, capability or period). Currency/count integer rounding is available
  via candidate unit metadata; the mock marks count queries only. Percent/date
  intent beyond native SQL result types needs future understanding work.
* Optional vLLM is a local-path skeleton, temperature zero, seed fixed, remote
  code disabled. Enable and declare the model before use; disabled defaults mean
  zero inference parameters. GPU loading/generation and hardware budget calibration
  are not validated in this phase. The guard starts before loading, prevents later
  questions and bounds SQL; it cannot interrupt an in-process vLLM load/generate.
* The default 19,800-second budget reserves 60 seconds. Once exhausted, remaining
  records are emitted as abstain with logs. Per-question exceptions are isolated;
  storage failures fail the run because durability cannot be claimed otherwise.
* Resume skips committed IDs. Only a torn final submission line is truncated;
  interior corruption and duplicate IDs fail validation. Logs are persisted before
  submission, so a crash between these writes can leave duplicate audit attempts.
  Mock submissions are byte-identical; real elapsed-time log fields necessarily vary.
* Scoring implements the documented contract, including aliases, NFC/case/punctuation
  string normalization, signed rounded percent, ordered lists/tables, missing IDs
  as abstain. No organizer executable has been provided for equivalence testing.

Next: deterministic temporal/rule parsing, schema/entity linking, answerability,
then model quality and multi-candidate voting. Validate offline GPU serving and
hard process deadlines before submission packaging. Docker is intentionally deferred.
