"""Stage-by-stage evaluation report: where do the wrong answers come from?

Joins the submission, the per-question logs and the gold answers. Where `scorer.score` only counts
correct/wrong/abstain, this also shows how far each question got (gated -> SQL extracted -> executed ->
answered -> correct) and groups the failures, so a change can be judged on the stage it targets.
"""
import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

from datamate.eval.scorer import matches

ERROR_KINDS = (
    ("syntax", r"parser error|syntax error"),
    ("binder", r"binder error"),            # unknown column / ambiguous name / wrong type for a function
    ("catalog", r"catalog error"),          # unknown table, view or function
    ("conversion", r"conversion error|could not convert"),
    ("timeout", r"timeout|interrupt"),
    ("not_single_select", r"only one select"),
)


def classify_error(error: str | None) -> str:
    text = (error or "").lower()
    return next((kind for kind, pattern in ERROR_KINDS if re.search(pattern, text)), "other")


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def question_outcome(prediction: Mapping[str, Any], gold: Mapping[str, Any], log: Mapping[str, Any] | None) -> dict:
    """Stage flags plus a single failure category (None when correct) for one question."""
    attempts = (log or {}).get("attempts") or []
    codes = [(a.get("candidate") or {}).get("code") for a in attempts]
    pred_type = prediction["type"]
    correct = pred_type != "abstain" and matches(prediction, gold)
    last = attempts[-1] if attempts else None
    flags = {
        "gated": pred_type == "unanswerable",
        "generated": bool(attempts),
        "sql_extracted": any(codes),
        "exec_ok": bool(last) and last.get("error") is None and bool(codes[-1]),
        "repaired_ok": len(attempts) > 1 and bool(last) and last.get("error") is None,
        "answered": pred_type not in {"abstain", "unanswerable"},
        "correct": correct,
        "gated_correct": correct and pred_type == "unanswerable",
    }
    failure = None
    if not correct:
        if gold["type"] == "unanswerable":
            failure = "should_be_unanswerable" if pred_type != "abstain" else "abstained_on_unanswerable"
        elif pred_type == "unanswerable":
            failure = "wrongly_blocked"
        elif pred_type == "abstain":
            if not attempts:
                failure = "abstain:generation_error" if (log or {}).get("error") else "abstain:no_attempt"
            elif not any(codes):
                failure = "abstain:no_sql_in_reply"
            elif last.get("error") is not None:
                failure = f"abstain:exec_{classify_error(last['error'])}"
            else:
                failure = "abstain:format_or_sanity"
        else:
            failure = "wrong_type" if pred_type != gold["type"] else "wrong_value"
    return {**flags, "failure": failure}


def build_report(submission: Iterable[Mapping], logs: Iterable[Mapping], gold: Iterable[Mapping],
                 templates: Mapping[str, str] | None = None) -> dict:
    predictions = {p["id"]: p for p in submission}
    by_log = {log["id"]: log for log in logs}
    gold = list(gold)
    stages: Counter = Counter()
    failures: Counter = Counter()
    exec_errors: Counter = Counter()
    per_type: dict[str, Counter] = defaultdict(Counter)
    per_template: dict[str, Counter] = defaultdict(Counter)
    elapsed, prompt_tokens, finish = [], [], Counter()
    for item in gold:
        prediction = predictions.get(item["id"], {"id": item["id"], "type": "abstain"})
        log = by_log.get(item["id"])
        outcome = question_outcome(prediction, item, log)
        stages.update(key for key, value in outcome.items() if key != "failure" and value)
        if outcome["failure"]:
            failures[outcome["failure"]] += 1
        for key, group in ((item["type"], per_type), ((templates or {}).get(item["id"]), per_template)):
            if key is not None:
                group[key]["total"] += 1
                group[key]["correct"] += outcome["correct"]
        if log:
            elapsed.append(float(log.get("elapsed_seconds") or 0))
            for attempt in log.get("attempts") or []:
                if attempt.get("error"):
                    exec_errors[classify_error(attempt["error"])] += 1
                meta = (attempt.get("candidate") or {}).get("meta") or {}
                if meta.get("prompt_tokens") is not None:
                    prompt_tokens.append(meta["prompt_tokens"])
                if meta.get("finish_reason"):
                    finish[meta["finish_reason"]] += 1
    total = len(gold)
    generated = stages["generated"]
    report: dict[str, Any] = {
        "total": total,
        "accuracy": _rate(stages["correct"], total),
        "stages": {key: stages[key] for key in ("gated", "generated", "sql_extracted", "exec_ok",
                                                 "repaired_ok", "answered", "correct")},
        "rates_over_generated": {"sql_extracted": _rate(stages["sql_extracted"], generated),
                                 "exec_ok": _rate(stages["exec_ok"], generated),
                                 "answered": _rate(stages["answered"], generated)},
        "precision_when_answered": _rate(stages["correct"] - stages["gated_correct"], stages["answered"]),
        "failures": dict(failures.most_common()),
        "exec_errors": dict(exec_errors.most_common()),
        "per_type": _table(per_type),
    }
    if per_template:
        report["per_template"] = _table(per_template)
    if elapsed:
        report["latency_seconds"] = {"mean": round(statistics.mean(elapsed), 3), "p95": round(_percentile(elapsed, .95), 3)}
    if prompt_tokens:
        report["prompt_tokens"] = {"mean": round(statistics.mean(prompt_tokens)), "max": max(prompt_tokens)}
    if finish:
        report["finish_reasons"] = dict(finish)   # "length" means the reply was cut by max_tokens
    return report


def _table(groups: Mapping[str, Counter]) -> dict:
    return {key: {"correct": c["correct"], "total": c["total"], "accuracy": _rate(c["correct"], c["total"])}
            for key, c in sorted(groups.items())}
