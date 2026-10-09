"""Klexikon twins over an alias (side finding of M84): how often, what part 1 prints from them, and fixes, measured in
the service's own flow (generate) on the requests of eval/artikelwahl/hauptartikel.yaml.

Before D100 ``_CorpusBuilder._add_twins`` took the twin from the title of the main article or one of its first two
aliases; since D100 it takes the title only, the variant titel. The variants replace that step, here only:

- heute: as built before D100.
- titel: the title only (a redirect of the other archive still followed, as ``read`` does).
- anfang: an alias only when the twin's first paragraph names every word of the title (``title_words``, each as
  ``TopicMention`` finds it).
- teilwort: an alias whose words are all words of the title - a shortened form like "Strom" of "Elektrischer Strom"
  or "Zelle" of "Zelle (Biologie)" - only when the twin's first paragraph names the title words it leaves out; an
  alias that is another name ("DNA", "Erderwärmung") as built.
- kurzform: such a shortened alias never; an alias that is another name as built (no reading of the twin).

Every request runs once per variant through ``service.generate`` (parts world, the profile of the command line); a
wrapper keeps the prepared topic, so the printed paragraphs (one citation each) can be read with their source. With
``balanced`` the LLM is asked over OpenAI directly (mc_openai_direkt.py, gpt-6-luna), and a transport keeps every
answer by its request body without the safety_identifier: all variants of a request hear the same answers, and a
variant whose question differs asks anew (counted).

Usage: python mc_klexikon_zwillinge.py <profile> <out.json> <pool.json>
    llm-free needs nothing; balanced needs LLM_ENABLED=true, B_API_KEY=direct, B_API_BASE_URL=https://b-api.invalid
    and OPENAI_API_KEY in the environment. out.json holds titles, counts and headings, pool.json the printed texts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from pathlib import Path

PROFILE = sys.argv[1]
if PROFILE == "llm-free":
    os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import httpx  # noqa: E402
import yaml  # noqa: E402

import app  # noqa: E402
from app.knowledge import corpus_sources  # noqa: E402
from app.knowledge.topic import TopicMention, title_words  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
WIKI = DATA / "wikipedia_de_all_nopic_2026-01.zim"
KLEX = DATA / "klexikon_de_all_maxi_2026-08.zim"
M2V = "JanSchachtschabel/m2v-gte-256-edu"
VARIANTS = ["heute", "titel", "anfang", "teilwort", "kurzform"]
OPENAI = "https://api.openai.com/v1"
_DROPPED = {"x-api-key", "host", "content-length"}

out_path, pool_path = Path(sys.argv[2]), Path(sys.argv[3])
GOLD = os.environ.get("GOLD", "eval/artikelwahl/hauptartikel.yaml")  # held-out check: the other two files, by |
gold = [entry for name in GOLD.split("|") for entry in yaml.safe_load(Path(name).read_text("utf-8"))["anfragen"]]
if os.environ.get("NUR"):  # a trial run on some requests, separated by |
    gold = [entry for entry in gold if entry["anfrage"] in os.environ["NUR"].split("|")]
print("app:", app.__file__, "| Profil:", PROFILE, "| Anfragen:", len(gold))


# --- the LLM: OpenAI directly, every answer kept by its question ------------------------------------------------
class CachedOpenAi(httpx.BaseTransport):
    """mc_openai_direkt.OpenAiDirect with a store: the same question (body without safety_identifier) gets the
    answer it got first."""

    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self._key = os.environ["OPENAI_API_KEY"]
        self.store: dict[str, tuple[int, bytes, str]] = {}
        self.live = 0
        self.replayed = 0
        self._lock = threading.Lock()

    @staticmethod
    def _question(request: httpx.Request) -> str:
        body = request.read()
        try:
            data = json.loads(body) if body else {}
            data.pop("safety_identifier", None)
            text = json.dumps(data, sort_keys=True, ensure_ascii=False)
        except ValueError:
            text = body.decode("utf-8", "replace")
        return hashlib.sha256(f"{request.method} {request.url.path} {text}".encode()).hexdigest()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        key = self._question(request)
        with self._lock:
            kept = self.store.get(key)
            if kept is not None:
                self.replayed += 1
        if kept is not None:
            status, content, ctype = kept
            return httpx.Response(status, content=content, headers={"content-type": ctype}, request=request)
        tail = request.url.path.split("/llm/openai", 1)[-1]
        headers = {name: value for name, value in request.headers.items() if name.lower() not in _DROPPED}
        headers["authorization"] = f"Bearer {self._key}"
        forwarded = httpx.Request(
            request.method, OPENAI + tail, params=request.url.params, headers=headers, content=request.read()
        )
        response = self._inner.handle_request(forwarded)
        content = response.read()
        with self._lock:
            self.live += 1
            if response.status_code == 200:
                self.store[key] = (200, content, response.headers.get("content-type", "application/json"))
        return httpx.Response(
            response.status_code, content=content, headers={"content-type": response.headers.get("content-type", "")},
            request=request,
        )


TRANSPORT: CachedOpenAi | None = None
if PROFILE != "llm-free":
    import app.wiring as wiring_module
    from app.llm.client import BApiClient

    TRANSPORT = CachedOpenAi()

    class DirectClient(BApiClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = TRANSPORT
            super().__init__(*args, **kwargs)

    wiring_module.BApiClient = DirectClient


# --- the variants of the twin step --------------------------------------------------------------------------------
STATE: dict = {"variant": "heute", "log": []}
_WORD = re.compile(r"[a-zäöüß]+")


def first_paragraph(archive, article) -> str:
    parsed = archive.parse(article)
    return next((p.text for s in parsed.sections for p in s.paragraphs), "")


def names_all(text: str, words: list[str]) -> bool:
    return all(TopicMention.of(word).found_in(text) for word in words)


def left_out(alias: str, title: str) -> list[str] | None:
    """The title words a shortened alias leaves out; None for an alias that is another name."""
    words = _WORD.findall(alias.lower())
    if not words or not all(TopicMention.of(word).found_in(title) for word in words):
        return None
    return [word for word in title_words(title) if not TopicMention.of(word).found_in(alias)]


def accepts(variant: str, index: int, candidate: str, title: str, lead: str) -> tuple[bool, str]:
    if index == 0 or variant == "heute":
        return True, "titel" if index == 0 else "alias"
    if variant == "titel":
        return False, "nur Titel"
    if variant == "anfang":
        words = title_words(title)
        return names_all(lead, words), f"Anfang nennt {words}"
    if variant == "teilwort":
        missing = left_out(candidate, title)
        if missing is None:
            return True, "anderer Name"
        return names_all(lead, missing), f"Anfang nennt {missing}"
    if variant == "kurzform":
        missing = left_out(candidate, title)
        if missing is None:
            return True, "anderer Name"
        return not missing, f"Kurzform ohne {missing}"
    raise ValueError(variant)


def add_twins(self, draft) -> None:
    """``_CorpusBuilder._add_twins`` as built, with the variant's check before an alias twin is taken."""
    primary = draft.primary
    for archive in self.archives:
        if archive is draft.archive:
            continue
        for index, candidate in enumerate([primary.title, *primary.aliases[:2]]):
            found = archive.read(candidate)
            if found is None or archive.parse(found).is_disambiguation:
                continue
            entry = archive._entry(candidate)  # noqa: SLF001 - the redirect flag, for the record only
            ok, why = accepts(STATE["variant"], index, candidate, primary.title, first_paragraph(archive, found))
            STATE["log"].append({
                "archiv": archive.project, "kandidat": candidate, "index": index, "gefunden": found.title,
                "weiterleitung": bool(entry is not None and entry.is_redirect), "genommen": ok, "grund": why,
            })
            if not ok:
                continue
            key = (archive.project, found.title.lower())
            if key in draft.seen:
                break
            draft.seen.add(key)
            twin = archive.to_source(found, is_primary=False)
            twin.origin = "same_topic"
            draft.sources.append(twin)
            break


