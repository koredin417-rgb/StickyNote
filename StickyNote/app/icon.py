"""App icon: ``app_icon.png`` next to this file (a yellow sticky note with a curled corner),
shrunk to the size asked for. Without that file, a plain note is drawn in code instead.

Run ``runtime\\python.exe icon.py`` to (re)write ``app.ico`` (every size Windows asks for).
"""
from pathlib import Path

from PIL import Image, ImageDraw

ICON_PNG = Path(__file__).with_name("app_icon.png")
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
_master = None


def _drawn(size: int) -> Image.Image:
    """The plain note, drawn in code (when app_icon.png is missing)."""
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fold = 64 * s
    left, top, right, bottom = 28 * s, 28 * s, 228 * s, 228 * s
    body = [(left, top), (right, top), (right, bottom - fold), (right - fold, bottom), (left, bottom)]
    d.polygon(body, fill=(255, 230, 110, 255), outline=(150, 128, 40, 255), width=max(1, round(6 * s)))
    d.polygon([(right, bottom - fold), (right - fold, bottom - fold), (right - fold, bottom)],
              fill=(230, 196, 70, 255), outline=(150, 128, 40, 255), width=max(1, round(6 * s)))
    for i, length in enumerate((140, 120, 90)):
        y = (84 + i * 36) * s
        d.line([(60 * s, y), ((60 + length) * s, y)], fill=(120, 104, 40, 255), width=max(1, round(10 * s)))
    return img


def draw_icon(size: int = 256) -> Image.Image:
    """The app icon, ``size`` px square (RGBA)."""
    global _master
    if _master is None:
        try:
            _master = Image.open(ICON_PNG).convert("RGBA")
        except OSError:
            _master = False
    if _master is False:
        return _drawn(size)
    return _master.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    frames = [draw_icon(n) for n in ICO_SIZES]
    for name in ("app.ico", "sticky_note.ico"):     # (sticky_note.ico: the shortcuts', install.py LINK_ICON)
        out = Path(__file__).with_name(name)
        frames[-1].save(out, format="ICO", sizes=[(n, n) for n in ICO_SIZES], append_images=frames[:-1])
        print("wrote", out)
