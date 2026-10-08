"""Threads of the service keep the context of their request (audit 2026-09-27, TE-03).

A ThreadPoolExecutor runs its tasks in the context of its own threads: the log lines of LLM calls made in parallel
named no request ("-"), so an error could not be found by the X-Request-ID the caller quotes.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from app.concurrency import Beside, map_in_threads
from app.llm.call import LlmSkipped, skipped_on_error
from app.logging import _RequestIdFilter, configure_logging, current_request_id, set_request_id


def in_a_request[T](request_id: str, work: Callable[[], T]) -> T:
    """``work`` in a context of its own, as a request of that id - the test's own context stays as it was."""

    def run() -> T:
        set_request_id(request_id)
        return work()

    return contextvars.copy_context().run(run)


def test_a_plain_pool_loses_the_request_id() -> None:
    """Why the helper exists: the threads of a pool start in a context of their own."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = in_a_request("rid-9", lambda: list(pool.map(lambda _: current_request_id(), range(3))))

    assert ids == ["-"] * 3


def test_the_threads_of_the_service_keep_the_request_id() -> None:
    ids = in_a_request("rid-9", lambda: map_in_threads(lambda _: current_request_id(), [1, 2, 3], workers=3))

    assert ids == ["rid-9"] * 3


def test_results_come_in_the_order_of_the_items() -> None:
    assert map_in_threads(lambda n: n * n, [3, 1, 2], workers=3) == [9, 1, 4]
    assert map_in_threads(lambda n: n, [], workers=3) == []


def test_a_job_beside_keeps_the_request_id() -> None:
    def started() -> str:
        with Beside(workers=1) as beside:
            return beside.start(current_request_id).result()

    assert in_a_request("rid-11", started) == "rid-11"


def test_leaving_does_not_wait_for_a_job_still_running() -> None:
    """Parts 2 and 3 run beside part 1; a request that fails in part 1 answers without waiting for them."""
    release = threading.Event()
    started = time.monotonic()

    with pytest.raises(LookupError), Beside(workers=1) as beside:
        beside.start(release.wait, 3.0)
        raise LookupError("Thema nicht gefunden")

    assert time.monotonic() - started < 1.0
    release.set()


def test_a_caller_that_fails_ends_the_time_of_its_jobs_and_one_that_succeeds_does_not() -> None:
    ended: list[str] = []

    with pytest.raises(LookupError), Beside(workers=1, on_failure=lambda: ended.append("failed")):
        raise LookupError("Thema nicht gefunden")
    with Beside(workers=1, on_failure=lambda: ended.append("succeeded")) as beside:
        beside.start(lambda: 1).result()

    assert ended == ["failed"]


def test_the_error_of_a_job_a_failed_caller_dropped_is_logged_with_its_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Review 2026-10-08: nobody read the result of a job left running, so its error was lost."""
    release = threading.Event()

    def failing() -> None:
        release.wait(3.0)
        raise RuntimeError("kaputt")

    def request() -> Future[None]:
        with pytest.raises(LookupError), Beside(workers=1) as beside:
            job = beside.start(failing)
            raise LookupError("Thema nicht gefunden")
        return job

    caplog.handler.addFilter(_RequestIdFilter())  # the field the service's own handler adds
    with caplog.at_level(logging.WARNING):
        in_a_request("rid-14", request)
        release.set()
        waited = time.monotonic()
        while not [r for r in caplog.records if "kaputt" in r.getMessage()] and time.monotonic() - waited < 3.0:
            time.sleep(0.01)  # the job logs from its own thread once it ends

    [record] = [record for record in caplog.records if "kaputt" in record.getMessage()]
    assert record.request_id == "rid-14"  # type: ignore[attr-defined]


def test_a_job_that_met_the_callers_kind_of_error_is_not_logged_as_another(caplog: pytest.LogCaptureFixture) -> None:
    """An unknown collection fails the preparation of the request and part 3, which reads the same collection beside
    it: every such 404 logged the job's not-found again as a dropped failure, with its traceback (review of
    2026-10-08)."""

    def not_found() -> None:
        raise LookupError("Sammlung nicht gefunden")

    with caplog.at_level(logging.WARNING), pytest.raises(LookupError), Beside(workers=1) as beside:
        beside.start(not_found).exception()  # the job has failed before the caller does
        raise LookupError("Sammlung nicht gefunden")

    assert not [record for record in caplog.records if "failed as well" in record.getMessage()]


def test_the_error_a_failed_caller_raised_itself_is_not_logged_twice(caplog: pytest.LogCaptureFixture) -> None:
    def failing() -> None:
        raise RuntimeError("kaputt")

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError), Beside(workers=1) as beside:
        beside.start(failing).result()

    assert not [record for record in caplog.records if "kaputt" in record.getMessage()]


def test_an_unexpected_error_is_a_fallback_and_a_log_line_that_names_the_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(item: int) -> str:
        raise RuntimeError("kaputt")

    caplog.handler.addFilter(_RequestIdFilter())  # the field the service's own handler adds
    with caplog.at_level(logging.ERROR):
        results = in_a_request(
            "rid-10", lambda: map_in_threads(skipped_on_error(boom, lambda item: f"Probe {item}"), [1], workers=1)
        )

    assert results == [LlmSkipped("unerwarteter Fehler (RuntimeError)")]
    [record] = [record for record in caplog.records if "failed unexpectedly" in record.getMessage()]
    assert record.getMessage() == "Probe 1 failed unexpectedly"
    assert record.request_id == "rid-10"  # type: ignore[attr-defined]


def test_the_services_log_line_names_the_request_of_a_worker_thread(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """TE-13 (audit 2026-09-28): under pytest the root logger has handlers already, so configure_logging never set
    the service's format and its request-id filter here. Without the filter every line in production became
    "--- Logging error ---", and suite and smoke probe stayed green."""
    root, httpx_logger = logging.getLogger(), logging.getLogger("httpx")
    levels = root.level, httpx_logger.level
    monkeypatch.setattr(root, "handlers", [])  # as in production; the test's own handlers come back afterwards
    try:
        configure_logging("INFO")
        in_a_request(
            "rid-13",
            lambda: map_in_threads(lambda item: logging.getLogger("app.probe").info("Probe %s", item), [1], workers=1),
        )
    finally:
        root.setLevel(levels[0])
        httpx_logger.setLevel(levels[1])

    [line] = [line for line in capsys.readouterr().out.splitlines() if "Probe 1" in line]
    assert line.split(" | ")[1:] == ["INFO    ", "app.probe", "rid-13", "Probe 1"]
