"""Per provider how many LLM calls a worker sends at once and how long a request may take (Jan, 2026-10-08, M75).

The OpenAI models take many calls at once; academiccloud queues them on few GPUs, so a request there runs longer with
fewer calls at once. Jan: "zeitgrenzen anheben bei b-api-accademiccloud oder besser generell damit es nicht schief
geht". A value set in LLM_MAX_CONCURRENCY or REQUEST_TIMEOUT_S holds for every provider; an empty entry is the
provider's default, as every setting left empty is its default (BE-13).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.llm.client import BApiClient
from app.main import build_llm
from app.observability.metrics import DURATION_BUCKETS
from app.settings import PROVIDER_REQUEST_TIMEOUT_S, Settings
from tests.conftest import make_settings
from tests.test_llm_client import FakeBApi


@pytest.mark.parametrize(("provider", "calls", "seconds"), [("openai", 20, 300), ("academiccloud", 2, 600)])
def test_the_provider_sets_the_calls_at_once_and_the_time_of_a_request(provider: str, calls: int, seconds: int) -> None:
    settings = Settings(_env_file=None, b_api_provider=provider)
    assert (settings.llm_concurrency, settings.request_time_limit_s) == (calls, seconds)


@pytest.mark.parametrize("provider", ["openai", "academiccloud"])
def test_a_value_set_holds_for_every_provider(provider: str) -> None:
    settings = Settings(_env_file=None, b_api_provider=provider, llm_max_concurrency=7, request_timeout_s=90)
    assert (settings.llm_concurrency, settings.request_time_limit_s) == (7, 90)


def test_an_empty_entry_is_the_providers_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B_API_PROVIDER", "academiccloud")
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "")
    monkeypatch.setenv("REQUEST_TIMEOUT_S", " ")
    settings = Settings(_env_file=None)
    assert (settings.llm_concurrency, settings.request_time_limit_s) == (2, 600)


def test_the_gateway_sends_as_many_calls_at_once_as_the_provider_takes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline_client(*args: Any, **kwargs: Any) -> BApiClient:
        return BApiClient(*args, transport=httpx.MockTransport(FakeBApi()), **kwargs)

    monkeypatch.setattr("app.main.BApiClient", offline_client)
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", b_api_provider="academiccloud")

    gateway = build_llm(settings)

    assert gateway is not None and gateway.client.max_concurrency == gateway.options.concurrency == 2


def test_the_duration_histogram_reaches_the_longest_request_a_provider_allows() -> None:
    """Review 2026-10-08: the buckets ended at 120 s, so every longer request of academiccloud counted as +Inf."""
    assert max(DURATION_BUCKETS) >= max(PROVIDER_REQUEST_TIMEOUT_S.values())
