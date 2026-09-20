"""Entities in a text (docs/umbau.md, U3): recognise first, link afterwards.

The two layers stand alone on purpose. Recognition by the model needs no archive, so a service that carries
only the Klexikon - or no archive at all - still answers with the names in the text. Linking uses whatever
archives are loaded and adds the article, its lead and the kind the lead reveals. The answer says which way
found what, so a caller can tell the difference instead of guessing.

The endpoint deliberately does not use ``get_service``: it needs no compendium service, and a service without
archives must answer here rather than report 503.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import archives_for
from app.api.limits import rate_limited
from app.domain.models import Source
from app.knowledge.entities import classify_entity, is_work
from app.knowledge.recognise import Mention, load_spacy, mentions_from_ner, mentions_from_titles, merge
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import ZimRegistry

router = APIRouter(prefix="/api/v2", tags=["v2"])

Method = Literal["ner", "dictionary"]
MAX_TEXT_CHARS = 50_000  # a request body is caller input; recognition is linear in the text length


def _default_methods() -> list[Method]:
    return ["ner", "dictionary"]


class EntitiesRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"text": "Alexander von Humboldt reiste 1799 nach Südamerika."}]}
    )

    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    methods: list[Method] = Field(
        default_factory=_default_methods,
        min_length=1,
        description="ner needs the spaCy model, dictionary needs archives; a way that cannot work is left out",
    )
    link: bool = Field(True, description="Look up the article behind each entity in the archives")
    archives: list[str] = Field(default_factory=list, description="Archive ids to ask; empty asks all of them")
    max_entities: int = Field(50, ge=1, le=200)


class EntityArticle(BaseModel):
    title: str
    archive: str
    project: str
    url: str
    lead: str
    kind: str | None = Field(description="Person, Organisation, Vorhaben, Netzwerk or Werk, read from the lead")


class Entity(BaseModel):
    text: str
    start: int
    end: int
    kind: str = Field(description="The model's label (PER, LOC, ORG, MISC); empty for a term of the archives")
    source: Method
    linked: bool
    article: EntityArticle | None = None


class EntitiesResponse(BaseModel):
    methods: list[Method] = Field(description="The ways that actually ran")
    archives: list[str] = Field(description="The archives that were asked")
    entities: list[Entity]


def _article_kind(source: Source) -> str | None:
    """What the lead reveals: an actor kind, ``Werk`` for a single work, or nothing for a subject."""
    return classify_entity(source) or ("Werk" if is_work(source) else None)


def _link(archives: list[ZimArchive], mention: Mention) -> EntityArticle | None:
    """The article of this name, from the first archive that has it; a disambiguation page is no link."""
    for archive in archives:
        article = archive.read(mention.text)
        if article is None or archive.parse(article).is_disambiguation:
            continue
        source = archive.to_source(article, is_primary=False)
        return EntityArticle(
            title=source.title,
            archive=archive.id,
            project=source.project,
            url=source.url,
            lead=source.lead_text[:400],
            kind=_article_kind(source),
        )
    return None


def _recognise(payload: EntitiesRequest, registry: ZimRegistry, model_path: str) -> tuple[list[Method], list[Mention]]:
    """Run the ways that can work here, and say which those were."""
    ran: list[Method] = []
    mentions: list[Mention] = []
    if "ner" in payload.methods:
        nlp = load_spacy(model_path)
        if nlp is not None:
            ran.append("ner")
            mentions.extend(mentions_from_ner(nlp, payload.text))
    if "dictionary" in payload.methods and registry.archives:
        ran.append("dictionary")
        mentions.extend(mentions_from_titles(registry.archives, payload.text))
    return ran, mentions


@router.post(
    "/entities",
    response_model=EntitiesResponse,
    dependencies=[Depends(rate_limited)],
    summary="Entitäten in einem Text erkennen",
)
def entities(payload: EntitiesRequest, request: Request) -> EntitiesResponse:
    """Recognise the entities of a text and, unless ``link`` is off, name the article behind each of them."""
    settings = request.app.state.settings
    registry = archives_for(request.app.state.registry, payload.archives)
    ran, mentions = _recognise(payload, registry, settings.spacy_model)
    if not ran:
        raise HTTPException(
            status_code=503,
            detail="Kein Verfahren verfügbar: für ner fehlt das spaCy-Modell, für dictionary fehlen die Archive",
        )
    found = merge(mentions)[: payload.max_entities]
    linked = [_link(registry.archives, mention) if payload.link else None for mention in found]
    return EntitiesResponse(
        methods=ran,
        archives=[archive.id for archive in registry.archives],
        entities=[
            Entity(
                text=mention.text,
                start=mention.start,
                end=mention.end,
                kind=mention.kind,
                source=mention.source,
                linked=article is not None,
                article=article,
            )
            for mention, article in zip(found, linked, strict=True)
        ],
    )
