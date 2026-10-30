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
                         seed=seed, **engine_kwargs(model))
        self.sampling = SamplingParams(temperature=0, seed=seed, max_tokens=512)

    def generate(self, prompt: str, linked: LinkResult) -> Candidate:
        output = self.model.generate([prompt], self.sampling, use_tqdm=False)[0].outputs[0].text.strip()
        if output.startswith("```"):
            output = "\n".join(output.splitlines()[1:-1])
        return Candidate(output)


def engine_kwargs(model: dict) -> dict:
    """Translate a models.yaml declaration into vLLM engine arguments.

    Only keys present in the declaration are forwarded, so the default
    configs/models.yaml (no quantization, one GPU) is unchanged. enforce_eager
    defaults to True: it skips CUDA-graph capture, which is slow to warm up and
    fragile on older GPUs such as Kaggle's T4; set it to false on the target machine.
    """
    kwargs = {"dtype": model.get("dtype", "auto"), "enforce_eager": bool(model.get("enforce_eager", True))}
    quantization = model.get("quantization")
    if quantization not in (None, "", "none"):
        kwargs["quantization"] = str(quantization)
    for key, cast in (("tensor_parallel_size", int), ("max_model_len", int),
                      ("gpu_memory_utilization", float), ("max_num_seqs", int)):
        if model.get(key) is not None:
            kwargs[key] = cast(model[key])
    return kwargs
