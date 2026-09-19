"""Job runner: interval parsing and the periodic loop with a trigger file."""

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from app.jobs.runner import parse_interval, run_periodically


def test_parse_interval() -> None:
    assert parse_interval("30d") == timedelta(days=30)
    assert parse_interval("12h") == timedelta(hours=12)
    assert parse_interval("45m") == timedelta(minutes=45)
    assert parse_interval("90s") == timedelta(seconds=90)
    assert parse_interval(" 7D ") == timedelta(days=7)
    for bad in ("", "7", "7w", "-1d", "abc"):
        with pytest.raises(ValueError):
            parse_interval(bad)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_loop_runs_immediately_then_every_interval() -> None:
    clock = FakeClock()
    stop = threading.Event()
    runs: list[float] = []

    def task() -> None:
        runs.append(clock.now)
        if len(runs) == 3:
            stop.set()

    run_periodically(task, timedelta(seconds=100), poll_s=10, stop=stop, clock=clock, sleep=clock.sleep)
    assert runs == [1000.0, 1100.0, 1200.0]


def test_trigger_file_runs_task_early_and_is_removed(tmp_path: Path) -> None:
    clock = FakeClock()
    stop = threading.Event()
    trigger = tmp_path / "sync.request"
    runs: list[float] = []

    def task() -> None:
        runs.append(clock.now)
        if len(runs) == 1:
            trigger.write_text("now", encoding="utf-8")
        if len(runs) == 2:
            stop.set()

    run_periodically(
        task, timedelta(seconds=1000), poll_s=10, trigger_file=trigger, stop=stop, clock=clock, sleep=clock.sleep
    )
    assert runs == [1000.0, 1010.0]
    assert not trigger.exists()


def test_failing_task_keeps_the_loop_alive() -> None:
    clock = FakeClock()
    stop = threading.Event()
    calls: list[int] = []

    def task() -> None:
        calls.append(1)
        if len(calls) == 2:
            stop.set()
        raise RuntimeError("boom")

    run_periodically(task, timedelta(seconds=50), poll_s=10, stop=stop, clock=clock, sleep=clock.sleep)
    assert len(calls) == 2


def test_a_failed_task_is_retried_before_the_next_interval() -> None:
    clock = FakeClock()
    stop = threading.Event()
    runs: list[float] = []

    def task() -> None:
        runs.append(clock.now)
        if len(runs) == 3:
            stop.set()
        if len(runs) == 1:
            raise OSError(28, "No space left on device")

    run_periodically(
        task,
        timedelta(seconds=1000),
        retry_after=timedelta(seconds=30),
        poll_s=10,
        stop=stop,
        clock=clock,
        sleep=clock.sleep,
    )
    assert runs == [1000.0, 1030.0, 2030.0]  # soon after the failure, then the interval again


def test_a_task_that_asks_for_an_early_retry_gets_it() -> None:
    clock = FakeClock()
    stop = threading.Event()
    runs: list[float] = []

    def task() -> bool:
        runs.append(clock.now)
        if len(runs) == 3:
            stop.set()
        return len(runs) != 1  # the first run kept a .part file that the next one can resume

    run_periodically(
        task,
        timedelta(seconds=1000),
        retry_after=timedelta(seconds=30),
        poll_s=10,
        stop=stop,
        clock=clock,
        sleep=clock.sleep,
    )
    assert runs == [1000.0, 1030.0, 2030.0]
