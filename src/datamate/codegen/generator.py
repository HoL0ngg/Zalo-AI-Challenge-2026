from datamate.codegen.prompt_builder import build_prompt
from datamate.core import Candidate, GateResult
from datamate.llm.base import LLMBackend


def generate(gate: GateResult, backend: LLMBackend) -> list[Candidate]:
    return [backend.generate(build_prompt(gate.linked), gate.linked)]
