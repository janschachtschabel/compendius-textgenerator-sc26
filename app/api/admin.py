"""Admin protection for operational endpoints: ``X-Admin-Token`` compared in constant time."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Header, HTTPException, Request

from app.api.gates import EARLY, first_time
from app.locks import LockHeldError

log = logging.getLogger(__name__)


def require_admin(
    request: Request,
    x_admin_token: str | None = Header(
        default=None,
        description="The value of ADMIN_TOKEN, compared in constant time; missing or wrong: 403. While ADMIN_TOKEN "
        "is empty every admin endpoint answers 404",
    ),
) -> None:
    """Dependency: 404 while no ADMIN_TOKEN is configured, 403 on a missing or wrong token; a gated route asks it
    before the body is read (``app.api.gates``)."""
    if not first_time(request, "admin"):
        return
    expected: str = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(status_code=404, detail="Admin-Endpunkte sind nicht aktiviert (ADMIN_TOKEN fehlt).")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Ungültiges Admin-Token.")


async def _admin_before_body(request: Request) -> None:
    require_admin(request, request.headers.get("x-admin-token"))


EARLY[require_admin] = _admin_before_body


@contextmanager
def admin_write(what: str) -> Iterator[None]:
    """A write of an admin route to a volume the service cannot write - mounted read-only (D113), full, or held by
    another writer - is a 503 that says why, no 500 (audit 2026-10-16). The answer names no server path; the log
    line does."""
    try:
        yield
    except LockHeldError as exc:
        log.warning("%s refused: %s", what, exc)
        detail = f"{what} nicht möglich: ein anderer Schreibvorgang hält die Sperre (letztes Lebenszeichen vor "
        raise HTTPException(status_code=503, detail=f"{detail}{exc.age_s:.0f} s); später erneut versuchen.") from exc
    except OSError as exc:
        log.warning("%s failed: %s", what, exc)
        reason = exc.strerror or type(exc).__name__
        detail = f"{what} nicht möglich: das Verzeichnis ist auf diesem Server nicht beschreibbar ({reason})."
        raise HTTPException(status_code=503, detail=detail) from exc
