"""Small Windows helpers (ctypes only). Every function is a harmless no-op elsewhere."""
from __future__ import annotations

import ctypes
import gc
import sys

IS_WINDOWS = sys.platform == "win32"

GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
DWMWA_TRANSITIONS_FORCEDISABLED = 3
WM_SYSCOMMAND = 0x0112
SC_MINIMIZE, SC_RESTORE = 0xF020, 0xF120
SW_MINIMIZE = 6
SW_RESTORE = 9
ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
SM_CXSCREEN, SM_CYSCREEN = 0, 1
MONITORINFOF_PRIMARY = 0x00000001

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


def clip_height(win, width=None, height=None) -> bool:
    """Show only the top ``height`` px of ``win`` (a window region), or all of it again
    (``width`` None). A roll moves this edge instead of resizing the window: nothing is
    laid out or uncovered, so there is nothing to paint late. False where it cannot."""
    hwnd = hwnd_of(win) if IS_WINDOWS else 0
    if not hwnd:
        return False
    gdi32 = ctypes.WinDLL("gdi32")
    gdi32.CreateRectRgn.restype = ctypes.c_void_p
    user32.SetWindowRgn.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
    if width is None:
        return bool(user32.SetWindowRgn(ctypes.c_void_p(hwnd), None, True))
    rgn = gdi32.CreateRectRgn(0, 0, int(width), max(1, int(height)))
    if not rgn:
        return False
    if not user32.SetWindowRgn(ctypes.c_void_p(hwnd), ctypes.c_void_p(rgn), True):
        gdi32.DeleteObject(ctypes.c_void_p(rgn))
        return False
    return True                             # (the window owns the region now)


def paint_now(win):
    """Paint ``win`` now (it just grew): Windows' paint request reaches Tk as window events,
    which are handled here, and Tk draws at once (idle tasks) instead of a frame later, so the
    part just uncovered never shows unpainted."""
    try:
        import _tkinter
        hwnd = hwnd_of(win) if IS_WINDOWS else 0
        if hwnd:
            user32.RedrawWindow(ctypes.c_void_p(hwnd), None, None, 0x0001 | 0x0100 | 0x0080)  # INVALIDATE|UPDATENOW|ALLCHILDREN
        for _ in range(64):                 # (only window events: no timers run in between)
            if not win.tk.dooneevent(_tkinter.WINDOW_EVENTS | _tkinter.DONT_WAIT):
                break
        win.update_idletasks()
    except Exception:
        pass


def snapshot(win):
    """What a Tk toplevel shows, drawn by the window itself (PrintWindow, so covered or
    off-screen parts too): (width, height, BGRX bytes), or None."""
    hwnd = hwnd_of(win) if IS_WINDOWS else 0
    if not hwnd:
        return None
    from ctypes import wintypes
    gdi32 = ctypes.WinDLL("gdi32")
    H = wintypes.HANDLE
    user32.GetDC.restype = H
    user32.GetDC.argtypes = (wintypes.HWND,)
    user32.ReleaseDC.argtypes = (wintypes.HWND, H)
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.PrintWindow.argtypes = (wintypes.HWND, H, wintypes.UINT)
    gdi32.CreateCompatibleDC.restype = H
    gdi32.CreateCompatibleDC.argtypes = (H,)
    gdi32.CreateCompatibleBitmap.restype = H
    gdi32.CreateCompatibleBitmap.argtypes = (H, ctypes.c_int, ctypes.c_int)
    gdi32.SelectObject.restype = H
    gdi32.SelectObject.argtypes = (H, H)
    gdi32.DeleteObject.argtypes = (H,)
    gdi32.DeleteDC.argtypes = (H,)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    gdi32.GetDIBits.argtypes = (H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.POINTER(BIH), wintypes.UINT)
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    try:
        gdi32.SelectObject(mdc, bmp)
        if not user32.PrintWindow(hwnd, mdc, 2):            # PW_RENDERFULLCONTENT
            return None
        bih = BIH(biSize=ctypes.sizeof(BIH), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0):
            return None
        return w, h, buf.raw
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, hdc)


def fine_timer(on: bool) -> bool:
    """Ask Windows for 1 ms timer ticks (``on``) or give them back. Tk's ``after`` otherwise
    waits in 15.6 ms steps, so an animation's frames come at 16 or 31 ms, unevenly. Since
    Windows 10 2004 this only affects this process. Returns whether it is on now."""
    if not IS_WINDOWS:
        return False
    try:
        winmm = ctypes.WinDLL("winmm")
        if on:
            return winmm.timeBeginPeriod(1) == 0      # TIMERR_NOERROR
        winmm.timeEndPeriod(1)
    except (OSError, AttributeError):
        pass
    return False


