"""Edge-triggered battery threshold engine.

The job of this module is to decide *when* to fire a low-battery alert, given a
stream of battery readings. It is deliberately pure (no HID, no toasts) so it
can be unit-tested in isolation.

Design goals:

* Fire each threshold **once** per discharge cycle. Dropping to 20% alerts you
  once; it will not nag you again at 19%, 18%, ...
* If several thresholds are crossed between two readings (e.g. the mouse was
  asleep and the reading jumped 22% -> 4%), emit a **single** alert for the most
  urgent level rather than a burst of toasts.
* **Re-arm** thresholds when the battery recovers (you plugged in and charged
  back up), so the next discharge cycle alerts you again.
* Never alert while the mouse is **charging**.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ThresholdEngine:
    """Turns raw battery readings into discrete alert events.

    Parameters
    ----------
    thresholds:
        Battery percentages to alert on, e.g. ``[20, 15, 10, 5, 1]``. Order does
        not matter; they are sorted internally.
    rearm_hysteresis:
        A threshold is only re-armed once the battery climbs this many points
        back above it. Prevents a reading hovering around a threshold from
        re-firing repeatedly.
    """

    thresholds: list[int]
    rearm_hysteresis: int = 3
    _fired: set[int] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        # Descending so index 0 is the least urgent (highest %) threshold.
        self.thresholds = sorted({int(t) for t in self.thresholds}, reverse=True)

    def reset(self) -> None:
        """Forget all fired thresholds (e.g. on charge complete)."""
        self._fired.clear()

    def update(self, battery: int, charging: bool) -> int | None:
        """Feed one reading. Return the threshold to alert on, or ``None``.

        The returned value is the *most urgent* (lowest) threshold newly crossed
        by this reading. Charging always re-arms and never alerts.
        """
        if charging:
            # Plugged in -> the discharge cycle is over. Re-arm everything so
            # the next time it drains we alert again from the top.
            self._fired.clear()
            return None

        # Re-arm any threshold the battery has climbed back above (+hysteresis).
        # This handles a top-up on battery power or noisy voltage-based readings.
        for t in list(self._fired):
            if battery >= t + self.rearm_hysteresis:
                self._fired.discard(t)

        crossed = [t for t in self.thresholds if battery <= t and t not in self._fired]
        if not crossed:
            return None

        # Mark every crossed threshold as fired so we don't emit them one by one
        # on subsequent readings, but only surface the most urgent one now.
        for t in crossed:
            self._fired.add(t)
        return min(crossed)

    @property
    def fired(self) -> set[int]:
        """Thresholds already alerted in the current discharge cycle."""
        return set(self._fired)
