"""Self-update from GitHub Releases: Settings → General → Update.

Nothing here runs on its own: a check starts only from the Update page's button, and a
download only from its "Update now". The release logic below is pure; the Updater does the
network work on a thread and the Tk loop reads its results (see Updater.pump).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

REPO = "koredin417-rgb/StickyNote"
ASSET = "StickyNote.zip"
PRERELEASE_ENV = "STICKYNOTE_UPDATE_PRERELEASE"     # "1": pre-releases too (testing a release first)

_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class Release:
    version: str            # without the "v"
    tag: str
    notes: str              # plain text (plain_notes)
    url: str                # the zip's download address
    size: int
    sha256: str | None      # hex, when GitHub gives the asset's digest


def parse_version(text: str) -> tuple[int, ...] | None:
    """"v1.2.0" -> (1, 2, 0); anything else (a "-beta", a word) -> None."""
    m = _VERSION_RE.fullmatch(text.strip()) if isinstance(text, str) else None
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def api_url(environ=os.environ) -> str:
    base = f"https://api.github.com/repos/{REPO}/releases"
    return base if environ.get(PRERELEASE_ENV) == "1" else base + "/latest"


def _release(item: dict) -> Release | None:
    """One release of the reply, or None when it can't be offered (a draft, an odd tag, no zip)."""
    if item.get("draft"):
        return None
    tag = item.get("tag_name")
    number = parse_version(tag) if isinstance(tag, str) else None
    if number is None:
        return None
    asset = next((a for a in item.get("assets") or () if isinstance(a, dict) and a.get("name") == ASSET), None)
    if asset is None or not isinstance(asset.get("size"), int) or not isinstance(asset.get("browser_download_url"), str):
        return None
    digest = asset.get("digest")
    sha = digest[len("sha256:"):].lower() if isinstance(digest, str) and digest.startswith("sha256:") else None
    body = item.get("body")
    return Release(version=".".join(map(str, number)), tag=tag, notes=plain_notes(body if isinstance(body, str) else ""),
                   url=asset["browser_download_url"], size=asset["size"], sha256=sha)


def pick_release(reply, current: str) -> Release | None:
    """The newest release in ``reply`` (one release, or a list of them) that is newer than
    ``current``, else None. A reply that isn't a release at all raises ValueError."""
    if isinstance(reply, dict):
        if "tag_name" not in reply:
            raise ValueError("not a release")
        items = [reply]
    elif isinstance(reply, list):
        items = reply
    else:
        raise ValueError("not a release")
    now = parse_version(current) or (0,)
    best = None
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("not a release")
        r = _release(item)
        if r is not None and parse_version(r.version) > now and (
                best is None or parse_version(r.version) > parse_version(best.version)):
            best = r
    return best


def plain_notes(markdown: str) -> str:
    """Release notes as plain text: headings without their #s, "* "/"- " items as "• ",
    no ** or backticks."""
    lines = []
    for line in markdown.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^(\s*)[*-] ", r"\1• ", line)
        lines.append(line.replace("**", "").replace("`", "").rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
