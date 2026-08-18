"""Reads battery level and charging state from a Pulsar X2 Crazylight dongle.

Protocol summary (Pulsar X2 Crazylight + 8K dongle)
---------------------------------------------------
* Vendor ID ``0x3710``.
* Product ID ``0x5406`` for the wireless 8K dongle, ``0x3414`` when wired.
* The battery lives on the vendor HID interface, usage page ``0xFF02``.
* You *request* a reading by writing a 17-byte "cmd04" output report:
  ``08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49``
* The dongle answers with an interrupt IN report of the form
  ``08 04 00 00 02 xx BB CC ...`` where **byte 6 (BB) is the battery percent**
  and **byte 7 (CC) is the charging flag** (``0x00`` idle, ``0x01`` charging).
* Some dongles ignore cmd04 until the vendor interface has been "warmed up".
  If the first cmd04 goes unanswered we replay a captured init sequence and
  retry.

Protocol credit
---------------
The report format and init sequence were reverse-engineered by the community.
This implementation is a clean-room reimplementation based on the documented
findings of:
  * Andrew Rabert - python-pulsar-mouse-tool (MIT)
  * jonkristian   - pulsar-x3-python
  * Elehiggle     - SimplePulsarBatteryNotification (MIT)
See README.md for links. The VID/PID and byte offsets are hardware facts.

Note: readings are approximate. The X2 has no fuel-gauge IC, so the dongle
reports a coarse, sometimes laggy value. It is good for "getting low" alerts,
not for precise calibration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

try:
    import hid  # provided by the `hidapi` pip package
except ImportError as exc:  # pragma: no cover - clearer error for users
    raise SystemExit(
        "The 'hid' module is missing. Install dependencies with:\n"
        "    pip install -r requirements.txt\n"
        f"(underlying import error: {exc})"
    )

VENDOR_ID = 0x3710
PID_WIRELESS = 0x5406   # Pulsar 8K dongle
PID_WIRED = 0x3414      # X2 Crazylight, wired
VENDOR_USAGE_PAGE = 0xFF02

_REPORT_ID = 0x08
_BATTERY_BYTE = 6
_CHARGING_BYTE = 7

# cmd04: "give me the battery". Trailing 0x49 is the packet's checksum byte.
_CMD04 = bytes([_REPORT_ID, 0x04] + [0x00] * 14 + [0x49])
_CMD03 = bytes([_REPORT_ID, 0x03] + [0x00] * 14 + [0x4A])
# Init/warm-up frames captured from the official Pulsar software. Only needed on
# dongles that stay silent until the vendor interface has been exercised.
_CMD01_A = bytes.fromhex("0801000000088e0c4d4c00000000000011")
_CMD01_B = bytes.fromhex("0801000000089505dd4b00000000000082")
_CMD02 = bytes.fromhex("0802000000010100000000000000000049")
_WARMUP = [
    _CMD01_A, _CMD03, _CMD03, _CMD03, _CMD01_A, _CMD03, _CMD03, _CMD01_A,
    _CMD03, _CMD01_B, _CMD03, _CMD03, _CMD03, _CMD02, _CMD03, _CMD03,
    _CMD04, _CMD04,
]


@dataclass(frozen=True)
class BatteryStatus:
    percent: int
    charging: bool


class DeviceNotFound(Exception):
    """No matching Pulsar vendor HID interface is present."""


def _candidate_interfaces(mode: str = "auto") -> list[dict]:
    """Enumerate the vendor HID interfaces we can talk cmd04 to."""
    if mode == "wireless":
        pids = {PID_WIRELESS}
    elif mode == "wired":
        pids = {PID_WIRED}
    else:
        pids = {PID_WIRELESS, PID_WIRED}

    found = []
    for info in hid.enumerate(VENDOR_ID, 0):
        if info.get("product_id") not in pids:
            continue
        if info.get("usage_page") != VENDOR_USAGE_PAGE:
            continue
        found.append(info)
    # Stable ordering so probing is deterministic across runs.
    found.sort(key=lambda i: (i.get("product_id", 0), _path_str(i.get("path"))))
    return found


def _path_str(path) -> str:
    return path.hex() if isinstance(path, bytes) else str(path)


def _normalize(data) -> bytes:
    """hidapi may return a list of ints and may drop the leading report ID."""
    if isinstance(data, list):
        data = bytes(data)
    if len(data) == 16:  # report ID stripped by the backend
        return bytes([_REPORT_ID]) + data
    return data


def _open(info: dict):
    dev = hid.device()
    dev.open_path(info["path"])
    return dev


def _drain(dev, attempts: int = 6) -> None:
    """Discard any stale reports queued on the interface before we query."""
    try:
        dev.set_nonblocking(1)
        for _ in range(attempts):
            if not dev.read(17):
                break
    except (OSError, ValueError):
        pass
    finally:
        try:
            dev.set_nonblocking(0)
        except (OSError, ValueError):
            pass


def _read_cmd04_response(dev, timeout_s: float) -> bytes | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = dev.read(17, 250)  # size, timeout_ms
        if not data:
            continue
        payload = _normalize(data)
        if len(payload) <= _CHARGING_BYTE:
            continue
        if payload[0] != _REPORT_ID or payload[1] != 0x04:
            continue  # not the cmd04 answer
        return payload
    return None


def _query(dev) -> BatteryStatus | None:
    _drain(dev)

    dev.write(_CMD04)
    payload = _read_cmd04_response(dev, timeout_s=0.8)

    if payload is None:
        # Dongle may need warming up before it answers cmd04.
        for frame in _WARMUP:
            dev.write(frame)
            time.sleep(0.01)
        payload = _read_cmd04_response(dev, timeout_s=2.0)

    if payload is None:
        return None

    percent = payload[_BATTERY_BYTE]
    charging = payload[_CHARGING_BYTE] != 0x00
    if not 0 <= percent <= 100:
        return None
    return BatteryStatus(percent=percent, charging=charging)


def read_battery(mode: str = "auto") -> BatteryStatus | None:
    """Return the current battery status, or ``None`` if the mouse didn't answer.

    A ``None`` return is normal and expected when the mouse is asleep (the dongle
    stops responding). Callers should treat it as "unknown", not "empty".

    Raises
    ------
    DeviceNotFound
        If no Pulsar vendor HID interface is present at all (dongle unplugged).
    """
    interfaces = _candidate_interfaces(mode)
    if not interfaces:
        raise DeviceNotFound(
            "No Pulsar X2 Crazylight vendor interface found. "
            "Is the dongle plugged in? (Looking for VID 0x3710, usage page 0xFF02.)"
        )

    for info in interfaces:
        dev = None
        try:
            dev = _open(info)
            status = _query(dev)
            if status is not None:
                return status
        except (OSError, ValueError):
            continue
        finally:
            if dev is not None:
                try:
                    dev.close()
                except OSError:
                    pass
    return None  # device present but asleep / not answering right now


def list_interfaces() -> list[dict]:
    """Diagnostic helper: every Pulsar HID interface hidapi can see."""
    return [
        i for i in hid.enumerate(VENDOR_ID, 0)
    ]