corpus_sources._CorpusBuilder._add_twins = add_twins

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

service = cli_service([str(WIKI), str(KLEX)])
service.settings.model2vec_path = M2V
captured: list = []
_prepare = service.prepare


def keep_prepared(*args, **kwargs):
    prepared = _prepare(*args, **kwargs)
    captured.append(prepared)
    return prepared


service.prepare = keep_prepared


def printed_bodies(text: str) -> dict[int, str]:
    """Citation number -> the text printed for it: a paragraph ends with " [n]", a table has "[n]" below it."""
    bodies: dict[int, str] = {}
    pieces = text.split("\n\n")
    for index, piece in enumerate(pieces):
        match = re.search(r"\s?\[(\d+)\]$", piece)
        if match is None:
            continue
        body = piece[: match.start()].strip()
        if not body and index:
            body = pieces[index - 1]
        bodies[int(match.group(1))] = body
    return bodies


def run(entry: dict, variant: str) -> tuple[dict, dict]:
    STATE["variant"], STATE["log"] = variant, []
    captured.clear()
    before = (TRANSPORT.live, TRANSPORT.replayed) if TRANSPORT else (0, 0)
    started = time.perf_counter()
    compendium = service.generate(GenerateRequest(topic=entry["anfrage"], parts=["world"], preset=PROFILE))
    seconds = time.perf_counter() - started
    prepared = captured[-1]
    chunks = {chunk.chunk_id: chunk for chunk in prepared.chunks}
    sources = {source.source_id: source for source in prepared.sources}
    content = {slot.id for slot in prepared.template.content_slots()}
    printed, texts = [], []
    for section in compendium.sections:
        if section.slot_id not in content:
            continue
        bodies = printed_bodies(section.text)
        for citation in section.citations:
            chunk, source = chunks.get(citation.chunk_id), sources.get(citation.source_id)
            row = {
                "baustein": section.title,
                "projekt": source.project if source else "?",
                "quelle": citation.source_title,
                "herkunft": source.origin if source else "?",
                "position": chunk.position if chunk else None,
                "ueberschrift": chunk.full_heading if chunk else citation.section_heading,
            }
            printed.append(row)
            texts.append({**row, "text": bodies.get(citation.number, citation.snippet)})
    twin = next((s for s in prepared.sources if s.origin == "same_topic"), None)
    resolution = prepared.resolution
    articles = prepared.articles
    filled = sum(1 for s in compendium.sections if s.slot_id in content and s.text.strip())
    llm = compendium.audit.llm_tokens or {}
    live, replayed = ((TRANSPORT.live - before[0], TRANSPORT.replayed - before[1]) if TRANSPORT else (0, 0))
    row = {
        "anfrage": entry["anfrage"],
        "art": entry["art"],
        "variante": variant,
        "hauptartikel": resolution.title,
        "aufloesung": resolution.method if hasattr(resolution, "method") else None,
        "artikelwahl": getattr(prepared, "article_choice", None) and str(prepared.article_choice)[:300],
        "genannt": list(articles.found) if articles is not None else [],
        "aliasse": next((list(s.aliases) for s in prepared.sources if s.is_primary), []),
        "zwilling": twin.title if twin else None,
        "zwilling_weg": [x for x in STATE["log"] if x["archiv"] == "klexikon"],
        "artikel": [f"{s.project}:{s.title}:{s.origin}" for s in prepared.sources],
        "absaetze_klexikon": sum(1 for c in prepared.chunks if sources[c.source_id].project == "klexikon"),
        "gedruckt": len(printed),
        "gedruckt_klexikon": sum(1 for p in printed if p["projekt"] == "klexikon"),
        "bausteine_gefuellt": filled,
        "gedruckte_absaetze": printed,
        "llm_tokens": llm,
        "llm_live": live,
        "llm_wiederholt": replayed,
        "llm_note": (compendium.audit.llm or {}).get("note") if compendium.audit.llm else None,
        "sekunden": round(seconds, 2),
    }
    pool = {"anfrage": entry["anfrage"], "variante": variant, "hauptartikel": resolution.title, "gedruckt": texts}
    return row, pool


