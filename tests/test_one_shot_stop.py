"""A run of an updater without --loop, as a CronJob of the Helm chart starts it (D116), stops on SIGTERM as the loop
does: it is PID 1 there, the kernel drops a signal without a handler for PID 1, and the run kept its lock until the pod
was killed (review of 2026-11-04)."""

from __future__ import annotations

import signal
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.cli_sync import run_sync


@pytest.fixture(autouse=True)
def keep_the_handler() -> Iterator[None]:
    before = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, before)


def test_a_run_once_takes_sigterm_as_an_interrupt_and_ends_with_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[object] = []

    def task() -> None:
        seen.append(signal.getsignal(signal.SIGTERM))
        raise KeyboardInterrupt  # what SIGTERM raises with the handler

    code = run_sync(task, loop=False, interval="1d", name="GND-Index", alive=tmp_path / "alive")

    assert seen == [signal.default_int_handler]
    assert code == 1
    assert "GND-Index abgebrochen" in capsys.readouterr().err
