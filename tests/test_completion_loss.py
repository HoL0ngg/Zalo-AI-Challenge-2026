"""Optional CPU/GPU-stack checks: no downloaded weights, tiny randomly initialized Qwen."""
import copy
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")
from peft import LoraConfig, get_peft_model
from transformers import Qwen2Config, Qwen2ForCausalLM, Trainer, TrainingArguments

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from train_lora import CompletionCollator, Examples, IGNORE


def collate(features):
    return {key: torch.tensor([f[key] for f in features]) for key in features[0]}


def tiny_model():
    torch.manual_seed(42)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=32, hidden_size=16, intermediate_size=32,
                                       num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
                                       max_position_embeddings=32, attention_dropout=0.0, use_cache=False))
    model = get_peft_model(model, LoraConfig(r=2, lora_alpha=4, task_type="CAUSAL_LM",
                                           target_modules=["q_proj", "v_proj"], lora_dropout=0.0))
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.train()
    return model


@pytest.mark.parametrize("batch_size", [1, 2])
def test_sparse_logits_preserve_loss_and_lora_gradients(batch_size):
    features = [dict(input_ids=[1, 2, 3, 4, 5, 6], attention_mask=[1] * 6,
                     labels=[IGNORE, IGNORE, IGNORE, 4, 5, 6]),
                dict(input_ids=[1, 2, 3, 4, 0, 0], attention_mask=[1, 1, 1, 1, 0, 0],
                     labels=[IGNORE, IGNORE, 3, 4, IGNORE, IGNORE])][:batch_size]
    full = tiny_model()
    sparse = copy.deepcopy(full)
    batch = collate(features)
    count = (batch["labels"][:, 1:] != IGNORE).sum()
    reference = full(**batch, num_items_in_batch=count)
    reduced = sparse(**CompletionCollator(collate)(features), num_items_in_batch=count)
    assert reduced.logits.shape[1] < reference.logits.shape[1]
    torch.testing.assert_close(reference.loss, reduced.loss)
    reference.loss.backward()
    reduced.loss.backward()
    trained = 0
    for (name, left), (_, right) in zip(full.named_parameters(), sparse.named_parameters()):
        if left.requires_grad:
            assert left.grad is not None and right.grad is not None, name
            torch.testing.assert_close(left.grad, right.grad, atol=1e-6, rtol=1e-4)
            trained += 1
    assert trained and any(p.grad.abs().sum() > 0 for p in sparse.parameters() if p.requires_grad)


def test_completion_collator_rejects_empty_supervision():
    with pytest.raises(ValueError, match="no supervised"):
        CompletionCollator(collate)([dict(input_ids=[1, 2], labels=[IGNORE, IGNORE])])


def test_completion_logits_train_with_real_trainer_accumulation(tmp_path):
    rows = [dict(input_ids=[1, 2, 3, 4], attention_mask=[1] * 4, labels=[IGNORE, IGNORE, 3, 4]) for _ in range(4)]
    model = tiny_model()
    before = {n: p.detach().clone() for n, p in model.named_parameters() if p.requires_grad}
    trainer = Trainer(model=model, args=TrainingArguments(
        output_dir=str(tmp_path), use_cpu=True, per_device_train_batch_size=1,
        gradient_accumulation_steps=2, max_steps=2, save_strategy="no", report_to=[],
        learning_rate=1e-3, disable_tqdm=True), train_dataset=Examples(rows),
        data_collator=CompletionCollator(collate))
    metrics = trainer.train().metrics
    assert torch.isfinite(torch.tensor(metrics["train_loss"]))
    assert trainer.state.global_step == 2
    assert any(not torch.equal(before[n], p.detach()) for n, p in model.named_parameters() if n in before)
