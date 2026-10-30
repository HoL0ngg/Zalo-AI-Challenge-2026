#!/usr/bin/env sh
set -eu
python -m src.cli generate
python -m pytest -q tests
python -m src.cli report
