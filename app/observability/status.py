"""Status gauges read at scrape time: archives, sidecar runs, curriculum cache, Wikidata and GND index, free space
of the volumes, LLM.

Everything here is read from the application state and the files the sidecars write, not counted in the
process, so every worker answers the same and nothing needs to be shared between workers. A value that is
not known (no sync ran yet, no cache) is left out instead of being reported as zero: an age computed from
a zero timestamp would look like a 56-year-old cache.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.metrics_core import Metric

from app import __version__, revision
from app.jobs.runner import last_alive
from app.jobs.zim_sync import ALIVE_FILE as ZIM_ALIVE_FILE
from app.jobs.zim_sync import read_status as read_zim_status
from app.sources.gnd.sync import read_status as read_gnd_status
from app.sources.lehrplan.harvest import ALIVE_FILE as LEHRPLAN_ALIVE_FILE
from app.sources.lehrplan.harvest import read_status as read_harvest_status
from app.sources.wikidata.sync import read_status as read_wikidata_status

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


def _index_gauges(name: str, index: Any, dated: str, status: Mapping[str, Any] | None) -> Iterator[Metric]:
    """A local index a sidecar keeps (D64, D65): there and readable, the date of what it was built from (the meta
    key ``dated``), and whether the sidecar's last run failed and when it ended - left out before its first run.

    Every daily check writes its end, one without a build too, so an old end means a sidecar that stopped (audit
    2026-09-27, BE-07); the date of the index says nothing about that, as it changes only with a newer source."""
    available = index is not None and index.available
    yield _gauge(f"kompendium_{name}_index_available", f"1 when {name}.db is present and readable", int(available))
    if index is not None and available and (day := index.meta().get(dated)):
        stamp = _timestamp(f"{day}T00:00:00+00:00")
        if stamp is not None:
            yield _gauge(
                f"kompendium_{name}_index_{dated}_timestamp_seconds", f"Date of the {dated} behind the index", stamp
            )
    if status is not None:
        run = _last_run(status)
        yield _gauge(
            f"kompendium_{name}_sync_failed", f"1 when the last {name} sync run failed", int(run.get("ok") is False)
        )
        finished = _timestamp(run.get("finished_at"))
        if finished is not None:  # a build under way keeps the run before it in the status
            yield _gauge(
                f"kompendium_{name}_sync_last_run_timestamp_seconds",
                f"End of the last {name} sync run or check",
                finished,
            )


def _alive_gauge(job: str, path: Path) -> Iterator[Metric]:
    """The last sign of life of a job loop (app/jobs/runner.py), left out before the first one."""
    alive = last_alive(path)
    if alive is not None:
        yield _gauge(
            f"kompendium_{job}_alive_timestamp_seconds",
            "Last sign of life of the loop; it writes one at least hourly while it waits",
            alive.timestamp(),
        )


class StatusCollector:
    """One scrape's view of the service state; ``state`` is the FastAPI ``app.state``."""

    def __init__(self, state: Any) -> None:
        self._state = state

    def collect(self) -> Iterator[Metric]:
        build = GaugeMetricFamily(
            "kompendium_build_info", "Version and commit of the service", labels=["version", "revision"]
        )
        build.add_metric([__version__, revision() or ""], 1)
        yield build
        # A failing section is left out of the scrape, and the alerts on its gauges then stay silent: the failure
        # itself is a gauge of its own (KompendiumStatusIncomplete)
        failed = GaugeMetricFamily(
            "kompendium_status_section_failed", "1 when a status section could not be read", labels=["section"]
        )
        sections = (
            ("archives", self._archives),
            ("zim_sync", self._zim_sync),
            ("curricula", self._curricula),
            ("wikidata", self._wikidata),
            ("gnd", self._gnd),
            ("volumes", self._volumes),
            ("edu_sharing", self._edu_sharing),
            ("llm", self._llm),
        )
        for name, section in sections:
            try:
                metrics = list(section())
            except Exception:  # one unreadable source must not fail the scrape and fire KompendiumDown
                log.exception("status section %s left out of this scrape", name)
                failed.add_metric([name], 1)
                continue
            failed.add_metric([name], 0)
            yield from metrics
        yield failed

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
        yield from _alive_gauge("zim_sync", Path(self._state.settings.zim_dir) / ZIM_ALIVE_FILE)
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
        if finished is None:  # a run is in progress: report the last one that finished
            earlier = status.get("last_finished")
            run = earlier if isinstance(earlier, dict) else {}
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
        yield from _alive_gauge("lehrplan_harvest", Path(self._state.settings.state_dir) / LEHRPLAN_ALIVE_FILE)
        status = read_harvest_status(Path(self._state.settings.state_dir))
        if status is None:
            return
        # the last finished run, also while the next one runs: the state alone was 1 for an hour after a failure and
        # 0 again with the retry, and the alert missed a harvest that failed every hour (audit 2026-09-28, BE-11);
        # and the last check, which fails before any run when MEM is out of reach (audit 2026-09-29, Q3)
        failed = status.get("state") == "error" or bool(status.get("last_error")) or bool(status.get("check_error"))
        yield _gauge(
            "kompendium_lehrplan_harvest_failed", "1 when the last curriculum harvest or its check failed", int(failed)
        )
        finished = _timestamp(_last_run(status).get("finished_at"))
        if finished is not None:
            yield _gauge(
                "kompendium_lehrplan_harvest_last_run_timestamp_seconds", "End of the last successful harvest", finished
            )

    def _wikidata(self) -> Iterator[Metric]:
        status = read_wikidata_status(Path(self._state.settings.state_dir))
        yield from _index_gauges("wikidata", getattr(self._state, "wikidata", None), "dump", status)

    def _gnd(self) -> Iterator[Metric]:
        status = read_gnd_status(Path(self._state.settings.state_dir))
        yield from _index_gauges("gnd", getattr(self._state, "gnd", None), "release", status)

    def _volumes(self) -> Iterator[Metric]:
        # A full volume stops the syncs and at last even their status files (audit 2026-09-27, BE-07)
        free = GaugeMetricFamily(
            "kompendium_volume_free_bytes", "Bytes free for the service on the disk of a volume", labels=["volume"]
        )
        settings = self._state.settings
        for volume, directory in (("zim", settings.zim_dir), ("state", settings.state_dir)):
            # Without the directory (development with ZIM_PATHS) a parent's free space would pass for the volume's
            if Path(directory).is_dir():
                free.add_metric([volume], shutil.disk_usage(directory).free)
        yield free

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
            yield _gauge("kompendium_llm_available", "1 when the LLM switches can use the LLM now", 0)
            return
        status = llm.status()  # the last known check and the shared daily counter; never calls the b-api
        yield _gauge(
            "kompendium_llm_available",
            "1 when the LLM switches can use the LLM now",
            int(bool(status["available"])),
        )
        budget = status["budget"]
        yield _gauge("kompendium_llm_tokens_used_today", "LLM tokens spent today, all workers", budget["used_today"])
        yield _gauge(
            "kompendium_llm_daily_budget_tokens", "Daily LLM token budget (LLM_DAILY_TOKEN_BUDGET)", budget["daily"]
        )
