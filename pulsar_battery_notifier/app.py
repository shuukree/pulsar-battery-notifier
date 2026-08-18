"""Ties everything together: poll the mouse, run thresholds, show toasts.

Two entry points:

* :func:`run_headless` - a plain loop that prints status and fires toasts. Good
  for debugging or running under a console.
* :func:`run_tray` - the same loop wrapped in a system-tray icon with a small
  menu. This is the normal way to use the app.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from functools import lru_cache

from . import __version__, config, notifications, updates
from .device import BatteryStatus, DeviceNotFound, current_device, read_battery
from .estimate import RuntimeEstimator, format_hours, load_history, save_history
from .history import BatteryLog
from .thresholds import ThresholdEngine


@dataclass
class Reading:
    percent: int | None
    charging: bool
    fresh: bool          # True if the dongle answered this poll
    device_present: bool
    at: float


class Notifier:
    """Owns the poll loop and threshold state. Thread-safe-ish for the tray."""

    def __init__(self, settings: config.Settings):
        self.settings = settings
        self.engine = ThresholdEngine(settings.thresholds, settings.rearm_hysteresis)
        self._last_good: BatteryStatus | None = None
        self._last_good_at: float = 0.0
        self._miss_streak = 0  # consecutive polls with no answer (asleep)
        self.estimator = RuntimeEstimator()
        # Persisted discharge history so the estimate survives restarts.
        self._history_path = config.history_path()
        self._last_hist_save = 0.0
        try:
            self.estimator.restore(load_history(self._history_path))
        except Exception:  # noqa: BLE001 - bad/old file must not block startup
            pass
        # Longer battery log for the history chart.
        self.log = BatteryLog(config.battery_log_path())
        try:
            self.log.load()
        except Exception:  # noqa: BLE001
            pass
        self._full_notified = False
        self._seen_below_full = False
        try:
            self._settings_mtime = os.path.getmtime(config.config_path())
        except OSError:
            self._settings_mtime = None
        self._stop = threading.Event()
        self._latest = Reading(None, False, False, False, 0.0)
        self._on_update = None  # optional callback(Reading) for the tray
        # Set by the background update check when a newer release is found.
        self._update: updates.UpdateInfo | None = None
        self._update_notified = False

    # -- polling -----------------------------------------------------------
    def _maybe_reload_settings(self) -> None:
        """Pick up edits to settings.json (from the GUI or a hand-edit) live."""
        try:
            m = os.path.getmtime(config.config_path())
        except OSError:
            return
        if self._settings_mtime is None:
            self._settings_mtime = m
            return
        if m != self._settings_mtime:
            self._settings_mtime = m
            try:
                new = config.load()
            except Exception:  # noqa: BLE001
                return
            self.settings = new
            self.engine = ThresholdEngine(new.thresholds, new.rearm_hysteresis)

    def poll_once(self) -> Reading:
        self._maybe_reload_settings()
        now = time.time()
        device_present = True
        # Once we've had a good reading the interface is warm, so a plain query
        # catches the wake and we skip the slow warm-up. But every 5th miss we
        # retry with warm-up in case the interface actually went cold.
        warmup = self._last_good is None or (
            self._miss_streak > 0 and self._miss_streak % 5 == 0
        )
        try:
            status = read_battery(self.settings.connection_mode, warmup=warmup)
        except DeviceNotFound:
            status = None
            device_present = False

        if status is not None:
            self._miss_streak = 0
            self._last_good = status
            self._last_good_at = now
            self.estimator.add(status.percent, status.charging, now)
            # Persist at most once a minute so a restart keeps the estimate.
            if now - self._last_hist_save >= 60:
                self._last_hist_save = now
                save_history(self._history_path, self.estimator.snapshot())
                self.log.add(status.percent, status.charging, now)
                self.log.save()
            reading = Reading(status.percent, status.charging, True, True, now)
            self._check_full(status)
            alert = self.engine.update(status.percent, status.charging)
            if alert is not None:
                notifications.notify_low_battery(
                    alert, status.percent, beep=self.settings.beep
                )
        else:
            self._miss_streak += 1
            # Mouse asleep or unplugged. Reuse the last good reading within the
            # grace window so the tray doesn't flap to "unknown" constantly.
            within_grace = (
                self._last_good is not None
                and (now - self._last_good_at) <= self.settings.stale_grace_seconds
            )
            if within_grace and self._last_good is not None:
                reading = Reading(
                    self._last_good.percent, self._last_good.charging,
                    False, device_present, now,
                )
            else:
                reading = Reading(None, False, False, device_present, now)

        self._latest = reading
        self._write_state(reading)
        if self._on_update is not None:
            self._on_update(reading)
        return reading

    def _write_state(self, reading: Reading) -> None:
        """Publish the latest reading for the live panel (separate process)."""
        est = None
        if reading.percent is not None and not reading.charging:
            est = self.estimator.hours_remaining()
        dev_name = dev_conn = None
        try:
            info = current_device(self.settings.connection_mode)
            if info is not None:
                dev_name, dev_conn = info
        except Exception:  # noqa: BLE001
            pass
        payload = {
            "percent": reading.percent,
            "charging": reading.charging,
            "fresh": reading.fresh,
            "device_present": reading.device_present,
            "at": reading.at,
            "estimate_hours": est,
            "device_name": dev_name,
            "device_conn": dev_conn,
        }
        try:
            path = config.state_path()
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)
        except OSError:
            pass

    def _check_full(self, status: BatteryStatus) -> None:
        """Fire a 'battery full' toast once per charge cycle, only after we've
        actually seen it charge up across the threshold (so booting with an
        already-full, plugged-in mouse stays quiet)."""
        if not status.charging:
            self._full_notified = False  # re-arm for the next charge
            self._seen_below_full = False
            return
        if status.percent < self.settings.full_level:
            self._seen_below_full = True
        if (
            self.settings.notify_full
            and not self._full_notified
            and self._seen_below_full
            and status.percent >= self.settings.full_level
        ):
            self._full_notified = True
            notifications.notify_charged(status.percent, beep=self.settings.beep)

    # -- loop --------------------------------------------------------------
    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - never let the loop die
                print(f"[poll error] {exc}", file=sys.stderr)
            self._stop.wait(self._next_interval())

    def _next_interval(self) -> int:
        """Poll fast while asleep/unknown so we notice the mouse waking; relax
        to the normal cadence once it's answering."""
        if self._latest.fresh:
            return max(1, self.settings.poll_seconds)
        return max(1, min(self.settings.wake_poll_seconds, self.settings.poll_seconds))

    def stop(self) -> None:
        self._stop.set()
        # Flush the latest history so the estimate/graph survive a clean exit.
        try:
            save_history(self._history_path, self.estimator.snapshot())
            self.log.save()
        except Exception:  # noqa: BLE001
            pass

    @property
    def latest(self) -> Reading:
        return self._latest


