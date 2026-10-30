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
- one candidate and no self-repair
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

The production pipeline is being implemented incrementally under
[src/](src/). Configuration and model declarations are ready first so later
fine-tuning and serving changes have one stable source of truth.
