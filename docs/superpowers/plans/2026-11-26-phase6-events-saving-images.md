# Phase 6: Events, Saving and Images, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- The idle app wakes less than once per second.
- A save with no change costs about 0 ms.
- The taskbar thumbnail peaks under 4 MB.
- A kill during a save leaves a loadable file.
- Image memory has a byte budget, and per-setup data and session lists stay bounded.

**Architecture:**
- **A wake channel (`waker.py`).** It is a loopback socket that Tcl listens on with `fileevent`. A `Waker.ping(word)` from anywhere, even a Windows message procedure that must not call Tk, wakes the event loop, which then runs that word's handler.
- **What uses it:**
  - the taskbar hook (instead of a 30 ms drain poll);
  - display, setting, DPI, time and power messages (instead of the 1 s monitor poll and the 30 s day check);
  - a second launch's "show" and the installer's "quit", through a port file (instead of the 800 ms signal-file poll).
- **Saving:** it skips the whole serialization when no note, pad or prefs attribute changed and no save was asked for. It always fully checks at exit, and writes with fsync.

**Tech Stack:** Python 3.15, Tkinter, Tcl sockets, ctypes, Pillow. Tests use stdlib `unittest`.

**Spec:** `docs/2026-11-25-redesign-design.md` §5.5–§5.7 and §7 (Phase 6 row: "images.py and the worker; thumbnail reduced; events in place of polls; persist.py; per-setup pruning"; done when "Idle wakeups < 1/s; save with no change ≈ 0 ms; thumbnail peak < 4 MB; kill-during-save test leaves a loadable file").

## Global Constraints

- **Keep today's behaviour:**
  - taskbar minimize/restore of notes and of the app (Win+M, Win+D);
  - a second launch brings the notes forward;
  - the installer's "quit" saves and closes;
  - monitor changes settle as today (600 ms settle, 3 s max);
  - the date and bin purge roll over at midnight.
- **The Windows message procedures never call tkinter** (the Tcl lock is held there).
- **Old app versions and installers keep working:** the signal files stay as a fallback, checked at start and every 10 s.
- **Data:** never touch `%APPDATA%\StickyNote`.
- **Tests:** run with `.\StickyNote\runtime\python.exe -m unittest discover -s tests`. All 181 tests stay green.

## Decisions

- **No image worker thread.**
  - Decoding off the UI thread changes timing (placeholders) and adds a thread-safety surface; the spec's done criteria don't depend on it.
  - The byte-budget cache is built; the worker is deferred and ledgered.
- **`persist.py` as a module is Phase 7's split.** Here the save logic changes in `store.py`/`app.py`.
- **The save skip:**
  - `Note`, `Pad` and `Prefs` bump a module counter (`store.edits`) in `__setattr__`, and `request_save()` marks the app dirty.
  - `save_now()` returns at once when neither moved and no window has a pending typing sync.
  - `quit()` calls `save_now(force=True)` (a full serialize-and-compare), so an in-place list change without a `request_save` is still written at exit, as today.
- **Wake words:**
  - `"sys"` (taskbar hook queued something);
  - `"screens"`, `"day"`, `"show"`, `"quit"`;
  - unknown words are ignored.
  - Port file: `<data folder>/wake.port` holds the port number; it is removed at quit.

---

### Task 1: The wake channel and the taskbar hook without polling

**Files:**
- Create: `StickyNote/app/waker.py` (`Waker(root, handlers: dict)`, `.ping(word: str)`, `.port`, `.close()`)
- Modify: `winapi.py` (`hook_syscommand(win, sink, wake=None)`: after appending, calls `wake()`; catches `WM_SIZE`/`SIZE_MINIMIZED` on the proxy as ("min", h, t)), `app.py` (a waker in `__init__`; `_drain_syscommands` runs on "sys" and no longer re-arms an `after(30)`; the proxy minimize is caught by the hook; `_check_thumbnail` runs from window changes, throttled 500 ms)
- Test: `tests/test_events.py`

