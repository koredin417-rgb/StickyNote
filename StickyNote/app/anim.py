"""The app's one frame clock (spec §5.1): every animation steps here, once per display frame.

This first part is pure: the motion tokens, the curves, and the maths that lets a moving
value turn toward a new target from where it is, at the speed it has (retargeting).
"""
from __future__ import annotations

import math

FAST, BASE, LONG = 120, 180, 240            # ms: fades and hover / most things / things that travel
GLIDE_MIN, GLIDE_MAX = 180, 320             # ms: a plan's glide, by how far it goes (glide_ms)
RETARGET_CAP = 1.5                          # a retarget's start slope: at most this x the normal one


def exit_ms(ms: int) -> int:
    """How long something takes to leave when it took ``ms`` to arrive."""
    return round(ms * 2 / 3)


def glide_ms(d: float) -> int:
    """How long a glide of ``d`` px (at 100 %) takes (B7): short hops are quick, long moves
    don't rush. 100 px -> 200 ms, 600 px -> 287 ms."""
    return min(GLIDE_MAX, max(GLIDE_MIN, round(140 + 6 * math.sqrt(max(0.0, d)))))


def smoothstep(s: float) -> float:
    return s * s * (3 - 2 * s)


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


# ---- the clock -------------------------------------------------------------------------------
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import tkinter as tk  # noqa: E402
import weakref  # noqa: E402

import perf  # noqa: E402
import winapi  # noqa: E402

BATCH_MOVES = True              # a frame's window moves go to Windows in one DeferWindowPos (spike S2)
GRID = 1 / 60                   # the frame grid when DWM cannot tell the display's timing
AHEAD, EARLY = 0.004, 0.002     # aim at the first vblank at least 4 ms away, 2 ms before it
TIMING_TTL = 0.5                # DWM timing is read again this often
FINE_RELEASE_S = 0.5            # the 1 ms timer is given back this long after the last frame
IDLE_S = 1.0                    # idle work (gc, idle()) once the clock has been quiet this long
IDLE_REPEAT_S = 10.0            # ... and garbage is collected at most this often while it stays quiet
HALF_RATE_BELOW = 0.0155        # a display faster than ~65 Hz may be stepped every second vblank ...
HALF_RATE_WINDOW = 6            # ... decided on the median work of the last this many ticks (B2):
HALF_RATE_ENTER = 0.8           # above this share of a period it steps every second vblank,
HALF_RATE_LEAVE = 0.55          # below this share it goes back to every vblank (between: it stays)
SKIP_MS = 1                     # Animations Off (or Reduced, for movement): it ends at the next frame, never
                                # inside the call that started it (a done that destroys a window would run
                                # before the caller's next line)


def next_deadline(now: float, vblank: float | None, period: float | None, every: int = 1) -> float:
    """When the next frame should run: the first vblank (vblank + k * period * every) at least
    AHEAD from now, EARLY before it. Without DWM timing, pass the loop's start and GRID."""
    if vblank is None or not period:
        vblank, period = now, GRID
    step = period * every
    k = math.ceil((now + AHEAD - vblank) / step)
    return vblank + k * step - EARLY


def _no_step(_k) -> None:
    pass


class _Anim:
    __slots__ = ("owner", "key", "t0", "ms", "ease", "step", "done", "tween", "v0", "v1", "m", "scalar",
                 "write")

    def __init__(self, owner, key, t0, ms, ease, done):
        self.owner, self.key, self.t0, self.ms, self.ease, self.done = owner, key, t0, ms, ease, done
        self.step = self.v0 = self.v1 = self.m = self.write = None
        self.tween, self.scalar = False, False

    def progress(self, now: float) -> float:
        """0..1. Before its first frame (t0 None) it has not started: 0."""
        if self.ms <= 0:
            return 1.0
        return 0.0 if self.t0 is None else min(1.0, (now - self.t0) * 1000 / self.ms)

    def value(self, s: float) -> tuple:
        if self.m is None:              # an exit (or any curve but ease_out): plain interpolation
            k = self.ease(s)
            return tuple(a + (b - a) * k for a, b in zip(self.v0, self.v1))
        return tuple(hermite(a, b, m, s) for a, b, m in zip(self.v0, self.v1, self.m))

    def velocity(self, s: float) -> tuple:
        """Per second, at s."""
        dur = max(self.ms, 1) / 1000
        if s >= 1.0:
            return tuple(0.0 for _ in self.v0)
        if self.m is None:
            ds = 1e-3
            a, b = self.value(s), self.value(min(1.0, s + ds))
            return tuple((q - p) / ds / dur for p, q in zip(a, b))
        return tuple(hermite_slope(a, b, m, s) / dur for a, b, m in zip(self.v0, self.v1, self.m))


