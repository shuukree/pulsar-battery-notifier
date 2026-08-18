"""User-editable settings, persisted as JSON in %APPDATA%.

Kept tiny on purpose: thresholds, poll interval, and whether to beep. Editing the
JSON by hand (via the tray's "Open config folder") is a first-class workflow, so
the file is human-friendly and re-read on change.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "PulsarBatteryNotifier"

DEFAULT_THRESHOLDS = [20, 15, 10, 5, 1]
DEFAULT_POLL_SECONDS = 30


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "settings.json"


def history_path() -> Path:
    return config_dir() / "discharge_history.json"


def battery_log_path() -> Path:
    return config_dir() / "battery_log.json"


@dataclass
class Settings:
    thresholds: list[int] = field(default_factory=lambda: list(DEFAULT_THRESHOLDS))
    poll_seconds: int = DEFAULT_POLL_SECONDS
    # Faster cadence used while the mouse is asleep/unknown, so we notice it
    # waking within a few seconds instead of up to a full poll_seconds.
    wake_poll_seconds: int = 12
    rearm_hysteresis: int = 3
    beep: bool = True
    # How long to trust the last reading while the mouse is asleep (dongle
    # silent). Beyond this the status shows as "unknown".
    stale_grace_seconds: int = 600
    connection_mode: str = "auto"  # auto | wireless | wired
    # Check GitHub for a newer release in the background, and how often.
    auto_update_check: bool = True
    update_check_hours: int = 24
    # Show an estimated time-to-empty in the tray tooltip, e.g. "85% (~12h)".
    show_time_estimate: bool = True
    # Notify once when charging reaches this level ("battery full, unplug").
    notify_full: bool = True
    full_level: int = 100

    def sanitized(self) -> "Settings":
        thresholds = sorted({int(t) for t in self.thresholds if 1 <= int(t) <= 100}, reverse=True)
        if not thresholds:
            thresholds = list(DEFAULT_THRESHOLDS)
        mode = self.connection_mode if self.connection_mode in {"auto", "wireless", "wired"} else "auto"
        return Settings(
            thresholds=thresholds,
            poll_seconds=max(2, int(self.poll_seconds)),
            wake_poll_seconds=max(2, int(self.wake_poll_seconds)),
            rearm_hysteresis=max(1, int(self.rearm_hysteresis)),
            beep=bool(self.beep),
            stale_grace_seconds=max(60, int(self.stale_grace_seconds)),
            connection_mode=mode,
            auto_update_check=bool(self.auto_update_check),
            update_check_hours=max(1, int(self.update_check_hours)),
            show_time_estimate=bool(self.show_time_estimate),
            notify_full=bool(self.notify_full),
            full_level=max(50, min(100, int(self.full_level))),
        )


def load() -> Settings:
    path = config_path()
    if not path.exists():
        settings = Settings()
        save(settings)
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = {**asdict(Settings()), **data}
        # Drop unknown keys so a hand-edited file can't crash construction.
        known = {f for f in asdict(Settings())}
        merged = {k: v for k, v in merged.items() if k in known}
        return Settings(**merged).sanitized()
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        # Corrupt file: fall back to defaults rather than refusing to start.
        return Settings()


def save(settings: Settings) -> None:
    config_path().write_text(
        json.dumps(asdict(settings.sanitized()), indent=2),
        encoding="utf-8",
    )
