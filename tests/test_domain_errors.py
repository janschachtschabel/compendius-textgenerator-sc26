"""One answer per refusal, whichever router raises it (audit 2026-09-27, AR-02).

Five routers translated the same errors of the service into HTTP answers, each its own list; an error a router did
not list became a 500. The app now registers the translation once, so a route lets the error rise.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.compendium.errors import (
    LlmNotConfiguredError,
    PartsUnavailableError,
    RepositoryUnavailableError,
    TopicNotFoundError,
)
from app.compose.regeneration import UnknownSectionsError
from app.domain.models import Resolution
from app.main import create_app
from app.matching.registry import UnknownMatcherError
from app.settings import Settings
from app.sources.lehrplan.subjects import UnknownSubjectError
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError, NodeNotFoundError
from app.sources.wlo.repository import RepositoryNotAllowedError
from app.templates.manager import TemplateNotFoundError

MISSING = TopicNotFoundError(Resolution(query="Quxbar", normalized="Quxbar", alternatives=["Qux"]))
SUBJECT = UnknownSubjectError("Quxkunde", ["Physik", "Chemie"])
SECTIONS = UnknownSectionsError(["x"], ["intro", "quellen"])

# What each error answers: its status and its detail, as the routers gave them before
ANSWERS: dict[str, tuple[Exception, int, Any]] = {
    "topic": (MISSING, 404, MISSING.detail()),
    "template": (TemplateNotFoundError("nope"), 404, "Template nicht gefunden: nope"),
    "subject": (SUBJECT, 422, str(SUBJECT)),
    "sections": (SECTIONS, 422, str(SECTIONS)),
    "matcher": (UnknownMatcherError("quux"), 422, "Unbekannte Matching-Strategie: quux"),
    "llm": (LlmNotConfiguredError("LLM_ENABLED ist nicht aktiv"), 503, "LLM_ENABLED ist nicht aktiv"),
    "parts": (
        PartsUnavailableError("Teil 3 braucht collection_id"),
        503,
        "Kein angefragter Teil ist erzeugbar: Teil 3 braucht collection_id",
    ),
    "address": (RepositoryNotAllowedError("nicht erlaubt: evil.test"), 422, "nicht erlaubt: evil.test"),
    "node": (NodeNotFoundError("Knoten x fehlt in repo.test"), 404, "Knoten x fehlt in repo.test"),
    "collection": (CollectionNotFoundError("Sammlung y fehlt in repo.test"), 404, "Sammlung y fehlt in repo.test"),
    "no_repository": (RepositoryUnavailableError("Kein Repository konfiguriert"), 503, "Kein Repository konfiguriert"),
    "repository": (EduSharingError("repo.test antwortet 500"), 502, "repo.test antwortet 500"),
}


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    probe = APIRouter()

    @probe.get("/probe/{kind}")
    def raise_it(kind: str) -> None:
        raise ANSWERS[kind][0]

    app.include_router(probe)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("kind", ANSWERS)
def test_an_error_of_the_service_gets_its_answer_from_any_route(client: TestClient, kind: str) -> None:
    _error, status, detail = ANSWERS[kind]
    response = client.get(f"/probe/{kind}")
    assert response.status_code == status, response.text
    assert response.json() == {"detail": detail}
    assert response.headers["x-request-id"]  # the answer still carries the id to quote


def test_a_refused_compendium_still_says_so_in_the_log(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    """docs/betrieb.md sends the operator to this line for the 503 of a part the server cannot make."""
    with caplog.at_level("WARNING"):
        client.get("/probe/parts")
    assert "compendium request refused: Teil 3 braucht collection_id" in caplog.text
