"""v2 endpoints: compendium generation and templates (archives: zim.py, matching: matching.py).

Reading templates is open; writing and deleting them sit behind ``ADMIN_TOKEN`` like the archive
endpoints, because a template decides what every following compendium looks like (docs/umbau.md U6).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.admin import require_admin
from app.api.deps import get_service
from app.api.limits import rate_limited
from app.compose.regeneration import UnknownSectionsError
from app.domain.models import Compendium
from app.domain.requests import GenerateRequest
from app.matching.registry import UnknownMatcherError
from app.observability.metrics import record_compendium
from app.service import (
    LlmNotConfiguredError,
    PartsUnavailableError,
    RepositoryUnavailableError,
    TopicNotFoundError,
)
from app.sources.lehrplan.subjects import UnknownSubjectError
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError, NodeNotFoundError
from app.sources.wlo.repository import RepositoryNotAllowedError
from app.templates.manager import TemplateNotFoundError
from app.templates.schema import Template

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])
admin = APIRouter(prefix="/api/v2", tags=["v2-admin"], dependencies=[Depends(require_admin)])


EXAMPLES = {
    "kuerzeste Anfrage": {
        "summary": "Das Nötigste: ein Thema, zwei Teile, eine Ziellänge",
        "value": {"topic": "Optik", "parts": ["world", "curricula"], "target_length": 8000},
    },
    "Profil llm-free": {
        "summary": "Profil llm-free: ohne Sprachmodell, für einen Dienst ohne LLM",
        "description": (
            "preset wählt eines der vier Profile der Entscheidungsvorlage; ohne preset gilt PRESET_DEFAULT, "
            "ausgeliefert balanced. llm-free: die "
            "Regeln wählen die Artikel, hybrid_light ordnet die Absätze zu, der Text bleibt wörtlich. 86 von 94 "
            "Hauptartikeln richtig, macro-F1 0,45, Teil 1 und 2 in rund 1,6 s, keine Tokens (M27)."
        ),
        "value": {"topic": "Optik", "parts": ["world"], "preset": "llm-free"},
    },
    "Profil balanced": {
        "summary": "Profil balanced (Standard): das LLM wählt die Artikel, alles andere bleibt lokal",
        "description": (
            "Wie llm-free, aber das LLM entscheidet, wo die Regeln beim Artikel unsicher sind - hier das "
            "mehrdeutige Wort Linse -, und verwirft unpassende Nebenartikel. 91 von 94 Hauptartikeln richtig, "
            "rund 3,4 s und 900 Tokens je Kompendium (M27). Ohne konfiguriertes LLM ist die Anfrage ein 503."
        ),
        "value": {"topic": "Physik: Linse", "parts": ["world"], "preset": "balanced"},
    },
    "Profil best-quality": {
        "summary": "Profil best-quality: das LLM wählt die Artikel und ordnet die Absätze zu",
        "description": (
            "Wie balanced, dazu matcher llm: macro-F1 0,70 statt 0,45, rund 14 s und 26.000 Tokens je "
            "Kompendium (M19, M27). Der Text bleibt wörtlich; lesbar formuliert ihn das Profil "
            "best-quality-generated."
        ),
        "value": {"topic": "Physik: Linse", "parts": ["world"], "preset": "best-quality"},
    },
    "Profil best-quality-generated": {
        "summary": "Profil best-quality-generated: alles mit dem LLM, der Text ergänzt und lesbar formuliert",
        "description": (
            "Wie best-quality, dazu schreibt das LLM jeden Baustein neu (generation llm) und darf eigenes Wissen "
            "ergänzen (enrichment model-knowledge); solche Sätze tragen keine Belegnummer und stehen als "
            "Evidenzgrad=Modellwissen im Text. Für Texte, die Menschen direkt lesen; rund 24 s und 35.000 Tokens "
            "(M27). Zwei Gutachter zogen den Text in 11 von 12 Urteilen dem wörtlichen vor; zwei Drittel des "
            "ergänzten Modellwissens sind aber Füllsätze (M28). Einzeln gesetzte Schalter gehen dem preset vor."
        ),
        "value": {"topic": "Optik", "parts": ["world"], "preset": "best-quality-generated"},
    },
    "mit den Schaltern": {
        "summary": "Was sonst noch geht: Template, Artikelwahl, Zuordnung, die drei Schreib-Schalter, Facetten",
        "description": (
            "article_choice wählt die Artikel (rule-based oder llm), matcher ordnet die Absätze den Bausteinen zu "
            "(hybrid_light, bm25, char_tfidf, lexicon_only oder llm; die Liste mit Güte, Zeit und Kosten steht unter "
            "GET /api/v2/matching/strategies). extraction wählt die Sätze, generation formuliert die Bausteine, "
            "enrichment entscheidet, ob das Modell eigenes Wissen beisteuern darf. Ohne konfiguriertes LLM ist ein "
            "LLM-Schalter ein 503; ist die b-api nur gerade nicht erreichbar, laufen die Regeln, und audit sagt "
            "hinterher, was wirklich lief."
        ),
        "value": {
            "topic": "Optik",
            "parts": ["world", "curricula"],
            "target_length": 12000,
            "template_id": "sc26",
            "article_choice": "llm",
            "matcher": "hybrid_light",
            "extraction": "llm",
            "generation": "llm-fast",
            "enrichment": "sources-only",
            "facets_visible": True,
            "max_articles": 12,
            "empty_slot_policy": "note",
        },
    },
    "Artikelwahl und Zuordnung durch das LLM": {
        "summary": "Das LLM wählt die Artikel und ordnet die Absätze zu; der Text bleibt wörtlich aus den Quellen",
        "description": (
            "article_choice llm entscheidet, wo die Regeln unsicher sind - hier das mehrdeutige Wort Linse -, und "
            "verwirft unpassende Nebenartikel. matcher llm lässt das LLM jeden Absatz einem Baustein zuordnen. "
            "Beides fällt ohne b-api auf die Regeln zurück; Güte, Sekunden und Tokens stehen in den Hilfetexten der "
            "beiden Felder."
        ),
        "value": {
            "topic": "Physik: Linse",
            "parts": ["world"],
            "article_choice": "llm",
            "matcher": "llm",
            "target_length": 12000,
        },
    },
    "mit einer Sammlung (Teil 3)": {
        "summary": "Alle drei Teile: Weltwissen, Lehrpläne und die Materialien einer edu-sharing-Sammlung",
        "description": (
            "collection_id ist die Knoten-ID der Sammlung im Repository, hier eine aus der Staging - für "
            "eine andere Umgebung ersetzen. Teil 3 braucht EDU_SHARING_BASE_URL; fehlt sie, bleibt Teil 3 aus und "
            "parts_status.collection sagt unavailable, und nur wenn kein angefragter Teil erzeugbar ist - oder das "
            "Thema allein aus der Sammlung käme -, antwortet der Endpunkt 503. Mit collection_id braucht Teil 3 "
            "keinen Artikel in den Archiven."
        ),
        "value": {
            "topic": "Optik",
            "parts": ["world", "curricula", "collection"],
            "collection_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "target_length": 12000,
        },
    },
    "aus einem Knoten des Repositorys": {
        "summary": "Thema, Fach und Stufe aus den Metadaten eines Knotens, hier die Sammlung Optik der WLO-Staging",
        "description": (
            "node_id nennt ein Material oder eine Sammlung, gelesen ohne Zugangsdaten, also nur Öffentliches. Der "
            "Titel wird zum Thema, alle Fächer zählen gleich; Bildungsstufen und Schlagwörter gehen als "
            "Kontextwörter mit, die bei einer Begriffsklärung nur zählen, wenn die Fächer keine eigenen Wörter "
            "haben. Die Antwort "
            "nennt den Knoten unter node. repository ist die REST-Adresse des Repositorys, ohne Angabe das "
            "konfigurierte; erlaubt sind nur Hosts aus EDU_SHARING_REPOSITORIES, über https. "
            "GET /api/v2/nodes/{node_id} zeigt vorab, was gelesen wird."
        ),
        "value": {
            "node_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
            "parts": ["world", "curricula"],
        },
    },
    "Material mit eigenem Thema": {
        "summary": "Ein Material der WLO-Staging mit einem Thema dazu: beide Artikel kommen in den Korpus",
        "description": (
            "Titel von Materialien nennen oft ihr Format (hier: Stationsarbeit zur Optik) statt eines "
            "Lexikonthemas; ohne topic suchen die Regeln den Artikel in Titel und Beschreibung (D47). Ein topic dazu "
            "geht vor, und der Artikel des Materials kommt als weitere Quelle dazu, wenn er mit dem Hauptartikel "
            "verlinkt ist; audit.node_article sagt, wie er gefunden wurde. Fach, Stufe und Schlagwörter des "
            "Materials gehen weiter in die Auflösung ein."
        ),
        "value": {
            "node_id": "ac66224b-42b0-4676-a53d-71b058dc780b",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
            "topic": "Optik",
            "parts": ["world"],
        },
    },
}


@router.post(
    "/compendium",
    response_model=Compendium,
    dependencies=[Depends(rate_limited)],
    summary="Kompendium erzeugen",
)
def generate_compendium(
    payload: Annotated[GenerateRequest, Body(openapi_examples=EXAMPLES)], request: Request
) -> Compendium:
    """Generate the compendium for a topic or a collection: the requested parts, with the requested switches.

    **What it makes.** ``parts`` picks the parts: ``world`` is part 1, the compendium text itself;
    ``curricula`` is part 2, the curriculum elements; ``collection`` is part 3, the materials of an
    edu-sharing collection and needs ``collection_id``. Without ``world`` there is no part 1, no sources
    of its own, no matching and no knowledge collection - the rest is rule-based by definition.

    **How long it gets.** ``target_length`` is shared over the blocks by weight and steers upwards until
    the sources run out. It is a steer, not a cap: a block is never shorter than its first paragraph.

    **Who writes it.** Three switches, and each falls back to ``rule-based`` when the b-api is missing:
    ``extraction`` picks the sentences (``rule-based`` takes the policy's paragraphs, ``llm`` lets the
    model choose among the best candidates and the wording stays the source's), ``generation`` writes the
    blocks (``rule-based``, ``llm-fast`` for the main ones, ``llm`` for every one - every sentence cited),
    and ``enrichment`` decides whether the model may add knowledge of its own (``sources-only`` or
    ``model-knowledge``, which is marked in the text). ``audit`` says afterwards what really ran.

    **Which level.** ``preset`` sets the switches of part 1 to one of three levels: ``llm-free`` (no LLM,
    what the service does without a preset), ``balanced`` (the LLM decides the unsure articles) and
    ``best-quality`` (it also assigns every paragraph). A switch the request sets itself wins; quality, time
    and tokens of each level are in the help text of the field.

    **Which articles.** ``article_choice`` decides who picks the articles: ``rule-based`` (the default)
    takes the rules alone, ``llm`` lets the model decide where the rules are unsure and drop the full-text
    hits that do not fit the topic. ``resolution`` says how the article was found and whether that is sure.

    **Which block.** ``matcher`` decides how the paragraphs find their block: ``hybrid_light`` (default),
    ``bm25``, ``char_tfidf`` and ``lexicon_only`` run locally, ``llm`` lets the model assign every paragraph.
    What each does, how good it is and what it costs: the help text of the field and
    ``GET /api/v2/matching/strategies``. An unknown name is a 422.

    **What else.** ``template_id`` picks the template,
    ``max_articles`` the size of the corpus, ``facets_visible`` and ``empty_slot_policy`` override the
    settings and the template. ``existing_markdown`` with ``regenerate_sections`` makes only the named
    blocks anew and keeps the rest word for word. ``frontmatter_in_markdown: false`` starts the text at
    the heading instead of the YAML block - the same data stays in the ``frontmatter`` field.

    **What comes back.** ``markdown`` is the whole document: every requested part joined in reading
    order, part 1 then part 2 then part 3. ``sections``, ``curricula`` and ``collection`` carry the same
    parts separately, so a caller can take the finished text or assemble it differently.

    **When it refuses.** Topic not in the archives: 404 with the resolution and its alternatives. Unknown
    collection or knowledge collection, or a node that is unknown or not public: 404. A ``subject`` outside the
    two subject vocabularies of edu-sharing (config/vocabs), a block in ``regenerate_sections`` the template does
    not have, or a field the request does not know: 422. Repository unreachable: 502; a ``repository`` outside the
    allowlist: 422; a ``node_id`` with neither ``repository`` nor a configured one: 503. No requested part can be
    made at all - part 3 without ``EDU_SHARING_BASE_URL``, for instance: 503. A profile or a switch that needs
    an LLM on a server without one (LLM_ENABLED, B_API_KEY): 503.
    """
    service = get_service(request)
    try:
        compendium = service.generate(payload)
    except TopicNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail()) from exc
    except (CollectionNotFoundError, NodeNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc  # the messages name the repository
    except RepositoryNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RepositoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EduSharingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    except UnknownMatcherError as exc:
        raise HTTPException(status_code=422, detail=f"Unbekannte Matching-Strategie: {exc}") from exc
    except (UnknownSubjectError, UnknownSectionsError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PartsUnavailableError as exc:
        # A gap in the configuration that no retry fixes; the log keeps it apart from missing archives
        log.warning("compendium request refused: %s", exc)
        raise HTTPException(status_code=503, detail=f"Kein angefragter Teil ist erzeugbar: {exc}") from exc
    record_compendium(compendium)
    return compendium


@router.get("/templates")
def list_templates(request: Request) -> list[dict[str, Any]]:
    """The templates this service knows, built-in and custom, with their slot count and version.

    A short row each: id, version, name, description, how many blocks it has and whether it ships with
    the image. The blocks themselves are in ``GET /api/v2/templates/{id}``. The id goes into
    ``template_id`` of a compendium request; without one the default from the settings applies.
    """
    return [
        {
            "id": t.id,
            "version": t.version,
            "name": t.name,
            "description": t.description,
            "slots": len(t.slots),
            "builtin": t.builtin,
        }
        for t in request.app.state.templates.list()
    ]


@router.get("/templates/{template_id}")
def get_template(template_id: str, request: Request) -> dict[str, Any]:
    """One template in full: every block with its budget, facets, search queries and generator.

    This is the shape ``PUT /api/v2/templates/{id}`` takes back, so it is also the way to start a custom
    template - read a built-in one, change what you need, write it under your own id. An unknown id is a
    404.
    """
    try:
        template = request.app.state.templates.get(template_id)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {template_id}") from exc
    data: dict[str, Any] = template.model_dump()
    return data


@admin.put("/templates/{template_id}", summary="Template anlegen oder ersetzen")
def put_template(template_id: str, payload: Template, request: Request) -> dict[str, Any]:
    """Store a custom template under this id; the version counts up on every write.

    The id in the path and the id in the body have to agree: silently renaming what the caller sent would
    put a template somewhere they did not ask for. Built-in templates are read-only (409).
    """
    if payload.id != template_id:
        raise HTTPException(
            status_code=422, detail=f"id im Pfad ({template_id}) und im Body ({payload.id}) stimmen nicht überein"
        )
    try:
        stored = request.app.state.templates.save(payload)
    except ValueError as exc:  # a built-in id; the message names it and says what to do instead
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log.info("template %s saved as version %d", stored.id, stored.version)
    data: dict[str, Any] = stored.model_dump()
    return data


@admin.delete("/templates/{template_id}", status_code=204, summary="Template löschen")
def delete_template(template_id: str, request: Request) -> None:
    """Delete a custom template (204).

    Built-in templates ship with the image and are refused (409); an unknown id is a 404. A compendium
    request naming the deleted id answers 404 from then on, so check what still uses it first.
    """
    try:
        removed = request.app.state.templates.delete(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {template_id}")
    log.info("template %s deleted", template_id)
