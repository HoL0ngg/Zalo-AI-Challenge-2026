import json
import pathlib
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml


def notebook():
    path = pathlib.Path("notebooks/kaggle_finetune.ipynb")
    return json.loads(path.read_text(encoding="utf-8"))


def test_finetune_notebook_cells_are_valid_python():
    for index, cell in enumerate(notebook()["cells"]):
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"notebook-cell-{index}", "exec")


@pytest.mark.parametrize("correct_counts,winner", [((4, 3), "checkpoint-1"), ((2, 2), "base")])
def test_checkpoint_selection_uses_full_holdout_and_keeps_base_on_tie(tmp_path, monkeypatch, correct_counts, winner):
    # Execute the real selection cell with fake GPU processes and real scorer/files/configs.
    def path(value):
        return tmp_path / str(value).removeprefix("/kaggle/working/") if str(value).startswith(
            "/kaggle/working/") else tmp_path if str(value) == "/kaggle/working" else pathlib.Path(value)

    train, base_dir, adapter_dir = (tmp_path / name for name in ("train", "base", "lora"))
    for directory in (train, base_dir, adapter_dir):
        directory.mkdir()
    repo = tmp_path / "repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "models").mkdir()
    for name in ("models_kaggle_lora.yaml", "kaggle_lora.yaml"):
        shutil.copy2(pathlib.Path("configs") / name, repo / "configs" / name)
    gold = [{"id": f"q{i}", "type": "number", "answer": 1} for i in range(4)]
    questions = [{"id": f"q{i}", "business_id": "held"} for i in range(4)] + [{"id": "other", "business_id": "trained"}]

    def write_rows(file, rows):
        file.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def predictions(correct):
        return [dict(row, answer=1 if i < correct else 0) for i, row in enumerate(gold)]

    write_rows(train / "answers.jsonl", gold)
    write_rows(train / "questions.jsonl", questions)
    write_rows(base_dir / "submission.jsonl", predictions(2))
    for i in (1, 2):
        checkpoint = adapter_dir / "checkpoints" / f"checkpoint-{i}"
        checkpoint.mkdir(parents=True)
        (checkpoint / "adapter_config.json").write_text('{"r":32}')
        (checkpoint / "adapter_model.safetensors").write_bytes(bytes([i]))

    def gpu_run(cmd, **kwargs):
        assert "--max-per-business" not in cmd
        config = yaml.safe_load(pathlib.Path(cmd[cmd.index("--config") + 1]).read_text())
        models = yaml.safe_load(pathlib.Path(config["models"]).read_text())
        model = models["models"]["code_generation"]
        assert pathlib.Path(model["local_path"]).is_absolute()
        index = int(pathlib.Path(model["lora_path"]).name.split("-")[-1])
        output = pathlib.Path(cmd[cmd.index("--result-dir") + 1])
        output.mkdir(parents=True)
        write_rows(output / "submission.jsonl", predictions(correct_counts[index - 1]))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", gpu_run)
    # Windows CI may not allow directory symlinks; keep all test writes in tmp_path.
    monkeypatch.setattr(pathlib.Path, "symlink_to", lambda self, target, **kwargs: self.write_text(str(target)))
    source = "".join(notebook()["cells"][13]["source"])
    namespace = dict(Path=path, pathlib=SimpleNamespace(Path=path), ROOT=repo,
                     TRAIN=SimpleNamespace(out=adapter_dir), TRAIN_DIR=train, R1=str(base_dir), HOLDOUT=["held"],
                     checked_cli=lambda *args, **kwargs: None, shutil=shutil)
    exec(compile(source, "checkpoint-selection", "exec"), namespace)
    selection = json.loads((tmp_path / "selection.json").read_text())
    assert selection["questions"] == 4 and selection["selected"] == winner
    if winner != "base":
        assert (adapter_dir / "adapter_model.safetensors").read_bytes() == b"\x01"


@pytest.mark.parametrize("duplicate", [False, True])
def test_base_winner_reuses_public_predictions_and_checks_ids(tmp_path, monkeypatch, duplicate):
    records = [{"id": "a", "type": "abstain"}, {"id": "b", "type": "abstain"}]
    (tmp_path / "questions.jsonl").write_text("\n".join(json.dumps(row) for row in records))
    (tmp_path / "submission.jsonl").write_text("\n".join(json.dumps(row) for row in
                                                         records + ([records[0]] if duplicate else [])))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Base inference must not run twice"))
    copies = []
    monkeypatch.setattr(shutil, "copy2", lambda src, dst: copies.append((src, dst)))

    def read_rows(file):
        return [json.loads(line) for line in pathlib.Path(file).read_text().splitlines()]

    namespace = dict(CONFIG="configs/kaggle.yaml", PUBLIC_BASE=str(tmp_path), TEST_DIR=tmp_path,
                     read_rows=read_rows, checked_cli=lambda *a: None, subprocess=subprocess)
    source = "".join(notebook()["cells"][14]["source"])
    if duplicate:
        with pytest.raises(AssertionError, match="ID"):
            exec(compile(source, "public-selection", "exec"), namespace)
        assert not copies
    else:
        exec(compile(source, "public-selection", "exec"), namespace)
        assert len(copies) == 1 and pathlib.Path(copies[0][0]) == tmp_path / "submission.jsonl"
        assert copies[0][1] == "/kaggle/working/submission.jsonl"
