import os
from pathlib import Path
from typing import Any

from datamate.codegen.prompt_builder import SYSTEM_PROMPT
from datamate.codegen.sql_parser import extract_sql
from datamate.core import Candidate, LinkResult

DEFAULT_MAX_TOKENS = 768


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
        self.tokenizer = self.model.get_tokenizer()
        self.enable_thinking = bool(model.get("enable_thinking", False))
        # Stop at the closing tag: the statement is complete, so the remaining tokens would be wasted.
        self.sampling = SamplingParams(temperature=0, seed=seed, stop=["</sql>"],
                                       max_tokens=int(model.get("max_tokens", DEFAULT_MAX_TOKENS)))

    def generate(self, prompt: str, linked: LinkResult) -> Candidate:
        text = render_chat(self.tokenizer, SYSTEM_PROMPT, prompt, self.enable_thinking)
        result = self.model.generate([text], self.sampling, use_tqdm=False)[0]
        output = result.outputs[0]
        return candidate_from_reply(output.text, output.finish_reason, len(result.prompt_token_ids))


def render_chat(tokenizer: Any, system: str, user: str, enable_thinking: bool = False) -> str:
    """Apply the model's own chat template. `enable_thinking` is read by Qwen3-style templates and ignored by others."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                         enable_thinking=enable_thinking)


def candidate_from_reply(raw: str, finish_reason: str | None, prompt_tokens: int | None = None) -> Candidate:
    """Parse a raw reply into a Candidate; the raw text and usage stay in `meta` for the per-question log."""
    return Candidate(extract_sql(raw), meta={"raw_output": raw, "finish_reason": finish_reason,
                                             "prompt_tokens": prompt_tokens})


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
