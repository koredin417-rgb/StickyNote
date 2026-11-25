"""The app's one frame clock (spec §5.1): every animation steps here, once per display frame.

This first part is pure: the motion tokens, the curves, and the maths that lets a moving
value turn toward a new target from where it is, at the speed it has (retargeting).
"""
from __future__ import annotations

FAST, BASE, LONG = 120, 180, 240            # ms: fades and hover / most things / things that travel
RETARGET_CAP = 1.5                          # a retarget's start slope: at most this x the normal one


def exit_ms(ms: int) -> int:
    """How long something takes to leave when it took ``ms`` to arrive."""
    return round(ms * 2 / 3)


def ease_out(s: float) -> float:
    return 1 - (1 - s) ** 3


def ease_in(s: float) -> float:
    return s * s


def hermite(v0: float, v1: float, m: float, s: float) -> float:
    """From v0 (start slope ``m``, in value per unit s) to v1 (end slope 0), at s in 0..1.
    With m = 3 (v1 - v0) this is exactly the ease-out cubic."""
    s2, s3 = s * s, s * s * s
    return (2 * s3 - 3 * s2 + 1) * v0 + (s3 - 2 * s2 + s) * m + (-2 * s3 + 3 * s2) * v1


def hermite_slope(v0: float, v1: float, m: float, s: float) -> float:
    """d hermite / d s."""
    s2 = s * s
    return (6 * s2 - 6 * s) * v0 + (3 * s2 - 4 * s + 1) * m + (-6 * s2 + 6 * s) * v1


def start_slope(v0: float, v1: float, velocity: float, duration_s: float) -> float:
    """The start slope for a curve from v0 to v1 over ``duration_s`` for a value already
    moving at ``velocity`` (value per second): it keeps that speed, capped, so a reversal
    slows and turns instead of snapping. Not moving: the ease-out cubic's own slope."""
    normal = 3 * (v1 - v0)
    if velocity == 0:
        return normal
    cap = RETARGET_CAP * max(abs(normal), 1.0)
    return max(-cap, min(cap, velocity * duration_s))
