"""QLoRA fine-tuning of the code model on the examples from scripts/build_sft_data.py.

Written for Kaggle T4 x2 (16 GB, no bfloat16, no FlashAttention-2): the base model is loaded in 4-bit NF4 with
fp16 compute, gradient checkpointing, one sequence per step. The loss is computed on the SQL answer only
(the prompt is masked), so the model learns what to write, not the schema it is shown.

    torchrun --nproc_per_node 2 scripts/train_lora.py --base /tmp/qwen-fp16 --data sft/train.jsonl --out lora

The adapter (a few hundred MB) is served by vLLM next to the AWQ base model (`lora_path` in the models file).
Uses only the train data the user passes; never the public or private test.
"""
import argparse
import json
import os
import random
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import Dataset
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq, Trainer,
                          TrainingArguments)

IGNORE = -100


def encode(tokenizer, messages: list[dict], max_len: int) -> dict | None:
    """Token ids and labels with the system+user part masked; None when the example is too long."""
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    full = prompt + messages[-1]["content"] + "<|im_end|>\n"
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if len(ids) > max_len or ids[:len(prompt_ids)] != prompt_ids:
        return None
    return {"input_ids": ids, "attention_mask": [1] * len(ids), "labels": [IGNORE] * len(prompt_ids) + ids[len(prompt_ids):]}


class Examples(Dataset):
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        return self.rows[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="directory of the unquantized base model (fp16/bf16 weights)")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=32)
    parser.add_argument("--accum", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261030)
    args = parser.parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    local = int(os.environ.get("LOCAL_RANK", 0))
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    rows = [encode(tokenizer, json.loads(line)["messages"], args.max_len)
            for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [r for r in rows if r]
    if local == 0:
        print(f"examples: {len(kept)} kept, {len(rows) - len(kept)} longer than {args.max_len} tokens dropped", flush=True)
    if not kept:
        raise SystemExit("no training examples")
    random.shuffle(kept)

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=quant, torch_dtype=torch.float16,
                                                 device_map={"": local}, attn_implementation="sdpa")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    arguments = TrainingArguments(
        output_dir=str(args.out / "checkpoints"), per_device_train_batch_size=1, gradient_accumulation_steps=args.accum,
        num_train_epochs=args.epochs, learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=0.05,
        fp16=True, logging_steps=10, save_strategy="no", report_to=[], seed=args.seed, remove_unused_columns=False,
        ddp_find_unused_parameters=False, group_by_length=False, optim="paged_adamw_8bit")
    trainer = Trainer(model=model, args=arguments, train_dataset=Examples(kept),
                      data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=IGNORE))
    trainer.train()
    if trainer.is_world_process_zero():
        args.out.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(args.out))
        print("adapter saved to", args.out, flush=True)


if __name__ == "__main__":
    main()
