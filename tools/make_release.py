"""Build the release zip: dist\\StickyNote.zip, the file a GitHub Release carries.

    .\\StickyNote\\runtime\\python.exe tools\\make_release.py

It zips StickyNote\\ (app, runtime, licenses, install.cmd, readme.txt; no __pycache__) under a
top folder StickyNote\\, and prints the tag to use (v + app\\version.py's VERSION) and the
zip's SHA-256. The installed apps find it through Settings → General → Update.
"""
from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "StickyNote" / "app"))
import install  # noqa: E402  (read_version: one reader of version.py for the installer, updater and this)

PARTS = ("app", "runtime", "licenses", "install.cmd", "readme.txt")     # (not preview.py: a developer's tool)


def build(root: Path, out: Path) -> tuple[str, str]:
    """Zip ``root``\\StickyNote into ``out``; returns (tag, sha256 hex)."""
    src = Path(root) / "StickyNote"
    missing = [part for part in PARTS if not (src / part).exists()]
    if missing:
        raise SystemExit(f"missing in {src}: {', '.join(missing)}")
    version = install.version_of(src)
    if not version:
        raise SystemExit(f"no VERSION in {src / 'app' / 'version.py'}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for name in PARTS:
                path = src / name
                files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
                for f in files:
                    rel = f.relative_to(src)
                    if "__pycache__" not in rel.parts:
                        z.write(f, "StickyNote/" + rel.as_posix())
        os.replace(part, out)
    finally:
        if part.exists():
            part.unlink()
    h = hashlib.sha256()
    with open(out, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return f"v{version}", h.hexdigest()


def main() -> int:
    out = ROOT / "dist" / "StickyNote.zip"
    tag, sha = build(ROOT, out)
    print(f"dist\\StickyNote.zip  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"tag:     {tag}")
    print(f"sha256:  {sha}")
    print(f"Next: GitHub → Releases → Draft a new release → tag {tag}, write the notes, "
          "attach dist\\StickyNote.zip, Publish.")
    print('To test first: tick "Set as a pre-release", then run the installed app with '
          "STICKYNOTE_UPDATE_PRERELEASE=1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
