"""A template is stored whole or not at all, and two saves never count to the same version (audit 2026-09-29, A07).

Several uvicorn workers and the CLI read one directory. save wrote the file in place: opening it cut it to nothing,
so a worker that read it meanwhile skipped it and answered 404, and a save that failed on the way left it empty. Two
saves at once both read version 1 and both wrote 2, and one of them was lost without a word.

The tests hold a save in the middle of writing the template's text, with its file already open: a stand-in for
another process that reads, or for a write that fails, at exactly that moment.
"""

from __future__ import annotations

import builtins
import errno
import io
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.locks import LockHeldError
from app.templates import manager as manager_module
from app.templates.manager import Expected, TemplateManager, TemplateNotFoundError, VersionConflictError
from app.templates.schema import Template, TemplateSlot

WhileWriting = Callable[[str, Callable[[], None]], None]


def template(name: str) -> Template:
    return Template(id="mein", name=name, slots=[TemplateSlot(id="a", slot="praxis", title="Praxis")])


def read(manager: TemplateManager) -> str:
    try:
        return manager.get("mein").name
    except TemplateNotFoundError:
        return "(fehlt)"


class _Held:
    """A file whose write of text holding ``marker`` runs ``hook`` first."""

    def __init__(self, handle: Any, marker: str, hook: Callable[[], None]) -> None:
        self._handle, self._marker, self._hook = handle, marker, hook

    def write(self, data: Any) -> Any:
        if isinstance(data, str) and self._marker in data:
            self._hook()
        return self._handle.write(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def __enter__(self) -> _Held:
        return self

    def __exit__(self, *exc: object) -> Any:
        return self._handle.__exit__(*exc)


@pytest.fixture
def while_writing(monkeypatch: pytest.MonkeyPatch) -> WhileWriting:
    """``arm(marker, hook)``: every file opened for writing from now on runs ``hook`` before it takes text holding
    ``marker``, in whichever thread writes it."""

    def arm(marker: str, hook: Callable[[], None]) -> None:
        real_open = io.open

        def opening(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            handle = real_open(file, mode, *args, **kwargs)
            return _Held(handle, marker, hook) if "w" in mode or "x" in mode else handle

        monkeypatch.setattr(io, "open", opening)
        monkeypatch.setattr(builtins, "open", opening)

    return arm


def test_another_worker_reading_during_a_save_sees_the_old_version(tmp_path: Path, while_writing: WhileWriting) -> None:
    TemplateManager(custom_dir=tmp_path).save(template("Alt"))
    other = TemplateManager(custom_dir=tmp_path)  # another worker, with a cache of its own
    seen: list[str] = []
    while_writing('"name": "Neu"', lambda: seen.append(read(other)))

    TemplateManager(custom_dir=tmp_path).save(template("Neu"))

    assert seen == ["Alt"]
    assert read(other) == "Neu"


def test_a_save_that_fails_midway_leaves_the_old_version(tmp_path: Path, while_writing: WhileWriting) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    manager.save(template("Alt"))

    def disk_full() -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    while_writing('"name": "Neu"', disk_full)
    with pytest.raises(OSError, match="No space"):
        manager.save(template("Neu"))

    assert read(TemplateManager(custom_dir=tmp_path)) == "Alt"
    assert [path.name for path in tmp_path.iterdir()] == ["mein.json"], "no half file and no lock stay behind"


def test_two_saves_at_once_count_to_different_versions(tmp_path: Path, while_writing: WhileWriting) -> None:
    TemplateManager(custom_dir=tmp_path).save(template("Start"))  # version 1
    first, second = TemplateManager(custom_dir=tmp_path), TemplateManager(custom_dir=tmp_path)  # two workers
    paused, resume = threading.Event(), threading.Event()

    def hold() -> None:
        paused.set()
        resume.wait(10)

    while_writing('"name": "Eins"', hold)
    versions: dict[str, int] = {}
    one = threading.Thread(target=lambda: versions.update(Eins=first.save(template("Eins")).version))
    two = threading.Thread(target=lambda: versions.update(Zwei=second.save(template("Zwei")).version))
    one.start()
    assert paused.wait(10), "the first save reached its write"
    two.start()
    two.join(0.5)  # unguarded, the second save runs through while the first one is held
    resume.set()
    one.join(10)
    two.join(10)

    assert sorted(versions.values()) == [2, 3]
    last = max(versions, key=versions.__getitem__)
    stored = TemplateManager(custom_dir=tmp_path).get("mein")
    assert (stored.name, stored.version) == (last, 3)


def test_two_saves_over_the_same_version_at_once_store_one(tmp_path: Path, while_writing: WhileWriting) -> None:
    """If-Match (F09) is compared under the lock of the write: two editors who read version 1 and save at once, the
    second while the first one writes, store one edit and refuse the other (review of 2026-10-08)."""
    TemplateManager(custom_dir=tmp_path).save(template("Start"))  # version 1
    first, second = TemplateManager(custom_dir=tmp_path), TemplateManager(custom_dir=tmp_path)
    paused, resume = threading.Event(), threading.Event()

    def hold() -> None:
        paused.set()
        resume.wait(10)

    while_writing('"name": "Eins"', hold)
    outcome: dict[str, object] = {}

    def save(manager: TemplateManager, name: str) -> None:
        try:
            outcome[name] = manager.save(template(name), Expected(versions=frozenset({1}))).version
        except VersionConflictError as exc:
            outcome[name] = exc

    one = threading.Thread(target=save, args=(first, "Eins"))
    two = threading.Thread(target=save, args=(second, "Zwei"))
    one.start()
    assert paused.wait(10), "the first save reached its write"
    two.start()
    two.join(0.5)
    resume.set()
    one.join(10)
    two.join(10)

    assert outcome["Eins"] == 2 and isinstance(outcome["Zwei"], VersionConflictError)
    assert TemplateManager(custom_dir=tmp_path).get("mein").name == "Eins"


def test_another_worker_notices_a_save_within_the_same_clock_tick(tmp_path: Path) -> None:
    TemplateManager(custom_dir=tmp_path).save(template("Alt"))
    other = TemplateManager(custom_dir=tmp_path)
    assert read(other) == "Alt"  # now cached
    path = tmp_path / "mein.json"
    before = path.stat()

    TemplateManager(custom_dir=tmp_path).save(template("Neu"))  # the same size: one name for another, 1 for 2
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # as a clock coarser than two saves leaves it

    assert path.stat().st_size == before.st_size
    assert read(other) == "Neu"


def test_a_stale_lock_of_a_save_that_died_is_taken_over(tmp_path: Path) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    manager.save(template("Alt"))
    lock = tmp_path / ".templates.lock"
    lock.write_text("pid 1\n", encoding="utf-8")
    os.utime(lock, (0, 0))  # left behind long ago

    assert manager.save(template("Neu")).version == 2
    assert not lock.exists()


def test_a_save_that_cannot_get_the_lock_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    manager.save(template("Alt"))
    (tmp_path / ".templates.lock").write_text("pid 1\n", encoding="utf-8")  # a save of another process, still running
    monkeypatch.setattr(manager_module, "LOCK_WAIT_S", 0.05)

    with pytest.raises(LockHeldError):
        manager.save(template("Neu"))
    assert read(TemplateManager(custom_dir=tmp_path)) == "Alt"


def test_a_template_another_process_deleted_meanwhile_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    manager.save(template("Alt"))
    original = Path.unlink

    def deleted_just_before(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == "mein.json":
            original(self)  # another process, a moment earlier
        original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deleted_just_before)
    assert manager.delete("mein") is False
