"""Themed Tkinter UI: the live corner panel and the settings window.

Both run as their own process (`main.py --panel` / `--settings`) so Tkinter owns
its main thread and never clashes with the tray's event loop. Colours follow the
Windows Light/Dark taskbar setting; all widgets are plain `tk` (not `ttk`) so we
can fully control the palette in both themes.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request

from . import config

_FONT = "Segoe UI"
_FONT_SEMI = "Segoe UI Semibold"

# Product photos on Pulsar's Shopify CDN, keyed by model. The mouse can't be
# auto-identified (the dongle only reports "Pulsar 8K Dongle"), so the user picks
# their model in Settings and we fetch + cache the matching photo.
MODEL_IMAGES = {
    "X2 CrazyLight": "https://eu.pulsar.gg/cdn/shop/files/Pulsar-X2-CrazyLight_medium_black_01-medium_1024x.png",
    "X2N CrazyLight": "https://eu.pulsar.gg/cdn/shop/files/Pulsar-X2N_FRONT-MINI_1024x.png",
    "X2H CrazyLight": "https://eu.pulsar.gg/cdn/shop/files/Pulsar-X2H_medium_black_front-medium_1024x.png",
    "X2 v3": "https://eu.pulsar.gg/cdn/shop/files/Pulsar_X2_v3_mini_Gaming_Mouse_Black_001_1024x.png",
    "X3 CrazyLight": "https://eu.pulsar.gg/cdn/shop/files/X3_crazylight_black_medium_Top_M_1024x.png",
    "Xlite CrazyLight": "https://eu.pulsar.gg/cdn/shop/files/Pulsar-Xlite-CrazyLight_Black_Medium_01-medium_1024x.png",
    "Xlite v4": "https://eu.pulsar.gg/cdn/shop/files/PulsarXlitev4GamingMouse_Black_001_1024x.png",
}
_GENERIC = "Generic (no photo)"


def _model_image_path(model: str):
    """Return a local cached PNG path for a model, downloading it once."""
    url = MODEL_IMAGES.get(model)
    if not url:
        return None
    safe = "".join(c for c in model if c.isalnum())
    path = config.config_dir() / f"model_{safe}.png"
    if path.exists():
        return str(path)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PulsarBatteryNotifier"})
        data = urllib.request.urlopen(req, timeout=15, context=ssl.create_default_context()).read()
        with open(path, "wb") as f:
            f.write(data)
        return str(path)
    except Exception:  # noqa: BLE001
        return None


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
    ml, mr, mt, mb = 34, 10, 8, 22
    x0, y0, x1, y1 = ml, mt, w - mr, h - mb
    if x1 <= x0 or y1 <= y0:
        return

    # Fixed time domain = the whole selected range, so the axis reads as a real
    # timeline (clock times) even when there's only a little data yet.
    t_start = now - hours * 3600
    t_end = now
    dom = max(1.0, t_end - t_start)

    def yof(p):
        return y1 - max(0.0, min(100.0, p)) / 100.0 * (y1 - y0)

    def xof(t):
        return x0 + (min(max(t, t_start), t_end) - t_start) / dom * (x1 - x0)

    for lvl in (0, 50, 100):
        y = yof(lvl)
        cv.create_line(x0, y, x1, y, fill=th["grid"])
        cv.create_text(x0 - 6, y, text=str(lvl), fill=th["sub"], anchor="e", font=(_FONT, 8))

    # X axis: clock-time ticks across the range, last one labelled "now".
    ticks = 4
    for i in range(ticks + 1):
        t = t_start + dom * i / ticks
        x = xof(t)
        lbl = "now" if i == ticks else time.strftime("%H:%M", time.localtime(t))
        cv.create_line(x, y1, x, y1 + 3, fill=th["border"])
        cv.create_text(x, y1 + 10, text=lbl, fill=th["sub"], font=(_FONT, 8))
    cv.create_line(x0, y1, x1, y1, fill=th["border"])

    pts = [(t, p, c) for (t, p, c) in samples if t >= t_start]
    if latest and latest.get("percent") is not None:
        pts = pts + [(min(latest.get("at", now), now), latest["percent"], bool(latest.get("charging")))]
    if len(pts) < 2:
        cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="Collecting data…",
                       fill=th["sub"], font=(_FONT, 9))
        return
    pts.sort()

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

    status = tk.Label(card, text="", bg=th["card"], fg=th["fg"], font=(_FONT_SEMI, 13), anchor="w")
    status.pack(fill="x", padx=14, pady=(2, 0))
    device = tk.Label(card, text="", bg=th["card"], fg=th["sub"], font=(_FONT, 8), anchor="w")
    device.pack(fill="x", padx=14)

    cv = tk.Canvas(card, bg=th["card"], highlightthickness=0, height=150)
    cv.pack(fill="both", expand=True, padx=8, pady=6)

    row = tk.Frame(card, bg=th["card"])
    row.pack(fill="x", padx=12, pady=(4, 14))

    def mkbtn(parent, text, cmd):
        btn = tk.Label(parent, text=text, bg=th["btn"], fg=th["btn_fg"],
                       font=(_FONT, 9), padx=14, pady=9, cursor="hand2")
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
        dn = st.get("device_name") if st else None
        dc = st.get("device_conn") if st else None
        device.config(text=(f"{dn} · {dc}" if dn else ""))
        _draw_graph(cv, cv.winfo_width() or W - 16, cv.winfo_height() or 150,
                    log.samples(), st, th, rng["hours"])
        root.after(1500, refresh)

    order = [1, 6, 24]

    def toggle_range():
        rng["hours"] = order[(order.index(rng["hours"]) + 1) % len(order)]
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


def _flat_check(parent, text, var, th):
    """A flat, custom-drawn checkbox (no Tk 3-D bevel)."""
    import tkinter as tk

    size = 18
    f = tk.Frame(parent, bg=th["card"], cursor="hand2")
    cv = tk.Canvas(f, width=size, height=size, bg=th["card"], highlightthickness=0, bd=0)
    cv.pack(side="left")
    lbl = tk.Label(f, text=text, bg=th["card"], fg=th["fg"], font=(_FONT, 10))
    lbl.pack(side="left", padx=(8, 0))

    def redraw():
        cv.delete("all")
        on = var.get()
        cv.create_rectangle(1, 1, size - 2, size - 2,
                            fill=th["accent"] if on else th["entry"],
                            outline=th["accent"] if on else th["border"], width=1)
        if on:
            cv.create_line(4, 9, 8, 13, fill="#ffffff", width=2)
            cv.create_line(8, 13, 14, 4, fill="#ffffff", width=2)

    def toggle(_e=None):
        var.set(not var.get())
        redraw()

    for w in (f, cv, lbl):
        w.bind("<Button-1>", toggle)
    redraw()
    return f


def _segmented(parent, var, options, th):
    """A flat segmented control (like iOS/WinUI) for a small set of choices."""
    import tkinter as tk

    wrap = tk.Frame(parent, bg=th["border"])
    btns = {}

    def refresh():
        for val, b in btns.items():
            sel = val == var.get()
            b.config(bg=th["accent"] if sel else th["card"], fg="#ffffff" if sel else th["sub"])

    for val in options:
        b = tk.Label(wrap, text=val, bg=th["card"], fg=th["sub"], font=(_FONT, 9),
                     padx=12, pady=5, cursor="hand2")
        b.pack(side="left", padx=1, pady=1)
        b.bind("<Button-1>", lambda _e, v=val: (var.set(v), refresh()))
        btns[val] = b
    refresh()
    return wrap


def _uentry(parent, var, th, width=8):
    """A flat underline-style number/text entry."""
    import tkinter as tk

    wrap = tk.Frame(parent, bg=th["border"])
    e = tk.Entry(wrap, textvariable=var, width=width, bg=th["card"], fg=th["fg"],
                 insertbackground=th["fg"], relief="flat", highlightthickness=0, bd=0,
                 font=(_FONT, 10), justify="right")
    e.pack(fill="x", padx=1, pady=(1, 2))
    return wrap


def _threshold_editor(parent, initial, th):
    """Toggleable % chips + add-custom. Returns (widget, getter)."""
    import tkinter as tk

    presets = [50, 40, 30, 25, 20, 15, 10, 5, 1]
    selected = {int(x) for x in initial}
    state = {"levels": set(presets) | selected, "selected": selected}

    wrap = tk.Frame(parent, bg=th["card"])
    chips = tk.Frame(wrap, bg=th["card"])
    chips.pack(fill="x")

    def render():
        for w in chips.winfo_children():
            w.destroy()
        for lvl in sorted(state["levels"], reverse=True):
            on = lvl in state["selected"]
            c = tk.Label(chips, text=f"{lvl}%", bg=th["accent"] if on else th["entry"],
                         fg="#ffffff" if on else th["sub"], font=(_FONT, 9),
                         padx=10, pady=4, cursor="hand2")
            c.pack(side="left", padx=(0, 6), pady=3)

            def tog(_e, level=lvl):
                state["selected"].discard(level) if level in state["selected"] \
                    else state["selected"].add(level)
                render()

            c.bind("<Button-1>", tog)

    add = tk.Frame(wrap, bg=th["card"])
    add.pack(fill="x", pady=(4, 0))
    addvar = tk.StringVar()
    _uentry(add, addvar, th, 4).pack(side="left")

    def add_custom(_e=None):
        try:
            v = int(addvar.get())
        except (TypeError, ValueError):
            return
        if 1 <= v <= 100:
            state["levels"].add(v)
            state["selected"].add(v)
            addvar.set("")
            render()

    ab = tk.Label(add, text="+ Add", bg=th["btn"], fg=th["btn_fg"], font=(_FONT, 9),
                  padx=10, pady=4, cursor="hand2")
    ab.bind("<Button-1>", add_custom)
    ab.pack(side="left", padx=(6, 0))
    render()
    return wrap, (lambda: sorted(state["selected"], reverse=True))


def _draw_mouse(cv, w, h, th):
    """A simple themed mouse silhouette used when we have no product photo."""
    cx = w / 2
    top, bot = 6, h - 6
    cv.create_oval(cx - 40, top, cx + 40, bot, fill=th["accent"], outline="")
    # left/right button split + scroll wheel
    cv.create_line(cx, top + 6, cx, top + (bot - top) * 0.42, fill=th["card"], width=2)
    cv.create_rectangle(cx - 3, top + 12, cx + 3, top + 30, fill=th["card"], outline="")


def _build_sidebar(parent, th, root, s):
    """Left device column: model photo/glyph + live details. Returns a getter
    for the currently selected model string ('' when Generic)."""
    import threading
    import tkinter as tk

    pad = tk.Frame(parent, bg=th["card"])
    pad.pack(fill="both", expand=True, padx=16, pady=16)
    tk.Label(pad, text="DEVICE", bg=th["card"], fg=th["accent"],
             font=(_FONT_SEMI, 9)).pack(anchor="w")

    imgbox = tk.Frame(pad, bg=th["card"], width=176, height=120)
    imgbox.pack(pady=(10, 8))
    imgbox.pack_propagate(False)

    def show_glyph():
        for w in imgbox.winfo_children():
            w.destroy()
        cv = tk.Canvas(imgbox, width=176, height=120, bg=th["card"], highlightthickness=0)
        cv.pack()
        _draw_mouse(cv, 176, 120, th)

    def show_image(path):
        try:
            from PIL import Image, ImageTk

            im = Image.open(path).convert("RGBA")
            im.thumbnail((176, 118))
            photo = ImageTk.PhotoImage(im)
            for w in imgbox.winfo_children():
                w.destroy()
            lbl = tk.Label(imgbox, image=photo, bg=th["card"])
            lbl.image = photo  # keep a reference
            lbl.pack(expand=True)
        except Exception:  # noqa: BLE001
            show_glyph()

    def load_image(model):
        if not model or model == _GENERIC:
            show_glyph()
            return

        def work():
            path = _model_image_path(model)
            root.after(0, lambda: show_image(path) if path else show_glyph())

        threading.Thread(target=work, daemon=True).start()

    # Model picker.
    picker = tk.Frame(pad, bg=th["card"])
    picker.pack(fill="x", pady=(0, 8))
    tk.Label(picker, text="Model", bg=th["card"], fg=th["sub"], font=(_FONT, 9)).pack(side="left")
    model_var = tk.StringVar(value=s.model if s.model in MODEL_IMAGES else _GENERIC)
    om = tk.OptionMenu(picker, model_var, _GENERIC, *MODEL_IMAGES.keys(),
                       command=lambda _v: load_image(model_var.get()))
    om.config(bg=th["btn"], fg=th["btn_fg"], activebackground=th["btn_hover"],
              activeforeground=th["btn_fg"], highlightthickness=0, relief="flat",
              font=(_FONT, 9), anchor="e")
    om["menu"].config(bg=th["card"], fg=th["fg"], activebackground=th["accent"],
                      activeforeground="#ffffff")
    om.pack(side="right")

    name = tk.Label(pad, text="Detecting…", bg=th["card"], fg=th["fg"],
                    font=(_FONT_SEMI, 11), wraplength=180, justify="left", anchor="w")
    name.pack(fill="x")

    rows = {}
    for key in ("Connection", "Charging", "Battery", "Polling", "Firmware"):
        r = tk.Frame(pad, bg=th["card"])
        r.pack(fill="x", pady=4)
        tk.Label(r, text=key, bg=th["card"], fg=th["sub"], font=(_FONT, 9)).pack(side="left")
        v = tk.Label(r, text="—", bg=th["card"], fg=th["fg"], font=(_FONT, 9))
        v.pack(side="right")
        rows[key] = v

    tk.Label(pad, text="Polling / firmware aren't read yet.", bg=th["card"], fg=th["sub"],
             font=(_FONT, 8), wraplength=180, justify="left").pack(anchor="w", pady=(10, 0))

    def read_state():
        try:
            with open(config.state_path(), encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}

    def refresh():
        st = read_state()
        pct = st.get("percent")
        if st.get("device_name"):
            name.config(text=st["device_name"])
        elif st.get("device_present") is False:
            name.config(text="No device connected")
        rows["Connection"].config(text=st.get("device_conn") or "—")
        rows["Charging"].config(
            text="Yes" if st.get("charging") else ("No" if pct is not None else "—"))
        rows["Battery"].config(text=f"{pct}%" if pct is not None else "—")
        root.after(2000, refresh)

    load_image(model_var.get())
    refresh()
    return lambda: "" if model_var.get() == _GENERIC else model_var.get()


def run_settings() -> None:
    import tkinter as tk

    th = _theme()
    s = config.load()

    root = tk.Tk()
    root.title("Pulsar Battery Notifier — Settings")
    root.configure(bg=th["bg"])
    root.resizable(False, False)

    container = tk.Frame(root, bg=th["bg"])
    container.pack(fill="both", expand=True, padx=16, pady=16)

    sidebar = tk.Frame(container, bg=th["card"], highlightbackground=th["border"],
                       highlightthickness=1, width=212)
    sidebar.pack(side="left", fill="y", padx=(0, 16))
    sidebar.pack_propagate(False)
    model_get = _build_sidebar(sidebar, th, root, s)

    outer = tk.Frame(container, bg=th["bg"])
    outer.pack(side="left", fill="both", expand=True)
    tk.Label(outer, text="Settings", bg=th["bg"], fg=th["fg"],
             font=(_FONT_SEMI, 16)).pack(anchor="w")
    tk.Label(outer, text="Changes apply to the running app within a few seconds.",
             bg=th["bg"], fg=th["sub"], font=(_FONT, 9)).pack(anchor="w", pady=(1, 10))

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
        inner.pack(fill="x", padx=16, pady=14)
        inner.columnconfigure(1, weight=1)
        tk.Label(inner, text=title.upper(), bg=th["card"], fg=th["accent"],
                 font=(_FONT_SEMI, 9)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        inner._row = 1  # type: ignore[attr-defined]
        return inner

    def field(inner, label, widget, hint=""):
        r = inner._row  # type: ignore[attr-defined]
        tk.Label(inner, text=label, bg=th["card"], fg=th["fg"],
                 font=(_FONT, 10)).grid(row=r, column=0, sticky="w", pady=6, padx=(0, 12))
        widget.grid(row=r, column=1, sticky="e", pady=6)
        inner._row = r + 1  # type: ignore[attr-defined]
        if hint:
            tk.Label(inner, text=hint, bg=th["card"], fg=th["sub"],
                     font=(_FONT, 8)).grid(row=inner._row, column=0, columnspan=2, sticky="w")
            inner._row += 1  # type: ignore[attr-defined]

    def full_row(inner, widget):
        r = inner._row  # type: ignore[attr-defined]
        widget.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(2, 4))
        inner._row = r + 1  # type: ignore[attr-defined]

    def add_check(inner, text, var):
        r = inner._row  # type: ignore[attr-defined]
        _flat_check(inner, text, var, th).grid(row=r, column=0, columnspan=2, sticky="w", pady=5)
        inner._row = r + 1  # type: ignore[attr-defined]

    # Alerts
    a = section("Alerts")
    tk.Label(a, text="Alert at these levels (click to toggle)", bg=th["card"], fg=th["fg"],
             font=(_FONT, 10)).grid(row=a._row, column=0, columnspan=2, sticky="w")  # type: ignore[attr-defined]
    a._row += 1  # type: ignore[attr-defined]
    thr_editor, thr_get = _threshold_editor(a, s.thresholds, th)
    full_row(a, thr_editor)
    add_check(a, "Beep on low battery", beep_var)
    add_check(a, "Notify when fully charged", full_var)
    field(a, "Full-charge level (%)", _uentry(a, full_lvl_var, th, 5))

    # Polling
    p = section("Polling")
    field(p, "Poll interval (s)", _uentry(p, poll_var, th, 5), "How often to check while awake (min 2)")
    field(p, "Wake poll (s)", _uentry(p, wake_var, th, 5), "Faster interval while asleep/unknown")
    field(p, "Connection mode", _segmented(p, mode_var, ["auto", "wireless", "wired"], th))

    # Display
    dsp = section("Display")
    add_check(dsp, "Show time-to-empty estimate in tooltip", est_var)

    # Updates
    u = section("Updates")
    add_check(u, "Automatically check GitHub for updates", upd_var)
    field(u, "Update check every (h)", _uentry(u, upd_hours_var, th, 5))

    status = tk.Label(outer, text="", bg=th["bg"], fg="#3fb56b", font=(_FONT, 9))
    status.pack(anchor="w", pady=(8, 0))

    def on_save():
        thr = thr_get()
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
            model=model_get(),
        )
        config.save(new)
        status.config(text="Saved ✓  — applied within a few seconds.")
        root.after(650, root.destroy)

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
