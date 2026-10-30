#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
export PYTHONHASHSEED=20261030
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m datamate.cli run --data-dir /data --result-dir /result "$@"
