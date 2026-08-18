"""Tkinter settings editor, launched as its own process (`main.py --settings`).

Running it in a separate process keeps Tkinter on its own main thread, away from
the tray's event loop. It writes settings.json; the running tray app notices the
file change and reloads within a few seconds.
"""

from __future__ import annotations

from . import config


def _to_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def run_settings() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    s = config.load()

    root = tk.Tk()
    root.title("Pulsar Battery Notifier - Settings")
    root.resizable(False, False)

    frm = ttk.Frame(root, padding=16)
    frm.grid(sticky="nsew")
    frm.columnconfigure(1, weight=1)

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

    row = 0

    def add_row(label: str, widget) -> None:
        nonlocal row
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

    add_row("Alert thresholds (%)", ttk.Entry(frm, textvariable=thresholds_var, width=26))
    add_row("Poll interval (s)", ttk.Spinbox(frm, from_=2, to=3600, textvariable=poll_var, width=10))
    add_row("Wake poll (s)", ttk.Spinbox(frm, from_=2, to=3600, textvariable=wake_var, width=10))
    add_row("Connection mode", ttk.Combobox(
        frm, values=["auto", "wireless", "wired"], textvariable=mode_var,
        state="readonly", width=12))
    add_row("Full-charge level (%)", ttk.Spinbox(frm, from_=50, to=100, textvariable=full_lvl_var, width=10))
    add_row("Update check (h)", ttk.Spinbox(frm, from_=1, to=168, textvariable=upd_hours_var, width=10))

    def add_check(text: str, var) -> None:
        nonlocal row
        ttk.Checkbutton(frm, text=text, variable=var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

    add_check("Beep on low battery", beep_var)
    add_check("Show time-to-empty estimate", est_var)
    add_check("Notify when fully charged", full_var)
    add_check("Auto-check for updates", upd_var)

    status = ttk.Label(frm, text="", foreground="#1a8a1a")
    status.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
    row += 1

    def on_save() -> None:
        raw = thresholds_var.get().replace(";", ",")
        try:
            thr = [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            messagebox.showerror(
                "Invalid thresholds",
                "Thresholds must be numbers, e.g. 20, 15, 10, 5, 1",
            )
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
        status.config(text="Saved. The tray app applies changes within a few seconds.")

    btns = ttk.Frame(frm)
    btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(14, 0))
    ttk.Button(btns, text="Save", command=on_save).grid(row=0, column=0, padx=4)
    ttk.Button(btns, text="Close", command=root.destroy).grid(row=0, column=1, padx=4)

    root.update_idletasks()
    root.eval("tk::PlaceWindow . center")
    root.mainloop()
