"""Publish a GitHub Release of the current main: the zip the installed apps update from.

    .\\StickyNote\\runtime\\python.exe tools\\release.py            (checks, then publishes)
    .\\StickyNote\\runtime\\python.exe tools\\release.py --dry-run  (checks and builds only)
    .\\StickyNote\\runtime\\python.exe tools\\release.py --title "Typing fixes"  (v1.2.3 — Typing fixes)

In this order, stopping at the first problem:
  1. On main, nothing uncommitted, level with origin/main (the zip is made from what is pushed).
  2. app/version.py's VERSION is new: no tag v<VERSION> yet, and CHANGELOG.md has its section.
  3. dist\\StickyNote.zip built (make_release) and checked with the updater's own unpack as that
     version (a zip whose VERSION is not its tag's is refused by the apps: v1.2.1 was).
  4. Tag v<VERSION> on HEAD, pushed; the release made with gh, the CHANGELOG section as its notes,
     the zip as its one asset (named exactly StickyNote.zip).
  5. The published asset's sha256 (GitHub's digest) compared with the local zip's.

Needs the GitHub CLI signed in (gh auth login); not on PATH yet it is found where it installs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "StickyNote" / "app"))
sys.path.insert(0, str(ROOT / "tools"))
import install  # noqa: E402
import make_release  # noqa: E402
import updater  # noqa: E402

REPO = "koredin417-rgb/StickyNote"
ZIP = ROOT / "dist" / "StickyNote.zip"
TITLE = ""


def gh_path() -> str:
    found = shutil.which("gh")
    if found:
        return found
    for p in (Path(r"C:\Program Files\GitHub CLI\gh.exe"), Path.home() / r"AppData\Local\Programs\GitHub CLI\gh.exe"):
        if p.is_file():
            return str(p)
    raise SystemExit("GitHub CLI not found: winget install --id GitHub.cli, then gh auth login")


def run(*args, capture=True) -> str:
    r = subprocess.run(args, cwd=ROOT, capture_output=capture, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"failed: {' '.join(map(str, args))}\n{(r.stderr or r.stdout or '').strip()}")
    return (r.stdout or "").strip()


def notes_for(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    head = f"## {version}"
    if head not in text:
        raise SystemExit(f"CHANGELOG.md has no '{head}' section")
    part = text.split(head, 1)[1]
    body = head + part.split("\n## ", 1)[0]
    return body.rstrip() + ("\n\n**Install / update:** installed apps offer this under Settings → General → "
                            "Update. For a new install, download StickyNote.zip, unzip it, and run install.cmd.\n")


def main() -> int:
    global TITLE
    dry = "--dry-run" in sys.argv
    TITLE = sys.argv[sys.argv.index("--title") + 1] if "--title" in sys.argv[:-1] else ""
    gh = gh_path()
    # 1. what is pushed, exactly
    if run("git", "rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise SystemExit("not on main: switch to main (git switch main; git pull) first")
    if run("git", "status", "--porcelain"):
        raise SystemExit("uncommitted changes: commit or stash them first")
    run("git", "fetch", "-q", "origin")
    if run("git", "rev-parse", "HEAD") != run("git", "rev-parse", "origin/main"):
        raise SystemExit("main is not level with origin/main: pull (or push) first")
    # 2. a new version, with notes
    version = install.version_of(ROOT / "StickyNote")
    tag = f"v{version}"
    if run("git", "tag", "--list", tag) or run("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"):
        raise SystemExit(f"{tag} exists already: raise VERSION in StickyNote/app/version.py")
    notes = notes_for(version)
    # 3. the zip, checked as the apps will
    built_tag, sha = make_release.build(ROOT, ZIP)
    assert built_tag == tag, (built_tag, tag)
    with tempfile.TemporaryDirectory() as d:
        updater._unpack(ZIP, Path(d), version)
    print(f"{tag}: dist\\StickyNote.zip {ZIP.stat().st_size / 1e6:.1f} MB, sha256 {sha}, unpacks as {version}")
    if dry:
        print("--dry-run: nothing tagged or published")
        return 0
    # 4. tag and release
    title = f"{tag} — {TITLE}" if TITLE else tag
    run("git", "tag", "-a", tag, "-m", title)
    run("git", "push", "origin", tag)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(notes + f"\nSHA-256 of StickyNote.zip: {sha}\n")
        notes_file = f.name
    run(gh, "release", "create", tag, str(ZIP), "--repo", REPO, "--title", title, "--notes-file", notes_file,
        "--latest", "--verify-tag")
    Path(notes_file).unlink(missing_ok=True)
    # 5. what went up is what was built
    info = json.loads(run(gh, "release", "view", tag, "--repo", REPO, "--json", "assets,url,isDraft,isPrerelease"))
    asset = next((a for a in info["assets"] if a["name"] == "StickyNote.zip"), None)
    digest = (asset or {}).get("digest") or ""
    if asset is None or (digest and digest != f"sha256:{sha}"):
        raise SystemExit(f"published asset does not match the local zip: {asset}")
    print(f"published {info['url']} (asset sha256 {'matches' if digest else 'not reported yet'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
