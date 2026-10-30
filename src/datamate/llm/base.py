from typing import Protocol

from datamate.core import Candidate, LinkResult


class LLMBackend(Protocol):
    def generate(self, prompt: str, linked: LinkResult) -> Candidate: ...
