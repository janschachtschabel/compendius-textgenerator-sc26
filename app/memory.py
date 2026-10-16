"""The heap a process freed, handed back to the system (audit 2026-10-16, C11).

Loading the models - the Model2Vec model (model2vec 0.10 copies its tokenizer and parses the vocabulary), spaCy - frees
a lot of memory that glibc keeps in the process. Measured in the container, per worker at rest: 1,790 MB without,
1,525 MB with ``malloc_trim(0)`` right after the Model2Vec model, 1,413 MB with it once the start is done.
"""

from __future__ import annotations

import ctypes
from typing import Any


def _libc() -> Any:
    return ctypes.CDLL("libc.so.6")


def give_back_freed_memory() -> None:
    """``malloc_trim(0)``; without glibc - Windows, macOS, musl - nothing to do."""
    try:
        _libc().malloc_trim(0)
    except (OSError, AttributeError):
        return
