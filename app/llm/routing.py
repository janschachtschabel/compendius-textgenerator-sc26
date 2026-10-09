"""The b-api's routing (D97): the provider ``router``, the name it gets, and its answers that no retry mends.

Measured on staging on 2026-10-09 with a route of our own: an unknown route is a 400 "No route configured for model
'x'", a model without a price a 503 "Model pricing unavailable", a route without an active deployment a 503 "No
deployment could serve model 'x' (no deployment left)", each within 0.15 s. The list of attempts, "attempts:
<deployment>:<cause> (HTTP <status>)", follows the b-api's doc of 2026-10-02, which names NOT_ELIGIBLE for a model
that cannot serve the endpoint. A retry got the same answer after 15 s (b-api test of 2026-10-01).
"""

from __future__ import annotations

import re

ROUTER = "router"  # the provider path of the b-api's routing
_NO_ROUTE = "No route configured"
_NO_PRICE = "Model pricing unavailable"
_NONE_LEFT = "(no deployment left)"
_NOT_ELIGIBLE = "NOT_ELIGIBLE"
_ATTEMPT = re.compile(r":([A-Z][A-Z_]*) \(HTTP \d{3}\)")  # the cause of one attempt in the list


def route_name(provider: str, model: str, route: str) -> str:
    """The route the router gets: ``route``, else one named like ``model``, the b-api's way to switch without an
    outage; "" for the other providers, which take the model itself."""
    if provider != ROUTER:
        return ""
    return route.strip() or model


def route_stop(status: int, text: str, route: str) -> tuple[bool, str] | None:
    """Whether the router answered what no retry mends, and why: lasting (``True``) for a route unknown or switched
    off, a model without a price and models that cannot chat; passing (``False``) for no deployment left, which the
    router pauses after errors and lets back. An answer listing attempts with other causes - a 429 or 5xx of the
    provider - is neither: it takes the retries of any 503 (review of 2026-10-09)."""
    name = repr(route)
    if status == 400 and _NO_ROUTE in text:
        why = f"Route {name} ist in der b-api weder für den Schlüssel noch global aktiv"
        return True, f"{why}; Route anlegen oder B_API_ROUTE prüfen"
    if status != 503:
        return None
    if _NO_PRICE in text:
        return True, f"ein Modell der Route {name} hat in der b-api keinen Preis; Modellnamen der Route prüfen"
    causes = _ATTEMPT.findall(text)
    if causes and all(cause == _NOT_ELIGIBLE for cause in causes):
        why = f"die Modelle der Route {name} beantworten keine Chat-Anfragen (NOT_ELIGIBLE); Modelle der Route prüfen"
        return True, why
    if _NONE_LEFT in text:
        return False, f"kein Modell der Route {name} ist aktiv oder erreichbar"
    return None


def family_hint(status: int, text: str, route: str, model: str) -> str:
    """Behind a route the provider's refusal of a parameter: the route bundles models of another family than
    B_API_MODEL, whose parameters the service sends. OpenAI's ``unsupported_value`` stays out: it also refuses a value
    the right family lacks, an effort or a verbosity (review of 2026-10-09)."""
    if not route or status != 400 or "unsupported_parameter" not in text:
        return ""
    return (
        f" - route {route!r} leads to a model that refuses the parameters of B_API_MODEL={model}; a route bundles "
        "models of one parameter family"
    )
