"""Logging setup: one line per event, no secrets, level from settings, and the id of the request it belongs to.

Every answer carries ``X-Request-ID``: the one the caller sent (shortened to what a log line can hold) or a new
one. The id lives in a context variable, so every log line written while the request runs names it — also from
the threads the service uses, because they inherit the context. Outside a request the field is ``-``.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(request_id)s | %(message)s"

REQUEST_ID_HEADER = "X-Request-ID"
MAX_REQUEST_ID_CHARS = 64  # a header is caller input; a log line must stay readable
NO_REQUEST = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST)


def current_request_id() -> str:
    """The id of the request being handled, or ``-`` outside one."""
    return _request_id.get()


def set_request_id(value: str | None) -> str:
    """Take the caller's id (trimmed) or make one; the value is what the answer reports."""
    cleaned = " ".join((value or "").split())[:MAX_REQUEST_ID_CHARS]
    request_id = cleaned or uuid.uuid4().hex[:12]
    _request_id.set(request_id)
    return request_id


class _RequestIdFilter(logging.Filter):
    """Adds the field the format string needs; a record written outside a request gets ``-``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or _request_id.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once; repeated calls only adjust the level."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler.addFilter(_RequestIdFilter())
        root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
