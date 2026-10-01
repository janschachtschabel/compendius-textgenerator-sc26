"""b-api client: request forms per model family, auth header, retries, error mapping, model check (offline)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.llm.client import BApiClient, LlmError

BASE = "https://b-api.test"
KEY = "secret-key-0123456789"

OPENAI_MODELS = {
    "object": "list",
    "data": [
        {"id": "gpt-6-luna", "object": "model", "created": 1, "owned_by": "openai", "shutdown_date": None},
        {"id": "gpt-5.6-luna", "object": "model", "created": 1, "owned_by": "openai", "shutdown_date": None},
        {"id": "gpt-4.1-mini", "object": "model", "created": 1, "owned_by": "openai", "shutdown_date": None},
    ],
}
ACADEMIC_MODELS = {
    "object": "list",
    "data": [
        {"id": "qwen3-30b-a3b-instruct-2507", "status": "ready", "demand": 0, "object": "model"},
        {"id": "deepseek-v4-flash-0731", "status": "ready", "demand": 2, "object": "model"},
        {"id": "mistral-medium-3.5-128b", "status": "loading", "demand": 0, "object": "model"},
        {"id": "openai-gpt-oss-120b", "status": "ready", "demand": 5, "object": "model"},
    ],
}


def completion(
    text: str,
    *,
    reasoning: str | None = None,
    prompt_tokens: int = 20,
    completion_tokens: int = 4,
    cached_tokens: int = 0,
) -> dict:  # type: ignore[type-arg]
    """A chat completion as b-api returned it on 2026-09-17 (OpenAI shape with usage); ``cached_tokens`` the part of
    the prompt read from the prompt cache, as it reported on 2026-10-01."""
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-5.6-luna",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            **({"prompt_tokens_details": {"cached_tokens": cached_tokens}} if cached_tokens else {}),
        },
    }


class FakeBApi:
    """Answers chat completions and model lists; records every request body."""

    def __init__(
        self,
        responder: Callable[[dict[str, Any]], str] | None = None,
        *,
        statuses: list[int] | None = None,
        transport_failures: int = 0,
        models: dict[str, Any] | None = None,
        reasoning_only: bool = False,
        transport_error: Exception | None = None,
        raw: Any = None,
        cached_tokens: int = 0,
    ) -> None:
        self.responder = responder or (lambda body: "OK")
        self.statuses = list(statuses or [])
        self.transport_failures = transport_failures
        self.models = models if models is not None else OPENAI_MODELS
        self.reasoning_only = reasoning_only
        self.transport_error = transport_error or httpx.ConnectError("boom")
        self.raw = raw  # a complete 200 payload that replaces the well-formed completion
        self.cached_tokens = cached_tokens  # reported as read from the prompt cache
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.transport_failures:
            self.transport_failures -= 1
            raise self.transport_error
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=self.models)
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                return httpx.Response(status, json={"error": {"message": f"status {status}"}})
        if self.raw is not None:
            return httpx.Response(200, json=self.raw)
        text = self.responder(body)
        if self.reasoning_only:
            return httpx.Response(200, json=completion("", reasoning=text, cached_tokens=self.cached_tokens))
        return httpx.Response(200, json=completion(text, cached_tokens=self.cached_tokens))


def make_client(fake: FakeBApi, **kwargs: Any) -> tuple[BApiClient, list[float]]:
    sleeps: list[float] = []
    options: dict[str, Any] = {"provider": "openai", "model": "gpt-5.6-luna", "timeout_s": 30.0}
    options.update(kwargs)
    client = BApiClient(
        BASE,
        KEY,
        transport=httpx.MockTransport(fake),
        sleep=sleeps.append,
        backoff_s=1.5,
        attempts=3,
        jitter=lambda: 0.5,  # the backoff without its spread: 1.5 s, 3 s
        **options,
    )
    return client, sleeps


MESSAGES = [{"role": "system", "content": "Antworte nur mit OK."}, {"role": "user", "content": "Test"}]


def test_gpt5_request_uses_completion_tokens_reasoning_effort_and_verbosity() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)
    result = client.chat(MESSAGES, max_output_tokens=50)
    assert result.text == "OK"
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (20, 4, 24)
    request = fake.requests[0]
    assert request.url == f"{BASE}/api/v1/llm/openai/chat/completions"
    assert request.headers["x-api-key"] == KEY
    body = fake.bodies[0]
    assert body["model"] == "gpt-5.6-luna" and body["messages"] == MESSAGES
    assert body["max_completion_tokens"] == 50
    assert body["reasoning_effort"] == "low" and body["verbosity"] == "low"
    assert "temperature" not in body and "max_tokens" not in body


def test_gpt6_models_get_the_same_reasoning_request_as_gpt5() -> None:
    """Measured 2026-09-24: gpt-6-luna answers max_tokens with HTTP 400 and wants max_completion_tokens (D44)."""
    fake = FakeBApi()
    client, _ = make_client(fake, model="gpt-6-luna")
    client.chat(MESSAGES, max_output_tokens=50)
    body = fake.bodies[0]
    assert body["model"] == "gpt-6-luna" and body["max_completion_tokens"] == 50
    assert body["reasoning_effort"] == "low" and body["verbosity"] == "low"
    assert "temperature" not in body and "max_tokens" not in body
    assert client.completion_limit(100) > 100, "its thinking counts in the same limit"


def test_every_call_names_itself_anew_so_the_b_api_answers_it_anew() -> None:
    """D70: the b-api answers a request it has seen word for word from a store - the same id, the same text, 0.4
    instead of 3.8 s (measured 2026-10-01). A safety_identifier of its own makes every call new; ``user`` would do so
    too, but it also scattered the provider's prompt cache (0 instead of 3,600 cached tokens)."""
    fake = FakeBApi()
    client, _ = make_client(fake)
    client.chat(MESSAGES, max_output_tokens=50)
    client.chat(MESSAGES, max_output_tokens=50)
    first, second = (body["safety_identifier"] for body in fake.bodies)
    assert first and second and first != second
    assert all("user" not in body for body in fake.bodies)