def status_text(reading: Reading) -> str:
    if not reading.device_present:
        return "Dongle not found"
    if reading.percent is None:
        return "Battery: unknown (mouse asleep?)"
    state = "charging" if reading.charging else "on battery"
    freshness = "" if reading.fresh else " (last known)"
    return f"Battery: {reading.percent}% \u2014 {state}{freshness}"


def tooltip_text(reading: Reading, est_hours: float | None = None) -> str:
    """Short tray-tooltip line, e.g. 'Pulsar battery: 85% (~12h) - On battery'."""
    if not reading.device_present:
        return "Pulsar battery: not connected"
    if reading.percent is None:
        return "Pulsar battery: unknown (asleep)"
    if reading.charging:
        return f"Pulsar battery: {reading.percent}% - Charging"
    est = format_hours(est_hours)
    pct = f"{reading.percent}% ({est})" if est else f"{reading.percent}%"
    suffix = "" if reading.fresh else " (last known)"
    return f"Pulsar battery: {pct} - On battery{suffix}"


def run_headless(settings: config.Settings) -> None:
    notifier = Notifier(settings)
    print(f"Pulsar Battery Notifier v{__version__} - thresholds {settings.thresholds}, "
          f"every {settings.poll_seconds}s. Ctrl+C to stop.")

    def echo(reading: Reading) -> None:
        print(time.strftime("%H:%M:%S"), status_text(reading))

    notifier._on_update = echo
    try:
        notifier.run()
    except KeyboardInterrupt:
        notifier.stop()


