# Pulsar Battery Notifier

<img src="assets/app.png" alt="Pulsar Battery Notifier icon" width="96" align="right">

A tiny Windows background app that watches your **Pulsar X2 Crazylight** mouse
battery and pops a toast (plus a beep) as it drops past thresholds you choose —
by default **20%, 15%, 10%, 5%, and 1%**. It runs quietly in the system tray
alongside Pulsar Fusion; it does not replace it.

Reads the battery straight from the wireless dongle over HID, so it works
whether or not the official app is open.

## Why

The Pulsar app's battery indicator is easy to miss, so the mouse tends to die
without warning. This gives you a staged heads-up instead of a single alert:
a gentle nudge at 20%, and a hard-to-ignore critical alert at 5% and 1%.

## Features

- Graduated alerts at configurable battery levels (default 20/15/10/5/1%).
- Each level fires **once** per discharge cycle — no nagging every poll.
- Coalesces multiple crossings into one alert if the mouse was asleep and the
  reading jumped (e.g. 22% → 4% → single "very low" toast, not four).
- Re-arms automatically when you charge back up.
- Never alerts while the mouse is charging.
- Tray icon shows the **battery % as a colour-coded number** — green (≥50),
  orange (≥20), red (<20), blue while charging, and `??` when there's no reading.
  Updates live and adapts to light/dark taskbars.
- Config is a plain JSON file you can hand-edit; reload from the tray.
- **Built-in updater**: checks GitHub for new releases in the background and
  offers a one-click **Check for updates** in the tray menu that downloads and
  launches the latest installer.

## Supported hardware

Works with **Pulsar wireless and wired gaming mice** (VID `0x3710`) that speak
the standard vendor battery protocol on HID usage page `0xFF02` — the X2 / X2H /
X2V2 / Xlite / X3 families and their 8K/4K dongles. Rather than hardcoding a
list of product IDs, the app probes any Pulsar device exposing that vendor
interface, so new models generally work out of the box.

Developed and verified against the **Pulsar X2 Crazylight** (8K dongle). If your
Pulsar mouse isn't detected, run `python main.py --list-devices` and open an
issue with the output — the offsets are consistent across the lineup, but a new
model may need a tweak.

## Install (recommended)

1. Go to the [**Releases**](https://github.com/shuukree/pulsar-battery-notifier/releases/latest) page.
2. Download **`PulsarBatteryNotifier-Setup.exe`**.
3. Run it and click through the wizard. Tick **"Start automatically when I sign
   in to Windows"** if you want it always on.

It installs per-user (no admin needed) and adds a Start Menu entry plus an
uninstaller (**Settings → Apps** → *Pulsar Battery Notifier*). The app then lives
in the system tray next to the clock.

> Windows SmartScreen may show a blue "unknown publisher" warning — expected for
> an unsigned hobby build. Click **More info → Run anyway**.

Prefer a portable single file? Grab **`PulsarBatteryNotifier.exe`** from the same
Release and run it directly — no install.

## Install (from source)

Requires Windows 10/11 and Python 3.8+.

```powershell
git clone https://github.com/<you>/pulsar-battery-notifier.git
cd pulsar-battery-notifier
pip install -r requirements.txt
python main.py
```

It starts in the tray. Left-click the tray icon for the menu.

## Usage

```powershell
python main.py                 # run in the system tray (normal use)
python main.py --console       # run in a console, no tray
python main.py --once          # print the battery once and exit
python main.py --list-devices  # list Pulsar HID interfaces (debugging)
python main.py --mode wired    # force wired/wireless instead of auto
python main.py --version       # print the version and exit
```

Tip: if `--once` says the battery is unknown, wiggle the mouse first. The dongle
stops answering when the mouse is asleep.

## Configuration

Settings live at `%APPDATA%\PulsarBatteryNotifier\settings.json` and are created
on first run. Use the tray's **Open config folder**, edit, then **Reload
settings**.

```json
{
  "thresholds": [20, 15, 10, 5, 1],
  "poll_seconds": 60,
  "rearm_hysteresis": 3,
  "beep": true,
  "stale_grace_seconds": 600,
  "connection_mode": "auto",
  "auto_update_check": true,
  "update_check_hours": 24
}
```

- **thresholds** — battery % levels to alert on. Any list works, e.g.
  `[30, 10]`.
- **poll_seconds** — how often to check (minimum 10).
- **rearm_hysteresis** — a level only re-arms once the battery climbs this many
  points back above it, so a reading hovering on a threshold won't re-fire.
- **stale_grace_seconds** — how long to keep showing the last reading while the
  mouse is asleep before the tray says "unknown".
- **connection_mode** — `auto`, `wireless`, or `wired`.
- **auto_update_check** — check GitHub for a newer release in the background.
- **update_check_hours** — how often the background check runs (hours).

## Updating

The app checks for new releases on startup and once a day. When one is found it
shows a toast and the tray menu changes to **Update to vX.Y.Z**. Click it (or
**Check for updates** any time) and it downloads the latest installer and runs
it — the install upgrades in place. You can turn the background check off with
`"auto_update_check": false`.

## Auto-start on login

Build the exe (below) or make a shortcut to `python main.py`, then drop the
shortcut in:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

## Building a standalone .exe

```powershell
.\build.ps1
```

Produces `dist\PulsarBatteryNotifier.exe`. Windows SmartScreen may warn about an
unknown publisher — expected for an unsigned hobby build.

If [Inno Setup](https://jrsoftware.org/isdl.php) is installed, `build.ps1` also
produces the installer `dist\PulsarBatteryNotifier-Setup.exe`. Or build it by
hand:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 installer.iss
```

In CI, the installer is built automatically and attached to every tagged
Release — you don't need to do any of this to ship one.

## How it works

The dongle exposes a vendor HID interface (usage page `0xFF02`). To read the
battery you write a 17-byte "cmd04" report and read the interrupt reply:

```
request : 08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49
reply   : 08 04 00 00 02 ..[BB][CC].. -> BB = battery %, CC = charging (0/1)
```

Some dongles ignore cmd04 until the interface has been "warmed up", so on the
first miss the app replays a captured init sequence and retries. The X2 has no
fuel-gauge IC, so readings are coarse and can lag — good for "getting low"
alerts, not precise metering.

## Credits / prior art

The battery protocol was reverse-engineered by the community. This project is an
independent implementation that stands on their documentation, with a new
multi-threshold alerting engine on top. Thanks to:

- [andrewrabert/python-pulsar-mouse-tool](https://github.com/andrewrabert/python-pulsar-mouse-tool) (MIT) — the canonical protocol reference.
- [jonkristian/pulsar-x3-python](https://github.com/jonkristian/pulsar-x3-python) — X3 protocol notes (battery at byte 6).
- [Elehiggle/SimplePulsarBatteryNotification](https://github.com/Elehiggle/SimplePulsarBatteryNotification) (MIT) — X2 Crazylight IDs and init sequence.

If you want a single-threshold tool or a C# version, those projects are worth a
look too.

## License

MIT — see [LICENSE](LICENSE).
