# AGENTS.md — DataMate (Zalo AI Challenge 2026)

Guidance for AI coding agents (Codex, Claude Code, etc.) working in this repository.
Human-readable deep dives live in `docs/` (Vietnamese). This file is the short, authoritative contract.

## 1. Project in one paragraph
DataMate is an **offline** agent that answers informal Vietnamese questions (slang, teencode, typos, missing diacritics)
over small-business tabular data (CSV / XLSX / SQLite). Given a data package, a question and an `as_of_date`, it returns a
typed answer (`number|percent|string|date|boolean|list|table`), or `unanswerable` (data cannot support the question), or
`abstain` (agent chooses not to answer). Scoring is **exact match per question, no partial credit**.

## 2. Approach (do not change without updating docs/01_architecture.md)
**Generate code, execute it, verify it. Never let the LLM guess numbers.**
Pipeline: Ingest & Profile -> Question Understanding (Normalizer + Temporal Resolver) -> Entity/Schema Linking ->
Answerability Gate -> Code Generator (N candidates) -> Sandbox Executor + Self-repair -> Execution-based Voting ->
Type Formatter -> Outputs (submission + logs).
Deterministic, rule-based code is preferred over LLM wherever possible (dates, rounding, normalization, voting).

## 3. HARD CONSTRAINTS (violating any of these disqualifies the solution)
1. **Fully offline** at inference: no network, no commercial LLM APIs, no downloads. Set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
2. **Total model parameters <= 15B** across ALL models used at inference (LLM + embedding + reranker + classifier), MoE counts all params.
   Enforced by `src/datamate/runtime/model_budget.py` from `configs/models.yaml`. Weights must be public before 2026-10-01. Declare models in README.
3. **Time limit 6h** for the whole private test set including model loading, on 2 x RTX 5090 (32 GB each), 512 GB RAM, CUDA >= 12.8.
   A global time guard writes `abstain` for remaining questions when the budget is nearly spent.
4. **Incremental output**: append + flush + fsync `/result/submission.jsonl` per question. Missing questions count as abstain.
5. **Deterministic**: fixed seeds, temperature 0 (or very low), stable ordering and tie-breaks. Two runs must agree within 0.03 accuracy.
6. **No hard-coding**: no answers, no logic keyed on question ids or business ids. A test greps for this.
7. **No human in the loop**; **no training on public/private test data**, no collecting test answers.
8. `/data` is **read-only**. Temp files go to `/tmp` or `/work`. Never write into `/data`.
9. Logs: `/result/logs/` must contain per-question: id, final answer, elapsed time, plus generated code / execution output.

## 4. Models (declared; edit `configs/models.yaml` — single source of truth)
| Role | Default (placeholder, confirm before freezing) | Params (B) |
|---|---|---|
| Code-generation LLM | Qwen3-8B (or Qwen2.5-Coder-7B / Qwen3-14B) | ~8.2 |
| Embedding (entity linking, few-shot retrieval) | BGE-M3 | ~0.57 |
| Reranker / classifier | none by default | 0 |
Budget check: sum must be <= 15. Using a ~14B LLM leaves almost no room for others; two big LLMs do not fit.
Quantization (AWQ/GPTQ/FP8) is allowed. Serve with vLLM (data parallel across 2 GPUs). Mock backend is used for CPU tests.

## 5. Repository layout
```
configs/        default.yaml, models.yaml, rules_defaults.yaml, prompts/
data/           teencode_dict.json, fewshot/, samples/ (tiny sample package)
src/datamate/
  ingest/         loader (DuckDB), profiler, readers for README / rulebook / calendar
  understanding/  normalizer.py, temporal.py  (rule-based dates)
  linking/        entity_linker.py, schema_linker.py
  gate/           answerability.py
  codegen/        prompt_builder.py, generator.py
  execution/      sandbox.py, repair.py
  voting/         voting.py
  formatting/     formatter.py, schemas.py (Pydantic per answer type)
  io/             question_reader.py, submission_writer.py, log_writer.py
  runtime/        pipeline.py, runner.py, time_guard.py, seeding.py, model_budget.py, cli.py
  llm/            base.py, vllm_backend.py, mock_backend.py
  eval/           scorer.py (mirrors official scoring)
scripts/        predict.sh, run_local.sh, eval_local.sh, build_docker.sh
docker/         Dockerfile (CUDA >= 12.8 base; replace with official base image), .dockerignore
models/         weights go here (copied into image at build time)
tests/          pytest (mock backend, CPU only)
docs/           detailed step-by-step documentation
```

## 6. Conventions
- Python 3.10+, type hints, small pure functions, standard `logging`, no global mutable state, no network calls.
- Every stage returns a typed dataclass; a failure in one question must never crash the run (catch -> `abstain`, log the error).
- Rulebook comes from the **split being answered** (it differs between splits). Never reuse the training rulebook.
- Dates are resolved by code from `as_of_date` + `calendar.csv` + rulebook params, never by the LLM.
- Strings in answers must match the data spelling; normalization for scoring: NFC, lowercase, non-letter/digit -> space, collapse spaces (diacritics kept).
- Numbers: VND/counts as integers; others rounded to 2 decimals; percent rounded to 2 decimals with correct sign.
- Prefer `unanswerable` when required columns/entities are provably missing; prefer `abstain` when evidence is conflicting or low-confidence.

## 7. Commands
```
make test          # pytest, CPU, mock backend
make run-sample    # run full pipeline on data/samples
make eval-sample   # score against data/samples answers
make docker        # build the submission image
bash scripts/predict.sh   # entrypoint used by organizers: reads /data, writes /result
```

## 8. Definition of done for any change
- `make test` passes; determinism test passes; no-hardcoding test passes.
- Model budget still <= 15B; README model table updated if models changed.
- Relevant doc in `docs/` updated.
- No network access introduced; `/data` not written.

## 9. Where to read more
`docs/00_overview.md` ... `docs/12_roadmap.md` (see index in `docs/README.md`).
