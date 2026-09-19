"""Status gauges read at scrape time: archives, sidecar runs, curriculum cache, repository, LLM.

Everything here is read from the application state and the files the sidecars write, not counted in the
process, so every worker answers the same and nothing needs to be shared between workers. A value that is
not known (no sync ran yet, no cache) is left out instead of being reported as zero: an age computed from
a zero timestamp would look like a 56-year-old cache.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.metrics_core import Metric

from app import __version__
from app.jobs.zim_sync import read_status as read_zim_status
from app.sources.lehrplan.harvest import read_status as read_harvest_status

log = logging.getLogger(__name__)


def _gauge(name: str, documentation: str, value: float) -> GaugeMetricFamily:
    return GaugeMetricFamily(name, documentation, value=value)


def _timestamp(value: object) -> float | None:
    """Seconds since the epoch of an ISO timestamp, or ``None`` when absent or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _last_run(status: Mapping[str, Any] | None) -> Mapping[str, Any]:
    run = (status or {}).get("last_run")
    return run if isinstance(run, dict) else {}


class StatusCollector:
    """One scrape's view of the service state; ``state`` is the FastAPI ``app.state``."""

    def __init__(self, state: Any) -> None:
        self._state = state

    def collect(self) -> Iterator[Metric]:
        build = GaugeMetricFamily("kompendium_build_info", "Version of the service", labels=["version"])
        build.add_metric([__version__], 1)
        yield build
        for section in (self._archives, self._zim_sync, self._curricula, self._edu_sharing, self._llm):
            try:
                metrics = list(section())
            except Exception:  # one unreadable source must not fail the scrape and fire KompendiumDown
                log.exception("status section %s left out of this scrape", section.__name__)
                continue
            yield from metrics

    def _archives(self) -> Iterator[Metric]:
        registry = self._state.registry
        missing = registry.has_ids(self._state.required_ids)
        yield _gauge("kompendium_zim_archives", "Open ZIM archives", len(registry.archives))
        yield _gauge(
            "kompendium_zim_ready",
            "1 when all required archives are open (as GET /ready)",
            int(registry.ready and not missing),
        )
        yield _gauge("kompendium_zim_required_missing", "Required archives that are not open", len(missing))
        articles = GaugeMetricFamily("kompendium_zim_archive_articles", "Articles per open archive", labels=["archive"])
        for archive in registry.archives:
            articles.add_metric([archive.id], archive.article_count)
        yield articles

    def _zim_sync(self) -> Iterator[Metric]:
        status = read_zim_status(Path(self._state.settings.zim_dir))
        if status is None:
            return
        yield _gauge(
            "kompendium_zim_sync_running", "1 while the ZIM sync job runs", int(status.get("state") == "running")
        )
        updated = _timestamp(status.get("updated_at"))
        if updated is not None:  # a running job writes at every step and download progress; a dead one stops
            yield _gauge(
                "kompendium_zim_sync_status_updated_timestamp_seconds", "Last write of sync_status.json", updated
            )
        run = _last_run(status)
        finished = _timestamp(run.get("finished_at"))
        if finished is not None:
            yield _gauge("kompendium_zim_sync_last_run_timestamp_seconds", "End of the last ZIM sync run", finished)
            errors = run.get("errors")
            yield _gauge(
                "kompendium_zim_sync_last_run_errors",
                "Errors of the last ZIM sync run (catalog, download, hash)",
                len(errors) if isinstance(errors, list) else 0,
            )

    def _curricula(self) -> Iterator[Metric]:
        curricula = getattr(self._state, "curricula", None)
        store = curricula.store if curricula is not None else None
        available = store is not None and store.available
        yield _gauge(
            "kompendium_lehrplan_cache_available", "1 when lehrplan.db is present and readable", int(available)
        )
        if store is not None and available:
            harvested = _timestamp(store.meta().get("harvested_at"))
            if harvested is not None:
                yield _gauge(
                    "kompendium_lehrplan_cache_harvested_timestamp_seconds",
                    "Start of the harvest behind the cache",
                    harvested,
                )
        status = read_harvest_status(Path(self._state.settings.state_dir))
        if status is None:
            return
        yield _gauge(
            "kompendium_lehrplan_harvest_failed",
            "1 when the last curriculum harvest failed",
            int(status.get("state") == "error"),
        )
        finished = _timestamp(_last_run(status).get("finished_at"))
        if finished is not None:
            yield _gauge(
                "kompendium_lehrplan_harvest_last_run_timestamp_seconds", "End of the last successful harvest", finished
            )

    def _edu_sharing(self) -> Iterator[Metric]:
        yield _gauge(
            "kompendium_edu_sharing_enabled",
            "1 when an edu-sharing repository is configured",
            int(getattr(self._state, "collections", None) is not None),
        )

    def _llm(self) -> Iterator[Metric]:
        llm = getattr(self._state, "llm", None)
        yield _gauge(
            "kompendium_llm_enabled", "1 when the b-api is configured (LLM_ENABLED and B_API_KEY)", int(llm is not None)
        )
        if llm is None:
            yield _gauge("kompendium_llm_available", "1 when hybrid modes can use the LLM now", 0)
            return
        status = llm.status()  # the last known check and the shared daily counter; never calls the b-api
        yield _gauge(
            "kompendium_llm_available", "1 when hybrid modes can use the LLM now", int(bool(status["available"]))
        )
        budget = status["budget"]
        yield _gauge("kompendium_llm_tokens_used_today", "LLM tokens spent today, all workers", budget["used_today"])
        yield _gauge(
            "kompendium_llm_daily_budget_tokens", "Daily LLM token budget (LLM_DAILY_TOKEN_BUDGET)", budget["daily"]
        )
