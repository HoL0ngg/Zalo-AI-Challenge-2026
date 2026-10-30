from datamate.codegen.prompt_builder import build_prompt
from datamate.core import Candidate, GateResult, LinkResult
from datamate.llm.base import LLMBackend


def apply_expected(candidate: Candidate, linked: LinkResult) -> Candidate:
    """Fill answer_type/unit from the linked question without overriding what the backend set.

    The type is forced only where the result shape cannot tell it (percent, list, table);
    the VND/count unit makes the formatter round money and counts to integers.
    """
    expected = (linked.schema or {}).get("expected") or {}
    if candidate.answer_type is None and expected.get("force_type"):
        candidate.answer_type = expected["type"]
    if candidate.unit is None and expected.get("unit"):
        candidate.unit = expected["unit"]
    return candidate


def generate(gate: GateResult, backend: LLMBackend) -> list[Candidate]:
    return [apply_expected(backend.generate(build_prompt(gate.linked), gate.linked), gate.linked)]
