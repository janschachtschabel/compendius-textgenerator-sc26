"""How an error answer reaches the caller (audit 2026-09-27, SE-02 and KO-19).

FastAPI's own handlers answer a 422 with every value that failed validation, so a 5 MB field came back as a 5 MB
error. And any answer that repeats caller text - a 422, the 404 that names an unknown template - failed to encode
when that text held a lone surrogate, which is legal in a JSON string but not in UTF-8: the 4xx became a 500. The
handlers here are FastAPI's with those two things changed, and a validator's reason stands without pydantic's
English prefix (AP-01). A 422 names at most twenty problems and cuts the field names it repeats: it listed every
problem, and 1.3 million unknown fields came back as 114 MB after 19 s (audit 2026-09-28, SE-15).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException

from app.domain.caller_values import cut

# What a validation error keeps: where the value was (loc), why it failed (type, msg) and the limits it broke
# (ctx) - never the value itself (input)
VALIDATION_KEYS = ("type", "loc", "msg", "ctx")
# pydantic puts this before the reason a validator raises, and the exception itself into ctx, where it encodes as {}
# (audit 2026-09-27, AP-01): the reasons are German sentences of their own
VALUE_ERROR_PREFIX = "Value error, "
MAX_PROBLEMS = 20  # problems a 422 names; one more counts the rest
# FastAPI answers a body it cannot decode - not UTF-8, JSON nested deeper than Python's recursion limit - with this 400,
# in English and described nowhere, while a truncated body is its 422 json_invalid. All three are that 422 now, in
# German, with the reason in ctx (audit 2026-09-29, S9)
FASTAPI_UNPARSED_BODY = "There was an error parsing the body"
UNREADABLE_BODY = "Der Anfragekörper ist kein lesbares JSON"
UNREADABLE_BECAUSE = {UnicodeDecodeError: "kein gültiges UTF-8", RecursionError: "zu tief verschachtelt"}


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
    if error.status_code == 400 and error.detail == FASTAPI_UNPARSED_BODY:
        return _unreadable_body(error.__cause__)
    headers = getattr(error, "headers", None)
    if not is_body_allowed_for_status_code(error.status_code):
        return Response(status_code=error.status_code, headers=headers)
    return JsonResponse({"detail": error.detail}, status_code=error.status_code, headers=headers)


async def validation_error(request: Request, exc: Exception) -> Response:
    """422 with where and why each value failed, without the value."""
    errors = cast(RequestValidationError, exc).errors()  # registered for RequestValidationError only
    kept = [_problem(error) for error in errors[:MAX_PROBLEMS]]
    if (omitted := len(errors) - MAX_PROBLEMS) > 0:
        kept.append(
            {
                "type": "too_many_errors",
                "loc": [],
                "msg": f"{omitted} weitere Fehler nicht aufgeführt",
                "ctx": {"omitted": omitted},
            }
        )
    return JsonResponse({"detail": jsonable_encoder(kept)}, status_code=422)


def _unreadable_body(cause: BaseException | None) -> Response:
    """The 422 json_invalid of a body FastAPI could not decode, with why (the exception it raised from)."""
    reason = next((text for kind, text in UNREADABLE_BECAUSE.items() if isinstance(cause, kind)), "nicht lesbar")
    problem = {"type": "json_invalid", "loc": ["body"], "msg": UNREADABLE_BODY, "ctx": {"error": reason}}
    return JsonResponse({"detail": [problem]}, status_code=422)


def _problem(error: Mapping[str, Any]) -> dict[str, Any]:
    problem = {key: error[key] for key in VALIDATION_KEYS if key in error}
    if problem.get("type") == "json_invalid":  # FastAPI's "JSON decode error"; ctx keeps the reason Python gave
        problem["msg"] = UNREADABLE_BODY
    problem["loc"] = [cut(part) if isinstance(part, str) else part for part in problem.get("loc", ())]
    if problem.get("type") == "value_error":
        problem["msg"] = str(problem.get("msg", "")).removeprefix(VALUE_ERROR_PREFIX)
        ctx = {key: value for key, value in (problem.pop("ctx", None) or {}).items() if key != "error"}
        if ctx:
            problem["ctx"] = ctx
    return problem
