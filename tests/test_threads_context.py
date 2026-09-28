"""Threads of the service keep the context of their request (audit 2026-09-27, TE-03).

A ThreadPoolExecutor runs its tasks in the context of its own threads: the log lines of LLM calls made in parallel
named no request ("-"), so an error could not be found by the X-Request-ID the caller quotes.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.concurrency import map_in_threads
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
