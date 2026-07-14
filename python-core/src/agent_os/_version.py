from __future__ import annotations

from pathlib import Path


__version__ = Path(__file__).with_name("VERSION").read_text(encoding="ascii").strip()

if not __version__:
    raise RuntimeError("Beacon VERSION must not be empty.")
