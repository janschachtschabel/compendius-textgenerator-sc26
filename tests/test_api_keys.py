"""The optional key for the profiles (audit 2026-09-27, SE-01 and SE-03; Jan's decision of the same day).

Without API_KEYS the service answers everyone, as before. With it, every endpoint that works under a profile - the
ones that spend the day's LLM budget or the workers' time - wants one of the keys in ``X-API-Key``; health, readiness,
templates and the status endpoints stay open. Tokens and keys shorter than 32 characters are refused at start, and
the refusal never repeats the value.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.keys import API_KEY_HEADER, require_api_key
from app.api.limits import rate_limited
from app.main import create_app
from app.settings import Settings
from tests.conftest import make_settings

KEY_A = "a" * 16 + "0123456789abcdef"  # 32 characters
KEY_B = "b" * 40
NODE = "00000000-0000-4000-8000-000000000000"
PROFILE_ROUTES = [
    ("POST", "/api/v2/compendium"),
    ("POST", "/api/v2/knowledge"),
    ("POST", "/api/v2/qa"),
    ("POST", "/api/v2/entities"),
    ("GET", "/api/v2/lehrplan/search"),
    ("GET", f"/api/v2/nodes/{NODE}"),
    ("GET", f"/api/v2/collections/{NODE}/overview"),
]
OPEN_ROUTES = ["/health", "/ready", "/api/v2/templates", "/api/v2/lehrplan/status", "/api/v2/zim/status"]


@pytest.fixture(scope="module")
def keyed(settings: Settings) -> TestClient:
    return TestClient(create_app(settings.model_copy(update={"api_keys": f"{KEY_A},{KEY_B}"})))


@pytest.mark.parametrize(("method", "path"), PROFILE_ROUTES)
def test_a_profile_endpoint_wants_a_key_once_the_server_has_keys(keyed: TestClient, method: str, path: str) -> None:
    missing = keyed.request(method, path, json={})
    wrong = keyed.request(method, path, json={}, headers={API_KEY_HEADER: "c" * 32})

    assert missing.status_code == wrong.status_code == 401
    assert API_KEY_HEADER in missing.json()["detail"]


@pytest.mark.parametrize("path", OPEN_ROUTES)
def test_health_readiness_and_status_stay_open(keyed: TestClient, path: str) -> None:
    assert keyed.get(path).status_code != 401


@pytest.mark.parametrize("key", [KEY_A, KEY_B])
def test_every_configured_key_opens_the_profiles(keyed: TestClient, key: str) -> None:
    response = keyed.post(
        "/api/v2/qa", json={"text": "Die Optik ist die Lehre vom Licht."}, headers={API_KEY_HEADER: key}
    )

    assert response.status_code == 200


def test_without_keys_the_profiles_stay_open(settings: Settings) -> None:
    response = TestClient(create_app(settings)).post("/api/v2/qa", json={"text": "Die Optik ist die Lehre vom Licht."})

    assert response.status_code == 200


def test_every_rate_limited_route_wants_the_key_and_no_other_route_does(settings: Settings) -> None:
    """A new profile endpoint gets both dependencies or the test names it."""
    app = create_app(settings)
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = [dependency.call for dependency in route.dependant.dependencies]
        assert (rate_limited in calls) == (require_api_key in calls), route.path
        if require_api_key in calls:
            assert calls.index(rate_limited) < calls.index(require_api_key), "a failed key counts as a request"


def test_the_docs_offer_the_key(settings: Settings) -> None:
    schema = TestClient(create_app(settings)).get("/openapi.json").json()

    [(name, scheme)] = schema["components"]["securitySchemes"].items()
    assert scheme == {"type": "apiKey", "in": "header", "name": API_KEY_HEADER, "description": scheme["description"]}
    assert schema["paths"]["/api/v2/compendium"]["post"]["security"] == [{name: []}]
    assert "security" not in schema["paths"]["/health"]["get"]


@pytest.mark.parametrize("field", ["api_keys", "admin_token", "metrics_token"])
def test_a_secret_shorter_than_32_characters_is_refused_without_repeating_it(settings: Settings, field: str) -> None:
    short = "kurz-und-geheim"

    with pytest.raises(ValidationError) as refused:
        make_settings([], settings.state_dir, **{field: short})

    message = str(refused.value)
    assert field.upper() in message and "32" in message
    assert short not in message


def test_one_short_key_among_long_ones_is_refused(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        make_settings([], settings.state_dir, api_keys=f"{KEY_A}, kurz")


def test_blanks_around_the_keys_are_no_part_of_them(settings: Settings) -> None:
    configured = make_settings([], settings.state_dir, api_keys=f" {KEY_A} , {KEY_B} ,")

    assert configured.api_key_list == [KEY_A, KEY_B]
