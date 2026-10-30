import time
from dataclasses import asdict

from datamate.codegen.generator import generate
from datamate.core import Answer, Question
from datamate.execution.repair import repair
from datamate.execution.sandbox import execute
from datamate.formatting.formatter import format_answer
from datamate.gate import gate
from datamate.ingest.loader import BusinessLoader
from datamate.linking import link, link_to_log
from datamate.llm.base import LLMBackend
from datamate.runtime.time_guard import TimeGuard
from datamate.understanding import periods_to_dicts, understand
from datamate.voting import vote_stub


class Pipeline:
    def __init__(self, loader: BusinessLoader, backend: LLMBackend, guard: TimeGuard,
                 timeout: float = 30, repair_attempts: int = 1):
        self.loader, self.backend, self.guard = loader, backend, guard
        self.timeout, self.repair_attempts = timeout, min(1, repair_attempts)

    def answer(self, record: dict) -> tuple[Answer, dict]:
        started = time.monotonic()
        answer = Answer(record["id"], "abstain")
        log = {"id": record["id"], "question": record, "attempts": [], "error": None}
        try:
            question = Question.model_validate(record)
            if self.guard.exhausted:
                raise TimeoutError("Global time budget exhausted")
            context = self.loader.load(question.business_id)
            log["ingest_warnings"] = context.warnings
            resolved = understand(question, context)
            log["understanding"] = {
                "normalized": resolved.normalized, "normalized_ascii": resolved.normalized_ascii,
                "periods": periods_to_dicts(resolved.periods), "intent_hints": resolved.intent_hints,
                "rule_params": resolved.rule_params, "warnings": resolved.warnings,
            }
            linked = link(resolved, context)
            log["linking"] = link_to_log(linked)
            decision = gate(linked)
            if not decision.allowed:
                answer = Answer(question.id, "unanswerable", reason=decision.reason)
            else:
                results = []
                for candidate in generate(decision, self.backend):
                    for attempt in range(self.repair_attempts + 1):
                        remaining = min(self.guard.remaining, self.timeout - (time.monotonic() - started))
                        result = execute(context, candidate, remaining)
                        log["attempts"].append(asdict(result))
                        if result.error is None or attempt == self.repair_attempts or self.guard.exhausted:
                            break
                        candidate = repair(linked, result, self.backend)
                    results.append(result)
                answer = format_answer(question, vote_stub(results))
        except Exception as error:
            log["error"] = f"{type(error).__name__}: {error}"
        log["final_answer"] = answer.to_dict()
        log["elapsed_seconds"] = time.monotonic() - started
        return answer, log
