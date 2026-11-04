"""Shared test helpers.

Temporary directories are created inside the repository (``tests/.tmp``) with a
plain ``mkdir`` instead of :func:`tempfile.mkdtemp`: the latter requests mode
``0o700``, and on locked-down Windows setups that mode can produce a directory
the current user is no longer allowed to write into.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def make_temp_dir(prefix: str = "case-") -> Path:
    """Create a throw-away directory under ``tests/.tmp``."""
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    for _attempt in range(100):
        candidate = TEMP_ROOT / f"{prefix}{uuid.uuid4().hex[:10]}"
        try:
            candidate.mkdir()
        except FileExistsError:  # pragma: no cover - astronomically unlikely
            continue
        return candidate
    raise RuntimeError("could not create a temporary directory")  # pragma: no cover


def remove_temp_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
