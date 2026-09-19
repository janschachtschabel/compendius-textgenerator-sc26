"""Full harvest of MEM curricula into the local cache (PLAN.md 5.2, decision D16).

Curricula are never fetched at inference time. The harvest asks all sixteen states (coverage grows as
MEM publishes more), lists each state's curricula, reads their head fields in VALUES chunks, fetches
the closure of every curriculum in one query, resolves node roles through the ontology and writes
everything into a new SQLite file that replaces the old one only on success. Measured 2026-09-17:
list 0.2 s per state, heads 0.5 s per 40 curricula, closure 0.3-4 s per curriculum; a full run takes
25 minutes for 2,514 curricula and 295,184 nodes (2,605 requests).
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.jobs.lock import LockHeldError, acquire_lock
from app.sources.lehrplan import queries
from app.sources.lehrplan.store import LehrplanRecord, LehrplanStore, LehrplanWriter
from app.sources.lehrplan.tree import ClassInfo, build_class_index, build_nodes
from app.sources.lehrplan.vocab import (
    BUNDESLAENDER,
    MAX_TREE_DEPTH,
    ONTOLOGY,
    ONTOLOGY_VERSION,
    ROLE_UNBEKANNT,
    Bundesland,
    bundesland_by_iri,
)
from app.sources.zim.active import atomic_write_text

log = logging.getLogger(__name__)

STATUS_FILE = "lehrplan_status.json"
TRIGGER_FILE = "lehrplan.request"
LOCK_FILE = "lehrplan.harvest.lock"
LOCK_STALE_S = 4 * 3600  # a harvest takes about 15 minutes; an older lock belongs to a crashed run
CHUNK_SIZE = 40
PAGE_SIZE = 500
PROGRESS_EVERY = 20

# Alternate grade labels such as "jg5" beside "Jahrgangsstufe 5" (RP, BY)
_SHORT_GRADE = re.compile(r"^jg\d+$", re.IGNORECASE)
# Berlin appends the vocabulary to its subject labels: "Physik (KIM-Schulfach)", "Physik (KIM)"
_SUBJECT_SUFFIX = re.compile(r"\s*\((KIM-Schulfach|KIM|Schulfach)\)\s*$")


class SparqlLike(Protocol):
    endpoint: str

    def select(self, query: str) -> list[dict[str, str]]: ...


class HarvestRunningError(RuntimeError):
    """Another harvest holds the lock file; two writers would corrupt the cache."""


@dataclass
class HarvestReport:
    started_at: str
    finished_at: str
    lehrplaene: dict[str, int] = field(default_factory=dict)
    nodes: int = 0
    unknown_classes: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    max_depth: int = 0
    queries: int = 0
    duration_s: float = 0.0


def read_status(state_dir: Path) -> dict[str, Any] | None:
    """Last status the harvest wrote, or ``None`` when there is none (or it is unreadable)."""
    path = Path(state_dir) / STATUS_FILE
    if not path.exists():
        return None
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    except (OSError, ValueError) as exc:
        log.warning("cannot read %s: %s", path, exc)
        return None


def _tidy(text: str) -> str:
    """Plain text with single spaces: MEM labels carry HTML entities such as ``&nbsp;`` and ``&#x2011;``."""
    return " ".join(html.unescape(text).split())


def _clean_labels(field_name: str, labels: Iterable[str]) -> list[str]:
    cleaned: set[str] = set()
    for label in labels:
        text = _tidy(label)
        if field_name == "jahrgangsstufe" and _SHORT_GRADE.match(text):
            continue
        if field_name == "schulfach":
            text = _SUBJECT_SUFFIX.sub("", text)
        if text:
            cleaned.add(text)
    return sorted(cleaned)


