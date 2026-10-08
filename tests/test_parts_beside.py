"""Part 2 and part 3 beside part 1 (M75; Jan, 2026-10-08: "die empfehlungen kann man umsetzen").

Part 1 waits on the model longest. Part 2 needs only what the article choice prepared, part 3 nothing of the topic:
after part 1, part 2 added 1.4 to 2.2 s to the profiles that check it with the LLM, and part 3 read without a cache
0.8 to 5.9 s at the very end (M75).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import pytest

from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.llm.prompts import get_prompt
from app.service import CompendiumService
from app.settings import Settings
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway
from tests.test_wlo_client import BASE, OPTIK, FakeRepository

ASSIGNMENT = get_prompt("paragraph_assignment").system
CURRICULUM = get_prompt("curriculum_check").system
WAIT_S = 3.0  # longer than any answer of the fakes; a part run after the other waits this long in vain
LISTINGS = ("/children/collections", "/children/references")


class ListingRepository(FakeRepository):
    """The fixtures' repository; ``on_read`` sees every read of part 3, ``on_listing`` its listings (part 1 reads
    neither)."""

    def __init__(self, on_listing: Any, on_read: Any = lambda: None) -> None:
        super().__init__()
        self.on_listing, self.on_read = on_listing, on_read
        self.begun: list[str] = []  # every read as it starts; ``requests`` has it once it is answered

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.begun.append(request.url.path)
        self.on_read()
        if request.url.path.endswith(LISTINGS):
            self.on_listing()
        return super().__call__(request)


def with_repository(service: CompendiumService, monkeypatch: pytest.MonkeyPatch, repository: FakeRepository) -> None:
    client = EduSharingClient(BASE, transport=httpx.MockTransport(repository))
    monkeypatch.setattr(service, "collections", CollectionBuilder(client=client, cache=None))


def test_part_2_is_checked_while_part_1_is_assigned(
    service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_cache(settings.state_dir)
    part_2_asked = threading.Event()
    overlapped: list[bool] = []

    def answer(body: dict[str, Any]) -> str:
        system = body["messages"][0]["content"]
        if system.startswith(CURRICULUM):
            part_2_asked.set()
            return json.dumps({"e1": 2})
        if system.startswith(ASSIGNMENT):  # part 1 holds its assignment until part 2 asked
            overlapped.append(part_2_asked.wait(WAIT_S))
            return json.dumps({})
        return json.dumps({"uebersicht": "Optik", "artikel": []})

    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(answer), per_request=400_000))

    result = service.generate(
        GenerateRequest(topic="Optik", parts=["world", "curricula"], subject="Physik", preset="best-quality")
    )

    assert overlapped and all(overlapped), "part 2 asked only after part 1 had its answers"
    assert result.curricula is not None and result.audit.timings_ms["curricula"] > 0


def test_part_3_is_read_from_the_start(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    listed = threading.Event()
    with_repository(service, monkeypatch, ListingRepository(listed.set))
    overlapped: list[bool] = []

    def answer(body: dict[str, Any]) -> str:  # the question N, the first call of part 1
        overlapped.append(listed.wait(WAIT_S))
        return json.dumps({"uebersicht": "Optik", "artikel": []})

    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(answer)))

    result = service.generate(
        GenerateRequest(topic="Optik", collection_id=OPTIK, parts=["world", "collection"], preset="balanced")
    )

    assert overlapped and overlapped[0], "part 3 started only after part 1"
    assert result.collection is not None and result.collection.available
    assert "collection" in result.audit.timings_ms


def test_a_topic_not_found_neither_waits_for_part_3_nor_lets_it_read_on(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 2026-10-08: a request that failed left part 3 reading the repository (and part 2 asking the model)."""
    part_3_reads, release = threading.Event(), threading.Event()
    repository = ListingRepository(lambda: release.wait(WAIT_S), on_read=part_3_reads.set)
    with_repository(service, monkeypatch, repository)
    overlapped: list[bool] = []

    def answer(body: dict[str, Any]) -> str:  # the question N, while part 3 reads
        overlapped.append(part_3_reads.wait(WAIT_S))
        return json.dumps({"uebersicht": "", "artikel": []})

    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(answer)))
    started = time.monotonic()

    with pytest.raises(TopicNotFoundError):
        service.generate(
            GenerateRequest(
                topic="Zzyzxquark Xylophonwolke", collection_id=OPTIK, parts=["world", "collection"], preset="balanced"
            )
        )

    assert time.monotonic() - started < WAIT_S, "the 404 waited for part 3 to read the collection"
    assert overlapped and overlapped[0], "part 3 started only after part 1"
    reads = len(repository.begun)
    release.set()
    time.sleep(0.5)  # part 3 would read on within milliseconds
    assert len(repository.begun) == reads, "part 3 read on after its request had failed"


def test_the_audit_names_the_time_of_the_whole_request(service: CompendiumService) -> None:
    """The stages of part 1, 2 and 3 overlap now; their sum is no longer the time of the request."""
    started = time.monotonic()
    result = service.generate(GenerateRequest(topic="Optik", parts=["world", "curricula"], preset="llm-free"))
    elapsed_ms = (time.monotonic() - started) * 1000

    assert result.audit.duration_ms is not None and 0 < result.audit.duration_ms <= elapsed_ms + 1
