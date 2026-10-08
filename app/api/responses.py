"""The error answers of the API as OpenAPI describes them (audit 2026-09-27, AP-01).

Three shapes of ``detail`` reach a caller, and they stay as they are for the callers that read them: a refusal gives
its reason as German text; a 422 of validation lists where and why each value failed, while a value a route checks
itself is refused with text; the 404 of a topic the archives do not have carries the resolution with its
alternatives. A route names the answers it can give with ``refusals``; each route's docstring says when.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain.models import Resolution


class Refusal(BaseModel):
    """Why the request is refused, in German."""

    detail: str


class Problem(BaseModel):
    """A value that failed validation: where it was, why, and the limits it broke - never the value itself."""

    type: str
    loc: list[str | int]
    msg: str
    ctx: dict[str, Any] | None = None


class Invalid(BaseModel):
    """The values that failed validation, or the text of one the route checks itself."""

    detail: list[Problem] | str


class TopicMissing(BaseModel):
    """A topic the archives do not have: why, how the service read it and, for a material, how its article was
    sought."""

    message: str
    resolution: Resolution
    node_article: dict[str, Any] | None = None


class NotFound(BaseModel):
    """A topic with its resolution, or the text that names the unknown template, node, collection, archive or file."""

    detail: TopicMissing | str


RESPONSES: dict[int, dict[str, Any]] = {
    400: {"model": Refusal, "description": "Not a plain .zim file name: a path or a hidden file"},
    401: {
        "model": Refusal,
        "description": "API_KEYS is set, and the header X-API-Key is missing or holds none of them",
    },
    403: {"model": Refusal, "description": "Wrong admin token"},
    404: {
        "model": NotFound,
        "description": "Unknown topic (with its resolution and alternatives), template, node, collection, archive or "
        "file; on an admin route: the admin endpoints are off (no ADMIN_TOKEN)",
    },
    409: {"model": Refusal, "description": "In the way of what the request wants: a built-in template, an active file"},
    412: {
        "model": Refusal,
        "description": "If-Match names no version the template has now: another write came since it was read",
    },
    413: {"model": Refusal, "description": "The body is larger than the service reads"},
    422: {
        "model": Invalid,
        "description": "A value the request may not have, or a combination it may not make; a body that is no "
        "readable JSON (truncated, not UTF-8, nested too deep) is the problem json_invalid",
    },
    429: {
        "model": Refusal,
        "description": "More than RATE_LIMIT requests of this client within a minute",
        "headers": {"Retry-After": {"description": "Seconds until it may send again", "schema": {"type": "integer"}}},
    },
    502: {"model": Refusal, "description": "The edu-sharing repository or the Kiwix catalog failed"},
    503: {
        "model": Refusal,
        "description": "Not possible on this server now: no archives loaded, no LLM or no repository configured, or no "
        "requested part can be made",
    },
}


def refusals(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The OpenAPI ``responses`` of a route that can give these error answers."""
    return {status: RESPONSES[status] for status in statuses}


# What every profile endpoint can answer besides its result: key, limit, validation, and the refusals of the service
PROFILE_REFUSALS = refusals(401, 404, 422, 429, 502, 503)
ADMIN_REFUSALS = refusals(403, 404, 429)
