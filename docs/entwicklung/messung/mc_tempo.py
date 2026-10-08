"""Messskript M75 (08.10.2026): wohin Zeit und Tokens je Profil gehen, Aufruf für Aufruf.

Jan, 08.10.2026: „abschließend sollten wir die frage analysieren ob wir bearbeitungsgeschwindigkeit und tokenverbrauch
verbessern können … die qualität muss aber im auge behalten werden - nochmal für alle profile durchdenken“.

Je Thema und Profil ein Kompendium mit Teil 1 und 2 im Einmal-Container mit eingehängtem Arbeitsstand, LLM über
OpenAI direkt (mc_openai_direkt.py). Jeder LLM-Aufruf wird aufgezeichnet: Prompt, wann er gestellt und wann gesendet
wurde (dazwischen das Warten auf einen freien Platz, LLM_MAX_CONCURRENCY), wann die Antwort kam, Versuche, Eingabe-
Tokens, davon aus dem Cache, Ausgabe-Tokens, davon Denken. Varianten, die keinen Prompt ändern:

- ``--variant=seq``: wie ausgeliefert, Teil 2 nach Teil 1;
- ``--variant=par``: Teil 2 beginnt nach der Artikelwahl neben Teil 1 (Prototyp: ``generate`` hier ersetzt);
- ``--batch=25``: die LLM-Zuordnung mit 25 statt 50 Absätzen je Aufruf;
- die Zahl gleichzeitiger Aufrufe kommt aus ``-e LLM_MAX_CONCURRENCY``.

``--part3=<id>,<id>`` misst stattdessen ohne LLM, wie lange Teil 3 einer Sammlung ohne und mit Cache braucht.

  cat mc_openai_direkt.py mc_tempo.py | docker compose run --rm --no-deps -T -v <ordner>:/out \\
      -v <app>:/src/app:ro -e PYTHONPATH=/src -e LLM_ENABLED=true -e B_API_KEY=direct \\
      -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY [-e LLM_MAX_CONCURRENCY=20] api \\
      python - /out/<lauf>.json --variant=seq --profiles=balanced,best-quality <thema> [...]

Die JSON-Datei wird nach jedem Lauf geschrieben; ein Lauf, der schon darin steht, wird übersprungen.
"""

# --- M75: every LLM call of a compendium, timed ---
import contextvars
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

import app.main as main_module
from app.compendium.assembly import assemble
from app.compendium.prepared import Made, Requested, Stopwatch, WorldPart
from app.domain.requests import GenerateRequest
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.main import build_registry, build_service
from app.service import CompendiumService
from app.settings import get_settings
from app.sources.wlo.part import CollectionBuilder
from app.templates.manager import TemplateManager

T0 = time.monotonic()
CALLS: list[dict] = []
BRANCHES: dict[str, float] = {}
_LOCK = threading.Lock()
_CURRENT = threading.local()
_HOP_BY_HOP = {"content-encoding", "content-length", "transfer-encoding"}


def now() -> float:
    return round(time.monotonic() - T0, 3)


