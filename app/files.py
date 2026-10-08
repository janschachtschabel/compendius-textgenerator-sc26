"""Files the service writes whole: a reader never sees half of one."""

from __future__ import annotations

import os
import time
from pathlib import Path

_REPLACE_ATTEMPTS = 5  # Windows refuses to replace a file another process has open for a moment


def atomic_write_text(target: Path, text: str) -> Path:
    """Write ``text`` to a temporary file next to ``target`` and move it into place atomically."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, target)
            break
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    return target
