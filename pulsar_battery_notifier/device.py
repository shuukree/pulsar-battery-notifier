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
VENDOR_USAGE_PAGE = 0xFF02

# Pulsar's gaming mice share the same cmd04 battery protocol on the same vendor
# HID interface (usage page 0xFF02), so instead of hardcoding a couple of PIDs
# we probe *any* 0x3710 device that exposes that interface. That covers the
# X2 / X2H / X2V2 / Xlite / X3 families and their 8K/4K dongles, wired or
# wireless, without needing a per-model entry.
#
# The table below is optional: it only supplies friendlier names and a
# wired/wireless label. Unknown PIDs still work in "auto" mode; the name
# heuristic below classifies them for explicit wired/wireless filtering.
PID_WIRELESS = 0x5406   # Pulsar 8K dongle (kept for reference)
PID_WIRED = 0x3414      # X2 Crazylight, wired (kept for reference)

# product_id -> (friendly name, "wireless" | "wired")
KNOWN_MODELS: dict[int, tuple[str, str]] = {
    0x5406: ("Pulsar 8K Dongle", "wireless"),
    0x3414: ("Pulsar X2 (wired)", "wired"),
}

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


def classify(info: dict) -> str:
    """Best-effort 'wireless' | 'wired' label for a Pulsar interface."""
    known = KNOWN_MODELS.get(info.get("product_id"))
    if known is not None:
        return known[1]
    name = (info.get("product_string") or "").lower()
    if any(w in name for w in ("dongle", "receiver", "wireless", "2.4")):
        return "wireless"
    return "wired"


def model_name(info: dict) -> str:
    known = KNOWN_MODELS.get(info.get("product_id"))
    if known is not None:
        return known[0]
    return (info.get("product_string") or "Pulsar mouse").strip()


def _candidate_interfaces(mode: str = "auto") -> list[dict]:
    """Enumerate the Pulsar vendor HID interfaces we can talk cmd04 to.

    In "auto" mode this returns every 0x3710 device exposing the 0xFF02 vendor
    interface. "wireless"/"wired" filter by :func:`classify`.
    """
    found = []
    for info in hid.enumerate(VENDOR_ID, 0):
        if info.get("usage_page") != VENDOR_USAGE_PAGE:
            continue
        if mode in ("wireless", "wired") and classify(info) != mode:
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


def _query(dev, warmup: bool = True) -> BatteryStatus | None:
    _drain(dev)

    dev.write(_CMD04)
    payload = _read_cmd04_response(dev, timeout_s=0.8)

    if payload is None and warmup:
        # A cold vendor interface may ignore cmd04 until it's exercised. Once
        # the mouse is awake a plain cmd04 answers, so callers that already have
        # a good reading skip this to keep wake-up polling cheap.
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


def read_battery(mode: str = "auto", *, warmup: bool = True) -> BatteryStatus | None:
    """Return the current battery status, or ``None`` if the mouse didn't answer.

    A ``None`` return is normal and expected when the mouse is asleep (the dongle
    stops responding). Callers should treat it as "unknown", not "empty".

    ``warmup`` replays a captured init sequence to coax a cold interface into
    answering. It matters on the first read; once the mouse has answered once,
    callers can pass ``warmup=False`` for cheap, fast wake-up polling.

    Raises
    ------
    DeviceNotFound
        If no Pulsar vendor HID interface is present at all (dongle unplugged).
    """
    interfaces = _candidate_interfaces(mode)
    if not interfaces:
        raise DeviceNotFound(
            "No Pulsar mouse or dongle found. Is it plugged in / powered on? "
            "(Looking for VID 0x3710 with the vendor interface usage page 0xFF02.)"
        )

    for info in interfaces:
        dev = None
        try:
            dev = _open(info)
            status = _query(dev, warmup=warmup)
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


def current_device(mode: str = "auto") -> tuple[str, str] | None:
    """(name, 'wireless'|'wired') of the first matching Pulsar interface, if any."""
    for info in _candidate_interfaces(mode):
        return model_name(info), classify(info)
    return None


# -- extended device info (firmware / polling / model) ---------------------
#
# Adapted from darthsoup/PulsarBattery (MIT) - the "cMouse" legacy 17-byte
# protocol shared by the X2/X2H/X2N/X3/Xlite CrazyLight family (VID 0x3710,
# CID 0x57). cmd 0x12 = firmware, cmd 0x01 = identify (CID/MID + connection).