class RecordingTransport(OpenAiDirect):  # noqa: F821 - defined by mc_openai_direkt.py, which comes first
    """Forwards as OpenAiDirect and notes each attempt of the call running in this thread."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        attempt: dict = {"sent": now()}
        response = super().handle_request(request)
        body = response.read()
        attempt["received"] = now()
        attempt["status"] = response.status_code
        try:
            usage = json.loads(body).get("usage") or {}
        except (ValueError, AttributeError):
            usage = {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        attempt.update(
            prompt=usage.get("prompt_tokens"),
            cached=prompt_details.get("cached_tokens"),
            completion=usage.get("completion_tokens"),
            reasoning=completion_details.get("reasoning_tokens"),
        )
        record = getattr(_CURRENT, "record", None)
        if record is not None:
            record["attempts"].append(attempt)
        headers = [(k, v) for k, v in response.headers.items() if k.lower() not in _HOP_BY_HOP]
        return httpx.Response(response.status_code, headers=headers, content=body, request=request)


class RecordingClient(BApiClient):
    def __init__(self, *args, **kwargs):
        kwargs["transport"] = RecordingTransport()
        super().__init__(*args, **kwargs)

    def chat(self, messages, *, prompt=None, **kwargs):
        record = {"prompt": prompt, "asked": now(), "attempts": []}
        _CURRENT.record = record
        try:
            return super().chat(messages, prompt=prompt, **kwargs)
        except Exception as exc:
            record["error"] = type(exc).__name__
            raise
        finally:
            record["done"] = now()
            _CURRENT.record = None
            with _LOCK:
                CALLS.append(record)


main_module.BApiClient = RecordingClient


def generate_parallel(self, request, *, deadline=None, budget=None):
    """CompendiumService.generate with part 2 beside part 1: it needs only what the article choice prepared."""
    if deadline is None:
        deadline = Deadline(self.settings.request_time_limit_s)
    request, profile = self._admit(request, deadline)
    if budget is None:
        budget = self.open_budget(profile)
    choice_requested, choice_note, choice = self.article_choice_job(request.article_choice, deadline, budget)
    budget = choice.budget if choice is not None else budget
    writing = request.generation if "world" in request.parts else None
    wording = self.wording_job(writing, choice, deadline, budget)
    prepared = self.prepare(request, deadline, choice, wording=wording)
    requested = Requested.of(request)
    timings = dict(prepared.timings)
    started = time.monotonic()

    def part_2():
        result = self._curricula_part(prepared, request, deadline)
        BRANCHES["part2"] = round(time.monotonic() - started, 3)
        return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        curricula_future = pool.submit(contextvars.copy_context().run, part_2)
        if "world" in request.parts:
            world = self._world_part(prepared, request, requested, deadline, timings, budget)
        else:
            world = WorldPart.skipped()
        BRANCHES["part1"] = round(time.monotonic() - started, 3)
        curricula = curricula_future.result()
    lap = Stopwatch(timings).lap
    lap("curricula")
    made = Made(
        prepared=prepared,
        world=world,
        requested=requested,
        choice_requested=choice_requested,
        choice_note=choice_note,
        curricula=curricula,
        collection=None,
        facets_visible=self._facets_visible(request),
        timings=timings,
        cached_tokens=budget.cached_tokens if budget is not None else 0,
    )
    archives = prepared.registry or self.registry
    return assemble(request, made, lap, llm=self.llm, facets=self.facets, zim_snapshot=archives.snapshot())


def run_compendia(service, settings, out: Path, topics, profiles, variant: str) -> None:
    rows = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    concurrency = settings.llm_concurrency
    done = {(r["topic"], r["profile"], r["variant"], r["concurrency"]) for r in rows}
    for topic in topics:
        for profile in profiles:
            if (topic, profile, variant, concurrency) in done:
                continue
            with _LOCK:
                CALLS.clear()
            BRANCHES.clear()
            start = now()
            try:
                result = service.generate(GenerateRequest(topic=topic, parts=["world", "curricula"], preset=profile))
            except Exception as exc:  # noqa: BLE001 - a measurement records the failure and goes on
                rows.append({"topic": topic, "profile": profile, "variant": variant, "concurrency": concurrency,
                             "error": f"{type(exc).__name__}: {exc}"[:300]})
                out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
                continue
            end = now()
            calls = []
            for call in sorted(CALLS, key=lambda c: c["asked"]):
                shifted = {**call, "asked": round(call["asked"] - start, 3), "done": round(call["done"] - start, 3)}
                shifted["attempts"] = [
                    {**a, "sent": round(a["sent"] - start, 3), "received": round(a["received"] - start, 3)}
                    for a in call["attempts"]
                ]
                calls.append(shifted)
            sections = [s for s in result.sections if s.text]
            curricula = result.curricula
            rows.append({
                "topic": topic, "profile": profile, "variant": variant, "concurrency": concurrency,
                "s": round(end - start, 2), "timings": result.audit.timings_ms, "branches": dict(BRANCHES),
                "tokens": result.audit.llm_tokens, "parts_status": result.parts_status,
                "main": result.resolution.title, "chars": sum(len(s.text) for s in sections),
                "sections": len(sections), "statuses": [str(s.status) for s in sections],
                "curricula_entries": len(curricula.entries) if curricula is not None else None,
                "llm_check": curricula.summary.get("llm_check") if curricula is not None else None,
                "llm": result.audit.llm, "calls": calls,
            })
            tokens = result.audit.llm_tokens or {}
            print(f"# {topic} | {profile} | {variant} c{concurrency} | {end - start:.1f} s | Aufrufe {len(calls)} | "
                  f"Tokens {tokens.get('total')} cached {tokens.get('cached')}", file=sys.stderr, flush=True)
            out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def run_part3(service, out: Path, ids) -> None:
    """Part 3 of each collection read twice: through a builder without a cache, then twice through one with it."""
    shared = service.collections
    rows = []
    for collection_id in ids:
        fresh = CollectionBuilder(client=shared.client, cache=None, options=shared.options)
        start = time.monotonic()
        part = fresh.overview(collection_id)
        cold = time.monotonic() - start
        shared.overview(collection_id)  # fills the cache
        start = time.monotonic()
        shared.overview(collection_id)
        warm = time.monotonic() - start
        rows.append({"collection": collection_id, "title": part.title, "cold_s": round(cold, 2),
                     "warm_s": round(warm, 3), "chars": len(part.markdown)})
        print(f"# Teil 3 {part.title}: ohne Cache {cold:.1f} s, mit Cache {warm:.2f} s", file=sys.stderr, flush=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    settings = get_settings()
    service = build_service(settings, build_registry(settings), TemplateManager())
    main_module.describe_matching(settings)  # loads Model2Vec as the app's start does; else the first run waits 35 s
    service.generate(GenerateRequest(topic="Licht", parts=["world", "curricula"], preset="llm-free"))  # archives warm
    out = Path(args[0])
    if "part3" in options:
        run_part3(service, out, options["part3"].split(","))
        return
    variant = options.get("variant", "seq")
    if variant == "par":
        CompendiumService.generate = generate_parallel
    if "batch" in options:  # paragraphs per call of the LLM assignment (shipped: 50)
        import app.matching.llm_assignment as llm_assignment

        llm_assignment.BATCH_SIZE = int(options["batch"])
        variant = f"{variant}-b{options['batch']}"
    run_compendia(service, settings, out, args[1:], options.get("profiles", "balanced").split(","), variant)


main()
