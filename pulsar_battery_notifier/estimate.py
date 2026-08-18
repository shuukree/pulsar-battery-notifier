"""Estimate remaining battery time from the recent discharge slope.

The Pulsar mice have no fuel-gauge IC, so the percentage is coarse and laggy.
Rather than trust two instantaneous readings, we keep a rolling window of
(time, percent) samples taken while discharging and fit a line through them; the
slope is the discharge rate in %/hour, and remaining time is current% / rate.

We only report an estimate once there is real signal (enough samples over enough
time, with a measurable drop) and reset whenever the battery charges or jumps up,
so a recharge never poisons the slope.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque


class RuntimeEstimator:
    def __init__(
        self,
        window_seconds: float = 3 * 3600,
        max_samples: int = 400,
        min_seconds: float = 10 * 60,
        min_drop: float = 2.0,
    ):
        self._samples: deque[tuple[float, float]] = deque()
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        self.min_seconds = min_seconds
        self.min_drop = min_drop

    def reset(self) -> None:
        self._samples.clear()

    def snapshot(self) -> list[list[float]]:
        """Serialisable copy of the current samples."""
        return [[t, p] for t, p in self._samples]

    def restore(self, samples, now: float | None = None) -> None:
        """Load persisted samples, dropping anything outside the time window."""
        now = time.time() if now is None else now
        cutoff = now - self.window_seconds
        cleaned: list[tuple[float, float]] = []
        for item in samples or ():
            try:
                t, p = float(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if t > now + 60 or t < cutoff:  # future or too old -> skip
                continue
            cleaned.append((t, p))
        cleaned.sort()
        self._samples = deque(cleaned[-self.max_samples:])

    def add(self, percent: int | None, charging: bool, at: float | None = None) -> None:
        """Feed a reading. Charging / unknown / a jump up clears the window."""
        now = time.time() if at is None else at
        if charging or percent is None:
            self.reset()
            return
        if self._samples and percent > self._samples[-1][1] + 1:
            # Battery went up (recharged or a fresh cell) -> old slope is stale.
            self.reset()
        self._samples.append((now, float(percent)))
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        while len(self._samples) > self.max_samples:
            self._samples.popleft()

    def hours_remaining(self) -> float | None:
        """Hours until 0%, or None if we don't have a confident estimate yet."""
        s = self._samples
        if len(s) < 3:
            return None
        span = s[-1][0] - s[0][0]
        if span < self.min_seconds:
            return None
        if (s[0][1] - s[-1][1]) < self.min_drop:
            return None  # not enough measurable drop to trust a slope

        # Least-squares slope of percent vs time (in hours).
        t0 = s[0][0]
        xs = [(t - t0) / 3600.0 for t, _ in s]
        ys = [p for _, p in s]
        n = len(s)
        sx = sum(xs)
        sy = sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        denom = n * sxx - sx * sx
        if denom == 0:
            return None
        slope = (n * sxy - sx * sy) / denom  # %/hour (negative while discharging)
        rate = -slope
        if rate <= 0.05:  # essentially flat -> no useful prediction
            return None
        hours = ys[-1] / rate
        if hours <= 0 or hours > 240:  # sanity cap at 10 days
            return None
        return hours


def save_history(path, samples) -> None:
    """Persist samples to a JSON file (atomic write)."""
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"samples": samples}, f)
        os.replace(tmp, path)
    except OSError:
        pass  # persistence is best-effort; never break the poll loop


def load_history(path) -> list:
    try:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("samples", [])
    except (OSError, ValueError):
        return []


def format_hours(hours: float | None) -> str | None:
    """'~45m', '~4h 30m', '~12h', '~1d 4h' - or None."""
    if hours is None:
        return None
    total_min = int(round(hours * 60))
    if total_min < 60:
        return f"~{max(1, total_min)}m"
    h, m = divmod(total_min, 60)
    if h >= 48:
        d, hh = divmod(h, 24)
        return f"~{d}d {hh}h" if hh else f"~{d}d"
    if m == 0:
        return f"~{h}h"
    return f"~{h}h {m}m"