def hwnd_of(win) -> int:
    """Outer (frame) window handle of a Tk toplevel, 0 if it does not exist yet."""
    try:
        return int(win.wm_frame(), 16)
    except Exception:
        return 0


def show_in_taskbar(win) -> bool:
    """Give a borderless (overrideredirect) window a taskbar button.

    Returns True when the style was changed; the window must then be hidden
    and shown again for the taskbar to notice.
    """
    hwnd = hwnd_of(win)
    if not IS_WINDOWS or not hwnd:
        return False
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    wanted = (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
    if wanted == ex:
        return False
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, wanted)
    return True


def set_owner(win, owner) -> None:
    """Make ``owner`` own ``win``: it then stays above the owner, comes forward
    with it and hides with it. (Tk's ``transient`` does not do this for
    borderless windows.)"""
    hwnd, owner_hwnd = hwnd_of(win), hwnd_of(owner)
    if IS_WINDOWS and hwnd and owner_hwnd:
        user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, owner_hwnd)


def is_iconic(win) -> bool:
    """Whether Windows has ``win`` minimized (also when Tk was not told)."""
    hwnd = hwnd_of(win)
    return bool(IS_WINDOWS and hwnd and user32.IsIconic(hwnd))


def minimize(win, raw: bool = False) -> None:
    """Minimize ``win``. This calls ShowWindow, which sends no WM_SYSCOMMAND, so it never
    reaches hook_syscommand's swallowing: ``raw`` only states that intent (the same either way)."""
    hwnd = hwnd_of(win)
    if IS_WINDOWS and hwnd:
        user32.ShowWindow(hwnd, SW_MINIMIZE)
    else:
        win.iconify()


def restore(win, raw: bool = False) -> None:
    """Restore ``win`` (see minimize for ``raw``)."""
    hwnd = hwnd_of(win)
    if IS_WINDOWS and hwnd:
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        win.deiconify()


def set_click_through(win, on: bool) -> None:
    """Mouse clicks pass through ``win`` to what is under it (on), or hit it again (off).
    Call after the window is first mapped.

    On adds WS_EX_TRANSPARENT | WS_EX_LAYERED; off clears only WS_EX_TRANSPARENT. Rule for every
    click-through window (decided with motion.Outlines; HolidayCard and the preview follow it):
    Tk must own the layering. Give the window ``-alpha`` below 1.0 (motion.CLICK_THROUGH_ALPHA,
    0.999, looks opaque) before turning this on, and keep it below 1.0 for as long as it is
    click-through (a ``-transparentcolor`` window is layered by Tk as well). Then Tk has called
    SetLayeredWindowAttributes itself, so the window draws, and its later ``-alpha`` changes
    (fades) keep both bits. On a window Tk has not layered, Tk's first ``-alpha`` change below
    1.0 writes its own style back and drops WS_EX_TRANSPARENT (seen with Tk 9), which calling
    SetLayeredWindowAttributes here would not prevent; so this function does not call it."""
    hwnd = hwnd_of(win)
    if not IS_WINDOWS or not hwnd:
        return
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    wanted = (ex | WS_EX_TRANSPARENT | WS_EX_LAYERED) if on else (ex & ~WS_EX_TRANSPARENT)
    if wanted != ex:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, wanted)


def disable_transitions(win) -> None:
    """Turn off Windows' own minimize/restore animation for ``win`` (the app animates itself).
    Ignored when DWM is unavailable."""
    hwnd = hwnd_of(win)
    if not IS_WINDOWS or not hwnd:
        return
    try:
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


DWMWA_FORCE_ICONIC_REPRESENTATION = 7
DWMWA_HAS_ICONIC_BITMAP = 10
DWMWA_DISALLOW_PEEK = 11
WM_DWMSENDICONICTHUMBNAIL = 0x0323


def use_iconic_thumbnail(win, on: bool = True) -> bool:
    """The taskbar preview of ``win`` is a picture the app draws (set_iconic_thumbnail, when
    DWM asks: WM_DWMSENDICONICTHUMBNAIL, see hook_syscommand), not the window itself; no Aero
    Peek of it either. ``on=False`` gives the plain preview back. Returns whether DWM took it."""
    hwnd = hwnd_of(win)
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        dwm = ctypes.windll.dwmapi
        ok = True
        for attr in (DWMWA_FORCE_ICONIC_REPRESENTATION, DWMWA_HAS_ICONIC_BITMAP, DWMWA_DISALLOW_PEEK):
            value = ctypes.c_int(1 if on else 0)
            ok &= dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(value),
                                            ctypes.sizeof(value)) == 0
        return ok
    except Exception:
        return False