# -- tray ------------------------------------------------------------------

# Windows fonts we prefer for the big tray number, in order.
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeuib.ttf",   # Segoe UI Bold
    r"C:\Windows\Fonts\arialbd.ttf",    # Arial Bold
    r"C:\Windows\Fonts\seguisb.ttf",    # Segoe UI Semibold
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)


@lru_cache(maxsize=8)
def _font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


# Digit fills per taskbar background. Colour conveys level either way; on a dark
# taskbar we use bright fills, on a light one deeper/saturated fills, each paired
# with a contrasting outline so the number stays crisp.
_PALETTE = {
    "dark": {
        "charging": (72, 170, 255, 255),
        "green": (86, 214, 122, 255),
        "orange": (245, 178, 46, 255),
        "red": (240, 84, 84, 255),
        "grey": (188, 188, 188, 255),
    },
    "light": {
        "charging": (14, 104, 210, 255),
        "green": (22, 146, 72, 255),
        "orange": (194, 116, 4, 255),
        "red": (200, 40, 40, 255),
        "grey": (92, 92, 92, 255),
    },
}
# Outline colour per theme (opposite luminance of the fill).
_OUTLINE = {"dark": (0, 0, 0, 165), "light": (255, 255, 255, 220)}

_theme_cache = {"at": 0.0, "light": False}


def _taskbar_is_light() -> bool:
    """True when Windows is using the Light taskbar. Cached briefly."""
    now = time.time()
    if now - _theme_cache["at"] < 5.0:
        return _theme_cache["light"]
    light = False
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            val, _ = winreg.QueryValueEx(k, "SystemUsesLightTheme")
            light = bool(val)
    except Exception:  # noqa: BLE001 - non-Windows or key missing -> assume dark
        light = False
    _theme_cache.update(at=now, light=light)
    return light


def _enable_dark_menus() -> None:
    """Best-effort: ask Windows to render this process's menus in dark mode.

    Native tray (right-click) menus can't be fully themed via pystray; this
    undocumented uxtheme call darkens them on Windows 10 1809+ when it works,
    and is a harmless no-op otherwise.
    """
    try:
        import ctypes

        uxtheme = ctypes.windll.uxtheme
        set_preferred = uxtheme[135]  # SetPreferredAppMode ordinal
        set_preferred.argtypes = [ctypes.c_int]
        set_preferred.restype = ctypes.c_int
        set_preferred(1)  # AllowDark
        uxtheme[136]()    # FlushMenuThemes
    except Exception:  # noqa: BLE001
        pass


def _level_key(reading: Reading) -> str:
    """'charging' | 'green' | 'orange' | 'red' | 'grey' for the current state."""
    if reading.percent is not None and reading.charging:
        return "charging"
    pct = reading.percent
    if pct is None:
        return "grey"
    if pct >= 50:
        return "green"
    if pct >= 20:
        return "orange"
    return "red"


