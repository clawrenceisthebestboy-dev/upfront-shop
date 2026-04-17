"""Resource-path helper.

Returns the filesystem path to a bundled resource file, whether the app
is running from source (``python main.py`` from the repo root) or from a
PyInstaller --onedir build.

Usage:
    from app.resources import resource_path
    icon = QIcon(str(resource_path('upfront_logo.png')))
"""
from __future__ import annotations
import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Where our bundled data lives at runtime."""
    # PyInstaller sets sys._MEIPASS for onefile/onedir builds.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # Source tree: this file is app/resources.py; repo root is two parents up.
    return Path(__file__).resolve().parent.parent


def resource_path(name: str) -> Path:
    """Return the absolute path to a file under ``resources/``.

    Falls back to the source-tree location if the bundled copy is missing,
    so the app still renders an icon-less-but-functional window instead of
    crashing when a build forgets to ship resources/.
    """
    root = _bundle_root()
    p = root / "resources" / name
    if p.is_file():
        return p
    # Dev-from-anywhere fallback: relative to the source tree.
    alt = Path(__file__).resolve().parent.parent / "resources" / name
    return alt