def set_iconic_thumbnail(win, image) -> int:
    """Give DWM ``image`` (a PIL RGBA image, no bigger than it asked for) as the taskbar preview
    of ``win``. Returns the HRESULT: 0 when DWM took it (-1: no call was made)."""
    hwnd = hwnd_of(win)
    if not IS_WINDOWS or not hwnd:
        return -1
    gdi32 = ctypes.WinDLL("gdi32")
    H = wintypes.HANDLE

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    gdi32.CreateDIBSection.restype = H
    gdi32.CreateDIBSection.argtypes = (H, ctypes.POINTER(BIH), wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                       H, wintypes.DWORD)
    gdi32.DeleteObject.argtypes = (H,)
    w, h = image.size
    # premultiplied BGRA, top-down
    r, g, b, a = image.convert("RGBA").split()
    from PIL import Image, ImageChops
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    raw = Image.merge("RGBA", (b, g, r, a)).tobytes()
    bih = BIH(biSize=ctypes.sizeof(BIH), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(None, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
    if not bmp:
        return -1
    try:
        ctypes.memmove(bits, raw, len(raw))
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetIconicThumbnail.argtypes = (wintypes.HWND, H, wintypes.DWORD)
        return dwm.DwmSetIconicThumbnail(hwnd, bmp, 0) & 0xFFFFFFFF
    except Exception:
        return -1
    finally:
        gdi32.DeleteObject(bmp)


def invalidate_iconic(win) -> None:
    """The taskbar preview is out of date: DWM asks for a new one when it next shows it."""
    hwnd = hwnd_of(win)
    if IS_WINDOWS and hwnd:
        try:
            ctypes.windll.dwmapi.DwmInvalidateIconicBitmaps(wintypes.HWND(hwnd))
        except Exception:
            pass


def virtual_screen() -> tuple[int, int, int, int] | None:
    """(x, y, width, height) covering all monitors."""
    if not IS_WINDOWS:
        return None
    m = user32.GetSystemMetrics
    box = (m(SM_XVIRTUALSCREEN), m(SM_YVIRTUALSCREEN),
           m(SM_CXVIRTUALSCREEN), m(SM_CYVIRTUALSCREEN))
    return box if box[2] > 0 and box[3] > 0 else None


def work_area(win) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of the usable part (without the taskbar) of the monitor
    that ``win`` is on."""
    hwnd = hwnd_of(win)
    if not IS_WINDOWS or not hwnd:
        return None

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    try:
        user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
        monitor = user32.MonitorFromWindow(hwnd, 2)         # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def _enum_monitors() -> list[tuple[bool, tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """(is primary, monitor, work area) of every monitor, each (left, top, right, bottom),
    in Windows' order. [] when Windows cannot list them."""
    if not IS_WINDOWS:
        return []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    found = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                   ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def each(monitor, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            m, w = info.rcMonitor, info.rcWork
            found.append((bool(info.dwFlags & MONITORINFOF_PRIMARY),
                          (m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom)))
        return True
    try:
        user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
        user32.EnumDisplayMonitors.argtypes = (wintypes.HDC, ctypes.c_void_p, proc_type, wintypes.LPARAM)
        user32.EnumDisplayMonitors(None, None, proc_type(each), 0)
    except Exception:
        return []
    return found


def work_areas() -> list[tuple[int, int, int, int]]:
    """(left, top, right, bottom) of the usable part of every monitor."""
    return [work for _primary, _monitor, work in _enum_monitors()]


def monitors() -> list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """(monitor, work area) of every monitor, each (left, top, right, bottom), the primary
    one first. If Windows lists none: the primary screen's size for both."""
    if not IS_WINDOWS:
        return []
    found = _enum_monitors()
    if not found:
        screen = (0, 0, user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN))
        return [(screen, screen)]
    found.sort(key=lambda f: not f[0])      # the primary first, the rest in Windows' order
    return [(monitor, work) for _primary, monitor, work in found]


def set_dpi_aware() -> None:
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_id(app_id: str) -> None:
    """Group our windows under our own taskbar icon (not python.exe's)."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def acquire_single_instance(name: str):
    """Return a mutex handle if we are the first instance, else None.

    Keep the returned handle alive for the life of the process.
    """
    if not IS_WINDOWS:
        return object()
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def load_private_fonts(folder) -> int:
    """Make the font files in ``folder`` usable by this program only (nothing is installed
    in Windows). Returns how many were loaded."""
    if not IS_WINDOWS:
        return 0
    from pathlib import Path
    add = ctypes.windll.gdi32.AddFontResourceExW
    add.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p)
    loaded = 0
    for path in sorted(Path(folder).glob("*.[ot]tf")):
        loaded += bool(add(str(path), 0x10, None))         # FR_PRIVATE
    return loaded


def is_admin() -> bool:
    """True when this process runs with administrator rights (elevated)."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def instance_running(name: str) -> bool:
    """True while some process holds the single-instance mutex ``name``."""
    if not IS_WINDOWS:
        return False
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


# ---- IME (Korean input) --------------------------------------------------------
# A Korean syllable is put together in the IME ("composition") before it reaches the
# text. Tk loses it when the user clicks elsewhere first, so the app finishes it itself.
GCS_COMPSTR = 0x0008
NI_COMPOSITIONSTR = 0x0015
CPS_COMPLETE, CPS_CANCEL = 0x0001, 0x0004
WM_KILLFOCUS, WM_NCDESTROY, WM_IME_SETCONTEXT = 0x0008, 0x0082, 0x0281
ISC_SHOWUICOMPOSITIONWINDOW = 0x80000000
ISC_SHOWUIALL = 0xC000000F

if IS_WINDOWS:
    imm32 = ctypes.WinDLL("imm32")
    comctl32 = ctypes.WinDLL("comctl32")
    _HIMC = wintypes.HANDLE
    imm32.ImmGetContext.argtypes = (wintypes.HWND,)
    imm32.ImmGetContext.restype = _HIMC
    imm32.ImmReleaseContext.argtypes = (wintypes.HWND, _HIMC)
    imm32.ImmGetCompositionStringW.argtypes = (_HIMC, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    imm32.ImmGetCompositionStringW.restype = ctypes.c_long
    imm32.ImmNotifyIME.argtypes = (_HIMC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
    _SUBCLASSPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.SetWindowSubclass.argtypes = (wintypes.HWND, _SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.RemoveWindowSubclass.argtypes = (wintypes.HWND, _SUBCLASSPROC, ctypes.c_size_t)
    comctl32.DefSubclassProc.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    comctl32.DefSubclassProc.restype = ctypes.c_ssize_t

_focus_hooks: dict = {}


# ---- Python window procs and the garbage collector ------------------------------
# hook_ime and hook_syscommand put Python code (ctypes callbacks) into a Tk window's message
# handling. Tk's event loop calls them from inside DispatchMessage, with _tkinter's saved
# thread state set for that loop. Any tkinter call made in there resets that state to NULL on
# its way out (LEAVE_TCL), and the next Python callback of the same update()/mainloop step
# aborts the process: "Fatal Python error: PyEval_RestoreThread ... thread state is NULL".
# The procs make no tkinter call themselves, but a cyclic garbage collection landing in one
# runs finalizers that do (tkinter.font.Font, tkinter.Image, PIL.ImageTk.PhotoImage and
# tkinter.Variable delete their Tcl side in __del__). So once a proc is in, Python collects
# no garbage by itself: the app calls collect_garbage() from a Tk ``after`` job instead.
def _keep_gc_out_of_procs() -> None:
    gc.disable()


def collect_garbage() -> None:
    """The collection Python would run by itself now (the oldest generation past its
    threshold), if any. Call it from a Tk callback (an ``after`` job), never from a proc."""
    counts, limits = gc.get_count(), gc.get_threshold()
    if not limits[0]:
        return                              # collection was turned off (threshold 0)
    gen = next((g for g in (2, 1, 0) if counts[g] > limits[g]), None)
    if gen is not None:
        gc.collect(gen)


def _notify_ime(hwnd, action) -> None:
    himc = imm32.ImmGetContext(hwnd)
    if himc:
        imm32.ImmNotifyIME(himc, NI_COMPOSITIONSTR, action, 0)
        imm32.ImmReleaseContext(hwnd, himc)


def composition(hwnd: int, take: bool = False) -> str:
    """The syllable the IME is still putting together for ``hwnd``'s thread ("" when
    nothing is being composed). ``take`` also takes it out of the IME, which then forgets it."""
    if not IS_WINDOWS or not hwnd:
        return ""
    himc = imm32.ImmGetContext(hwnd)
    if not himc:
        return ""
    try:
        size = imm32.ImmGetCompositionStringW(himc, GCS_COMPSTR, None, 0)
        if size <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(size // 2 + 1)
        imm32.ImmGetCompositionStringW(himc, GCS_COMPSTR, buf, size)
        if take:
            imm32.ImmNotifyIME(himc, NI_COMPOSITIONSTR, CPS_CANCEL, 0)
        return buf.value
    finally:
        imm32.ImmReleaseContext(hwnd, himc)


def hide_ime_box(hwnd: int) -> None:
    """Tell the IME once more not to draw its own box for the syllable being typed (see
    hook_ime). It only hears this when its window gets the focus from Windows; a focus
    change inside the app (or a moment the hook missed) could leave the white box on."""
    if not IS_WINDOWS or not hwnd or not hook_ime(hwnd):
        return
    send = user32.SendMessageW
    send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    send(hwnd, WM_IME_SETCONTEXT, 1, ISC_SHOWUIALL & ~ISC_SHOWUICOMPOSITIONWINDOW)


def take_composition(hwnd: int) -> str:
    return composition(hwnd, take=True)


def hook_ime(hwnd: int) -> bool:
    """Korean input for the window ``hwnd`` (a Tk toplevel's own window):

    * When it loses the keyboard focus, finish the IME's syllable first. Tk handles the
      focus loss before the IME's last character and then throws that character away;
      finished first, it arrives in time.
    * The IME does not draw its own (white) box for the syllable being typed: the app
      shows it in the text itself (NoteWindow._show_preedit).

    Its proc is Python run inside Tk's window proc: hooked, Python collects no garbage by
    itself (see collect_garbage)."""
    if not IS_WINDOWS or not hwnd:
        return False
    if hwnd in _focus_hooks:
        return True

    @_SUBCLASSPROC
    def proc(h, msg, wparam, lparam, uid, _data):
        try:
            if msg == WM_KILLFOCUS:
                _notify_ime(h, CPS_COMPLETE)
            elif msg == WM_IME_SETCONTEXT:
                lparam &= ~ISC_SHOWUICOMPOSITIONWINDOW
            elif msg == WM_NCDESTROY:
                comctl32.RemoveWindowSubclass(h, proc, uid)
                _focus_hooks.pop(h, None)
        except Exception:
            pass
        return comctl32.DefSubclassProc(h, msg, wparam, lparam)

    if not comctl32.SetWindowSubclass(hwnd, proc, 1, 0):
        return False
    _focus_hooks[hwnd] = proc           # keep the callback alive while the window lives
    _keep_gc_out_of_procs()
    return True


_syscmd_hooks: dict = {}


def hook_syscommand(win, sink: list) -> None:
    """Swallow the system's minimize and restore of ``win`` (the taskbar button, Win+D...) and
    append ("min" | "restore", hwnd, time.monotonic()) to ``sink`` instead; the app does the
    animation itself. Other messages go on as before. The proc only appends to the list: it
    never calls tkinter (a Tcl thread-state hazard), so the app drains ``sink`` from an
    ``after`` poll. The subclass (uid 2, beside hook_ime's uid 1) removes itself on WM_NCDESTROY.
    Like hook_ime, it turns Python's own garbage collection off (see collect_garbage)."""
    hwnd = hwnd_of(win)
    if not IS_WINDOWS or not hwnd or hwnd in _syscmd_hooks:
        return
    import time

    @_SUBCLASSPROC
    def proc(h, msg, wparam, lparam, uid, _data):
        try:
            if msg == WM_SYSCOMMAND:
                command = wparam & 0xFFF0
                if command == SC_MINIMIZE:
                    sink.append(("min", h, time.monotonic()))
                    return 0
                if command == SC_RESTORE:
                    sink.append(("restore", h, time.monotonic()))
                    return 0
            elif msg == WM_DWMSENDICONICTHUMBNAIL:     # the taskbar preview: the app draws it (later)
                sink.append(("thumb", h, ((lparam >> 16) & 0xFFFF, lparam & 0xFFFF)))
                return 0
            elif msg == WM_NCDESTROY:
                comctl32.RemoveWindowSubclass(h, proc, uid)
                _syscmd_hooks.pop(h, None)
        except Exception:
            pass
        return comctl32.DefSubclassProc(h, msg, wparam, lparam)

    if comctl32.SetWindowSubclass(hwnd, proc, 2, 0):
        _syscmd_hooks[hwnd] = proc          # keep the callback alive while the window lives
        _keep_gc_out_of_procs()
