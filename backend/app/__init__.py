"""PhotoSorter2Claude - semi-automatic photo sorter."""

import os
from pathlib import Path


def _read_version() -> str:
    env = os.environ.get("PHOTOSORTER_VERSION_OVERRIDE")
    if env:
        return env
    for candidate in (Path(__file__).resolve().parent / "VERSION", Path(__file__).resolve().parents[2] / "VERSION"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return "0.0.0-dev"


__version__ = _read_version()