rows, pool = [], []
for number, entry in enumerate(gold, 1):
    for variant in VARIANTS:
        for attempt in range(3):
            try:
                row, texts = run(entry, variant)
                break
            except Exception as exc:  # a failed request is recorded, not hidden
                print(f"  Fehler {entry['anfrage']} {variant} (Versuch {attempt + 1}): {type(exc).__name__}: {exc}")
                row, texts = {"anfrage": entry["anfrage"], "art": entry["art"], "variante": variant,
                              "fehler": f"{type(exc).__name__}: {exc}"}, None
                time.sleep(5)
        rows.append(row)
        if texts is not None:
            pool.append(texts)
        if "fehler" not in row:
            print(f"{number:>2} {entry['anfrage'][:30]:<30} {variant:<8} -> {str(row['hauptartikel'])[:28]:<28} "
                  f"Zwilling {str(row['zwilling'])[:22]:<22} gedruckt {row['gedruckt']:>3} (Klexikon "
                  f"{row['gedruckt_klexikon']:>2}) Bausteine {row['bausteine_gefuellt']:>2} "
                  f"LLM live {row['llm_live']} wdh {row['llm_wiederholt']} {row['sekunden']:.1f}s")
    out_path.write_text(json.dumps({"profil": PROFILE, "zeilen": rows}, ensure_ascii=False, indent=1), "utf-8")
    pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1), "utf-8")

summary = Counter()
for row in rows:
    if "fehler" in row:
        summary[(row["variante"], "fehler")] += 1
        continue
    summary[(row["variante"], "zwilling")] += row["zwilling"] is not None
    summary[(row["variante"], "gedruckt_klexikon")] += row["gedruckt_klexikon"]
    summary[(row["variante"], "gedruckt")] += row["gedruckt"]
    summary[(row["variante"], "bausteine")] += row["bausteine_gefuellt"]
for variant in VARIANTS:
    print(variant, {k[1]: v for k, v in summary.items() if k[0] == variant})
if TRANSPORT:
    print("LLM live", TRANSPORT.live, "wiederholt", TRANSPORT.replayed)
