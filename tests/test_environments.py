"""Repository and b-api belong together (PLAN.md 3.5): the one follows the other unless told otherwise.

Both addresses are free settings. Left empty, the b-api is the one of the configured repository, so a service
pointed at staging does not quietly ask the production model - and the other way round. A deliberate mix stays
possible, but it is said out loud in the log.
"""

from __future__ import annotations

import logging

import pytest

from app.main import resolve_b_api
from app.settings import Settings, b_api_for

STAGING_REPO = "https://repository.staging.openeduhub.net/edu-sharing/rest"
PROD_REPO = "https://redaktion.openeduhub.net/edu-sharing/rest"
STAGING_API = "https://b-api.staging.openeduhub.net"
PROD_API = "https://b-api.prod.openeduhub.net"


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


@pytest.mark.parametrize(("repository", "expected"), [(STAGING_REPO, STAGING_API), (PROD_REPO, PROD_API)])
def test_every_known_repository_names_its_own_b_api(repository: str, expected: str) -> None:
    assert b_api_for(repository) == expected


def test_an_unknown_repository_names_no_b_api() -> None:
    assert b_api_for("https://repository.example.org/edu-sharing/rest") == ""


def test_the_default_is_the_staging_pair() -> None:
    current = settings()
    assert current.edu_sharing_base_url == STAGING_REPO
    assert resolve_b_api(current) == STAGING_API


def test_without_a_configured_b_api_the_repository_decides() -> None:
    assert resolve_b_api(settings(edu_sharing_base_url=PROD_REPO, b_api_base_url="")) == PROD_API


def test_a_configured_b_api_wins() -> None:
    own = "https://b-api.intern.example.org"
    assert resolve_b_api(settings(edu_sharing_base_url=PROD_REPO, b_api_base_url=own)) == own


def test_a_b_api_from_the_other_environment_is_said_out_loud(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        resolved = resolve_b_api(settings(edu_sharing_base_url=PROD_REPO, b_api_base_url=STAGING_API))
    assert resolved == STAGING_API  # the explicit setting is obeyed
    assert "b-api.prod.openeduhub.net" in caplog.text and "redaktion.openeduhub.net" in caplog.text


def test_an_unknown_repository_without_a_b_api_leaves_it_empty(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        resolved = resolve_b_api(settings(edu_sharing_base_url="https://own.example.org/rest", b_api_base_url=""))
    assert resolved == ""
    assert "B_API_BASE_URL" in caplog.text
