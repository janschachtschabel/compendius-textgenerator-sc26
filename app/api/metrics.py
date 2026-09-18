"""GET /metrics for Prometheus: runtime metrics of all workers plus the status read at scrape time.

A plain function, because the status reads SQLite and JSON files: FastAPI runs it in the threadpool. Each
scrape builds one registry, so the output has exactly one end marker in the OpenMetrics format, and the
format follows the scraper's Accept header. With ``PROMETHEUS_MULTIPROC_DIR`` set (the image's API command
sets it for its uvicorn workers) the runtime metrics are the sum over all workers.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Iterable

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import REGISTRY, CollectorRegistry
from prometheus_client.exposition import choose_encoder
from prometheus_client.metrics_core import Metric
from prometheus_client.multiprocess import MultiProcessCollector

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


@router.get(METRICS_PATH, include_in_schema=False)
def metrics(request: Request) -> Response:
    _check_token(request)
    registry = CollectorRegistry()
    multiprocess_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiprocess_dir:
        MultiProcessCollector(registry, path=multiprocess_dir)  # type: ignore[no-untyped-call]  # unannotated upstream
    else:
        registry.register(_Forward(REGISTRY))
    registry.register(StatusCollector(request.app.state))
    encoder, content_type = choose_encoder(request.headers.get("accept", ""))
    return Response(content=encoder(registry), media_type=content_type)
