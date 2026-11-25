"""Start Sticky Note.

Notes are stored in %APPDATA%\\StickyNote (notes.json + images\\).
Starting the app a second time just brings the running one to the front.
"""
import os
import sys
from pathlib import Path

import winapi

APP_ID = "KMH.StickyNote"
MUTEX_NAME = "KMH_StickyNote_SingleInstance"


def data_folder() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "StickyNote"


def main() -> None:
    folder = data_folder()
    signal = folder / "show.signal"
    instance = winapi.acquire_single_instance(MUTEX_NAME)
    if instance is None:                       # already running: ask it to come forward
        folder.mkdir(parents=True, exist_ok=True)
        signal.touch()
        return

    winapi.set_dpi_aware()
    winapi.set_app_id(APP_ID)
    from app import App                        # import after DPI setup
    app = App(folder, signal_file=signal)
    app.root.mainloop()
    del instance


if __name__ == "__main__":
    sys.exit(main())
