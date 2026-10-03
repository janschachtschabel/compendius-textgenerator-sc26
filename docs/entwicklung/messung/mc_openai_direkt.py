"""Measurement helper (not part of the service): the service's LLM client, sent straight to OpenAI.

Jan, 2026-10-03: extensive LLM tests run over the provider openai with gpt-6-luna, "gleiches verhalten wie bei der
b-api nur das wir eine andere abrechnung haben". The b-api passes the chat completions body through to OpenAI, so the
transport below forwards every request the service builds for /api/v1/llm/openai/... to https://api.openai.com/v1/...
with the key of OPENAI_API_KEY as a Bearer token. Use: run the measuring script with LLM_ENABLED=true, any
B_API_KEY and B_API_BASE_URL (they are never used), OPENAI_API_KEY passed through, and call install() before
build_service. The key is never printed.
"""

import os

import httpx

OPENAI = "https://api.openai.com/v1"
_DROPPED = {"x-api-key", "host", "content-length"}


class OpenAiDirect(httpx.BaseTransport):
    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self._key = os.environ["OPENAI_API_KEY"]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        tail = request.url.path.split("/llm/openai", 1)[-1]  # /chat/completions or /models
        headers = {name: value for name, value in request.headers.items() if name.lower() not in _DROPPED}
        headers["authorization"] = f"Bearer {self._key}"
        forwarded = httpx.Request(
            request.method, OPENAI + tail, params=request.url.params, headers=headers, content=request.read()
        )
        return self._inner.handle_request(forwarded)

    def close(self) -> None:
        self._inner.close()


def install() -> None:
    """Every BApiClient the app builds from now on sends to OpenAI."""
    import app.main as main_module
    from app.llm.client import BApiClient

    class DirectClient(BApiClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = OpenAiDirect()
            super().__init__(*args, **kwargs)

    main_module.BApiClient = DirectClient
