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

from app.files import atomic_write_text
from app.locks import HeldLock, LockHeldError, acquire_lock
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

log = logging.getLogger(__name__)

STATUS_FILE = "lehrplan_status.json"
TRIGGER_FILE = "lehrplan.request"
ALIVE_FILE = "lehrplan_alive"  # the sign of life of the harvest loop (app/jobs/runner.py)
LOCK_FILE = "lehrplan.harvest.lock"
LOCK_STALE_S = 4 * 3600  # a harvest takes about 15 minutes; an older lock belongs to a crashed run
CHUNK_SIZE = 40
PAGE_SIZE = 500
PROGRESS_EVERY = 20
# Curricula whose element query came back empty twice although the cache held elements for them, taken without
# a refusal (audit 2026-09-28, KO-20). simplify: no measured bound - MEM has not yet emptied a curriculum on
# purpose; more such curricula in one run point to a reload, and an operator who knows better forces the run.
EMPTIED_TOLERATED = 2

# Alternate grade labels such as "jg5" beside "Jahrgangsstufe 5" (RP, BY)
_SHORT_GRADE = re.compile(r"^jg\d+$", re.IGNORECASE)
# Berlin appends the vocabulary to its subject labels: "Physik (KIM-Schulfach)", "Physik (KIM)"
_SUBJECT_SUFFIX = re.compile(r"\s*\((KIM-Schulfach|KIM|Schulfach)\)\s*$")


class SparqlLike(Protocol):
    endpoint: str

    def select(self, query: str) -> list[dict[str, str]]: ...


class HarvestRunningError(RuntimeError):
    """Another harvest holds the lock file; two writers would corrupt the cache."""


class HarvestRefusedError(RuntimeError):
    """The run found far less than the cache holds; the cache stays, ``force`` takes the result anyway."""


