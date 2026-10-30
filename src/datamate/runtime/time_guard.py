import time
from dataclasses import dataclass, field


@dataclass
class TimeGuard:
    budget: float = 19800
    reserve: float = 60
    started: float = field(default_factory=time.monotonic)

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget - self.reserve - (time.monotonic() - self.started))

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0
