import math
from pathlib import Path

import yaml


def check_model_budget(path: Path) -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    total = 0.0
    for model in config["models"].values():
        value = float(model["parameters_billion"])
        if not math.isfinite(value) or value < 0:
            raise ValueError("Invalid model parameter declaration")
        if model["enabled"]:
            total += value
    limit = float(config["budget"]["max_parameters_billion"])
    if not math.isfinite(limit) or not 0 < limit <= 15 or total > limit:
        raise ValueError(f"Model budget exceeded or invalid: {total}B (hard limit 15B)")
    return config
