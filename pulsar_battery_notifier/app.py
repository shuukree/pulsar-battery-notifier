"""Ties everything together: poll the mouse, run thresholds, show toasts.

Two entry points:

* :func:`run_headless` - a plain loop that prints status and fires toasts. Good
  for debugging or running under a console.
* :func:`run_tray` - the same loop wrapped in a system-tray icon with a small
  menu. This is the normal way to use the app.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from . import __version__, config, notifications, updates
from .device import BatteryStatus, DeviceNotFound, read_battery
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
        self._stop = threading.Event()
        self._latest = Reading(None, False, False, False, 0.0)
        self._on_update = None  # optional callback(Reading) for the tray
        # Set by the background update check when a newer release is found.
        self._update: updates.UpdateInfo | None = None
        self._update_notified = False

    # -- polling -----------------------------------------------------------
    def poll_once(self) -> Reading:
        now = time.time()
        device_present = True
        try:
            status = read_battery(self.settings.connection_mode)
        except DeviceNotFound:
            status = None
            device_present = False

        if status is not None:
            self._last_good = status
            self._last_good_at = now
            reading = Reading(status.percent, status.charging, True, True, now)
            alert = self.engine.update(status.percent, status.charging)
            if alert is not None:
                notifications.notify_low_battery(
                    alert, status.percent, beep=self.settings.beep
                )
        else:
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
        if self._on_update is not None:
            self._on_update(reading)
        return reading

    # -- loop --------------------------------------------------------------
    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - never let the loop die
                print(f"[poll error] {exc}", file=sys.stderr)
            self._stop.wait(self.settings.poll_seconds)

    def stop(self) -> None:
        self._stop.set()

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

def _make_icon_image(reading: Reading):
    """Draw a tiny battery glyph coloured by charge level."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pct = reading.percent
    if not reading.device_present or pct is None:
        fill = (128, 128, 128, 255)
        level = 0.0
    else:
        level = max(0.0, min(1.0, pct / 100.0))
        if reading.charging:
            fill = (60, 160, 255, 255)
        elif pct <= 5:
            fill = (230, 60, 60, 255)
        elif pct <= 20:
            fill = (240, 170, 40, 255)
        else:
            fill = (70, 200, 110, 255)

    # Battery body + terminal.
    body = (8, 20, 50, 44)
    d.rounded_rectangle(body, radius=6, outline=(230, 230, 230, 255), width=4)
    d.rectangle((50, 28, 56, 36), fill=(230, 230, 230, 255))

    inner_l, inner_t, inner_r, inner_b = 13, 25, 45, 39
    width = int((inner_r - inner_l) * level)
    if width > 0:
        d.rectangle((inner_l, inner_t, inner_l + width, inner_b), fill=fill)
    if not reading.device_present or pct is None:
        d.line((14, 26, 44, 38), fill=(230, 90, 90, 255), width=3)
    return img


def run_tray(settings: config.Settings) -> None:
    try:
        import pystray
    except ImportError:
        print("pystray/pillow not installed; falling back to headless mode.",
              file=sys.stderr)
        run_headless(settings)
        return

    notifier = Notifier(settings)

    def on_check_now(icon, item):
        reading = notifier.poll_once()
        notifications.notify_text("Pulsar Battery", status_text(reading))

    def on_open_config(icon, item):
        folder = str(config.config_dir())
        try:
            os.startfile(folder)  # type: ignore[attr-defined]  # Windows only
        except AttributeError:
            subprocess.Popen(["xdg-open", folder])

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
            return f"Update to v{notifier._update.latest}"
        return "Check for updates"

    def _update_flow(icon) -> None:
        """Check GitHub and, if a newer release exists, download + launch it."""
        notifications.notify_text("Pulsar Battery Notifier", "Checking for updates…")
        try:
            info = updates.check_for_update(__version__)
        except Exception as exc:  # noqa: BLE001 - network/parse errors
            notifications.notify_text(
                "Update check failed", str(exc) or "Could not reach GitHub."
            )
            return

        if not info.available:
            notifier._update = None
            _refresh_menu(icon)
            notifications.notify_text(
                "Pulsar Battery Notifier", f"You're up to date (v{info.current})."
            )
            return

        notifier._update = info
        _refresh_menu(icon)

        if not info.setup_url:
            notifications.notify_text(
                "Update available", f"v{info.latest} — opening the download page."
            )
            updates.open_release_page(info.release_url)
            return

        notifications.notify_text(
            "Pulsar Battery Notifier", f"Downloading v{info.latest}…"
        )
        try:
            path = updates.download(
                info.setup_url, info.setup_name or "PulsarBatteryNotifier-Setup.exe"
            )
        except Exception as exc:  # noqa: BLE001
            notifications.notify_text("Update download failed", str(exc))
            updates.open_release_page(info.release_url)
            return

        notifications.notify_text(
            "Pulsar Battery Notifier",
            f"Installing v{info.latest}. The app will close to finish updating.",
        )
        updates.launch(path)
        # Quit so our exe unlocks for the installer to overwrite it.
        notifier.stop()
        try:
            icon.stop()
        except Exception:  # noqa: BLE001
            pass

    def on_check_updates(icon, item):
        threading.Thread(target=_update_flow, args=(icon,), daemon=True).start()

    def _refresh_menu(icon) -> None:
        try:
            icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def _auto_update_loop(icon) -> None:
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
                    _refresh_menu(icon)
                    if not notifier._update_notified:
                        notifier._update_notified = True
                        notifications.notify_text(
                            "Pulsar Battery Notifier",
                            f"Update available: v{info.latest}. "
                            "Open the tray menu to install it.",
                        )
            except Exception:  # noqa: BLE001 - never let the loop die
                pass
            notifier._stop.wait(max(1, notifier.settings.update_check_hours) * 3600)

    icon = pystray.Icon(
        "pulsar_battery",
        icon=_make_icon_image(notifier.latest),
        title="Pulsar Battery Notifier",
        menu=pystray.Menu(
            pystray.MenuItem(title_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Check now", on_check_now),
            pystray.MenuItem(update_label, on_check_updates),
            pystray.MenuItem("Open config folder", on_open_config),
            pystray.MenuItem("Reload settings", on_reload),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        ),
    )

    def on_update(reading: Reading) -> None:
        try:
            icon.icon = _make_icon_image(reading)
            icon.title = f"Pulsar Battery \u2014 {status_text(reading)}"
        except Exception:  # noqa: BLE001
            pass

    notifier._on_update = on_update

    thread = threading.Thread(target=notifier.run, daemon=True)
    thread.start()
    threading.Thread(target=_auto_update_loop, args=(icon,), daemon=True).start()
    icon.run()
