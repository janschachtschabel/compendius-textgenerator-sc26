"""Logging setup: one line per event, no secrets, level from settings, and the id of the request it belongs to.

Every answer carries ``X-Request-ID``: the one the caller sent (its harmless signs, shortened to what a log line can
hold) or a new one. The id lives in a context variable, so every log line written while the request runs names it —
also from the threads the service uses: anyio's threads inherit the context, and the pools of the LLM stages and the
material reads run in a copy of it (app/concurrency.py; a plain ThreadPoolExecutor does not, audit 2026-09-27,
TE-03). Outside a request the field is ``-``.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(request_id)s | %(message)s"

REQUEST_ID_HEADER = "X-Request-ID"
MAX_REQUEST_ID_CHARS = 64  # a header is caller input; a log line must stay readable
_NOT_IN_AN_ID = re.compile("[^A-Za-z0-9._:@+/=-]")
NO_REQUEST = "-"
# uvicorn's loggers with handlers of their own; uvicorn.error writes through "uvicorn"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.access")
# The HTTP client: httpx names every request at INFO, and httpcore writes a dozen lines per request at DEBUG, the
# response headers among them - so the session cookie edu-sharing hands the configured account (logging review of
# 2026-10-08). Both stay at WARNING, whatever LOG_LEVEL says
QUIET_LOGGERS = ("httpx", "httpcore")

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST)


def current_request_id() -> str:
    """The id of the request being handled, or ``-`` outside one."""
    return _request_id.get()


def set_request_id(value: str | None) -> str:
    """Take the caller's id or make one; the value is what the answer reports.

    Only letters, digits and ``._:@+/=-`` stay, the signs UUIDs, W3C trace ids and the ids of Rails and Heroku are
    written with: ESC, BEL and DEL reached every log line and the answer's header, which h11 lets through, and a
    space and "|" forged the fields of a log line (audit 2026-09-29, S4). An id with nothing left gets a new one. The
    header is cut before it is read: split whole, 12 MB cost 0.25 s and 219 MB of the event loop (audit 2026-09-28,
    SE-19)."""
    cleaned = _NOT_IN_AN_ID.sub("", (value or "")[: 4 * MAX_REQUEST_ID_CHARS])[:MAX_REQUEST_ID_CHARS]
    request_id = cleaned or uuid.uuid4().hex[:12]
    _request_id.set(request_id)
    return request_id


class _RequestIdFilter(logging.Filter):
    """Adds the field the format string needs; a record written outside a request gets ``-``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or _request_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per event (LOG_FORMAT=json, audit 2026-09-18, OPS-03): a log collector reads its fields without
    a pattern of its own, and a traceback stays inside its line."""

    def format(self, record: logging.LogRecord) -> str:
        moment = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        event = {
            "time": moment.replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", NO_REQUEST),
            "message": record.getMessage(),
        }
        if record.exc_info:
            event["exc"] = self.formatException(record.exc_info)
        return json.dumps(event, ensure_ascii=False)


def configure_logging(level: str = "INFO", format_: str = "text") -> None:
    """Configure the root logger once, as plain lines or with ``format_`` json as JSON lines; repeated calls only
    adjust the level."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter() if format_ == "json" else logging.Formatter(_FORMAT))
        handler.addFilter(_RequestIdFilter())
        root.addHandler(handler)
    if format_ == "json":
        # uvicorn sets up its loggers in every worker before the app is built, with plain lines of their own: the
        # access line of every request and the traceback of an error stayed text between the JSON lines (review of
        # 2026-10-08). They write through the root's handler instead
        for name in UVICORN_LOGGERS:
            uvicorn_logger = logging.getLogger(name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True
    root.setLevel(level.upper())
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def json_log_config(level: str = "INFO") -> dict[str, Any]:
    """LOG_FORMAT=json as uvicorn's ``--log-config``: its own process writes before any worker builds the app - the
    start, the stop, a worker that died - and so never runs configure_logging."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": f"{__name__}._JsonFormatter"}},
        "filters": {"request_id": {"()": f"{__name__}._RequestIdFilter"}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
                "filters": ["request_id"],
            }
        },
        "loggers": {name: {"handlers": [], "propagate": True} for name in UVICORN_LOGGERS},
        "root": {"handlers": ["stdout"], "level": level.upper()},
    }