def _make_icon_image(reading: Reading):
    """Render the battery percentage as a colour-coded number, like a badge.

    Shows ``??`` when there is no reading (dongle unplugged or mouse asleep past
    the grace window). Colours and the outline adapt to the Windows Light/Dark
    taskbar so the digits stay legible either way.
    """
    from PIL import Image, ImageDraw

    S = 64
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if not reading.device_present or reading.percent is None:
        text = "??"
    else:
        text = str(max(0, min(100, reading.percent)))

    theme = "light" if _taskbar_is_light() else "dark"
    fill = _PALETTE[theme][_level_key(reading)]
    # Shrink the font for wider strings ("100") so it always fits the box.
    size = 60 if len(text) <= 2 else 44
    font = _font(size)
    d.text(
        (S / 2, S / 2), text,
        font=font, fill=fill, anchor="mm",
        stroke_width=3, stroke_fill=_OUTLINE[theme],
    )
    return img


# -- native modal dialogs (Windows MessageBox) -----------------------------

_MB_OK = 0x00000000
_MB_YESNO = 0x00000004
_MB_ICONERROR = 0x00000010
_MB_ICONQUESTION = 0x00000020
_MB_ICONINFO = 0x00000040
_MB_TOPMOST = 0x00040000
_MB_SETFOREGROUND = 0x00010000
_IDYES = 6


def _message_box(title: str, text: str, style: int = _MB_OK) -> int | None:
    """Show a native modal dialog and return the clicked button id.

    Safe to call from a worker thread (MessageBox pumps its own modal loop).
    Falls back to a toast on non-Windows / if user32 is unavailable.
    """
    try:
        import ctypes

        flags = style | _MB_TOPMOST | _MB_SETFOREGROUND
        return int(ctypes.windll.user32.MessageBoxW(0, text, title, flags))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - non-Windows or no user32
        notifications.notify_text(title, text)
        return None


