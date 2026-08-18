"""Windows toast notifications + optional beep.

Isolated so the rest of the app never imports Windows-Toasts directly. If the
toast backend is unavailable (wrong OS, missing dependency), notifications
degrade to a console print rather than crashing the notifier loop.
"""

from __future__ import annotations

import sys

_APP_ID = "Pulsar Battery Notifier"

try:
    from windows_toasts import Toast, WindowsToaster
    try:
        from windows_toasts import ToastScenario
    except ImportError:  # older versions
        ToastScenario = None
    _toaster = WindowsToaster(_APP_ID)
except Exception:  # noqa: BLE001 - any failure means "no toasts available"
    Toast = None
    WindowsToaster = None
    ToastScenario = None
    _toaster = None


def _severity_title(threshold: int, percent: int) -> str:
    if threshold <= 1:
        return "Mouse battery critical"
    if threshold <= 5:
        return "Mouse battery very low"
    return "Mouse battery low"


def notify_low_battery(threshold: int, percent: int, *, beep: bool = True) -> None:
    """Show a low-battery toast for a crossed threshold."""
    title = _severity_title(threshold, percent)
    body = f"Pulsar X2 at {percent}% (crossed {threshold}%). Charge it soon."

    if _toaster is not None and Toast is not None:
        try:
            toast = Toast()
            toast.text_fields = [title, body]
            # Make the critical alert stick around instead of auto-dismissing.
            if ToastScenario is not None and threshold <= 5:
                try:
                    toast.scenario = ToastScenario.Important
                except Exception:  # noqa: BLE001
                    pass
            _toaster.show_toast(toast)
        except Exception:  # noqa: BLE001
            print(f"[notify] {title}: {body}", file=sys.stderr)
    else:
        print(f"[notify] {title}: {body}", file=sys.stderr)

    if beep:
        _beep(urgent=threshold <= 5)


def notify_text(title: str, body: str) -> None:
    """Generic informational toast (used for 'check now' etc.)."""
    if _toaster is not None and Toast is not None:
        try:
            toast = Toast()
            toast.text_fields = [title, body]
            _toaster.show_toast(toast)
            return
        except Exception:  # noqa: BLE001
            pass
    print(f"[notify] {title}: {body}", file=sys.stderr)


def _beep(urgent: bool = False) -> None:
    try:
        import winsound

        if urgent:
            for _ in range(3):
                winsound.Beep(880, 180)
        else:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:  # noqa: BLE001 - non-Windows or no audio
        pass