def lost_states(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """States of ``before`` that ``after`` lacks or keeps less than half the curricula of.

    MEM's Virtuoso answers with HTTP 200 and no rows while it reloads a graph, and ``due`` starts a harvest exactly
    when MEM's counts change; a run during a reload lists a state as empty or short (audit 2026-09-27, KO-01).
    simplify: half is no measured bound - MEM has not yet withdrawn a large share of a state's curricula; an operator
    who sees it happen takes the result with ``compendium lehrplan harvest --force``.
    """
    return sorted(code for code, count in before.items() if after.get(code, 0) * 2 < count)


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
    emptied: list[str] = field(default_factory=list)  # curricula without elements now, with some in the cache before
    duration_s: float = 0.0


def read_status(state_dir: Path) -> dict[str, Any] | None:
    """Last status the harvest wrote, or ``None`` when there is none (or it is unreadable)."""
    path = Path(state_dir) / STATUS_FILE
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("cannot read %s: %s", path, exc)
        return None
    if not isinstance(loaded, dict):  # every reader expects the object the job writes
        log.warning("%s holds no JSON object; ignored", path)
        return None
    return loaded


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
        self._lock: HeldLock | None = None

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
        """A harvest is due without a usable cache, with broken pages in it, with a cache older than ``max_age`` or
        when MEM changed. A crash right after a swap could leave broken pages behind readable meta rows: every search
        failed, and nothing harvested again for up to 30 days (audit 2026-09-28, DB-02)."""
        if not self.store.available or not self.store.intact():
            return True
        harvested_at = self.store.meta().get("harvested_at")
        if not harvested_at:
            return True
        if self._clock() - datetime.fromisoformat(harvested_at) >= max_age:
            return True
        try:
            changed: bool = self.check()["changed"]
        except Exception as exc:
            self._record_check(exc)
            raise
        self._record_check(None)
        return changed

    def _record_check(self, error: Exception | None) -> None:
        """A check that failed goes to the status as ``check_error``, which the gauge and its alert see as they see a
        failed run - four weeks of an unreachable MEM wrote nothing (audit 2026-09-29, Q3); a good check clears it, as
        those of the Wikidata and GND syncs do. A run's error stays for a run that succeeds, or the next run would start
        with the gauge at 0 (BE-11). While a run holds the lock the check writes nothing: the run writes its outcome."""
        failure = None if error is None else f"{type(error).__name__}: {error}"
        try:
            lock = self._acquire_lock()
        except HarvestRunningError:
            return
        except OSError as exc:  # the check's own outcome goes on to the caller either way
            log.warning("cannot record the check in %s: %s", STATUS_FILE, exc)
            return
        try:
            previous = read_status(self._state_dir)
            if (previous or {}).get("check_error") != failure:
                update = {"updated_at": self._clock().isoformat(), "check_error": failure}
                self._save_status({**(previous or {"state": "idle"}), **update})
        finally:
            lock.release()

    # --- the harvest -----------------------------------------------------------------------------

    def run(self, *, force: bool = False) -> HarvestReport:
        """Harvest all states into a fresh cache file; on any error the previous file stays.

        Only one harvest may run per state directory (``HarvestRunningError`` otherwise). A run that lists no
        curriculum at all, loses a state of the cache or most of its elements (``lost_states``), or twice gets no answer
        about the roles of element classes or the head fields the cache holds, keeps the previous file and raises
        ``HarvestRefusedError``, unless it is forced.
        """
        self._lock = self._acquire_lock()
        try:
            return self._run(force=force)
        finally:
            self._lock.release()
            self._lock = None

    def _acquire_lock(self) -> HeldLock:
        try:
            return acquire_lock(
                self._state_dir / LOCK_FILE,
                stale_s=LOCK_STALE_S,
                now=lambda: self._clock().timestamp(),
                owner=f"pid {os.getpid()}\nstarted {self._clock().isoformat()}\n",
            )
        except LockHeldError as exc:
            raise HarvestRunningError(f"Ein Harvest läuft bereits ({exc.path}, seit {exc.age_s:.0f} s)") from None

    def _run(self, *, force: bool) -> HarvestReport:
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
        nodes_per_state: Counter[str] = Counter()
        matchable_per_state: Counter[str] = Counter()
        emptied: list[str] = []
        try:
            if not force:
                self._refuse_a_counted_loss()
            before = self.store.nodes_per_lehrplan()
            had_heads = self.store.lehrplaene_with_heads()
            writer = LehrplanWriter(self._db_path)
            for land in self._states:
                listed = self._list(land.iri)
                if not listed:
                    continue
                per_state[land.code] = len(listed)
                heads = self._heads([iri for iri, _label in listed], had_heads=had_heads, force=force)
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
                    if not rows and before.get(iri):
                        # Virtuoso answers with no rows while it reloads, and the reload may begin after the list of
                        # the state: asked once more, and still empty it is counted (audit 2026-09-28, KO-20)
                        rows = self._select(queries.closure(iri))
                        if not rows:
                            emptied.append(iri)
                    for row in rows:
                        if row.get("label"):
                            row["label"] = _tidy(row["label"])
                    self._extend_class_index(rows, class_index, asked_types, force=force)
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
                    nodes_per_state[land.code] += len(nodes)
                    matchable_per_state[land.code] += sum(1 for node in nodes if node.matchable)
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
            if not force:
                self._refuse_a_loss(per_state, dict(nodes_per_state), dict(matchable_per_state), emptied)
            elif emptied:
                log.warning("forced harvest takes %d curricula without their elements: %s", len(emptied), emptied)
            finished = self._clock()
            writer.set_meta(
                {
                    "harvested_at": started.isoformat(),
                    "finished_at": finished.isoformat(),
                    "endpoint": self._client.endpoint,
                    "ontology_version": ONTOLOGY_VERSION,
                    "counts": json.dumps(per_state),
                    "nodes": str(nodes_total),
                    "nodes_per_state": json.dumps(dict(nodes_per_state)),
                    "max_depth": str(max_depth),
                }
            )
            writer.commit()
        except BaseException as exc:  # also Ctrl+C: the status must not stay "running"
            if writer is not None:
                writer.abort()
            if isinstance(exc, KeyboardInterrupt):
                # A stopped container is no failed harvest, as in the ZIM and dump syncs (KO-13): it fired
                # KompendiumLehrplanHarvestFailed after an hour stopped (logging review of 2026-10-08)
                log.info("harvest stopped; the next start checks MEM again")
                self._write_status("idle", started_at=started.isoformat())
            else:
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
            emptied=emptied,
        )
        self._write_status("idle", last_run=asdict(report))
        return report

    def _refuse_a_counted_loss(self) -> None:
        """Refuse before anything is pulled when MEM's own count already shows a loss: the check after the run came
        after about 2,600 queries in 25 minutes, and a loop that retried hourly pulled MEM 17 times a day while it
        listed less (audit 2026-09-28, BE-11). One query; the check after the run stays."""
        if not self.store.available:
            return
        before, remote = self.local_counts(), self.remote_counts()
        lost = lost_states(before, remote)
        if before and (not remote or lost):
            detail = ", ".join(f"{code} {remote.get(code, 0)} statt {before[code]}" for code in lost) or "keinen"
            raise HarvestRefusedError(
                f"MEM zählt deutlich weniger Lehrpläne als der Cache hält ({detail}); der bisherige Cache bleibt, "
                "nichts wurde abgerufen (übernehmen: compendium lehrplan harvest --force)"
            )

    def _refuse_a_loss(
        self, harvested: dict[str, int], nodes: dict[str, int], matchable: dict[str, int], emptied: list[str]
    ) -> None:
        if not harvested:
            raise HarvestRefusedError(
                "MEM listet keinen Lehrplan; der bisherige Cache bleibt "
                "(übernehmen: compendium lehrplan harvest --force)"
            )
        before = self.local_counts() if self.store.available else {}
        lost = lost_states(before, harvested)
        if lost:
            detail = ", ".join(f"{code} {harvested.get(code, 0)} statt {before[code]}" for code in lost)
            raise HarvestRefusedError(
                f"MEM listet deutlich weniger Lehrpläne als der Cache hält ({detail}); der bisherige Cache bleibt "
                "(übernehmen: compendium lehrplan harvest --force)"
            )
        before_nodes = json.loads(self.store.meta().get("nodes_per_state") or "{}") if self.store.available else {}
        lost_nodes = lost_states(before_nodes, nodes)
        if lost_nodes:
            detail = ", ".join(f"{code} {nodes.get(code, 0)} statt {before_nodes[code]}" for code in lost_nodes)
            raise HarvestRefusedError(
                f"MEM liefert deutlich weniger Lehrplanelemente als der Cache hält ({detail}); der bisherige Cache "
                "bleibt (übernehmen: compendium lehrplan harvest --force)"
            )
        # Without the ontology graph - as while MEM reloads it - the class query still answers a row per class, only
        # without roles: the elements stay, and a search no longer finds them (audit 2026-09-29, Q1)
        before_matchable = self.store.matchable_per_state()
        lost_matchable = lost_states(before_matchable, matchable)
        if lost_matchable:
            detail = ", ".join(
                f"{code} {matchable.get(code, 0)} statt {before_matchable[code]}" for code in lost_matchable
            )
            raise HarvestRefusedError(
                f"MEM liefert deutlich weniger auffindbare Lehrplanelemente (Themenbereich, Kompetenz, Inhalt) als der "
                f"Cache hält ({detail}); der bisherige Cache bleibt (übernehmen: compendium lehrplan harvest --force)"
            )
        if len(emptied) > EMPTIED_TOLERATED:
            raise HarvestRefusedError(
                f"{len(emptied)} Lehrpläne kamen zweimal ohne Elemente zurück, die der Cache hat; der bisherige Cache "
                "bleibt (übernehmen: compendium lehrplan harvest --force)"
            )
        if emptied:
            log.warning("%d curricula came back without elements they had: %s", len(emptied), emptied)

    def _select(self, query: str) -> list[dict[str, str]]:
        if self._lock is not None:
            # A sign of life before each query: a slow run must not look crashed to a second one (audit KO-18)
            self._lock.refresh()
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

    def _heads(self, iris: Sequence[str], *, had_heads: set[str], force: bool) -> dict[str, dict[str, list[str]]]:
        """Head field labels per curriculum, asked for in blocks of ``CHUNK_SIZE``.

        A block may name no head field with a label, but not while the cache holds head fields for its curricula:
        Virtuoso answers with no rows while it reloads a graph. Such an answer is asked for once more, and still empty
        the run is refused unless forced (audit 2026-09-29, Q1).
        """
        heads: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for start in range(0, len(iris), CHUNK_SIZE):
            chunk = iris[start : start + CHUNK_SIZE]
            answer = self._select(queries.lehrplan_heads(chunk))
            known = had_heads.intersection(chunk)
            if not answer and known:
                answer = self._select(queries.lehrplan_heads(chunk))
                if not answer:
                    self._refuse(
                        "MEM liefert zweimal keine Kopfdaten (Fach, Schulart, Stufe) zu Lehrplänen, die der Cache "
                        f"damit hält, etwa {min(known)}",
                        force=force,
                    )
            for row in answer:
                if row.get("s") and row.get("field") and row.get("label"):
                    heads[row["s"]][row["field"]].append(row["label"])
        return heads

    def _extend_class_index(
        self, rows: Sequence[dict[str, str]], index: dict[str, ClassInfo], asked: set[str], *, force: bool
    ) -> None:
        """Ask the ontology about node classes not seen before (only its own namespace can carry roles).

        All but the VALUES block of ``class_roles`` are OPTIONAL, so every class asked for answers at least one row, and
        an empty answer is Virtuoso reloading a graph: it is asked for once more, and still empty the run is refused
        unless forced. Classes count as asked only after an answer with rows, so a forced run asks for them again with
        the next curriculum that has them (audit 2026-09-29, Q1).
        """
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
            answer = self._select(queries.class_roles(chunk))
            if not answer:
                answer = self._select(queries.class_roles(chunk))
            if not answer:
                self._refuse(
                    f"MEM nennt zweimal keine Rollen zu Klassen der Lehrplanelemente, etwa {chunk[0]}", force=force
                )
                continue
            index.update(build_class_index(answer))
            asked.update(chunk)

    @staticmethod
    def _refuse(reason: str, *, force: bool) -> None:
        """Refuse the run for ``reason``, the cache stays; a forced run goes on with what MEM answered."""
        if not force:
            raise HarvestRefusedError(
                f"{reason}; der bisherige Cache bleibt (übernehmen: compendium lehrplan harvest --force)"
            )
        log.warning("forced harvest goes on: %s", reason)

    def _write_status(self, state: str, **fields: Any) -> None:
        previous = read_status(self._state_dir) or {}
        payload = {
            "state": state,
            "updated_at": self._clock().isoformat(),
            "started_at": fields.get("started_at", previous.get("started_at")),
            "progress": fields.get("progress", previous.get("progress")),
            "last_run": fields.get("last_run", previous.get("last_run")),
            "error": fields.get("error"),
            # the error of the last finished run: it stays while the next one runs and goes with a run that succeeds, so
            # the gauge and its alert see a failure for longer than the second after it (audit 2026-09-28, BE-11)
            "last_error": fields["error"]
            if state == "error"
            else None
            if "last_run" in fields
            else previous.get("last_error"),
            "check_error": previous.get("check_error"),  # only a check writes it (``_record_check``)
        }
        self._save_status(payload)

    def _save_status(self, payload: dict[str, Any]) -> None:
        try:
            atomic_write_text(self._state_dir / STATUS_FILE, json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError as exc:
            log.warning("cannot write %s: %s", STATUS_FILE, exc)
