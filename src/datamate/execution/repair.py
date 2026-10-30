from datamate.codegen.prompt_builder import build_prompt
from datamate.core import Candidate, ExecResult, LinkResult
from datamate.llm.base import LLMBackend


def repair(linked: LinkResult, failed: ExecResult, backend: LLMBackend) -> Candidate:
    prompt = build_prompt(linked) + f"\nRepair this SQL once:\n{failed.candidate.code}\nError: {failed.error}"
    return backend.generate(prompt, linked)
