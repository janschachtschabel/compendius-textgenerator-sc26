"""Admin protection for operational endpoints: ``X-Admin-Token`` compared in constant time."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request


def require_admin(
    request: Request,
    x_admin_token: str | None = Header(
        default=None,
        description="The value of ADMIN_TOKEN, compared in constant time; missing or wrong: 403. While ADMIN_TOKEN "
        "is empty every admin endpoint answers 404",
    ),
) -> None:
    """Dependency: 404 while no ADMIN_TOKEN is configured, 403 on a missing or wrong token."""
    expected: str = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(status_code=404, detail="Admin-Endpunkte sind nicht aktiviert (ADMIN_TOKEN fehlt).")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Ungültiges Admin-Token.")
