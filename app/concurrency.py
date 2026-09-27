"""Threads that keep the context of the request that started them (audit 2026-09-27, TE-03).

A ``ThreadPoolExecutor`` runs its tasks in the context of its own threads, not the caller's: the log lines of LLM calls
made in parallel named no request ("-") and could not be found by the X-Request-ID a caller quotes, and the route that
labels the LLM metrics was lost the same way. Every task here runs in a copy of the caller's context.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor


def map_in_threads[T, R](fn: Callable[[T], R], items: Sequence[T], workers: int) -> list[R]:
    """``fn`` over ``items`` in at most ``workers`` threads; the results in the order of ``items``."""
    if not items:
        return []
    # One copy per task: a context can be entered by one thread at a time
    contexts = [contextvars.copy_context() for _ in items]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as pool:
        return list(pool.map(lambda context, item: context.run(fn, item), contexts, items))
