"""GET /metrics for Prometheus: runtime metrics of all workers plus the status read at scrape time.

The status reads SQLite and JSON files, so the output is built in the monitoring threads
(app/api/system_threads.py): a scrape answers while compendium requests hold the default threads. Each
scrape builds one registry, so the output has exactly one end marker in the OpenMetrics format, and the
format follows the scraper's Accept header. With ``PROMETHEUS_MULTIPROC_DIR`` set (the image's API command
sets it for its uvicorn workers) the runtime metrics are the sum over all workers.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import REGISTRY, CollectorRegistry
from prometheus_client.exposition import choose_encoder
from prometheus_client.metrics_core import Metric
from prometheus_client.multiprocess import MultiProcessCollector

from app.api.system_threads import run_system
from app.observability.status import StatusCollector

METRICS_PATH = "/metrics"

router = APIRouter(tags=["system"])


class _Forward:
    """Hands the process-wide registry's metrics to the per-scrape registry (single-process mode)."""

    def __init__(self, source: CollectorRegistry) -> None:
        self._source = source

    def collect(self) -> Iterable[Metric]:
        return self._source.collect()


def _check_token(request: Request) -> None:
    expected: str = request.app.state.settings.metrics_token
    if not expected:
        return
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(credentials.encode(), expected.encode()):
        raise HTTPException(
            status_code=401, detail="Metriken nur mit gültigem Token.", headers={"WWW-Authenticate": "Bearer"}
        )


def _render(state: Any, accept: str) -> tuple[bytes, str]:
    registry = CollectorRegistry()
    multiprocess_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiprocess_dir:
        MultiProcessCollector(registry, path=multiprocess_dir)  # type: ignore[no-untyped-call]  # unannotated upstream
    else:
        registry.register(_Forward(REGISTRY))
    registry.register(StatusCollector(state))
    encoder, content_type = choose_encoder(accept)
    return encoder(registry), content_type


@router.get(METRICS_PATH, include_in_schema=False)
async def metrics(request: Request) -> Response:
    _check_token(request)
    content, content_type = await run_system(request, _render, request.app.state, request.headers.get("accept", ""))
    return Response(content=content, media_type=content_type)
