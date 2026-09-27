"""The optional key for the profiles (audit 2026-09-27, SE-01 and SE-03).

The service knows no login, and a public server answered everyone: one anonymous caller could spend the day's LLM
budget, which all callers share, in minutes. With API_KEYS set, every endpoint that works under a profile wants one
of the keys in ``X-API-Key``; without it they stay open, as before. The check runs after the rate limit, so a
failed try counts as a request of its client.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

API_KEY_HEADER = "X-API-Key"
_SCHEME = APIKeyHeader(
    name=API_KEY_HEADER,
    scheme_name="API-Schlüssel",
    description="Einer der Schlüssel aus API_KEYS. Nur nötig, wenn der Server Schlüssel verlangt; dann antworten "
    "alle Endpunkte mit einem Profil ohne gültigen Schlüssel mit 401",
    auto_error=False,
)


async def require_api_key(request: Request, key: str | None = Security(_SCHEME)) -> None:
    """Route dependency: 401 without a valid key while API_KEYS names any; ``async``, so no thread is spent on it."""
    keys: list[str] = request.app.state.settings.api_key_list
    if not keys:
        return
    offered = (key or "").encode()
    # Every key is compared, so the time taken does not tell which one came close
    matches = [hmac.compare_digest(offered, known.encode()) for known in keys]
    if not any(matches):
        raise HTTPException(
            status_code=401,
            detail=f"Dieser Endpunkt verlangt einen gültigen API-Schlüssel im Header {API_KEY_HEADER}.",
            headers={"WWW-Authenticate": "APIKey"},
        )
