"""Debug-only measurements: frame intervals per animation, time spent in handlers, and the
process's memory and handles. Off unless the environment has STICKY_PERF=1; every hook in
the app is ``if perf.ENABLED: ...``, so when it is off it costs one attribute read.

tools/baseline.py turns it on, drives the app through fixed scenarios and writes report().
"""
from __future__ import annotations

import os
import time
import weakref
from contextlib import contextmanager

import winapi

ENABLED = os.environ.get("STICKY_PERF") == "1"
RUN_GAP_S = 0.250               # a pause this long between frames starts a new run (not an interval)


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    s = sorted(values)

    def rank(p):                # nearest rank
        return s[min(len(s) - 1, max(0, -(-len(s) * p // 100) - 1))]
    return {"n": len(s), "p50": rank(50), "p95": rank(95), "max": s[-1]}


class Perf:
    def __init__(self):
        self.reset()
        self._windows: weakref.WeakSet = weakref.WeakSet()

    def reset(self) -> None:
        self._last: dict[str, float] = {}           # key -> time of its last frame
        self._intervals: dict[str, list[float]] = {}
        self._spans: dict[str, list[float]] = {}

    def frame(self, key: str, t: float) -> None:
        """One frame of the animation ``key`` at ``t`` (perf_counter seconds)."""
        last = self._last.get(key)
        self._last[key] = t
        if last is not None and t - last <= RUN_GAP_S:
            self._intervals.setdefault(key, []).append((t - last) * 1000)

    @contextmanager
    def span(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._spans.setdefault(name, []).append((time.perf_counter() - t0) * 1000)

    def track_window(self, obj) -> None:
        self._windows.add(obj)

    def live_windows(self) -> int:
        return len(self._windows)

    def sample(self) -> dict:
        gdi, user = winapi.gui_handles()
        return {"private_bytes": winapi.process_memory(), "gdi": gdi, "user": user,
                "live_windows": self.live_windows()}

    def report(self) -> dict:
        return {"frames": {k: _stats(v) for k, v in self._intervals.items()},
                "spans": {k: _stats(v) for k, v in self._spans.items()}}


perf = Perf()


def timed(name: str, enabled: bool | None = None, into: Perf | None = None):
    """Decorator: time each call into ``into`` (default: the module's ``perf``) as span
    ``name``. When measuring is off it returns the function itself, so it costs nothing."""
    on = ENABLED if enabled is None else enabled

    def wrap(fn):
        if not on:
            return fn
        import functools

        @functools.wraps(fn)
        def inner(*a, **kw):
            with (into or perf).span(name):
                return fn(*a, **kw)
        return inner
    return wrap
