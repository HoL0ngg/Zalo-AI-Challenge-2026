"""Loaders for bundled data files (repo-root `data/` and `configs/`).

Nothing here touches the network. Missing files degrade to empty/builtin values so a
question is never lost because a resource file is absent; callers add a warning.
Results are cached read-only values (pure functions of the file content).
"""
from __future__ import annotations

import copy
import json
import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Fallback only; configs/rules_defaults.yaml is the editable source of truth.
BUILTIN_DEFAULTS: dict[str, Any] = {
    "week": {"starts_on": "monday"},
    "time": {
        "month_to_as_of": True,
        "this_week_mode": "week_to_date",
        "quarter_to_as_of": True,
        "year_to_as_of": True,
        "rolling_window_includes_as_of": True,
        "pre_tet_days": 7,
        "post_tet_days": 7,
        "tet_lunar_start": "12-23",
        "tet_lunar_end": "01-10",
        "bare_cung_ky": "year",
    },
}


def repo_root() -> Path:
    override = os.environ.get("DATAMATE_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip().lower()


@lru_cache(maxsize=None)
def _json(path: str) -> Any:
    file = Path(path)
    if not file.is_file():
        return {}
    return json.loads(file.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=None)
def _lines(path: str) -> tuple[str, ...]:
    file = Path(path)
    if not file.is_file():
        return ()
    lines = (_nfc(line) for line in file.read_text(encoding="utf-8-sig").splitlines())
    return tuple(line for line in lines if line and not line.startswith("#"))


def load_teencode(root: Path | None = None) -> dict[str, tuple[str, ...]]:
    """canonical phrase -> variants (data/teencode_dict.json)."""
    raw = _json(str((root or repo_root()) / "data" / "teencode_dict.json"))
    return {unicodedata.normalize("NFC", k): tuple(unicodedata.normalize("NFC", v) for v in vs)
            for k, vs in raw.items()}


def load_lexicon(root: Path | None = None) -> tuple[str, ...]:
    return _lines(str((root or repo_root()) / "data" / "vi_lexicon.txt"))


def load_homographs(root: Path | None = None) -> frozenset[str]:
    return frozenset(_lines(str((root or repo_root()) / "data" / "vi_homographs.txt")))


@lru_cache(maxsize=None)
def _rule_defaults(path: str) -> dict[str, Any]:
    merged = copy.deepcopy(BUILTIN_DEFAULTS)
    file = Path(path)
    if file.is_file():
        loaded = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
    return merged


def load_rule_defaults(root: Path | None = None) -> dict[str, Any]:
    return copy.deepcopy(_rule_defaults(str((root or repo_root()) / "configs" / "rules_defaults.yaml")))


@lru_cache(maxsize=None)
def _schema_roles(path: str) -> dict[str, Any]:
    file = Path(path)
    if not file.is_file():
        return {}
    return yaml.safe_load(file.read_text(encoding="utf-8")) or {}


def load_schema_roles(root: Path | None = None) -> dict[str, Any]:
    """Role/concept synonym tables for the canonical layer (configs/schema_roles.yaml)."""
    return copy.deepcopy(_schema_roles(str((root or repo_root()) / "configs" / "schema_roles.yaml")))
