"""Themed Tkinter UI: the live corner panel and the settings window.

Both run as their own process (`main.py --panel` / `--settings`) so Tkinter owns
its main thread and never clashes with the tray's event loop. Colours follow the
Windows Light/Dark taskbar setting; all widgets are plain `tk` (not `ttk`) so we
can fully control the palette in both themes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from . import config

_FONT = "Segoe UI"
_FONT_SEMI = "Segoe UI Semibold"


# -- theme -----------------------------------------------------------------

def taskbar_is_light() -> bool:
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            val, _ = winreg.QueryValueEx(k, "SystemUsesLightTheme")
            return bool(val)
    except Exception:  # noqa: BLE001
        return False


def _theme() -> dict:
    if taskbar_is_light():
        return {
            "bg": "#f5f5f7", "card": "#ffffff", "fg": "#1b1b1f", "sub": "#5c5c66",
            "accent": "#4f46e5", "grid": "#e6e6ea", "line": "#4f46e5",
            "chg_band": "#e3ecfd", "border": "#dcdce3",
            "btn": "#ececf1", "btn_hover": "#e2e2ea", "btn_fg": "#1b1b1f",
            "entry": "#ffffff", "entry_fg": "#1b1b1f", "dark": False,
        }
    return {
        "bg": "#1e1f22", "card": "#2b2d31", "fg": "#f2f3f5", "sub": "#b5bac1",
        "accent": "#9a9aff", "grid": "#3a3c42", "line": "#9a9aff",
        "chg_band": "#26374d", "border": "#3a3c42",
        "btn": "#383a40", "btn_hover": "#45474f", "btn_fg": "#f2f3f5",
        "entry": "#1e1f22", "entry_fg": "#f2f3f5", "dark": True,
    }


def _dark_titlebar(root, dark: bool) -> None:
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (20, or 19 pre-20H1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:  # noqa: BLE001
        pass


def _work_area() -> tuple[int, int, int, int]:
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:  # noqa: BLE001
        return 0, 0, 1920, 1040


def _spawn(*args: str):
    try:
        if getattr(sys, "frozen", False):
            return subprocess.Popen([sys.executable, *args])
        return subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), *args])
    except Exception:  # noqa: BLE001
        return None


# -- live panel ------------------------------------------------------------

def _draw_graph(cv, w, h, samples, latest, th, hours) -> None:
    cv.delete("all")
    now = time.time()
    ml, mr, mt, mb = 34, 10, 8, 20
    x0, y0, x1, y1 = ml, mt, w - mr, h - mb
    if x1 <= x0 or y1 <= y0:
        return

    def yof(p):
        return y1 - max(0.0, min(100.0, p)) / 100.0 * (y1 - y0)

    for lvl in (0, 50, 100):
        y = yof(lvl)
        cv.create_line(x0, y, x1, y, fill=th["grid"])
        cv.create_text(x0 - 6, y, text=str(lvl), fill=th["sub"], anchor="e", font=(_FONT, 8))

    pts = [(t, p, c) for (t, p, c) in samples if t >= now - hours * 3600]
    if latest and latest.get("percent") is not None:
        pts = pts + [(latest.get("at", now), latest["percent"], bool(latest.get("charging")))]
    if len(pts) < 2:
        cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="Collecting data…",
                       fill=th["sub"], font=(_FONT, 9))
        return

    tmin = pts[0][0]
    tmax = max(now, pts[-1][0])
    span = max(1.0, tmax - tmin)

    def xof(t):
        return x0 + (t - tmin) / span * (x1 - x0)

    seg = None
    for i, (t, _p, c) in enumerate(pts):
        if c and seg is None:
            seg = t
        if (not c or i == len(pts) - 1) and seg is not None:
            cv.create_rectangle(xof(seg), y0, xof(t), y1, fill=th["chg_band"], outline="")
            seg = None

    coords = []
    for (t, p, _c) in pts:
        coords += [xof(t), yof(p)]
    cv.create_line(*coords, fill=th["line"], width=2, smooth=True)
    cv.create_line(x0, y1, x1, y1, fill=th["border"])
    for i in range(5):
        t = tmin + span * i / 4
        ago = (now - t) / 3600.0
        lbl = "now" if ago < 0.05 else f"-{ago:.0f}h"
        cv.create_text(xof(t), y1 + 9, text=lbl, fill=th["sub"], font=(_FONT, 8))


def run_panel() -> None:
    import tkinter as tk

    from .estimate import format_hours
    from .history import BatteryLog

    th = _theme()
    log = BatteryLog(config.battery_log_path())
    rng = {"hours": 6}

    root = tk.Tk()
    root.title("Pulsar battery")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    W, H = 380, 280
    l, t, r, b = _work_area()
    root.geometry(f"{W}x{H}+{max(l, r - W - 12)}+{max(t, b - H - 12)}")
    root.configure(bg=th["border"])

    card = tk.Frame(root, bg=th["card"])
    card.pack(fill="both", expand=True, padx=1, pady=1)

    header = tk.Frame(card, bg=th["card"])
    header.pack(fill="x", padx=14, pady=(12, 2))
    tk.Label(header, text="Pulsar battery", bg=th["card"], fg=th["fg"],
             font=(_FONT_SEMI, 11)).pack(side="left")
    close = tk.Label(header, text="✕", bg=th["card"], fg=th["sub"],
                     font=(_FONT, 11), cursor="hand2")
    close.pack(side="right")
    close.bind("<Button-1>", lambda e: root.destroy())

    status = tk.Label(card, text="", bg=th["card"], fg=th["fg"], font=(_FONT, 10), anchor="w")
    status.pack(fill="x", padx=14)

    cv = tk.Canvas(card, bg=th["card"], highlightthickness=0, height=150)
    cv.pack(fill="both", expand=True, padx=8, pady=6)

    row = tk.Frame(card, bg=th["card"])
    row.pack(fill="x", padx=12, pady=(0, 12))

    def mkbtn(parent, text, cmd):
        btn = tk.Label(parent, text=text, bg=th["btn"], fg=th["btn_fg"],
                       font=(_FONT, 9), padx=12, pady=6, cursor="hand2")
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e: btn.config(bg=th["btn_hover"]))
        btn.bind("<Leave>", lambda e: btn.config(bg=th["btn"]))
        return btn

    def read_state():
        try:
            with open(config.state_path(), encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}

    def status_line(st):
        if not st or st.get("device_present") is False:
            return "Not connected"
        p = st.get("percent")
        if p is None:
            return "Asleep — no reading"
        if st.get("charging"):
            return f"{p}%  ·  Charging"
        est = format_hours(st.get("estimate_hours"))
        return f"{p}% ({est})  ·  On battery" if est else f"{p}%  ·  On battery"

    def refresh():
        try:
            log.load()
        except Exception:  # noqa: BLE001
            pass
        st = read_state()
        status.config(text=status_line(st))
        _draw_graph(cv, cv.winfo_width() or W - 16, cv.winfo_height() or 150,
                    log.samples(), st, th, rng["hours"])
        root.after(1500, refresh)

    def toggle_range():
        rng["hours"] = 24 if rng["hours"] == 6 else 6
        rng_btn.config(text=f"Last {rng['hours']}h")

    rng_btn = mkbtn(row, "Last 6h", toggle_range)
    rng_btn.pack(side="left")
    mkbtn(row, "Settings", lambda: _spawn("--settings")).pack(side="right")

    _dark_titlebar(root, th["dark"])
    root.after(50, refresh)
    root.bind("<Escape>", lambda e: root.destroy())
    # Flyout behaviour: close shortly after losing focus (bound late so the
    # initial focus grab doesn't immediately dismiss it).
    root.after(700, lambda: root.bind("<FocusOut>", lambda e: root.after(120, root.destroy)))
    try:
        root.focus_force()
    except Exception:  # noqa: BLE001
        pass
    root.mainloop()


# -- settings --------------------------------------------------------------

def _to_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def run_settings() -> None:
    import tkinter as tk
    from tkinter import messagebox

    th = _theme()
    s = config.load()

    root = tk.Tk()
    root.title("Pulsar Battery Notifier — Settings")
    root.configure(bg=th["bg"])
    root.resizable(False, False)

    outer = tk.Frame(root, bg=th["bg"])
    outer.pack(fill="both", expand=True, padx=20, pady=18)
    tk.Label(outer, text="Settings", bg=th["bg"], fg=th["fg"],
             font=(_FONT_SEMI, 16)).pack(anchor="w")
    tk.Label(outer, text="Changes apply to the running app within a few seconds.",
             bg=th["bg"], fg=th["sub"], font=(_FONT, 9)).pack(anchor="w", pady=(1, 10))

    thresholds_var = tk.StringVar(value=", ".join(str(t) for t in s.thresholds))
    poll_var = tk.StringVar(value=str(s.poll_seconds))
    wake_var = tk.StringVar(value=str(s.wake_poll_seconds))
    mode_var = tk.StringVar(value=s.connection_mode)
    full_lvl_var = tk.StringVar(value=str(s.full_level))
    upd_hours_var = tk.StringVar(value=str(s.update_check_hours))
    beep_var = tk.BooleanVar(value=s.beep)
    est_var = tk.BooleanVar(value=s.show_time_estimate)
    full_var = tk.BooleanVar(value=s.notify_full)
    upd_var = tk.BooleanVar(value=s.auto_update_check)

    def section(title: str):
        card = tk.Frame(outer, bg=th["card"], highlightbackground=th["border"],
                        highlightthickness=1)
        card.pack(fill="x", pady=6)
        inner = tk.Frame(card, bg=th["card"])
        inner.pack(fill="x", padx=14, pady=12)
        inner.columnconfigure(1, weight=1)
        tk.Label(inner, text=title.upper(), bg=th["card"], fg=th["accent"],
                 font=(_FONT_SEMI, 9)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        inner._row = 1  # type: ignore[attr-defined]
        return inner

    def field(inner, label, widget, hint=""):
        r = inner._row  # type: ignore[attr-defined]
        tk.Label(inner, text=label, bg=th["card"], fg=th["fg"],
                 font=(_FONT, 10)).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 12))
        widget.grid(row=r, column=1, sticky="e", pady=5)
        inner._row = r + 1  # type: ignore[attr-defined]
        if hint:
            tk.Label(inner, text=hint, bg=th["card"], fg=th["sub"],
                     font=(_FONT, 8)).grid(row=inner._row, column=0, columnspan=2, sticky="w")
            inner._row += 1  # type: ignore[attr-defined]

    def check(inner, text, var):
        r = inner._row  # type: ignore[attr-defined]
        c = tk.Checkbutton(inner, text=text, variable=var, bg=th["card"], fg=th["fg"],
                           selectcolor=th["entry"], activebackground=th["card"],
                           activeforeground=th["fg"], font=(_FONT, 10), anchor="w",
                           highlightthickness=0, bd=0)
        c.grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
        inner._row = r + 1  # type: ignore[attr-defined]

    def entry(inner, var, width=10):
        return tk.Entry(inner, textvariable=var, width=width, bg=th["entry"],
                        fg=th["entry_fg"], insertbackground=th["fg"], relief="flat",
                        highlightbackground=th["border"], highlightcolor=th["accent"],
                        highlightthickness=1, font=(_FONT, 10), justify="right")

    # Alerts
    a = section("Alerts")
    field(a, "Alert thresholds (%)", entry(a, thresholds_var, 20),
          "Comma-separated, e.g. 20, 15, 10, 5, 1")
    check(a, "Beep on low battery", beep_var)
    check(a, "Notify when fully charged", full_var)
    field(a, "Full-charge level (%)", entry(a, full_lvl_var, 6))

    # Polling
    p = section("Polling")
    field(p, "Poll interval (s)", entry(p, poll_var, 6), "How often to check while awake (min 2)")
    field(p, "Wake poll (s)", entry(p, wake_var, 6), "Faster interval while asleep/unknown")
    om = tk.OptionMenu(p, mode_var, "auto", "wireless", "wired")
    om.config(bg=th["btn"], fg=th["btn_fg"], activebackground=th["btn_hover"],
              activeforeground=th["btn_fg"], highlightthickness=0, relief="flat",
              font=(_FONT, 10), width=8, anchor="e")
    om["menu"].config(bg=th["card"], fg=th["fg"], activebackground=th["accent"],
                      activeforeground="#ffffff")
    field(p, "Connection mode", om)

    # Display
    dsp = section("Display")
    check(dsp, "Show time-to-empty estimate in tooltip", est_var)

    # Updates
    u = section("Updates")
    check(u, "Automatically check GitHub for updates", upd_var)
    field(u, "Update check every (h)", entry(u, upd_hours_var, 6))

    status = tk.Label(outer, text="", bg=th["bg"], fg="#3fb56b", font=(_FONT, 9))
    status.pack(anchor="w", pady=(8, 0))

    def on_save():
        raw = thresholds_var.get().replace(";", ",")
        try:
            thr = [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            messagebox.showerror("Invalid thresholds",
                                 "Thresholds must be numbers, e.g. 20, 15, 10, 5, 1")
            return
        new = config.Settings(
            thresholds=thr or list(config.DEFAULT_THRESHOLDS),
            poll_seconds=_to_int(poll_var.get(), s.poll_seconds),
            wake_poll_seconds=_to_int(wake_var.get(), s.wake_poll_seconds),
            rearm_hysteresis=s.rearm_hysteresis,
            beep=beep_var.get(),
            stale_grace_seconds=s.stale_grace_seconds,
            connection_mode=mode_var.get(),
            auto_update_check=upd_var.get(),
            update_check_hours=_to_int(upd_hours_var.get(), s.update_check_hours),
            show_time_estimate=est_var.get(),
            notify_full=full_var.get(),
            full_level=_to_int(full_lvl_var.get(), s.full_level),
        )
        config.save(new)
        status.config(text="Saved ✓  — applied within a few seconds.")

    btns = tk.Frame(outer, bg=th["bg"])
    btns.pack(fill="x", pady=(14, 0))

    def mkbutton(parent, text, cmd, primary=False):
        bg = th["accent"] if primary else th["btn"]
        fg = "#ffffff" if primary else th["btn_fg"]
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=(_FONT_SEMI if primary else _FONT, 10),
                     padx=16, pady=7, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    mkbutton(btns, "Close", root.destroy).pack(side="right", padx=(8, 0))
    mkbutton(btns, "Save", on_save, primary=True).pack(side="right")

    _dark_titlebar(root, th["dark"])
    root.update_idletasks()
    try:
        root.eval("tk::PlaceWindow . center")
    except Exception:  # noqa: BLE001
        pass
    root.mainloop()