_CMD_VERSION = 0x12
_CMD_INFO = 0x01
# Fixed challenge for the identify command; the reply mixes it in and we invert.
_INFO_CHALLENGE = bytes([0x37, 0x11, 0x2A, 0x5C])

# Connection code (from cmd 0x01) -> (kind, link rate Hz).
_CONNECTION = {
    0x00: ("wireless", 1000),
    0x01: ("wireless", 4000),
    0x02: ("wired", 1000),
    0x03: ("wired", 8000),
    0x04: ("wireless", 2000),
    0x05: ("wireless", 8000),
}

# MID -> model name (subset of darthsoup's CmouseDeviceCatalog, CID 0x57).
CMOUSE_MODELS = {
    1: "X2 CrazyLight", 2: "X2 CrazyLight", 3: "X2 CrazyLight", 4: "X2 CrazyLight",
    5: "X2 CrazyLight", 6: "X2 CrazyLight", 7: "TenZ", 8: "TenZ",
    9: "X2 CrazyLight", 10: "X2 CrazyLight",
    12: "X2 CrazyLight T1 Edition (Red)", 13: "X2 CrazyLight T1 Edition (Black)",
    14: "X2 CrazyLight PRX Edition", 15: "X2 CrazyLight Boardzy Edition",
    16: "X2 CrazyLight Randomfrankp Edition",
    17: "Xlite CrazyLight (Black)", 18: "Xlite CrazyLight (White)",
    19: "X3 CrazyLight (Black)", 20: "X3 CrazyLight (White)",
    21: "X3 LHD CrazyLight (Black)", 22: "X3 LHD CrazyLight (White)",
    23: "X2H CrazyLight (Black)", 24: "X2H CrazyLight (White)",
    25: "X2N CrazyLight (Black)", 26: "X2N CrazyLight (White)",
    27: "X2 CrazyLight Medium", 29: "X2H CrazyLight Medium",
    34: "Xlite CrazyLight Medium",
    70: "X2 CrazyLight Medium (White)", 71: "Xlite CrazyLight Medium (White)",
    72: "X3 CrazyLight Medium (Black)", 73: "X3 CrazyLight Medium (White)",
    76: "X2H CrazyLight Medium (White)", 77: "X2N CrazyLight Medium (Black)",
    78: "X2N CrazyLight Medium (White)",
}


def _checksum(first16: bytes) -> int:
    return (0x55 - (sum(first16) & 0xFF)) & 0xFF


def _build_packet(cmd: int, payload: bytes = b"") -> bytes:
    p = bytearray(17)
    p[0] = _REPORT_ID
    p[1] = cmd
    p[2:2 + len(payload)] = payload
    p[16] = _checksum(bytes(p[0:16]))
    return bytes(p)


def _send_and_read(dev, packet: bytes, expect_cmd: int, timeout_s: float) -> bytes | None:
    _drain(dev)
    dev.write(packet)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = dev.read(17, 250)
        if not data:
            continue
        payload = _normalize(data)
        if len(payload) >= 8 and payload[0] == _REPORT_ID and payload[1] == expect_cmd:
            return payload
    return None


def _query_version(dev) -> str | None:
    payload = _send_and_read(dev, _build_packet(_CMD_VERSION), _CMD_VERSION, 0.8)
    if payload is None or len(payload) < 8 or payload[2] != 0x00:
        return None
    major, minor = payload[6], payload[7]
    if major == 0 and minor == 0:
        return None
    return f"{major:02d}.{minor:02X}"  # minor renders as hex, per the protocol


def _query_info(dev) -> tuple[int, int, int] | None:
    payload_out = bytearray(8)
    payload_out[3] = 0x08
    payload_out[4:8] = _INFO_CHALLENGE
    payload = _send_and_read(dev, _build_packet(_CMD_INFO, bytes(payload_out)), _CMD_INFO, 0.8)
    if payload is None or len(payload) < 14 or payload[2] != 0x00:
        return None
    decoded = bytearray(4)
    for i in range(4):
        decoded[i] = (payload[6 + i] - (_INFO_CHALLENGE[i] * (i + 1))
                      - _INFO_CHALLENGE[(i + 1) % 4]) & 0xFF
    if decoded[0] != payload[10] or decoded[1] != payload[11]:
        return None  # cross-check with cleartext CID/MID failed
    model_id = (decoded[0] << 8) | decoded[1]
    return model_id, payload[12], payload[13]  # model_id, connection code, dongle type


