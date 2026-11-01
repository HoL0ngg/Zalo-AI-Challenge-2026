import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_sft_data import example, pick_holdout  # noqa: E402
from datamate.codegen.prompt_builder import SYSTEM_PROMPT  # noqa: E402
from datamate.llm.vllm_backend import engine_kwargs  # noqa: E402


def test_holdout_is_deterministic_spread_and_sized():
    businesses = [f"biz_{i}" for i in range(101, 131)]
    held = pick_holdout(list(reversed(businesses)), 5)
    assert held == pick_holdout(businesses, 5) and len(held) == 6
    assert held == ["biz_105", "biz_110", "biz_115", "biz_120", "biz_125", "biz_130"]


def test_example_uses_the_inference_system_prompt_and_the_sql_tags_the_parser_expects():
    row = example("PROMPT", "\n SELECT 1 \n")
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    assert row["messages"][0]["content"] == SYSTEM_PROMPT and row["messages"][1]["content"] == "PROMPT"
    assert row["messages"][2]["content"] == "<sql>\nSELECT 1\n</sql>"


def test_lora_adapter_enables_vllm_lora_only_when_declared():
    assert "enable_lora" not in engine_kwargs({"dtype": "float16"})
    kwargs = engine_kwargs({"dtype": "float16", "lora_path": "models/lora", "max_lora_rank": 32})
    assert kwargs["enable_lora"] is True and kwargs["max_lora_rank"] == 32
