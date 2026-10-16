"""A worker hands the heap its start freed back to the system (audit 2026-10-16, C11)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import main, memory
from app.main import create_app
from tests.conftest import make_settings


class FakeLibc:
    def __init__(self) -> None:
        self.trims: list[int] = []

    def malloc_trim(self, pad: int) -> int:
        self.trims.append(pad)
        return 1


def test_the_freed_heap_goes_back_to_the_system(monkeypatch: pytest.MonkeyPatch) -> None:
    libc = FakeLibc()
    monkeypatch.setattr(memory, "_libc", lambda: libc)

    memory.give_back_freed_memory()

    assert libc.trims == [0]


def test_without_glibc_nothing_happens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows, macOS and musl have no malloc_trim."""

    def no_glibc() -> Any:
        raise OSError("libc.so.6: cannot open shared object file")

    monkeypatch.setattr(memory, "_libc", no_glibc)

    memory.give_back_freed_memory()


def test_the_start_gives_back_what_loading_the_models_freed(
    sample_zims: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured in the container, per worker at rest: 1,790 MB without, 1,413 MB with the trim after the start; a trim
    right after loading the Model2Vec model alone reached 1,525 MB."""
    order: list[str] = []

    def entities(settings: object) -> dict[str, Any]:
        order.append("models")
        return {"ner": False, "model": ""}

    monkeypatch.setattr(main, "describe_entities", entities)
    monkeypatch.setattr(main, "give_back_freed_memory", lambda: order.append("trim"))

    create_app(make_settings(sample_zims.values(), tmp_path / "state"))

    assert order == ["models", "trim"]