- [ ] Test `test_ping_wakes_handler`: `Waker.ping("x")` from a plain Python call runs the "x" handler within one pump, and unknown words are ignored.
- [ ] Test `test_no_drain_timer_when_idle`: after start-up settles, no `after` job for `_drain_syscommands` is pending (`app._sys_job is None`), and an appended ("restore", hwnd) plus `wake()` restores a minimized note.
- [ ] Test `test_idle_wakeups_under_one_per_second`: count Tk timer callbacks (wrapping `root.after`/`after_idle` callbacks) over 10 s of idle pumping. There are fewer than 10.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf(events): the taskbar hook wakes the app; no 30 ms drain poll`.

### Task 2: Show, quit, monitors and the day by events

**Files:**
- Modify: `app.py` (the port file; `"show"`/`"quit"` handlers; the signal files checked at start and every 10 s; the proxy hook passes display (0x7E), setting (0x1A with `SPI_SETWORKAREA` 0x2F), DPI (0x2E0), time (0x1E) and power-resume (0x218 with 0x12/0x7) messages as `"screens"`/`"day"`; the monitor poll every 15 s; the day check at the next midnight + 1 s), `winapi.py` (the hook's extra messages), `main.py` and `install.py` (send "show"/"quit" to the port, falling back to the files)
- Test: `tests/test_events.py`

- [ ] Test `test_second_launch_shows_via_port`: a client connecting to `wake.port` and sending `show\n` brings a minimized note back.
- [ ] Test `test_quit_via_port_saves`: sending `quit\n` saves and closes (`app.closed`).
- [ ] Test `test_day_timer_aims_at_midnight`: the pending day job's delay is the time to the next midnight + 1 s (± 2 s).
- [ ] Test `test_screens_word_starts_check`: `ping("screens")` calls `check_screens` (Spy).
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf(events): show, quit, monitors and the date by events, not polls`.

### Task 3: Saving: nothing to do costs nothing; fsync

**Files:**
- Modify: `store.py` (`edits` counter in `Note`/`Pad`/`Prefs.__setattr__`; compact JSON; `os.fsync` before the replace), `app.py` (`request_save` marks dirty; `save_now(force=False)` skips when clean; `quit` forces)
- Test: `tests/test_saving.py`

- [ ] Test `test_save_without_change_skips`: after a save, `save_now()` makes no `json.dumps` call (Spy on `store.json.dumps`) and takes under 1 ms.
- [ ] Test `test_any_attribute_change_saves`: setting `note.color`, `pad.x` or `prefs.snap_gap` alone (no `request_save`) is written by the next `save_now()`.
- [ ] Test `test_quit_writes_in_place_list_change`: `prefs.custom_colors.append("#123456")` with no `request_save`, then `quit()`, puts it in the file.
- [ ] Test `test_kill_during_save_leaves_loadable_file`: with `os.replace` patched to raise after the `.tmp` is written, `notes.json` still loads with the previous content.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf(save): a save with nothing changed returns at once; fsync before replace`.

### Task 4: Thumbnail, image budget, bounded per-setup data

**Files:**
- Modify: `app.py` (`_send_thumbnail` reduces each window's shot before compositing onto a thumbnail-sized canvas; the signature drops `note.modified`; `picture()` cache by bytes, 64 MB; `_closed` keeps the last 20), the setup stamping (8 most recent setups by last-seen in `pad.setups`, `calendar_setups`, `prefs.setup_scales`, `grid_homes`)
- Test: `tests/test_bounded.py`

- [ ] Test `test_thumbnail_never_full_size`: with 20 notes and a 200×120 request, no `Image.new` in `_send_thumbnail` is bigger than 200×120 (Spy on `Image.new`), and the result is sent.
- [ ] Test `test_picture_cache_budget`: filling `app.picture` with images past 64 MB of pixels keeps the total under the budget.
- [ ] Test `test_setups_pruned_to_eight`: stamping 12 different setups leaves the 8 most recent in each per-setup map.
- [ ] Test `test_closed_list_bounded`: closing 30 notes keeps 20 in `_closed`.
- [ ] Run, watch them fail, then implement and run until they pass. Commit: `perf: thumbnail from reduced shots; image budget; bounded setups and closed list`.

### Task 5: Measure and write results

- [ ] Idle wakeups per second (10 s idle with 5 notes), a no-change save, and the thumbnail's largest image. Write a "Phase 6 results" section in the spec. Commit: `perf: phase 6 results`.
