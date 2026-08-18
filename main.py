"""Pulsar X2 Crazylight battery notifier - entry point.

Usage:
    python main.py                 # run in the system tray (normal use)
    python main.py --console       # run in the console (no tray)
    python main.py --once          # print battery once and exit
    python main.py --list-devices  # list Pulsar HID interfaces (debugging)
"""

from __future__ import annotations

import argparse
import sys

from pulsar_battery_notifier import __version__, config
from pulsar_battery_notifier.app import Notifier, run_headless, run_tray, status_text
from pulsar_battery_notifier.device import (
    DeviceNotFound,
    classify,
    list_interfaces,
    model_name,
    read_battery,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pulsar mouse battery notifier")
    parser.add_argument("--version", action="version", version=f"Pulsar Battery Notifier {__version__}")
    parser.add_argument("--console", action="store_true", help="run in console instead of tray")
    parser.add_argument("--once", action="store_true", help="print battery once and exit")
    parser.add_argument("--list-devices", action="store_true", help="list Pulsar HID interfaces")
    parser.add_argument("--settings", action="store_true", help="open the settings window")
    parser.add_argument("--history", action="store_true", help="render + open the battery history chart")
    parser.add_argument("--mode", choices=["auto", "wireless", "wired"], help="override connection mode")
    args = parser.parse_args(argv)

    if args.settings:
        from pulsar_battery_notifier.gui import run_settings
        run_settings()
        return 0

    if args.history:
        import os
        import tempfile
        from pulsar_battery_notifier.history import BatteryLog, render_chart
        log = BatteryLog(config.battery_log_path())
        log.load()
        out = os.path.join(tempfile.gettempdir(), "pulsar_battery_history.png")
        render_chart(log.samples(), out, hours=24)
        os.startfile(out)  # type: ignore[attr-defined]  # Windows only
        return 0

    settings = config.load()
    if args.mode:
        settings.connection_mode = args.mode
        settings = settings.sanitized()

    if args.list_devices:
        interfaces = list_interfaces()
        if not interfaces:
            print("No Pulsar (VID 0x3710) HID interfaces found. Is the dongle plugged in?")
            return 1
        for i, info in enumerate(interfaces):
            up = info.get("usage_page")
            print(
                f"{i}: pid=0x{info.get('product_id', 0):04x} "
                f"iface={info.get('interface_number')} "
                f"usage_page={('0x%04x' % up) if up is not None else 'None'} "
                f"conn={classify(info)} "
                f"name={model_name(info)!r} "
                f"product={info.get('product_string')!r}"
            )
        return 0

    if args.once:
        try:
            status = read_battery(settings.connection_mode)
        except DeviceNotFound as exc:
            print(exc)
            return 1
        if status is None:
            print("Battery: unknown (mouse asleep or not answering). Try moving the mouse.")
            return 2
        state = "charging" if status.charging else "on battery"
        print(f"Battery: {status.percent}% - {state}")
        return 0

    if args.console:
        run_headless(settings)
    else:
        run_tray(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