def test_with_the_response_cache_allowed_a_call_carries_no_identifier() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake, response_cache=True)
    client.chat(MESSAGES, max_output_tokens=50)
    assert "safety_identifier" not in fake.bodies[0]


def test_classic_models_get_max_tokens_and_temperature_qwen3_without_thinking() -> None:
    fake = FakeBApi(models=ACADEMIC_MODELS)
    client, _ = make_client(fake, provider="academiccloud", model="qwen3-30b-a3b-instruct-2507", temperature=0.3)
    client.chat(MESSAGES, max_output_tokens=80)
    assert fake.requests[0].url.path == "/api/v1/llm/academiccloud/chat/completions"
    body = fake.bodies[0]
    assert body["max_tokens"] == 80 and body["temperature"] == 0.3
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in body and "max_completion_tokens" not in body

    fake = FakeBApi(models=ACADEMIC_MODELS)
    client, _ = make_client(fake, provider="academiccloud", model="mistral-medium-3.5-128b")
    client.chat(MESSAGES, max_output_tokens=80)
    assert "chat_template_kwargs" not in fake.bodies[0]


def test_text_falls_back_to_reasoning_when_content_is_empty() -> None:
    fake = FakeBApi(lambda body: "aus dem Denkfeld", reasoning_only=True)
    client, _ = make_client(fake)
    assert client.chat(MESSAGES, max_output_tokens=10).text == "aus dem Denkfeld"


def thought_only(thought: str, finish_reason: str) -> dict[str, Any]:
    """An answer with nothing but a thought, as some academiccloud models give it, and its usage."""
    payload: dict[str, Any] = completion("", prompt_tokens=900, completion_tokens=1500)
    payload["choices"][0]["message"] = {"role": "assistant", "content": None, "reasoning_content": thought}
    payload["choices"][0]["finish_reason"] = finish_reason
    return payload


@pytest.mark.parametrize(("finish_reason", "text"), [("stop", "Die Antwort ist 3."), ("length", "")])
def test_the_reasoning_field_is_the_answer_only_when_the_model_finished(finish_reason: str, text: str) -> None:
    """Cut off at the output limit, the field holds a thought, not an answer: the article choice read {"wahl": 3} from
    one and the synthesis printed thoughts as [Modellwissen] (audit 2026-09-29, L2)."""
    client, _ = make_client(FakeBApi(raw=thought_only("Die Antwort ist 3.", finish_reason)))

    result = client.chat(MESSAGES, max_output_tokens=10)

    assert result.text == text and result.finish_reason == finish_reason
    assert result.total_tokens == 2400, "the tokens of the thought count all the same"


