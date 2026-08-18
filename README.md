# Pulsar Battery Notifier

<img src="assets/app.png" alt="Pulsar Battery Notifier icon" width="96" align="right">

A tiny Windows background app that watches your **Pulsar mouse** battery —
wireless or wired — and pops a toast (plus a beep) as it drops past thresholds
you choose, by default **20%, 15%, 10%, 5%, and 1%**. It shows the live level
right on the tray icon, and clicking it opens a small graph panel in the corner.
It runs quietly alongside Pulsar Fusion; it does not replace it.

Reads the battery straight from the dongle (or the wired mouse) over HID, so it
works whether or not the official app is open. Tested on the **Pulsar X2
Crazylight**; other Pulsar models using the same vendor protocol work too.

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
- Low-battery alert shows a toast **and** a topmost on-screen banner that stays
  visible over borderless-fullscreen games (plus the beep, which is audible even
  in exclusive fullscreen). Toggle the banner in Settings.
- Tray icon shows the **battery % as a colour-coded number** — green (≥50),
  orange (≥20), red (<20), blue while charging, and `??` when there's no reading.
- **Auto taskbar-theme detection** — digit colours and outline adapt to Windows
  Light/Dark taskbars automatically, no configuration.
- **Time-to-empty estimate** — hover the tray icon to see a predicted runtime,
  e.g. `Pulsar battery: 85% (~12h) - On battery`, inferred from the recent
  discharge slope. Toggle it from the tray menu.
- **Fully-charged alert** — an optional toast when charging completes, so you
  know when to unplug. Fires once per charge cycle.
- **Live panel** — left-click the tray icon (or **Battery history**) to open a
  themed panel in the corner with a dynamic graph that updates in place
  (charging spans highlighted), plus a 6h/24h range toggle.
- **Settings window** — a **Settings…** tray item opens a themed, sectioned
  editor for thresholds, intervals and toggles; changes apply live (no restart).
  A device column shows live status — **model name, firmware, polling rate,
  connection, real polling rate** (read from EEPROM) and **dongle firmware** —
  all over the cMouse protocol, and **auto-picks your mouse's photo** from
  pulsar.gg (cached locally).
- Edit settings in the **Settings** window, or hand-edit the JSON — either way
  changes apply live (the app watches the file).
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

Prefer portable? Grab **`PulsarBatteryNotifier-portable.zip`** from the same
Release, extract it anywhere, and run `PulsarBatteryNotifier.exe` inside — no
install.

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
  "poll_seconds": 30,
  "wake_poll_seconds": 12,
  "rearm_hysteresis": 3,
  "beep": true,
  "stale_grace_seconds": 600,
  "connection_mode": "auto",
  "auto_update_check": true,
  "update_check_hours": 24,
  "show_time_estimate": true,
  "notify_full": true,
  "full_level": 100,
  "overlay_alert": true
}
```

- **thresholds** — battery % levels to alert on. Any list works, e.g.
  `[30, 10]`.
- **poll_seconds** — how often to check while the mouse is awake (minimum 2).
  Lower = more responsive to plug/unplug, at the cost of a little more USB/CPU
  chatter. Try `5` (or even `3`) if you want near-instant charging updates.
- **wake_poll_seconds** — faster interval used while the mouse is asleep/unknown,
  so it notices the mouse waking within a few seconds (minimum 2).

For an on-demand refresh any time, use the tray's **Check now** — it reads
immediately.
- **rearm_hysteresis** — a level only re-arms once the battery climbs this many
  points back above it, so a reading hovering on a threshold won't re-fire.
- **stale_grace_seconds** — how long to keep showing the last reading while the
  mouse is asleep before the tray says "unknown".
- **connection_mode** — `auto`, `wireless`, or `wired`.
- **auto_update_check** — check GitHub for a newer release in the background.
- **update_check_hours** — how often the background check runs (hours).
- **show_time_estimate** — show the predicted time-to-empty in the tooltip (also
  toggleable from the tray menu).
- **overlay_alert** — also show a topmost on-screen banner on low-battery
  alerts, so it's visible over borderless-fullscreen games.
- **notify_full** — toast once when charging reaches **full_level**.
- **full_level** — the % considered "full" for that alert (50–100).

Settings can also be edited from the tray's **Settings…** window; saving there
takes effect within a few seconds (the app watches the file).

## Time-to-empty estimate

The mice have no fuel-gauge IC, so remaining time can't be read from the device
— it's **inferred from how fast the percentage falls**. The app samples
`(time, %)` while discharging, fits a line through a rolling ~3-hour window to get
the discharge rate (%/hour), and divides the current % by that rate. It only
appears once there's enough signal (a few samples over ≥10 min with a ≥2% drop),
and it resets whenever you charge or the battery jumps up, so a recharge never
skews it. Expect it to be a rough guide that tightens the longer you're on
battery, not a precise countdown.

The sample history is saved to `discharge_history.json` in the config folder and
reloaded on startup (pruned to the window), so the estimate survives restarts
and app updates instead of recalibrating from scratch.

## Updating

The app checks for new releases on startup and once a day. When one is found it
shows a toast and the tray menu changes to **Update to vX.Y.Z**.

Clicking **Check for updates** (or the update item) opens a dialog:

- Up to date → an info box confirming you're on the latest version.
- Update available → a **Yes/No** box showing installed vs. latest; choose
  **Yes** and it downloads the installer, tells you it's ready, then launches it
  and closes the app so the upgrade can finish in place.

Turn the background check off with `"auto_update_check": false`.

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

Produces the one-dir bundle `dist\PulsarBatteryNotifier\` (run
`PulsarBatteryNotifier.exe` inside). Windows SmartScreen may warn about an
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
- [darthsoup/PulsarBattery](https://github.com/darthsoup/PulsarBattery) (MIT) — the
  cMouse 17-byte protocol for firmware, polling-rate and model identification
  (`CmdVersion` / `CmdInfo`, CID/MID catalog), adapted in `device.py`.

If you want a single-threshold tool or a C# version, those projects are worth a
look too.

## License

MIT — see [LICENSE](LICENSE).
