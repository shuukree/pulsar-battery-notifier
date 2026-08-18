"""Long-window battery log + a PNG chart renderer for the tray 'history' view.

Separate from estimate.py's short discharge window: this keeps a longer record
(default ~48h) including charging, purely so we can draw a nice graph. Rendered
to a PNG with Pillow (already a dependency) and opened in the default image
viewer - no GUI toolkit, so it can't clash with the tray's event loop.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque


class BatteryLog:
    def __init__(self, path, window_seconds: float = 48 * 3600, max_samples: int = 5000):
        self.path = path
        self.window_seconds = window_seconds
        self.max_samples = max_samples
        self._samples: deque[tuple[float, int, bool]] = deque()

    def add(self, percent: int, charging: bool, at: float | None = None) -> None:
        now = time.time() if at is None else at
        self._samples.append((now, int(percent), bool(charging)))
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        while len(self._samples) > self.max_samples:
            self._samples.popleft()

    def samples(self) -> list[tuple[float, int, bool]]:
        return list(self._samples)

    def snapshot(self) -> list[list]:
        return [[t, p, int(c)] for t, p, c in self._samples]

    def save(self) -> None:
        try:
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"samples": self.snapshot()}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def load(self) -> None:
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f).get("samples", [])
        except (OSError, ValueError):
            return
        now = time.time()
        cutoff = now - self.window_seconds
        cleaned: list[tuple[float, int, bool]] = []
        for item in raw:
            try:
                t, p, c = float(item[0]), int(item[1]), bool(item[2])
            except (TypeError, ValueError, IndexError):
                continue
            if t > now + 60 or t < cutoff:
                continue
            cleaned.append((t, p, c))
        cleaned.sort()
        self._samples = deque(cleaned[-self.max_samples:])


# -- chart -----------------------------------------------------------------

_BG = (250, 250, 250, 255)
_GRID = (222, 222, 222, 255)
_AXIS = (120, 120, 120, 255)
_TEXT = (60, 60, 60, 255)
_LINE = (79, 70, 229, 255)       # indigo
_FILL = (79, 70, 229, 40)
_CHG = (66, 165, 245, 60)        # charging band


def _font(size: int):
    from PIL import ImageFont

    for path in (
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_chart(samples, out_path, hours: float = 24.0) -> str:
    """Render a battery-vs-time PNG for the last `hours`. Returns out_path."""
    from PIL import Image, ImageDraw

    W, H = 900, 420
    ml, mr, mt, mb = 56, 20, 46, 40
    img = Image.new("RGBA", (W, H), _BG)
    d = ImageDraw.Draw(img)

    now = time.time()
    pts = [(t, p, c) for (t, p, c) in samples if t >= now - hours * 3600]
    title_font = _font(20)
    small = _font(13)

    d.text((ml, 14), f"Pulsar battery - last {int(hours)}h", font=title_font, fill=_TEXT)

    px0, py0 = ml, mt
    px1, py1 = W - mr, H - mb

    def y_of(pct: float) -> float:
        return py1 - (max(0.0, min(100.0, pct)) / 100.0) * (py1 - py0)

    # Horizontal gridlines + y labels.
    for lvl in (0, 20, 50, 80, 100):
        y = y_of(lvl)
        d.line((px0, y, px1, y), fill=_GRID, width=1)
        d.text((px0 - 30, y - 7), f"{lvl}", font=small, fill=_AXIS)

    if len(pts) < 2:
        d.text((ml, H // 2), "Not enough data yet - come back after using the mouse a while.",
                font=small, fill=_TEXT)
        img.convert("RGB").save(out_path)
        return out_path

    t_min = pts[0][0]
    t_max = max(now, pts[-1][0])
    span = max(1.0, t_max - t_min)

    def x_of(t: float) -> float:
        return px0 + (t - t_min) / span * (px1 - px0)

    # Charging bands (light blue behind the line).
    seg_start = None
    for i, (t, _p, c) in enumerate(pts):
        if c and seg_start is None:
            seg_start = t
        if (not c or i == len(pts) - 1) and seg_start is not None:
            d.rectangle((x_of(seg_start), py0, x_of(t), py1), fill=_CHG)
            seg_start = None

    # Area fill + line.
    line = [(x_of(t), y_of(p)) for (t, p, _c) in pts]
    poly = [(px0, py1)] + line + [(line[-1][0], py1)]
    d.polygon(poly, fill=_FILL)
    d.line(line, fill=_LINE, width=3, joint="curve")

    # Axis frame.
    d.line((px0, py0, px0, py1), fill=_AXIS, width=1)
    d.line((px0, py1, px1, py1), fill=_AXIS, width=1)

    # X time labels (a few ticks).
    ticks = 4
    for i in range(ticks + 1):
        t = t_min + span * i / ticks
        x = x_of(t)
        ago = (now - t) / 3600.0
        label = "now" if ago < 0.05 else f"-{ago:.0f}h"
        d.line((x, py1, x, py1 + 4), fill=_AXIS, width=1)
        d.text((x - 10, py1 + 8), label, font=small, fill=_AXIS)

    cur = pts[-1][1]
    state = "charging" if pts[-1][2] else "on battery"
    d.text((px1 - 150, 16), f"now: {cur}% ({state})", font=small, fill=_TEXT)

    img.convert("RGB").save(out_path)
    return out_path
