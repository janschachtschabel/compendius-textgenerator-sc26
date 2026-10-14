"""The b-api key of the request being handled (D105).

Behind the b-api's proxy a service gets the key of its caller passed on - ``Authorization: Bearer <key>``, or
``X-API-KEY`` where the caller used that - and sends it back unchanged when it asks the b-api's LLM endpoints, so the
b-api books the call on the caller's key and applies that key's limits (b-api, "Authentifizierung über den
durchgereichten Authorization-Header", measured on staging 2026-10-13). With B_API_KEY_SOURCE=request the service
does so; without a key of its request it answers with B_API_KEY, as every call outside a request does.

A key belongs to its request alone: it lives in a context variable, which the threads of the LLM stages inherit
(app/concurrency.py), never in an object the requests share; it is never logged and goes to no host but the b-api.
Once the b-api refuses it - a limit reached, the LLM switched off for it, no right - the rest of the request runs
without the LLM (D106): the refusal is noted on the key, which all threads of the request see.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

AUTHORIZATION = "Authorization"
X_API_KEY = "X-API-KEY"  # the b-api's name; HTTP headers ignore case, so the service's own X-API-Key is the same one
# A b-api key had 36 characters, with "Bearer " 43; anything far longer is no key, and a header is caller input
MAX_KEY_CHARS = 1024
# Visible ASCII, spaces only inside: what an HTTP header carries unchanged. The b-api takes "Bearer <key>" and refuses
# "bearer <key>" (2026-10-13); the service passes the value on as it came and leaves that judgement to the b-api
_SENDABLE = re.compile("^[!-~](?:[ -~]*[!-~])?$")


class UnusableKeyError(ValueError):
    """A key header holds nothing a header to the b-api could carry; the message names the header, never its value."""


@dataclass(eq=False)
class RequestKey:
    """The key of one request: the header it came in and its value, as it came. ``refused`` holds why the b-api
    refused it once it has (D106)."""

    header: str
    value: str = field(repr=False)
    refused: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def refuse(self, reason: str) -> bool:
        """Note why the b-api refused the key; ``True`` for the first refusal of the request, which is logged."""
        with self._lock:
            if self.refused is not None:
                return False
            self.refused = reason
            return True


_current: ContextVar[RequestKey | None] = ContextVar("b_api_request_key", default=None)


def offered_key(headers: Mapping[str, str], *, own_x_api_key: bool = False) -> RequestKey | None:
    """The b-api key a request brings: ``Authorization``, else ``X-API-Key``; ``None`` without one.

    ``own_x_api_key``: X-API-Key carries the service's own key (API_KEYS is set), so only Authorization can bring a
    b-api key. Raises ``UnusableKeyError`` for a value no header to the b-api could carry.
    """
    names = (AUTHORIZATION,) if own_x_api_key else (AUTHORIZATION, X_API_KEY)
    for name in names:
        value = headers.get(name.lower(), "")
        if not value:
            continue
        if len(value) > MAX_KEY_CHARS or not _SENDABLE.match(value):
            raise UnusableKeyError(f"Der Header {name} trägt keinen Schlüssel, den die b-api annehmen kann.")
        return RequestKey(name, value)
    return None


def use_request_key(key: RequestKey | None) -> None:
    """Make ``key`` the b-api key of the request being handled (an app-wide dependency calls it, app/api)."""
    _current.set(key)


def request_key() -> RequestKey | None:
    """The b-api key of the request being handled, ``None`` without one or outside a request."""
    return _current.get()


@contextmanager
def own_key_only() -> Iterator[None]:
    """Calls within ask with the service's own key, whatever the request brought: the model check, whose result holds
    for all requests."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)
