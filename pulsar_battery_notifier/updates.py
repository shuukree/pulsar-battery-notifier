"""Check GitHub Releases for a newer version and pull it in.

Uses only the standard library (urllib/ssl/json) so nothing new is bundled into
the frozen exe. The update path downloads the release's ``*-Setup.exe`` and
launches it; because the installer keeps a stable AppId it upgrades the existing
install in place. Portable-exe users get a normal fresh install instead.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass

REPO = "shuukree/pulsar-battery-notifier"
_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
_RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
_TIMEOUT = 15
_UA = "PulsarBatteryNotifier-Updater"


@dataclass
class UpdateInfo:
    available: bool
    current: str
    latest: str
    release_url: str
    setup_url: str | None
    setup_name: str | None


def _parse(v: str) -> tuple[int, ...]:
    """Turn 'v1.2.0', '1.2.0-beta', '1.2' into a comparable tuple of ints."""
    head = re.split(r"[-+ ]", (v or "").strip().lstrip("vV"), maxsplit=1)[0]
    parts = []
    for chunk in head.split("."):
        m = re.match(r"\d+", chunk)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse(latest), _parse(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def _get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_ctx()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pick_setup(assets: list[dict]) -> tuple[str | None, str | None]:
    """Prefer the *-Setup.exe installer; fall back to any .exe asset."""
    exes = [a for a in assets if str(a.get("name", "")).lower().endswith(".exe")]
    for a in exes:
        if str(a["name"]).lower().endswith("-setup.exe"):
            return a.get("browser_download_url"), a.get("name")
    if exes:
        return exes[0].get("browser_download_url"), exes[0].get("name")
    return None, None


def check_for_update(current: str) -> UpdateInfo:
    """Query GitHub for the latest release. Raises on network/parse errors."""
    data = _get_json(_API_LATEST)
    latest = str(data.get("tag_name") or "").lstrip("vV")
    release_url = data.get("html_url") or _RELEASES_PAGE
    setup_url, setup_name = _pick_setup(data.get("assets") or [])
    available = bool(latest) and is_newer(latest, current)
    return UpdateInfo(
        available=available,
        current=current,
        latest=latest or current,
        release_url=release_url,
        setup_url=setup_url,
        setup_name=setup_name,
    )


def download(url: str, name: str) -> str:
    """Download an asset to a temp folder and return its path."""
    dest_dir = os.path.join(tempfile.gettempdir(), "PulsarBatteryNotifier")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_ctx()) as resp:
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    return dest


def launch(path: str) -> None:
    """Start the installer detached so it outlives our own process exiting."""
    try:
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    except AttributeError:
        subprocess.Popen([path])


def open_release_page(url: str = _RELEASES_PAGE) -> None:
    import webbrowser

    webbrowser.open(url)
