"""Per-part status of an answer (PLAN.md 8.1): what came out whole, what stayed empty, what was cut short."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.sources.lehrplan.store import LehrplanStore
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.test_wlo_client import BASE, OPTIK, FakeRepository


def test_a_plain_compendium_reports_every_requested_part(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"]))
    assert result.parts_status == {"world": "ok"}
    assert result.audit.parts_status == result.parts_status


def test_a_part_without_its_source_says_unavailable(
    service: CompendiumService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A cache of its own that is not there: other tests write one into the session's state_dir (audit TE-01)
    assert service.curricula is not None
    missing = replace(service.curricula, store=LehrplanStore(tmp_path / "lehrplan.db"))
    monkeypatch.setattr(service, "curricula", missing)
    result = service.generate(GenerateRequest(topic="Optik", parts=["world", "curricula"]))
    assert result.parts_status["world"] == "ok"
    assert result.parts_status["curricula"] == "unavailable"


def test_a_listing_cut_short_by_the_time_budget_is_incomplete(
    service: CompendiumService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    client = EduSharingClient(BASE, transport=httpx.MockTransport(repo), page_size=10)
    monkeypatch.setattr(service, "collections", CollectionBuilder(client=client, cache=TtlCache(tmp_path / "c.db")))

    class OnePage:
        """The request's budget ends with the first page of the listing; one spent from the start asks the
        repository nothing more, and part 3 is unavailable (audit 2026-09-29, A06)."""

        def __init__(self, seconds: float) -> None:
            self.seconds = seconds

        def remaining(self) -> float:
            return 0.0 if any(request.url.path.endswith("/references") for request in repo.requests) else 60.0

        def branch(self) -> OnePage:  # part 3 runs on this budget beside part 1 (D93)
            return self

        def expire(self) -> None:
            pass

    monkeypatch.setattr("app.service.Deadline", OnePage)
    result = service.generate(GenerateRequest(collection_id=OPTIK, parts=["collection"]))
    assert result.parts_status == {"collection": "incomplete"}
