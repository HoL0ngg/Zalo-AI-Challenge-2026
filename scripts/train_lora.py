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
import math
import os
import random
from pathlib import Path

IGNORE = -100


def encode(tokenizer, messages: list[dict], max_len: int) -> dict | None:
    """Token ids and labels with the system+user part masked; None when the example is too long."""
    if [m["role"] for m in messages] != ["system", "user", "assistant"] or not messages[-1]["content"].strip():
        raise ValueError("Expected system/user/assistant messages with a non-empty SQL completion")
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False)
    full = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False,
                                         enable_thinking=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if len(ids) > max_len or len(ids) <= len(prompt_ids) or ids[:len(prompt_ids)] != prompt_ids:
        return None
    return {"input_ids": ids, "attention_mask": [1] * len(ids), "labels": [IGNORE] * len(prompt_ids) + ids[len(prompt_ids):]}


class Examples:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict:
        return self.rows[index]


def training_options(args, examples: int, world_size: int) -> dict:
    """Use integer warmup_steps, supported by both Transformers 4 and 5."""
    steps = args.max_steps if args.max_steps > 0 else math.ceil(
        math.ceil(math.ceil(examples / world_size) / args.accum) * args.epochs)
    return dict(
        output_dir=str(args.out / "checkpoints"), per_device_train_batch_size=1,
        gradient_accumulation_steps=args.accum, num_train_epochs=args.epochs, max_steps=args.max_steps,
        learning_rate=args.lr, lr_scheduler_type="cosine", warmup_steps=math.ceil(steps * 0.05),
        fp16=True, logging_steps=1, save_strategy="epoch", save_only_model=True, save_total_limit=2,
        report_to=[], seed=args.seed, data_seed=args.seed, remove_unused_columns=False,
        ddp_find_unused_parameters=False, optim="paged_adamw_8bit",
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="directory of the unquantized base model (fp16/bf16 weights)")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--rank", type=int, default=32)
    parser.add_argument("--accum", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--max-steps", type=int, default=-1, help="positive value for a short DDP training smoke test")
    args = parser.parse_args()
    if (args.max_len < 1 or args.epochs <= 0 or args.lr <= 0 or args.rank < 1 or args.accum < 1
            or args.max_steps == 0 or args.max_steps < -1):
        parser.error("length, epochs, lr, rank, accum must be positive; max-steps must be -1 or positive")
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq,
                              Trainer, TrainingArguments)

    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    local = int(os.environ.get("LOCAL_RANK", 0))
    torch.cuda.set_device(local)
    world = int(os.environ.get("WORLD_SIZE", 1))
    # Validate the training API before loading any weights, including in notebook preflight.
    TrainingArguments(**training_options(args, 1, world))
    tokenizer = AutoTokenizer.from_pretrained(args.base, local_files_only=True, padding_side="right")
    rows = [encode(tokenizer, json.loads(line)["messages"], args.max_len)
            for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [r for r in rows if r]
    if local == 0:
        print(f"examples: {len(kept)} kept, {len(rows) - len(kept)} too long or template-mismatched dropped; "
              f"max_len={args.max_len}, effective batch={world * args.accum}", flush=True)
    if not kept:
        raise SystemExit("no training examples")
    random.shuffle(kept)
    arguments = TrainingArguments(**training_options(args, len(kept), world))
    if local == 0:
        lengths = sorted(len(row["input_ids"]) for row in kept)
        print(f"sequence tokens: median={lengths[len(lengths)//2]}, max={lengths[-1]}; "
              f"warmup_steps={arguments.warmup_steps}", flush=True)

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=quant, torch_dtype=torch.float16,
                                                 device_map={"": local}, attn_implementation="sdpa",
                                                 local_files_only=True)
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    trainer = Trainer(model=model, args=arguments, train_dataset=Examples(kept),
                      data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=IGNORE))
    metrics = trainer.train().metrics
    if trainer.is_world_process_zero():
        args.out.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(args.out))
        tokenizer.save_pretrained(str(args.out))
        trainer.save_metrics("train", metrics)
        (args.out / "training_summary.json").write_text(json.dumps({
            "examples": len(kept), "dropped": len(rows) - len(kept), "world_size": world,
            "effective_batch": world * args.accum, "arguments": vars(args), "metrics": metrics,
        }, default=str, indent=2), encoding="utf-8")
        print("adapter saved to", args.out, flush=True)


if __name__ == "__main__":
    main()
