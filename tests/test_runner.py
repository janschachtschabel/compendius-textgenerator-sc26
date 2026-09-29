"""Job runner: interval parsing and the periodic loop with a trigger file."""

import signal
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from app.jobs.runner import parse_interval, run_periodically, stop_on_sigterm


def test_parse_interval() -> None:
    assert parse_interval("30d") == timedelta(days=30)
    assert parse_interval("12h") == timedelta(hours=12)
    assert parse_interval("45m") == timedelta(minutes=45)
    assert parse_interval("90s") == timedelta(seconds=90)
    assert parse_interval(" 7D ") == timedelta(days=7)
    for bad in ("", "7", "7w", "-1d", "abc"):
        with pytest.raises(ValueError):
            parse_interval(bad)


def test_an_interval_under_a_minute_is_refused_with_the_minimum() -> None:
    """An interval of 0 ran a loop without a pause - 1000 runs in 0.0 s, and the GND sidecar asked data.dnb.de three
    times a run (audit 2026-09-29, Q4)."""
    for short in ("0s", "0d", "00h", " 0 m ", "59s"):
        with pytest.raises(ValueError, match="at least 1m"):
            parse_interval(short)
    assert parse_interval("60s") == parse_interval("1m") == timedelta(minutes=1)


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


def test_a_task_that_names_its_next_run_gets_it_before_the_interval() -> None:
    """A sync that retired an archive runs again when its retention ends, not after ZIM_SYNC_INTERVAL (audit
    2026-09-28, BE-12); a wait longer than the interval changes nothing."""
    clock = FakeClock()
    stop = threading.Event()
    runs: list[float] = []

    def task() -> timedelta | None:
        runs.append(clock.now)
        if len(runs) == 3:
            stop.set()
        return {1: timedelta(seconds=240), 2: timedelta(seconds=5000)}.get(len(runs))

    run_periodically(task, timedelta(seconds=1000), poll_s=10, stop=stop, clock=clock, sleep=clock.sleep)
    assert runs == [1000.0, 1240.0, 2240.0]


def test_a_container_stop_reaches_the_job_as_a_keyboard_interrupt() -> None:
    # docker stop sends SIGTERM to PID 1 and kills it ten seconds later; as KeyboardInterrupt the running job still
    # writes its final status and releases its lock
    previous = signal.getsignal(signal.SIGTERM)
    try:
        stop_on_sigterm()
        assert signal.getsignal(signal.SIGTERM) is signal.default_int_handler
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_a_waiting_loop_signs_life_at_its_start_and_every_hour() -> None:
    """BE-15 (audit 2026-09-28): the ZIM loop checks every 30 days and the curriculum loop every seven, and a check
    without a pull wrote nothing, so a stopped sidecar showed after weeks. The loop signs life while it waits."""
    clock = FakeClock()
    stop = threading.Event()
    signs: list[float] = []

    def alive() -> None:
        signs.append(clock.now)
        if len(signs) == 4:
            stop.set()

    run_periodically(
        lambda: None, timedelta(days=30), poll_s=600, stop=stop, clock=clock, sleep=clock.sleep, alive=alive
    )

    assert signs == [1000.0, 4600.0, 8200.0, 11800.0]


def test_a_sign_of_life_that_cannot_be_written_stops_nothing() -> None:
    clock = FakeClock()
    stop = threading.Event()
    runs: list[float] = []

    def alive() -> None:
        raise OSError("volume full")

    def task() -> None:
        runs.append(clock.now)
        if len(runs) == 2:
            stop.set()

    run_periodically(task, timedelta(hours=2), poll_s=600, stop=stop, clock=clock, sleep=clock.sleep, alive=alive)

    assert runs == [1000.0, 8200.0]
