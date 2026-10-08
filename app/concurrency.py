"""Threads that keep the context of the request that started them (audit 2026-09-27, TE-03).

A ``ThreadPoolExecutor`` runs its tasks in the context of its own threads, not the caller's: the log lines of LLM calls
made in parallel named no request ("-") and could not be found by the X-Request-ID a caller quotes, and the route that
labels the LLM metrics was lost the same way. Every task here runs in a copy of the caller's context.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from types import TracebackType
from typing import Any

log = logging.getLogger(__name__)


def map_in_threads[T, R](fn: Callable[[T], R], items: Sequence[T], workers: int) -> list[R]:
    """``fn`` over ``items`` in at most ``workers`` threads; the results in the order of ``items``."""
    if not items:
        return []
    # One copy per task: a context can be entered by one thread at a time
    contexts = [contextvars.copy_context() for _ in items]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as pool:
        return list(pool.map(lambda context, item: context.run(fn, item), contexts, items))


class Beside:
    """Jobs that run beside the caller's own work, each in a copy of the caller's context.

    Leaving the block does not wait for a job still running: a request that fails in its own work answers at once,
    and the job's result is dropped. Jobs not yet started are cancelled; ``on_failure`` tells the others, such as by
    ending the time they run on, and an error of theirs that nobody reads goes to the log (review 2026-10-08).
    """

    def __init__(self, workers: int, on_failure: Callable[[], None] | None = None) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="beside")
        self._on_failure = on_failure
        self._jobs: list[tuple[Future[Any], contextvars.Context]] = []

    def start[**P, R](self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> Future[R]:
        """``fn(*args, **kwargs)`` in a thread of its own; its result or error through the future."""
        context = contextvars.copy_context()
        job = self._pool.submit(lambda: context.run(fn, *args, **kwargs))
        self._jobs.append((job, context))
        return job

    def __enter__(self) -> Beside:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        if error is None:
            return
        if self._on_failure is not None:
            self._on_failure()
        for job, context in self._jobs:
            job.add_done_callback(partial(_log_dropped, context, error))


def _log_dropped(context: contextvars.Context, error: BaseException, job: Future[Any]) -> None:
    """The error of a job its failed caller dropped, logged in the job's context so the line names its request; the
    caller's own error, raised from a job, it logs itself, and an error of the same kind the job met where the caller
    did: an unknown collection fails the preparation and part 3, which reads it beside (review of 2026-10-08)."""
    failure = None if job.cancelled() else job.exception()
    if failure is not None and failure is not error and type(failure) is not type(error):
        context.run(log.warning, "a job beside a failed request failed as well: %r", failure, exc_info=failure)
