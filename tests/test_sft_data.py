import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_sft_data import example, pick_holdout, restore_baseline, verified_example  # noqa: E402
from train_lora import IGNORE, encode, training_options  # noqa: E402
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


class Tokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        assert not tokenize and not enable_thinking
        text = "".join(f'<{m["role"]}>{m["content"]}</end>\n' for m in messages)
        return text + ("<assistant>" if add_generation_prompt else "")

    def __call__(self, text, add_special_tokens):
        assert not add_special_tokens
        return {"input_ids": list(text.encode("utf-8"))}


def test_training_masks_prompt_but_keeps_sql_and_template_end_tokens():
    tokenizer = Tokenizer()
    messages = example("câu hỏi", "SELECT 1")["messages"]
    row = encode(tokenizer, messages, 10000)
    start = next(i for i, label in enumerate(row["labels"]) if label != IGNORE)
    assert row["labels"][:start] == [IGNORE] * start
    assert bytes(row["labels"][start:]).decode() == "<sql>\nSELECT 1\n</sql></end>\n"
    assert row["labels"][start:] == row["input_ids"][start:]
    assert encode(tokenizer, messages, len(row["input_ids"]) - 1) is None
    messages[-1]["content"] = " "
    with pytest.raises(ValueError, match="non-empty"):
        encode(tokenizer, messages, 10000)


def test_training_rejects_a_template_that_changes_the_prompt_prefix():
    class Mismatch(Tokenizer):
        def apply_chat_template(self, *args, **kwargs):
            text = super().apply_chat_template(*args, **kwargs)
            return text if kwargs["add_generation_prompt"] else "different" + text

    assert encode(Mismatch(), example("q", "SELECT 1")["messages"], 10000) is None


def test_training_schedule_handles_ddp_accumulation_and_partial_batches():
    args = SimpleNamespace(out=Path("lora"), accum=8, epochs=2, max_steps=-1, lr=5e-5, seed=42)
    options = training_options(args, 888, 2)
    # ceil(444/8) steps per epoch, 112 total, not floor(444/8).
    assert options["warmup_steps"] == 6
    assert "warmup_ratio" not in options and "group_by_length" not in options
    assert options["save_strategy"] == "epoch" and options["save_only_model"]
    args.max_steps = 2
    assert training_options(args, 888, 2)["warmup_steps"] == 1


def test_sft_reexecutes_sql_instead_of_trusting_old_correct_logs(tmp_path):
    from datamate.core import Question
    from datamate.ingest.loader import BusinessLoader
    from datamate.linking import link
    from datamate.understanding import understand

    context = BusinessLoader(Path("data/samples"), tmp_path).load("shop")
    question = Question(id="sft-check", business_id="shop", question="q", as_of_date="2026-01-01")
    linked = link(understand(question, context), context)
    gold = {"id": question.id, "type": "number", "answer": 2}
    assert verified_example(linked, "SELECT count(*) FROM sales", gold)
    assert verified_example(linked, "SELECT 3", gold) is None
    assert verified_example(linked, "SELECT nonexistent FROM sales", gold) is None


def test_restore_baseline_checks_questions_and_never_extracts_other_zip_members(tmp_path):
    import json
    import zipfile

    train = tmp_path / "train"
    train.mkdir()
    question = {"id": "q", "business_id": "shop", "question": "q", "as_of_date": "2026-01-01"}
    (train / "questions.jsonl").write_text(json.dumps(question) + "\n")
    archive = tmp_path / "stage1.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("result/stage1/submission.jsonl", json.dumps({"id": "q", "type": "abstain"}))
        z.writestr("result/stage1/logs/questions.jsonl", json.dumps({"id": "q", "question": question}))
        z.writestr("../../escape.txt", "bad")
        z.writestr("sft/train.jsonl", "unverified SFT")
    output = tmp_path / "out"
    restore_baseline(archive, train, output)
    assert (output / "submission.jsonl").exists() and (output / "logs/questions.jsonl").exists()
    assert not (tmp_path / "sft").exists() and not (tmp_path / "escape.txt").exists()
    with pytest.raises(ValueError, match="overwrite"):
        restore_baseline(archive, train, output)
    question["question"] = "changed"
    (train / "questions.jsonl").write_text(json.dumps(question) + "\n")
    with pytest.raises(ValueError, match="do not match"):
        restore_baseline(archive, train, tmp_path / "other")
    assert not (tmp_path / "other").exists()
