"""The b-api key of a request for its LLM calls (D105).

With B_API_KEY_SOURCE=request the key the b-api passes on from its caller - Authorization, else X-API-Key; while
API_KEYS is set, X-API-Key carries the service's own key and only Authorization a b-api key - goes back with the LLM
calls of that request (app/llm/credentials.py). A header that no request to the b-api could carry is a 401.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.llm.credentials import UnusableKeyError, offered_key, use_request_key


async def take_b_api_key(request: Request) -> None:
    """App-wide dependency; ``async``, so it runs in the request's own context, which its threads inherit
    (app/concurrency.py), and the key reaches no other request."""
    settings = request.app.state.settings
    if settings.b_api_key_source != "request":
        return
    try:
        key = offered_key(request.headers, own_x_api_key=bool(settings.api_key_list))
    except UnusableKeyError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from None
    use_request_key(key)
