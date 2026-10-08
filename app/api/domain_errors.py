"""The answer to each error of the service, whichever route raised it (audit 2026-09-27, AR-02).

Five routers translated the same errors into HTTP answers, each with its own list, and an error one of them missed
became a 500. ``create_app`` registers this table once; a route lets the error rise. Starlette picks the handler
along the exception's MRO, so a subclass (``NodeNotFoundError``) finds its own entry before its base
(``EduSharingError``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import Request, Response

from app.api.errors import JsonResponse
from app.compendium.errors import (
    LlmNotConfiguredError,
    PartsUnavailableError,
    RepositoryUnavailableError,
    TopicNotFoundError,
)
from app.compose.regeneration import UnknownSectionsError, UnplacedSectionsError, UnreadableDocumentError
from app.matching.registry import UnknownMatcherError
from app.sources.lehrplan.subjects import UnknownSubjectError
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError, NodeNotFoundError
from app.sources.wlo.repository import RepositoryNotAllowedError
from app.templates.manager import TemplateNotFoundError

log = logging.getLogger(__name__)

Handler = Callable[[Request, Exception], Awaitable[Response]]


def _answer(status: int, detail: Callable[[Exception], Any] = str, failure: str | None = None) -> Handler:
    """The answer to an error; ``failure`` names in the log one on the server's side: the 5xx alarm sends the operator
    there, and a 502 of a repository answer the service could not read, or the 503 of a server without an LLM, left
    no line (logging review of 2026-10-08). A refusal of what the caller sent stays out of the log."""

    async def answer(request: Request, exc: Exception) -> Response:
        if failure is not None:
            log.warning("%s: %s", failure, exc)
        return JsonResponse({"detail": detail(exc)}, status_code=status)

    return answer


def _no_part(exc: Exception) -> str:
    return f"Kein angefragter Teil ist erzeugbar: {exc}"


DOMAIN_ERRORS: dict[type[Exception], Handler] = {
    TopicNotFoundError: _answer(404, lambda exc: cast(TopicNotFoundError, exc).detail()),
    TemplateNotFoundError: _answer(404, lambda exc: f"Template nicht gefunden: {exc.args[0]}"),
    CollectionNotFoundError: _answer(404),  # the messages of the repository errors name the repository
    NodeNotFoundError: _answer(404),
    RepositoryNotAllowedError: _answer(422),
    UnknownSubjectError: _answer(422),
    UnknownSectionsError: _answer(422),
    UnreadableDocumentError: _answer(422),
    UnplacedSectionsError: _answer(422),
    UnknownMatcherError: _answer(422, lambda exc: f"Unbekannte Matching-Strategie: {exc}"),
    EduSharingError: _answer(502, failure="repository failed"),
    LlmNotConfiguredError: _answer(503, failure="request refused"),
    RepositoryUnavailableError: _answer(503, failure="request refused"),
    # A gap in the configuration that no retry fixes; the log keeps it apart from missing archives (docs/betrieb.md)
    PartsUnavailableError: _answer(503, _no_part, failure="compendium request refused"),
}