def test_retries_with_backoff_on_429_and_503() -> None:
    fake = FakeBApi(statuses=[429, 503, 200])
    client, sleeps = make_client(fake)
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"
    assert len(fake.requests) == 3
    assert sleeps == [1.5, 3.0]


def test_other_http_errors_are_not_retried_and_keep_the_upstream_body_out_of_the_message() -> None:
    fake = FakeBApi(statuses=[400])
    client, sleeps = make_client(fake)
    with pytest.raises(LlmError) as info:
        client.chat(MESSAGES, max_output_tokens=10)
    assert info.value.status == 400
    assert len(fake.requests) == 1 and sleeps == []
    assert "status 400" not in str(info.value), "upstream error bodies reach /health and the frontmatter otherwise"


def test_a_key_with_surrounding_whitespace_is_stripped_and_an_invalid_one_rejected_without_echo() -> None:
    fake = FakeBApi()
    client = BApiClient(BASE, f"  {KEY}{chr(10)}", provider="openai", model="m", transport=httpx.MockTransport(fake))
    client.chat(MESSAGES, max_output_tokens=10)
    assert fake.requests[0].headers["x-api-key"] == KEY
    with pytest.raises(ValueError, match="B_API_KEY") as info:
        BApiClient(BASE, f"abc{chr(10)}def secret", provider="openai", model="m")
    assert "secret" not in str(info.value)


def test_transport_error_text_never_carries_the_key() -> None:
    """httpx quotes an illegal header value (the key) in its error text; messages reach logs, /health, frontmatter."""
    fake = FakeBApi(transport_failures=9, transport_error=httpx.LocalProtocolError(f"Illegal header value b'{KEY}'"))
    client, _ = make_client(fake)
    with pytest.raises(LlmError) as info:
        client.chat(MESSAGES, max_output_tokens=10)
    assert KEY not in str(info.value) and "LocalProtocolError" in str(info.value)
    fake.transport_failures = 9
    check = client.check_model()
    assert KEY not in check.message and not check.ok


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [{"message": "text instead of an object"}]},
        {"choices": [{"index": 0}], "usage": {}},
        ["not", "an", "object"],
        {"choices": [{"message": {"content": {"unexpected": "object"}}}]},
    ],
)
def test_malformed_success_payloads_become_llm_errors(payload: Any) -> None:
    client, _ = make_client(FakeBApi(raw=payload))
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)


@pytest.mark.parametrize("usage", [None, [1, 2], {"prompt_tokens": "n/a"}, {}])
def test_missing_or_broken_usage_is_estimated_so_the_budget_keeps_counting(usage: Any) -> None:
    payload = completion("Eine brauchbare Antwort mit Beleg [1].")
    payload["usage"] = usage
    client, _ = make_client(FakeBApi(raw=payload))
    result = client.chat(MESSAGES, max_output_tokens=10)
    assert result.text.startswith("Eine brauchbare Antwort")
    assert result.prompt_tokens > 0 and result.completion_tokens > 0
    assert result.total_tokens == result.prompt_tokens + result.completion_tokens


@pytest.mark.parametrize(
    ("details", "cached"),
    [
        ({"cached_tokens": 3481}, 3481),
        ({"cached_tokens": 99_999}, 3507),
        ({"cached_tokens": "viele"}, 0),
        ({}, 0),
        (None, 0),
    ],
)
def test_the_prompt_tokens_the_b_api_read_from_its_cache_are_reported(details: Any, cached: int) -> None:
    """The b-api passes the prompt cache of the model through: on 2026-10-01 a second call with the same opening of
    3,507 tokens read 3,481 of them from it. More than the prompt is no cache read, and a malformed count none."""
    payload = completion("Eine Antwort.", prompt_tokens=3507, completion_tokens=88)
    if details is not None:
        payload["usage"]["prompt_tokens_details"] = details
    client, _ = make_client(FakeBApi(raw=payload))
    assert client.chat(MESSAGES, max_output_tokens=10).cached_tokens == cached


