# DataMate

Offline Vietnamese business QA agent for CSV, XLSX, and SQLite data.

## Baseline setup

Python 3.10+ is required. The baseline uses the mock backend, so it can be
installed and tested on Windows without downloading model weights:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The inference model declarations are in
[configs/models.yaml](configs/models.yaml). `pip` installs the Python runtime,
not model weights. For a real offline run, copy the declared weights into the
configured `local_path` values before starting the container.

The default configuration is intentionally safe:

- `runtime.backend: mock`
- no network calls at inference
- one candidate and at most one self-repair
- fail-safe result: `abstain`

Edit [configs/default.yaml](configs/default.yaml) only after the baseline is
working. The optional Linux/CUDA stack is in `requirements-gpu.txt`; it
includes vLLM and must not be installed on Windows.

## Synthetic benchmark

The deterministic benchmark generator is under [synth/](synth/):

```powershell
Set-Location synth
py -3 -m pip install -r ..\requirements.txt
py -3 -m src.cli all
```

## Runnable baseline

Install only the baseline dependencies with `python -m pip install -e ".[test]"`.
Then run `make test`, `make run-sample`, and `make eval-sample`.
See [baseline usage and limitations](docs/13_baseline.md) for Windows commands,
input layout, mock grammar, stage boundaries, resume and timeout behavior.

| Model | Parameters (B) | Default inference status |
|---|---:|---|
| Qwen2.5-Coder-7B-Instruct | 7.61 | Disabled; optional local vLLM |
| BGE-M3 | 0.568 | Disabled; no embedding stage yet |
| Reranker / classifier | 0 | None |
| Mock backend | 0 | Enabled |

Declarations and enabled-model budget checks use `configs/models.yaml`.
Model weights and pre-cutoff publication eligibility must be verified before freezing
the optional GPU configuration. No model weights are required for baseline tests.
