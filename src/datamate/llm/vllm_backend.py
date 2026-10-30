import os
from pathlib import Path

from datamate.core import Candidate, LinkResult


class VLLMBackend:
    """Optional local-only skeleton; never accepts a Hub model ID as a path."""
    def __init__(self, model: dict, seed: int):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["VLLM_NO_USAGE_STATS"] = "1"
        path = Path(model["local_path"]).resolve()
        if not model["enabled"] or not path.is_dir():
            raise ValueError("Enable a declared model with an existing local weight directory")
        from vllm import LLM, SamplingParams
        self.model = LLM(model=str(path), tokenizer=str(path), trust_remote_code=False,
                         seed=seed, dtype=model.get("dtype", "auto"))
        self.sampling = SamplingParams(temperature=0, seed=seed, max_tokens=512)

    def generate(self, prompt: str, linked: LinkResult) -> Candidate:
        output = self.model.generate([prompt], self.sampling, use_tqdm=False)[0].outputs[0].text.strip()
        if output.startswith("```"):
            output = "\n".join(output.splitlines()[1:-1])
        return Candidate(output)