_CMD_ONLINE = 0x03
_CMD_DRIVER = 0x02
_CMD_EEPROM_READ = 0x08
_CMD_DONGLE_VERSION = 0x1D
_ADDR_REPORT_RATE = 0x0000
# EEPROM polling-rate code -> Hz (the *actual* report rate the user set).
_POLLING_HZ = {0x08: 125, 0x04: 250, 0x02: 500, 0x01: 1000, 0x10: 2000, 0x20: 4000, 0x40: 8000}


def _build_command_packet(cmd: int, data: bytes = b"") -> bytes:
    """cMouse command frame: length at byte 5, data at byte 6 (vs. _build_packet)."""
    p = bytearray(17)
    p[0] = _REPORT_ID
    p[1] = cmd
    p[5] = len(data)
    p[6:6 + len(data)] = data
    p[16] = _checksum(bytes(p[0:16]))
    return bytes(p)


def _read_matching(dev, expect_cmd: int, timeout_s: float) -> bytes | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = dev.read(17, 250)
        if not data:
            continue
        p = _normalize(data)
        if len(p) >= 7 and p[0] == _REPORT_ID and p[1] == expect_cmd:
            return p
    return None


def _wait_online(dev, timeout_s: float = 1.5) -> bool:
    """Block until the mouse itself is reachable (not just the receiver)."""
    pkt = _build_packet(_CMD_ONLINE)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            dev.write(pkt)
        except OSError:
            return False
        r = _read_matching(dev, _CMD_ONLINE, 0.4)
        if r is not None and len(r) > 10 and r[6] == 0x01 and r[10] == 0x00:
            return True
        time.sleep(0.02)
    return False


def _query_dongle_version(dev) -> str | None:
    payload = _send_and_read(dev, _build_packet(_CMD_DONGLE_VERSION), _CMD_DONGLE_VERSION, 0.8)
    if payload is None or len(payload) < 8 or payload[2] != 0x00:
        return None
    major, minor = payload[6], payload[7]
    if major == 0 and minor == 0:
        return None
    return f"{major:02d}.{minor:02X}"


def _read_polling_hz(dev) -> int | None:
    """Read the real report rate from EEPROM (needs the mouse awake + online)."""
    if not _wait_online(dev):
        return None
    try:
        dev.write(_build_command_packet(_CMD_DRIVER, bytes([0x01])))  # announce driver
    except OSError:
        return None
    _read_matching(dev, _CMD_DRIVER, 0.5)
    pkt = _build_packet(_CMD_EEPROM_READ, bytes([0x00, 0x00, 0x00, 0x06]))
    try:
        for _ in range(5):
            try:
                dev.write(pkt)
            except OSError:
                return None
            resp = _read_matching(dev, _CMD_EEPROM_READ, 0.8)
            if (resp is not None and resp[2] == 0 and resp[3] == 0
                    and resp[4] == 0 and resp[5] == 6):
                code, check = resp[6], resp[7]
                if ((code + check) & 0xFF) == 0x55:
                    return _POLLING_HZ.get(code)
        return None
    finally:
        # Release the driver so we don't hold it against Pulsar Fusion.
        try:
            dev.write(_build_command_packet(_CMD_DRIVER, bytes([0x00])))
        except OSError:
            pass


def read_device_info(mode: str = "auto") -> dict | None:
    """Model / firmware / dongle firmware / polling rate, or None. Mouse must be awake."""
    for info in _candidate_interfaces(mode):
        dev = None
        try:
            dev = _open(info)
            result: dict = {}
            _query(dev, warmup=True)  # wake the mouse so version/EEPROM answer
            ver = _query_version(dev)
            if ver:
                result["firmware"] = ver
            dver = _query_dongle_version(dev)
            if dver:
                result["dongle_firmware"] = dver
            inf = _query_info(dev)
            if inf is not None:
                model_id, conn_code, _dongle = inf
                mid = model_id & 0xFF
                result["model"] = CMOUSE_MODELS.get(mid) or f"Pulsar mouse (id {mid})"
                result["model_id"] = model_id
                conn = _CONNECTION.get(conn_code)
                if conn is not None:
                    result["connection"], result["link_hz"] = conn
            poll = _read_polling_hz(dev)
            if poll is not None:
                result["polling_hz"] = poll  # real report rate, not the link rate
            if result:
                return result
        except (OSError, ValueError):
            continue
        finally:
            if dev is not None:
                try:
                    dev.close()
                except OSError:
                    pass
    return None


def list_interfaces() -> list[dict]:
    """Diagnostic helper: every Pulsar HID interface hidapi can see."""
    return [
        i for i in hid.enumerate(VENDOR_ID, 0)
    ]
