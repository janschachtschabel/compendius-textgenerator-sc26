"""SPARQL SELECT client for the MEM endpoint (Virtuoso), the harvest's only door to the network.

Form-encoded POST as the endpoint expects it, rows flattened to ``{variable: value}``, a pause between
requests (PLAN.md 5.2: one to two requests per second), retries with backoff for dropped connections
and transient HTTP errors, and no retry for a refused query: a 400 is our query, a 500 is Virtuoso
failing the same query again (transitive temp memory), and both need a person, not a loop.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.sources.lehrplan.vocab import DEFAULT_ENDPOINT

log = logging.getLogger(__name__)

USER_AGENT = "compendious-text-fastapi/2.0 (+https://wirlernenonline.de; Kompendium-Lehrplanbezuege)"
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_PAUSE_S = 0.5
DEFAULT_ATTEMPTS = 3
BACKOFF_S = 1.5
TRANSIENT_STATUS = {429, 502, 503, 504}
_BODY_EXCERPT = 300


class SparqlError(RuntimeError):
    """The endpoint could not be reached, refused the query or answered something unusable."""


class SparqlClient:
    """Executes SELECT queries; ``transport``, ``sleep`` and ``clock`` are test seams."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        pause_s: float = DEFAULT_PAUSE_S,
        attempts: int = DEFAULT_ATTEMPTS,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.endpoint = endpoint
        self._pause_s = pause_s
        self._attempts = max(1, attempts)
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout_s,
            headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
        )

    def close(self) -> None:
        self._client.close()

    def select(self, query: str) -> list[dict[str, str]]:
        """Rows as ``{variable: value}``; unbound OPTIONAL variables are absent from the row."""
        document = self._post(query)
        try:
            bindings = document["results"]["bindings"]
            return [{name: cell["value"] for name, cell in row.items()} for row in bindings]
        except (KeyError, TypeError, AttributeError) as exc:
            raise SparqlError("Antwort des MEM-Endpunkts ist kein SPARQL-JSON-Ergebnis") from exc

    def _pace(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = self._pause_s - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
                now += wait  # the request leaves after the pause; the next one is paced from then
        self._last_request = now

    def _post(self, query: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            self._pace()
            try:
                response = self._client.post(self.endpoint, data={"query": query})
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("MEM endpoint unreachable (attempt %d/%d): %s", attempt, self._attempts, exc)
            else:
                if response.status_code in TRANSIENT_STATUS:
                    last_error = SparqlError(f"HTTP {response.status_code} von {self.endpoint}")
                    log.warning(
                        "MEM endpoint answered %d (attempt %d/%d)", response.status_code, attempt, self._attempts
                    )
                elif response.status_code >= 400:
                    body = response.text[:_BODY_EXCERPT]
                    raise SparqlError(f"HTTP {response.status_code} von {self.endpoint}: {body}")
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise SparqlError("Antwort des MEM-Endpunkts ist kein JSON") from exc
            if attempt < self._attempts:
                self._sleep(BACKOFF_S * attempt)
        raise SparqlError(f"MEM-Endpunkt {self.endpoint} nicht erreichbar: {last_error}") from last_error