def run_tray(settings: config.Settings) -> None:
    try:
        import pystray
    except ImportError:
        print("pystray/pillow not installed; falling back to headless mode.",
              file=sys.stderr)
        run_headless(settings)
        return

    if not _taskbar_is_light():
        _enable_dark_menus()

    notifier = Notifier(settings)

    def on_open_config(icon, item):
        folder = str(config.config_dir())
        try:
            os.startfile(folder)  # type: ignore[attr-defined]  # Windows only
        except AttributeError:
            subprocess.Popen(["xdg-open", folder])

    _panel_proc = {"p": None}

    def _spawn_self(*args: str):
        """Relaunch our own program with extra CLI args (e.g. --panel)."""
        try:
            if getattr(sys, "frozen", False):
                return subprocess.Popen([sys.executable, *args])
            return subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), *args])
        except Exception:  # noqa: BLE001
            return None

    def on_settings(icon, item):
        _spawn_self("--settings")

    def on_panel(icon, item):
        p = _panel_proc["p"]
        if p is not None and p.poll() is None:
            return  # panel already open
        _panel_proc["p"] = _spawn_self("--panel")

    def on_reload(icon, item):
        new_settings = config.load()
        notifier.settings = new_settings
        notifier.engine = ThresholdEngine(
            new_settings.thresholds, new_settings.rearm_hysteresis
        )
        notifications.notify_text(
            "Pulsar Battery", f"Reloaded settings: thresholds {new_settings.thresholds}"
        )

    def on_quit(icon, item):
        notifier.stop()
        icon.stop()

    def title_text(_item=None) -> str:
        return status_text(notifier.latest)

    def update_label(_item=None) -> str:
        if notifier._update is not None:
            return f"Update to v{notifier._update.latest}…"
        return "Check for updates…"

    def _refresh_menu() -> None:
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def _download_and_install(info: updates.UpdateInfo) -> None:
        """Download the installer, tell the user, launch it, and quit."""
        if not info.setup_url:
            _message_box(
                "Update",
                f"Version v{info.latest} is available, but no installer was found "
                "in the release. Opening the download page instead.",
                _MB_OK | _MB_ICONINFO,
            )
            updates.open_release_page(info.release_url)
            return

        try:
            icon.title = f"Pulsar Battery — downloading v{info.latest}…"
        except Exception:  # noqa: BLE001
            pass
        try:
            path = updates.download(
                info.setup_url, info.setup_name or "PulsarBatteryNotifier-Setup.exe"
            )
        except Exception as exc:  # noqa: BLE001
            _message_box(
                "Download failed",
                f"Couldn't download the update:\n\n{exc}\n\n"
                "Opening the download page instead.",
                _MB_OK | _MB_ICONERROR,
            )
            updates.open_release_page(info.release_url)
            return

        _message_box(
            "Update ready",
            f"Downloaded v{info.latest}.\n\n"
            "The installer will open now, and Pulsar Battery Notifier will close "
            "to finish updating.",
            _MB_OK | _MB_ICONINFO,
        )
        updates.launch(path)
        # Quit so our exe unlocks for the installer to overwrite it.
        notifier.stop()
        try:
            icon.stop()
        except Exception:  # noqa: BLE001
            pass

    def _manual_check() -> None:
        """Menu-triggered check: always ends in a clear modal dialog."""
        try:
            info = updates.check_for_update(__version__)
        except Exception as exc:  # noqa: BLE001 - network/parse errors
            _message_box(
                "Update check failed",
                f"Couldn't reach GitHub to check for updates:\n\n{exc}",
                _MB_OK | _MB_ICONERROR,
            )
            return

        if not info.available:
            notifier._update = None
            _refresh_menu()
            _message_box(
                "You're up to date",
                f"Pulsar Battery Notifier v{info.current} is the latest version.",
                _MB_OK | _MB_ICONINFO,
            )
            return

        notifier._update = info
        _refresh_menu()
        resp = _message_box(
            "Update available",
            "A new version of Pulsar Battery Notifier is available.\n\n"
            f"Installed:\tv{info.current}\n"
            f"Latest:\t\tv{info.latest}\n\n"
            "Download and install it now?",
            _MB_YESNO | _MB_ICONQUESTION,
        )
        if resp == _IDYES:
            _download_and_install(info)

    def on_check_updates(icon, item):
        threading.Thread(target=_manual_check, daemon=True).start()

    def _auto_update_loop() -> None:
        if not notifier.settings.auto_update_check:
            return
        # Small delay so we don't compete with startup.
        if notifier._stop.wait(8):
            return
        while not notifier._stop.is_set():
            try:
                info = updates.check_for_update(__version__)
                if info.available:
                    notifier._update = info
                    _refresh_menu()
                    if not notifier._update_notified:
                        notifier._update_notified = True
                        notifications.notify_text(
                            "Pulsar Battery Notifier",
                            f"Update available: v{info.latest}. "
                            "Open the tray menu to install it.",
                        )
                elif notifier._update is not None:
                    # We were showing an update that no longer applies.
                    notifier._update = None
                    _refresh_menu()
            except Exception:  # noqa: BLE001 - never let the loop die
                pass
            notifier._stop.wait(max(1, notifier.settings.update_check_hours) * 3600)

    icon = pystray.Icon(
        "pulsar_battery",
        icon=_make_icon_image(notifier.latest),
        title="Pulsar Battery Notifier",
        menu=pystray.Menu(
            pystray.MenuItem(title_text, on_panel, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Battery history", on_panel),
            pystray.MenuItem(update_label, on_check_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings…", on_settings),
            pystray.MenuItem("Quit", on_quit),
        ),
    )

    def on_update(reading: Reading) -> None:
        try:
            est = None
            if (
                notifier.settings.show_time_estimate
                and reading.percent is not None
                and not reading.charging
            ):
                est = notifier.estimator.hours_remaining()
            icon.icon = _make_icon_image(reading)
            icon.title = tooltip_text(reading, est)
        except Exception:  # noqa: BLE001
            pass

    notifier._on_update = on_update

    thread = threading.Thread(target=notifier.run, daemon=True)
    thread.start()
    threading.Thread(target=_auto_update_loop, daemon=True).start()
    icon.run()
