"""Windows shortcuts (.lnk) and the user's Desktop / Start menu folders.

Uses the shell's own COM objects through ctypes, so it needs nothing outside
the standard library (no pywin32, no PowerShell).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

ole32 = ctypes.OleDLL("ole32")
shell32 = ctypes.OleDLL("shell32")
ole32.CoTaskMemFree.restype = None
ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
ole32.CoInitializeEx.restype = ctypes.c_long        # S_FALSE / RPC_E_CHANGED_MODE are fine too
ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        ole32.CLSIDFromString(text, ctypes.byref(self))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT), ("reserved1", wintypes.WORD), ("reserved2", wintypes.WORD),
                ("reserved3", wintypes.WORD), ("value", ctypes.c_void_p), ("value2", ctypes.c_void_p)]


CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
IID_SHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
APP_ID_KEY = ("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}", 5)   # System.AppUserModel.ID
FOLDERS = {"desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
           "programs": "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}"}   # Start menu > Programs
CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2
VT_LPWSTR = 31
STGM_READ = 0
MAX_TEXT = 1024

# vtable slots (IUnknown takes 0-2)
QUERY_INTERFACE, RELEASE = 0, 2
GET_PATH, GET_DESCRIPTION, SET_DESCRIPTION = 3, 6, 7
GET_WORKDIR, SET_WORKDIR, GET_ARGUMENTS, SET_ARGUMENTS = 8, 9, 10, 11
GET_ICON, SET_ICON, SET_PATH = 16, 17, 20
FILE_LOAD, FILE_SAVE = 5, 6
STORE_GET, STORE_SET, STORE_COMMIT = 5, 6, 7


def _call(obj, slot, *args, argtypes=(), restype=ctypes.HRESULT):
    """Call method number ``slot`` of COM object ``obj`` (HRESULT errors raise OSError)."""
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[slot])
    return method(obj, *args)


def _release(obj) -> None:
    if obj:
        _call(obj, RELEASE, restype=ctypes.c_ulong)


def _query(obj, iid: str) -> ctypes.c_void_p:
    out = ctypes.c_void_p()
    _call(obj, QUERY_INTERFACE, ctypes.byref(GUID(iid)), ctypes.byref(out),
          argtypes=(ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)))
    return out


def _new_link() -> ctypes.c_void_p:
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    link = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(GUID(CLSID_SHELL_LINK)), None, CLSCTX_INPROC_SERVER,
                           ctypes.byref(GUID(IID_SHELL_LINK_W)), ctypes.byref(link))
    return link


def _app_id_key() -> PROPERTYKEY:
    return PROPERTYKEY(GUID(APP_ID_KEY[0]), APP_ID_KEY[1])


def create(path, target, arguments: str = "", workdir="", icon="", app_id: str = "",
           description: str = "") -> None:
    """Write a shortcut at ``path`` that starts ``target`` with ``arguments``.

    ``app_id`` (System.AppUserModel.ID) ties the shortcut to windows that use
    the same id, so pinning the running app to the taskbar pins this shortcut.
    """
    text = (wintypes.LPCWSTR,)
    link = _new_link()
    store = persist = None
    try:
        _call(link, SET_PATH, str(target), argtypes=text)
        _call(link, SET_ARGUMENTS, arguments, argtypes=text)
        if workdir:
            _call(link, SET_WORKDIR, str(workdir), argtypes=text)
        if icon:
            _call(link, SET_ICON, str(icon), 0, argtypes=(wintypes.LPCWSTR, ctypes.c_int))
        if description:
            _call(link, SET_DESCRIPTION, description, argtypes=text)
        if app_id:
            store = _query(link, IID_PROPERTY_STORE)
            value = ctypes.create_unicode_buffer(app_id)
            variant = PROPVARIANT(vt=VT_LPWSTR, value=ctypes.cast(value, ctypes.c_void_p))
            _call(store, STORE_SET, ctypes.byref(_app_id_key()), ctypes.byref(variant),
                  argtypes=(ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)))
            _call(store, STORE_COMMIT)
        persist = _query(link, IID_PERSIST_FILE)
        _call(persist, FILE_SAVE, str(path), True, argtypes=(wintypes.LPCWSTR, wintypes.BOOL))
    finally:
        _release(store)
        _release(persist)
        _release(link)


def read(path) -> dict:
    """The fields of an existing shortcut (target, arguments, workdir, icon, app_id, description)."""
    link = _new_link()
    store = persist = None
    buf = ctypes.create_unicode_buffer(MAX_TEXT)
    text_out = (wintypes.LPWSTR, ctypes.c_int)

    def text(slot, *extra, argtypes=text_out):
        buf.value = ""
        _call(link, slot, buf, MAX_TEXT, *extra, argtypes=argtypes)
        return buf.value

    try:
        persist = _query(link, IID_PERSIST_FILE)
        _call(persist, FILE_LOAD, str(path), STGM_READ, argtypes=(wintypes.LPCWSTR, wintypes.DWORD))
        icon_index = ctypes.c_int()
        got = {
            "target": text(GET_PATH, None, 0, argtypes=text_out + (ctypes.c_void_p, wintypes.DWORD)),
            "arguments": text(GET_ARGUMENTS),
            "workdir": text(GET_WORKDIR),
            "icon": text(GET_ICON, ctypes.byref(icon_index), argtypes=text_out + (ctypes.POINTER(ctypes.c_int),)),
            "description": text(GET_DESCRIPTION),
        }
        store = _query(link, IID_PROPERTY_STORE)
        variant = PROPVARIANT()
        _call(store, STORE_GET, ctypes.byref(_app_id_key()), ctypes.byref(variant),
              argtypes=(ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)))
        got["app_id"] = ctypes.wstring_at(variant.value) if variant.vt == VT_LPWSTR and variant.value else ""
        ole32.PropVariantClear(ctypes.byref(variant))
        return got
    finally:
        _release(store)
        _release(persist)
        _release(link)


def known_folder(name: str) -> Path:
    """The user's real "desktop" or Start menu "programs" folder (also when moved to OneDrive)."""
    out = ctypes.c_void_p()
    shell32.SHGetKnownFolderPath(ctypes.byref(GUID(FOLDERS[name])), 0, None, ctypes.byref(out))
    try:
        return Path(ctypes.wstring_at(out.value))
    finally:
        ole32.CoTaskMemFree(out)
