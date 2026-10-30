import os
import random


def seed_everything(seed: int) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    random.seed(seed)
    import numpy as np
    np.random.seed(seed)
