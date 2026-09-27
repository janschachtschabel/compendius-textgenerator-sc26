"""How an error answer reaches the caller (audit 2026-09-27, SE-02 and KO-19).

FastAPI's own handlers answer a 422 with every value that failed validation, so a 5 MB field came back as a 5 MB
error. And any answer that repeats caller text - a 422, the 404 that names an unknown template - failed to encode
when that text held a lone surrogate, which is legal in a JSON string but not in UTF-8: the 4xx became a 500. The
handlers here are FastAPI's with those two things changed.
"""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException

# What a validation error keeps: where the value was (loc), why it failed (type, msg) and the limits it broke
# (ctx) - never the value itself (input)
VALIDATION_KEYS = ("type", "loc", "msg", "ctx")


class JsonResponse(JSONResponse):
    """JSON that always encodes: an answer holding a lone surrogate goes out with ASCII escapes instead of failing."""

    def render(self, content: Any) -> bytes:
        try:
            return super().render(content)
        except UnicodeEncodeError:
            return json.dumps(content, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


async def http_error(request: Request, exc: Exception) -> Response:
    """FastAPI's handler for ``HTTPException``, answering with ``JsonResponse``."""
    error = cast(HTTPException, exc)  # registered for HTTPException only
    headers = getattr(error, "headers", None)
    if not is_body_allowed_for_status_code(error.status_code):
        return Response(status_code=error.status_code, headers=headers)
    return JsonResponse({"detail": error.detail}, status_code=error.status_code, headers=headers)


async def validation_error(request: Request, exc: Exception) -> Response:
    """422 with where and why each value failed, without the value."""
    errors = cast(RequestValidationError, exc).errors()  # registered for RequestValidationError only
    kept = [{key: error[key] for key in VALIDATION_KEYS if key in error} for error in errors]
    return JsonResponse({"detail": jsonable_encoder(kept)}, status_code=422)
