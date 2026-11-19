"""Chat-spike detector: fires when chat suddenly gets much busier than normal."""
from __future__ import annotations

import time
from collections import deque


class SpikeDetector:
    def __init__(self, cfg: dict):
        d = cfg["detector"]
        self.window = d["window_seconds"]
        self.baseline = d["baseline_seconds"]
        self.multiplier = d["spike_multiplier"]
        self.min_weight = d["min_weight"]
        self.cooldown = d["cooldown_seconds"]
        self.warmup = d["warmup_seconds"]
        self.keywords = [k.upper() for k in d["keywords"]]
        self.keyword_weight = d["keyword_weight"]

        self.started = time.time()
        self.last_fire = 0.0
        self.win: deque[tuple[float, float]] = deque()   # last `window` seconds
        self.base: deque[tuple[float, float]] = deque()  # older, up to `baseline`
        self.win_sum = 0.0
        self.base_sum = 0.0

    def weight(self, text: str) -> float:
        up = text.upper()
        return self.keyword_weight if any(k in up for k in self.keywords) else 1.0

    def _roll(self, now: float) -> None:
        while self.win and self.win[0][0] < now - self.window:
            item = self.win.popleft()
            self.win_sum -= item[1]
            self.base.append(item)
            self.base_sum += item[1]
        while self.base and self.base[0][0] < now - self.baseline:
            self.base_sum -= self.base.popleft()[1]

    def feed(self, text: str, now: float | None = None) -> dict | None:
        """Add one chat message. Returns a spike dict when a clip should be made."""
        now = now or time.time()
        w = self.weight(text)
        self.win.append((now, w))
        self.win_sum += w
        self._roll(now)

        elapsed = now - self.started
        if elapsed < self.warmup:
            return None

        base_span = max(min(self.baseline, elapsed) - self.window, 1.0)
        base_per_window = max(self.base_sum / base_span * self.window, 3.0)
        ratio = self.win_sum / base_per_window

        if (
            self.win_sum >= self.min_weight
            and ratio >= self.multiplier
            and now - self.last_fire >= self.cooldown
        ):
            self.last_fire = now
            return {"time": now, "weight": round(self.win_sum, 1), "ratio": round(ratio, 2)}
        return None