def test_decoding_errors_are_llm_errors_and_timeouts_are_not_retried() -> None:
    fake = FakeBApi(transport_failures=9, transport_error=httpx.DecodingError("bad gzip"))
    client, _ = make_client(fake)
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    fake = FakeBApi(transport_failures=9, transport_error=httpx.ReadTimeout("slow"))
    client, sleeps = make_client(fake)
    with pytest.raises(LlmError) as info:
        client.chat(MESSAGES, max_output_tokens=10)
    assert len(fake.requests) == 1 and sleeps == [], "a request that timed out once will not answer in time on retry"
    assert "ReadTimeout" in str(info.value)


def test_circuit_breaker_fails_fast_after_a_connection_failure_and_recovers() -> None:
    now = [1000.0]
    fake = FakeBApi(transport_failures=3)
    client, _ = make_client(fake, clock=lambda: now[0])
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)
    assert len(fake.requests) == 3
    with pytest.raises(LlmError, match="ausgesetzt"):
        client.chat(MESSAGES, max_output_tokens=10)
    assert len(fake.requests) == 3, "no request while the breaker is open"
    now[0] += 61
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"


def test_transport_errors_exhaust_the_attempts() -> None:
    fake = FakeBApi(transport_failures=5)
    client, sleeps = make_client(fake)
    with pytest.raises(LlmError) as info:
        client.chat(MESSAGES, max_output_tokens=10)
    assert info.value.status is None
    assert len(fake.requests) == 3 and len(sleeps) == 2


def test_persistent_503_ends_in_an_error_with_the_status() -> None:
    fake = FakeBApi(statuses=[503, 503, 503])
    client, _ = make_client(fake)
    with pytest.raises(LlmError) as info:
        client.chat(MESSAGES, max_output_tokens=10)
    assert info.value.status == 503


def test_model_check_against_the_openai_list() -> None:
    client, _ = make_client(FakeBApi())
    check = client.check_model()
    assert check.ok and check.found and check.status is None and check.demand is None
    assert check.model == "gpt-5.6-luna"

    client, _ = make_client(FakeBApi(), model="gpt-5.7-nova")
    check = client.check_model()
    assert not check.ok and not check.found
    assert "gpt-5.7-nova" in check.message


def test_model_check_uses_status_and_demand_of_academiccloud() -> None:
    def check_for(model: str) -> Any:
        client, _ = make_client(FakeBApi(models=ACADEMIC_MODELS), provider="academiccloud", model=model)
        return client.check_model()

    ready = check_for("qwen3-30b-a3b-instruct-2507")
    assert ready.ok and ready.status == "ready" and ready.demand == 0
    assert check_for("deepseek-v4-flash-0731").ok
    loading = check_for("mistral-medium-3.5-128b")
    assert not loading.ok and loading.found and loading.status == "loading"
    busy = check_for("openai-gpt-oss-120b")
    assert not busy.ok and busy.demand == 5 and "demand" in busy.message


def test_model_check_reports_an_unreachable_api_instead_of_raising() -> None:
    fake = FakeBApi(transport_failures=5)
    client, sleeps = make_client(fake)
    check = client.check_model()
    assert not check.ok and not check.found
    assert len(fake.requests) == 1 and sleeps == [], "a health probe must not wait for chat retries"
    assert "boom" in check.message or "erreichbar" in check.message
    assert KEY not in check.message


def test_model_check_uses_a_short_timeout_chat_the_configured_one() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)  # timeout_s=30
    client.check_model()
    client.chat(MESSAGES, max_output_tokens=10)
    assert fake.requests[0].extensions["timeout"]["read"] == pytest.approx(10.0, abs=0.5)
    assert fake.requests[1].extensions["timeout"]["read"] == pytest.approx(30.0, abs=0.5)


def test_models_url_and_chat_url_follow_the_provider() -> None:
    client, _ = make_client(FakeBApi(), provider="academiccloud", model="x")
    assert client.chat_url == f"{BASE}/api/v1/llm/academiccloud/chat/completions"
    assert client.models_url == f"{BASE}/api/v1/llm/academiccloud/models"
