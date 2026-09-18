"""SPARQL client for the MEM harvest: form POST, flattened rows, pacing, retries, error reporting."""

from collections.abc import Callable

import httpx
import pytest

from app.sources.lehrplan.sparql import SparqlClient, SparqlError

ROWS = {
    "head": {},
    "results": {
        "bindings": [
            {"s": {"type": "uri", "value": "https://x/1"}, "l": {"type": "literal", "value": "A"}},
            {"s": {"type": "uri", "value": "https://x/2"}},
        ]
    },
}


def _client(handler: Callable[[httpx.Request], httpx.Response], **kwargs: object) -> SparqlClient:
    kwargs.setdefault("sleep", lambda _seconds: None)
    return SparqlClient("https://sparql.test/sparql/", transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]


def test_select_posts_the_query_as_a_form_and_flattens_the_bindings() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ROWS)

    rows = _client(handler).select("SELECT ?s WHERE { ?s ?p ?o }")
    assert rows == [{"s": "https://x/1", "l": "A"}, {"s": "https://x/2"}]
    request = seen[0]
    assert request.method == "POST"
    assert request.headers["accept"] == "application/sparql-results+json"
    assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert "compendious-text-fastapi" in request.headers["user-agent"]
    assert request.content.decode().startswith("query=SELECT")


def test_transport_errors_are_retried_with_backoff_and_then_reported() -> None:
    calls: list[int] = []
    pauses: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("boom")

    client = _client(handler, attempts=3, sleep=pauses.append, pause_s=0.0)
    with pytest.raises(SparqlError, match="nicht erreichbar"):
        client.select("SELECT 1")
    assert len(calls) == 3
    assert pauses == [1.5, 3.0]


def test_http_400_is_not_retried_and_carries_the_virtuoso_message() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, text="Virtuoso 37000 Error SP030: SPARQL compiler, line 9: syntax error")

    with pytest.raises(SparqlError, match=r"HTTP 400.*SP030"):
        _client(handler).select("SELECT 1")
    assert len(calls) == 1


def test_transient_http_errors_are_retried() -> None:
    responses = iter([httpx.Response(503, text="busy"), httpx.Response(200, json=ROWS)])
    assert len(_client(lambda _request: next(responses), pause_s=0.0).select("SELECT 1")) == 2


def test_non_json_answer_is_an_error() -> None:
    with pytest.raises(SparqlError, match="JSON"):
        _client(lambda _request: httpx.Response(200, text="<html>maintenance</html>")).select("SELECT 1")


def test_requests_are_paced_by_the_pause() -> None:
    ticks = iter([0.0, 0.1, 0.6])
    pauses: list[float] = []
    client = _client(
        lambda _request: httpx.Response(200, json=ROWS), pause_s=0.5, sleep=pauses.append, clock=lambda: next(ticks)
    )
    client.select("SELECT 1")
    client.select("SELECT 2")
    client.select("SELECT 3")
    assert pauses == [pytest.approx(0.4), pytest.approx(0.4)]  # the pause counts from the paced send time
