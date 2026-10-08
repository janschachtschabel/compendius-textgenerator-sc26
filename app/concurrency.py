"""Threads that keep the context of the request that started them (audit 2026-09-27, TE-03).

A ``ThreadPoolExecutor`` runs its tasks in the context of its own threads, not the caller's: the log lines of LLM calls
made in parallel named no request ("-") and could not be found by the X-Request-ID a caller quotes, and the route that
labels the LLM metrics was lost the same way. Every task here runs in a copy of the caller's context.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from types import TracebackType


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
    and the job's result is dropped. Jobs not yet started are cancelled.
    """

    def __init__(self, workers: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="beside")

    def start[**P, R](self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> Future[R]:
        """``fn(*args, **kwargs)`` in a thread of its own; its result or error through the future."""
        context = contextvars.copy_context()
        return self._pool.submit(lambda: context.run(fn, *args, **kwargs))

    def __enter__(self) -> Beside:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
