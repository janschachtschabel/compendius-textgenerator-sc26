"""Which commit an image was built from (audit 2026-09-27, BE-03).

The version stayed 2.0.0 through 139 commits, so the advice to compare it after an update said nothing. The publish
job bakes the commit into the image as GIT_REVISION; /health and kompendium_build_info report it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.main import create_app
from app.settings import Settings
from tests.test_metrics import scrape, value

COMMIT = "06f28b2a36ab2056c516c2aa16dfdce60c8117e7"


def test_health_names_the_commit_of_the_image(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_REVISION", COMMIT)

    health = TestClient(create_app(settings)).get("/health").json()

    assert health["revision"] == COMMIT
    assert health["version"] == __version__


def test_a_local_build_has_no_revision(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_REVISION", raising=False)

    assert TestClient(create_app(settings)).get("/health").json()["revision"] is None


def test_the_build_info_metric_carries_the_revision(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_REVISION", COMMIT)

    samples = scrape(TestClient(create_app(settings)))

    assert value(samples, "kompendium_build_info", revision=COMMIT, version=__version__) == 1
