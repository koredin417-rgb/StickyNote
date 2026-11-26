# Phase 7: Module Split, Implementation Plan

**Goal:**
- `app.py` keeps the wiring and the lifecycle and is under 600 lines.
- The App class's methods move, unchanged, to modules by responsibility.
- Every earlier phase's check still passes.

**Spec:** `docs/2026-11-25-redesign-design.md` §5.8 and §7 (Phase 7 row: done when "`app.py` < 600 lines; all phases' checks still pass").

## Approach (decided)

- **Mixin classes.**
  - Each new module holds one mixin class with its methods moved verbatim: the source text of each method, its decorators and the comment lines above it.
  - `App` inherits them all. `self.` reach-ins keep working, so no behaviour changes.
  - The spec's separate objects with public methods would rewrite every cross-call. That is a bigger, riskier change for the same layout of files, and is left for later.
- **The move is a script** (`ast` method spans), not hand edits, so no method body is retyped.
- **Shared names:**
  - App's former module-level constants and helpers go to `appbase.py`.
  - Each module repeats `app.py`'s imports, `from ui_note import *` included. That keeps every module an `_APP_PART`, so `set_shared` updates (`UI_FONT`, `BIN_DAYS`) reach it.

| Module | Mixin | Methods |
|---|---|---|
| `taskbar.py` | `TaskbarMixin` | proxy, taskbar requests (drain), preview |
| `persist.py` | `PersistMixin` | request_save, autosave, save_now, shutdown save |
| `screens.py` | `ScreensMixin` | monitors, setups, per-setup copies, change checks |
| `settings_ctl.py` | `SettingsMixin` | the setters |
| `registry.py` | `RegistryMixin` | notes and windows: open, close, reopen, bin, pin; calendar ownership; pictures |
| `magnet.py` | `MagnetMixin` | snap, hold, links, groups |
| `layout.py` | `LayoutMixin` | space model, find spot, grow, close up, give back, settle drop, apply / Undo, fold |
| `tiles.py` | `TilesMixin` | tidy, auto layout grid, respace |

## Also from §5.8

- The duplicate `calendar()` definition is removed (the first one never ran).
- The duplicate `import calgeom` is removed.
- **Left for later** (ledgered):
  - replacing `from ui_note import *` with explicit imports (the star chain is how `set_shared` reaches every part);
  - each module's unused imports, from the copied import block;
  - `settings_changed(key)` broadcast in place of the per-setter loops.

## Checks

- [ ] The full suite (206 tests) passes.
- [ ] The phase tools still run: `tools/interact_bench.py`, `tools/render_bench.py`, `tools/idle_bench.py` and `tools/look_capture.py`.
- [ ] `app.py` is under 600 lines.
