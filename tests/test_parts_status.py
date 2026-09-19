"""Per-part status of an answer (PLAN.md 8.1): what came out whole, what stayed empty, what was cut short."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.test_wlo_client import BASE, OPTIK, FakeRepository


def test_a_plain_compendium_reports_every_requested_part(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"]))
    assert result.parts_status == {"world": "ok"}
    assert result.audit.parts_status == result.parts_status


def test_a_part_without_its_source_says_unavailable(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["world", "curricula"]))
    assert result.parts_status["world"] == "ok"
    assert result.parts_status["curricula"] == "unavailable"  # no harvested curriculum cache in the tests


def test_a_listing_cut_short_by_the_time_budget_is_incomplete(
    service: CompendiumService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository()), page_size=10)
    monkeypatch.setattr(service, "collections", CollectionBuilder(client=client, cache=TtlCache(tmp_path / "c.db")))
    monkeypatch.setattr(service.settings, "request_timeout_s", 0)
    result = service.generate(GenerateRequest(collection_id=OPTIK, parts=["collection"]))
    assert result.parts_status == {"collection": "incomplete"}