class LehrplanHarvest:
    """One full harvest run plus the cheap weekly change check."""

    def __init__(
        self,
        client: SparqlLike,
        db_path: Path,
        *,
        state_dir: Path | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        states: Sequence[Bundesland] = BUNDESLAENDER,
    ) -> None:
        self._client = client
        self._db_path = Path(db_path)
        self._state_dir = Path(state_dir) if state_dir is not None else self._db_path.parent
        self._clock = clock
        self._states = tuple(states)
        self._queries = 0
        self._skipped: list[str] = []

    @property
    def store(self) -> LehrplanStore:
        return LehrplanStore(self._db_path)

    # --- change detection ------------------------------------------------------------------------

    def remote_counts(self) -> dict[str, int]:
        """Curricula per state code as the endpoint counts them right now (one query)."""
        counts: dict[str, int] = {}
        for row in self._select(queries.count_lehrplaene()):
            land = bundesland_by_iri(row.get("bl", ""))
            if land is not None:
                counts[land.code] = int(row.get("n", "0"))
        return counts

    def local_counts(self) -> dict[str, int]:
        raw = self.store.meta().get("counts")
        loaded: dict[str, int] = json.loads(raw) if raw else {}
        return loaded

    def check(self) -> dict[str, Any]:
        """Compare the endpoint's per-state counts with the last harvest (PLAN.md 5.2, weekly)."""
        remote, local = self.remote_counts(), self.local_counts()
        return {"changed": remote != local, "remote": remote, "local": local}

    def due(self, *, max_age: timedelta) -> bool:
        """A harvest is due without a usable cache, with a cache older than ``max_age`` or when MEM changed."""
        if not self.store.available:
            return True
        harvested_at = self.store.meta().get("harvested_at")
        if not harvested_at:
            return True
        if self._clock() - datetime.fromisoformat(harvested_at) >= max_age:
            return True
        changed: bool = self.check()["changed"]
        return changed

    # --- the harvest -----------------------------------------------------------------------------

    def run(self) -> HarvestReport:
        """Harvest all states into a fresh cache file; on any error the previous file stays.

        Only one harvest may run per state directory (``HarvestRunningError`` otherwise).
        """
        lock = self._acquire_lock()
        try:
            return self._run()
        finally:
            lock.unlink(missing_ok=True)

    def _acquire_lock(self) -> Path:
        try:
            return acquire_lock(
                self._state_dir / LOCK_FILE,
                stale_s=LOCK_STALE_S,
                now=lambda: self._clock().timestamp(),
                owner=f"pid {os.getpid()}\nstarted {self._clock().isoformat()}\n",
            )
        except LockHeldError as exc:
            raise HarvestRunningError(f"Ein Harvest läuft bereits ({exc.path}, seit {exc.age_s:.0f} s)") from None

    def _run(self) -> HarvestReport:
        started = self._clock()
        wall = time.perf_counter()
        self._queries = 0
        self._skipped = []
        per_state: dict[str, int] = {}
        nodes_total = 0
        unknown: Counter[str] = Counter()
        max_depth = 0
        class_index: dict[str, ClassInfo] = {}
        asked_types: set[str] = set()
        self._write_status("running", started_at=started.isoformat(), progress={})
        writer: LehrplanWriter | None = None
        try:
            writer = LehrplanWriter(self._db_path)
            for land in self._states:
                listed = self._list(land.iri)
                if not listed:
                    continue
                per_state[land.code] = len(listed)
                heads = self._heads([iri for iri, _label in listed])
                for done, (iri, label) in enumerate(listed, start=1):
                    fields = heads.get(iri, {})
                    writer.add_lehrplan(
                        LehrplanRecord(
                            iri=iri,
                            label=label,
                            bundesland_code=land.code,
                            bundesland=land.name,
                            schularten=_clean_labels("schulart", fields.get("schulart", [])),
                            schulfaecher=_clean_labels("schulfach", fields.get("schulfach", [])),
                            jahrgangsstufen=_clean_labels("jahrgangsstufe", fields.get("jahrgangsstufe", [])),
                            schulstufen=_clean_labels("schulstufe", fields.get("schulstufe", [])),
                        )
                    )
                    rows = self._select(queries.closure(iri))
                    for row in rows:
                        if row.get("label"):
                            row["label"] = _tidy(row["label"])
                    self._extend_class_index(rows, class_index, asked_types)
                    nodes = build_nodes(rows, class_index)
                    for node in nodes:
                        node.jahrgangsstufen = _clean_labels("jahrgangsstufe", node.jahrgangsstufen)
                        if node.rollen == [ROLE_UNBEKANNT]:
                            unknown.update(node.types)
                    deepest = max((node.depth for node in nodes), default=0)
                    if deepest >= MAX_TREE_DEPTH - 1:
                        log.warning("%s reaches the transitive bound (depth %d); deeper parts may be cut", iri, deepest)
                    max_depth = max(max_depth, deepest)
                    writer.add_nodes(iri, nodes)
                    nodes_total += len(nodes)
                    if done % PROGRESS_EVERY == 0:
                        self._write_status(
                            "running",
                            started_at=started.isoformat(),
                            progress={
                                "state": land.code,
                                "lehrplaene_done": done,
                                "of": len(listed),
                                "nodes": nodes_total,
                            },
                        )
                log.info("harvested %s: %d curricula, %d nodes so far", land.code, len(listed), nodes_total)
            finished = self._clock()
            writer.set_meta(
                {
                    "harvested_at": started.isoformat(),
                    "finished_at": finished.isoformat(),
                    "endpoint": self._client.endpoint,
                    "ontology_version": ONTOLOGY_VERSION,
                    "counts": json.dumps(per_state),
                    "nodes": str(nodes_total),
                    "max_depth": str(max_depth),
                }
            )
            writer.commit()
        except BaseException as exc:  # also Ctrl+C: the status must not stay "running"
            if writer is not None:
                writer.abort()
            self._write_status("error", started_at=started.isoformat(), error=f"{type(exc).__name__}: {exc}")
            raise
        report = HarvestReport(
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            lehrplaene=per_state,
            nodes=nodes_total,
            unknown_classes=dict(unknown.most_common()),
            skipped=list(self._skipped),
            max_depth=max_depth,
            queries=self._queries,
            duration_s=round(time.perf_counter() - wall, 1),
        )
        self._write_status("idle", last_run=asdict(report))
        return report

    def _select(self, query: str) -> list[dict[str, str]]:
        self._queries += 1
        return self._client.select(query)

    def _list(self, land_iri: str) -> list[tuple[str, str]]:
        listed: list[tuple[str, str]] = []
        offset = 0
        while True:
            rows = self._select(queries.lehrplan_list(land_iri, limit=PAGE_SIZE, offset=offset))
            for row in rows:
                iri = row.get("s")
                if not iri:
                    continue
                try:
                    queries.validate_iri(iri)
                except ValueError as exc:
                    log.warning("skipping curriculum with an unusable IRI: %s", exc)
                    self._skipped.append(iri)
                    continue
                listed.append((iri, _tidy(row.get("label") or "") or iri))
            if len(rows) < PAGE_SIZE:
                return listed
            offset += PAGE_SIZE

    def _heads(self, iris: Sequence[str]) -> dict[str, dict[str, list[str]]]:
        heads: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for start in range(0, len(iris), CHUNK_SIZE):
            for row in self._select(queries.lehrplan_heads(iris[start : start + CHUNK_SIZE])):
                if row.get("s") and row.get("field") and row.get("label"):
                    heads[row["s"]][row["field"]].append(row["label"])
        return heads

    def _extend_class_index(self, rows: Sequence[dict[str, str]], index: dict[str, ClassInfo], asked: set[str]) -> None:
        """Ask the ontology about node classes not seen before (only its own namespace can carry roles)."""
        fresh = sorted(
            {
                iri
                for row in rows
                for iri in row.get("types", "").split(queries.SEPARATOR)
                if iri.startswith(ONTOLOGY) and iri not in asked
            }
        )
        for start in range(0, len(fresh), CHUNK_SIZE):
            chunk = fresh[start : start + CHUNK_SIZE]
            index.update(build_class_index(self._select(queries.class_roles(chunk))))
            asked.update(chunk)

    def _write_status(self, state: str, **fields: Any) -> None:
        previous = read_status(self._state_dir) or {}
        payload = {
            "state": state,
            "updated_at": self._clock().isoformat(),
            "started_at": fields.get("started_at", previous.get("started_at")),
            "progress": fields.get("progress", previous.get("progress")),
            "last_run": fields.get("last_run", previous.get("last_run")),
            "error": fields.get("error"),
        }
        try:
            atomic_write_text(self._state_dir / STATUS_FILE, json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError as exc:
            log.warning("cannot write %s: %s", STATUS_FILE, exc)