class FrameClock:
    def __init__(self, root: tk.Misc):
        self.root = root
        self.mode = "full"                          # "full" | "reduced" | "off" (App.apply_motion)
        self._anims: dict = {}                      # (id(owner), key) -> _Anim
        self._requests: dict = {}                   # fn -> None, in order: run once at the next tick
        self._moves: dict = {}                      # the frame's window moves (move / _flush)
        self._boxes = weakref.WeakKeyDictionary()   # window -> the box a glide last put it at
        self._geometry_only = weakref.WeakSet()     # windows Tk did not follow after DeferWindowPos
        self._job = None
        self._grid0: float | None = None            # the loop's start: the fallback grid
        self._timing = None                         # (vblank, period) or None
        self._timing_at = -1.0
        self._work: list[float] = []                # the last ticks' work, seconds (no done, no first ticks)
        self._half = False                          # stepping every second vblank (_every)
        self._fine = False
        self._fine_job = None
        self._idle_fns: list = []
        self._quiet_fns: list = []                  # quiet(): run once when the clock next goes still
        self._idle_job = None
        self._idle_since = time.perf_counter()
        self._gc_at = 0.0

    # ---- asking ----------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return bool(self._anims or self._requests or self._moves)

    @property
    def fine_timer_held(self) -> bool:
        return self._fine

    def active(self, owner, key: str) -> bool:
        return (id(owner), key) in self._anims

    # ---- starting ----------------------------------------------------------------------------
    def request(self, fn) -> None:
        """Run ``fn`` once at the next frame (the same fn asked twice runs once)."""
        self._requests[fn] = None
        self._wake()

    def take(self, fn) -> bool:
        """Take back ``fn`` asked for the next frame: True if it was waiting (the caller runs it now)."""
        return self._requests.pop(fn, 0) is None

    def flush_moves(self) -> None:
        """Do the window moves queued for this frame now (a gesture let go before the frame)."""
        self._flush(time.perf_counter())

    def _instant(self, kind: str) -> bool:
        """The Animations setting (B9): Off ends everything at once; Reduced ends movement at once
        and keeps fades (opacity and colour changes)."""
        return self.mode == "off" or (self.mode == "reduced" and kind != "fade")

    def animate(self, owner, key: str, ms: int, step, done=None, ease=ease_out, kind: str = "move") -> None:
        """``step(ease(t))`` once a frame for ``ms``, t from 0 to 1, then ``done()``. The same
        (owner, key) again replaces the running one (its done is not called). A TclError from
        step (the widget is gone) ends it quietly. It takes its first step at once. ``kind``:
        "move" or "fade" (the Animations setting, _instant): an instant one takes its last step
        at once, and its done comes at the next frame (never inside the call that started it)."""
        k = (id(owner), key)
        self._anims.pop(k, None)
        instant = self._instant(kind)
        if instant:
            ms = SKIP_MS
        a = _Anim(owner, key, None, ms, ease, done)       # (its clock starts at its first frame: _tick)
        a.step = step
        try:
            step(ease(1.0 if instant else a.progress(0.0)))
        except tk.TclError:
            return
        if instant:
            a.step = _no_step                       # (its end is shown: the frame only runs its done)
        if a.progress(0.0) >= 1.0:
            if done is not None:
                done()
            return
        self._anims[k] = a
        self._wake()

    def tween(self, owner, channel: str, to, ms: int, *, read, write, ease=ease_out, frm=None,
              done=None, kind: str | None = None, velocity: tuple | None = None) -> None:
        """Move a value (a float or a tuple of floats) to ``to`` over ``ms``. If (owner, channel)
        is moving already it turns toward ``to`` from where it is, keeping its speed (no snap).
        ``kind``: "fade" or "move" (default: "alpha" is a fade, every other channel a move); an
        instant one (_instant) is written at once, its done at the next frame. ``velocity`` (per
        component, value per second): a value not moving yet starts at that speed (a throw, B8)."""
        k = (id(owner), channel)
        now = time.perf_counter()
        scalar = not isinstance(to, (tuple, list))
        v1 = (float(to),) if scalar else tuple(float(v) for v in to)
        if self._instant(kind or ("fade" if channel == "alpha" else "move")):
            self._anims.pop(k, None)
            write(v1[0] if scalar else v1)          # (Off / Reduced: its end now, no start state first)
            if done is not None:
                self.animate(owner, channel, SKIP_MS, _no_step, done)
            return
        old = self._anims.pop(k, None)
        vel = None
        if old is not None and old.tween:
            s = old.progress(now)
            v0, vel = old.value(s), old.velocity(s)
        elif frm is not None:
            v0 = (float(frm),) if scalar else tuple(float(v) for v in frm)
        else:
            cur = read()
            v0 = (float(cur),) if scalar else tuple(float(v) for v in cur)
        if vel is None and velocity is not None:
            vel = tuple(float(v) for v in velocity)
        a = _Anim(owner, channel, None, ms, ease, done)   # (its clock starts at its first frame: _tick)
        a.tween, a.scalar, a.v0, a.v1, a.write = True, scalar, v0, v1, write
        if ease is ease_out:
            a.m = tuple(start_slope(p, q, (vel[i] if vel else 0.0), max(ms, 1) / 1000)
                        for i, (p, q) in enumerate(zip(v0, v1)))
        if ms <= 0:
            self._write(a, v1)
            if done is not None:
                done()
            return
        if frm is not None and old is None:
            self._write(a, v0)
        self._anims[k] = a
        self._wake()

    @staticmethod
    def _write(a, v: tuple) -> None:
        a.write(v[0] if a.scalar else v)

    def quiet(self, fn) -> None:
        """Run ``fn`` once, as soon as nothing moves: right after the last frame of what runs
        now, or at the next idle moment when nothing does (work kept out of the frames, B4)."""
        if self.busy:
            self._quiet_fns.append(fn)
            return
        try:
            self.root.after_idle(fn)
        except tk.TclError:
            pass

    def idle(self, fn) -> None:
        """Run ``fn`` once the clock has been quiet for IDLE_S."""
        self._idle_fns.append(fn)
        if not self.busy:
            self._arm_idle()

    # ---- stopping ----------------------------------------------------------------------------
    def stop(self, owner, key: str | None = None) -> None:
        """Stop where it is now (no done). ``key`` None: everything this owner runs."""
        if key is None or key == "box":
            self._moves.pop(id(owner), None)        # (its move queued this frame goes too)
        if key is not None:
            self._anims.pop((id(owner), key), None)
            return
        for k in [k for k in self._anims if k[0] == id(owner)]:
            del self._anims[k]

    drop_owner = stop

    def close(self) -> None:
        """The app is quitting: nothing runs any more, the 1 ms timer is given back."""
        for name in ("_job", "_fine_job", "_idle_job"):
            job = getattr(self, name)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        self._anims.clear()
        self._requests.clear()
        self._moves.clear()
        self._quiet_fns.clear()
        if self._fine:
            winapi.fine_timer(False)
            self._fine = False

    # ---- the loop ----------------------------------------------------------------------------
    def _wake(self) -> None:
        if self._job is None:
            if not self._fine:                      # the first frame's after() is on time too
                self._fine = bool(winapi.fine_timer(True))
            if self._idle_job is not None:
                self.root.after_cancel(self._idle_job)
                self._idle_job = None
            if self._grid0 is None:
                self._grid0 = time.perf_counter()
            self._schedule()

    def _display(self, now: float):
        if now - self._timing_at > TIMING_TTL:
            self._timing, self._timing_at = winapi.composition_timing(), now
        return self._timing

    def _period(self) -> float:
        """The display's frame period (s): DWM's, else the fallback grid."""
        timing = self._display(time.perf_counter())
        return timing[1] if timing is not None and timing[1] else GRID

    def _schedule(self) -> None:
        now = time.perf_counter()
        timing = self._display(now)
        if timing is None:
            vblank, period = self._grid0, GRID
        else:
            vblank, period = timing
        delay = max(1, round((next_deadline(now, vblank, period, self._every(period)) - now) * 1000))
        try:
            self._job = self.root.after(delay, self._tick)
        except tk.TclError:
            self._job = None

    def _every(self, period: float) -> int:
        """1: step at every vblank; 2: every second one, while the work of a frame stays too heavy
        for a fast display (B2). One heavy tick changes nothing: it is the median of the last
        HALF_RATE_WINDOW ticks, with hysteresis. Too few ticks to say: as it was."""
        if not period or period >= HALF_RATE_BELOW:
            self._half = False
            return 1
        recent = sorted(self._work[-HALF_RATE_WINDOW:])
        if len(recent) >= HALF_RATE_WINDOW:
            n = len(recent)
            median = (recent[(n - 1) // 2] + recent[n // 2]) / 2
            if median > HALF_RATE_ENTER * period:
                self._half = True
            elif median < HALF_RATE_LEAVE * period:
                self._half = False
        return 2 if self._half else 1

    def _report(self) -> None:
        try:
            self.root.report_callback_exception(*sys.exc_info())
        except Exception:
            pass

    def _tick(self) -> None:
        self._job = None
        now = time.perf_counter()
        if not self._fine:
            self._fine = bool(winapi.fine_timer(True))
        if self._fine_job is not None:
            self.root.after_cancel(self._fine_job)
            self._fine_job = None
        requests, self._requests = list(self._requests), {}
        for fn in requests:
            try:
                fn()
            except Exception:
                self._report()
        finished, logged, first = [], set(), False
        period = self._period()
        for k, a in list(self._anims.items()):
            if self._anims.get(k) is not a:
                continue                            # replaced or stopped by an earlier step
            if a.t0 is None:                        # its first frame: one frame in (B1), however long
                a.t0 = now - period                 # the work between its start and this frame took
                first = True                        # (a first step builds things: not the frame's load, B2)
            s = a.progress(now)
            try:
                if a.tween:
                    self._write(a, a.v1 if s >= 1.0 else a.value(s))
                else:
                    a.step(a.ease(s))
            except tk.TclError:
                self._anims.pop(k, None)
                continue
            except Exception:
                self._anims.pop(k, None)
                self._report()
                continue
            if perf.ENABLED and a.key not in logged:   # one frame per key per tick (many windows share "box")
                logged.add(a.key)
                perf.perf.frame(a.key, now)
            if s >= 1.0:
                if self._anims.get(k) is a:
                    del self._anims[k]
                finished.append(a)
        self._flush(now)
        if not first:                               # the frame's own work: steps and moves, no done (B2)
            self._work = (self._work + [time.perf_counter() - now])[-HALF_RATE_WINDOW:]
        for a in finished:
            if a.done is not None:
                try:
                    a.done()
                except Exception:
                    self._report()
        if self.busy:
            if self._job is None:
                self._schedule()
        else:
            self._went_idle()

    # ---- windows ----------------------------------------------------------------------------
    def move(self, win, x: int, y: int, w: int | None = None, h: int | None = None) -> None:
        """Put ``win`` there (and size it, with w and h) at this frame's end, together with every
        other window moved in the frame (one DeferWindowPos). The last move per window wins."""
        self._moves[id(win)] = (win, int(x), int(y), None if w is None else int(w), None if h is None else int(h))
        self._wake()

    def box_now(self, win) -> tuple | None:
        """The box a glide last put ``win`` at."""
        try:
            return self._boxes.get(win)
        except TypeError:
            return None

    def glide(self, win, to, ms: int, *, frm=None, done=None, sized: bool = False, write_extra=None,
              ease=ease_out, velocity: tuple | None = None) -> None:
        """Glide ``win`` to the box ``to`` (x0, y0, x1, y1): a tween on its "box" channel, so a
        later glide turns from where it is. ``sized``: its size changes on the way too.
        ``velocity`` (vx, vy) px/s: it starts moving at that speed (a thrown note, B8)."""
        def read():                         # (only when no glide runs: where the window really is)
            x, y = win.winfo_rootx(), win.winfo_rooty()
            return x, y, x + win.winfo_width(), y + win.winfo_height()

        def write(v):
            b = tuple(int(round(c)) for c in v)
            self._boxes[win] = b
            if sized:
                self.move(win, b[0], b[1], b[2] - b[0], b[3] - b[1])
            else:
                self.move(win, b[0], b[1])
            if write_extra is not None:
                write_extra(b)
        vel = None if velocity is None else (velocity[0], velocity[1], velocity[0], velocity[1])
        self.tween(win, "box", tuple(to), ms, read=read, write=write, ease=ease, frm=frm, done=done, velocity=vel)

    def _flush(self, now: float) -> None:
        """Apply the frame's window moves: one DeferWindowPos for all of them (BATCH_MOVES),
        else (or for a window where Tk did not follow) one geometry() each."""
        if not self._moves:
            return
        moves, self._moves = list(self._moves.values()), {}
        live = []
        for m in moves:
            try:
                if m[0].winfo_exists():
                    live.append(m)
            except tk.TclError:
                pass
        batch = [m for m in live if BATCH_MOVES and m[0] not in self._geometry_only]
        rest = [m for m in live if m not in batch]
        if batch:
            hwnds = [winapi.hwnd_of(m[0]) for m in batch]
            if all(hwnds) and winapi.defer_move([(h, x, y, w, hh) for h, (_win, x, y, w, hh) in zip(hwnds, batch)]):
                for m in batch:
                    win, x, y = m[0], m[1], m[2]
                    try:
                        if (win.winfo_rootx(), win.winfo_rooty()) != (x, y):
                            self._geometry_only.add(win)        # Tk did not follow: geometry() from now on
                            print(f"anim: {win} falls back to geometry()", file=sys.stderr)
                            rest.append(m)
                    except tk.TclError:
                        pass
            else:
                rest += batch
        for win, x, y, w, h in rest:
            try:
                win.geometry(f"{w}x{h}+{x}+{y}" if w is not None and h is not None else f"+{x}+{y}")
            except tk.TclError:
                pass

    # ---- going quiet ------------------------------------------------------------------------
    def _went_idle(self) -> None:
        self._grid0 = None
        self._work, self._half = [], False          # the next motion starts at full rate (B2)
        fns, self._quiet_fns = self._quiet_fns, []
        for fn in fns:
            try:
                fn()
            except Exception:
                self._report()
        self._idle_since = time.perf_counter()
        try:
            self._fine_job = self.root.after(int(FINE_RELEASE_S * 1000), self._release_fine)
        except tk.TclError:
            pass
        self._arm_idle()

    def _release_fine(self) -> None:
        self._fine_job = None
        if self._fine and not self.busy:
            winapi.fine_timer(False)
            self._fine = False

    def _arm_idle(self) -> None:
        if self._idle_job is not None:
            return
        wait = max(0.0, IDLE_S - (time.perf_counter() - self._idle_since))
        try:
            self._idle_job = self.root.after(max(1, round(wait * 1000)), self._run_idle)
        except tk.TclError:
            self._idle_job = None

    def _run_idle(self) -> None:
        self._idle_job = None
        if self.busy:
            return                                  # (armed again when it goes quiet)
        fns, self._idle_fns = self._idle_fns, []
        for fn in fns:
            try:
                fn()
            except Exception:
                self._report()
        now = time.perf_counter()
        if self._gc_at == 0.0 or now - self._gc_at >= IDLE_REPEAT_S:
            self._gc_at = now
            winapi.collect_garbage()
        try:                                        # quiet a while longer: collect again later
            self._idle_job = self.root.after(int(IDLE_REPEAT_S * 1000), self._run_idle)
        except tk.TclError:
            self._idle_job = None


def install(root: tk.Misc) -> FrameClock:
    """The clock of this Tk root (made on first use)."""
    clock = getattr(root, "_frame_clock", None)
    if clock is None:
        clock = root._frame_clock = FrameClock(root)
    return clock


def clock_of(widget) -> FrameClock:
    return install(widget._root())
