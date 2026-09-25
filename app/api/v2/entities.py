"""Entities in a text (docs/umbau.md, U3): recognise first, link afterwards.

The two layers stand alone on purpose. Recognition by the model needs no archive, so a service that carries
only the Klexikon - or no archive at all - still answers with the names in the text. Linking uses whatever
archives are loaded and adds the article, its lead and the kind the lead reveals. The answer says which way
found what, so a caller can tell the difference instead of guessing.

The endpoint deliberately does not use ``get_service``, which reports 503 until the archives are loaded: recognition
needs no archive, and a node (``node_id``) is read through the service without one.

The dictionary promises terms that have an article, so a term whose entry turns out to be a disambiguation
page is left out rather than returned unlinked - measured against the real Wikipedia, that removes about half
the noise and costs no real term (docs/umbau.md U3b). Recognition by the model is never filtered this way:
it makes no promise about archives.

A linked Wikipedia article also names its identifiers (D43), all from local data: GND and VIAF from the Normdaten
block the dump keeps, the Wikidata number from the index ``compendium wikidata build`` writes, the DBpedia URI built
from the title. No live API is asked; without the index the Wikidata number is simply missing.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.api.deps import archives_for, node_errors
from app.api.limits import rate_limited
from app.domain.models import NodeInput, Source
from app.domain.requests import NODE_ID_HELP, NODE_ID_PATTERN, REPOSITORY_HELP
from app.knowledge.entities import classify_entity, is_work
from app.knowledge.identifiers import identifiers
from app.knowledge.linking import article_of
from app.knowledge.recognise import Mention, load_spacy, mentions_from_ner, mentions_from_titles, merge
from app.sources.wikidata.index import WikidataIndex
from app.sources.wlo.models import NodeInfo
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import ZimRegistry

router = APIRouter(prefix="/api/v2", tags=["v2"])

Method = Literal["ner", "dictionary"]
MAX_TEXT_CHARS = 50_000  # a request body is caller input; recognition is linear in the text length
EXAMPLES = {
    "aus einem Text": {
        "summary": "Namen und Begriffe eines Textes, mit Artikel und Kennungen",
        "value": {"text": "Alexander von Humboldt reiste 1799 nach Südamerika."},
    },
    "aus einem Knoten des Repositorys": {
        "summary": "Titel, Beschreibung und Schlagwörter eines Materials der WLO-Staging",
        "description": (
            "node_id nennt ein Material oder eine Sammlung. Gelesen wird ohne Zugangsdaten, also nur Öffentliches; "
            "die Antwort gibt den gelesenen Text unter text zurück, start und end zählen darin."
        ),
        "value": {
            "node_id": "ac66224b-42b0-4676-a53d-71b058dc780b",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
        },
    },
}
UNCHECKED_NOTE = (
    "link=false: ohne Nachschlagen lässt sich nicht erkennen, ob hinter einem Begriff ein Artikel oder eine "
    "Begriffsklärungsseite steht; die Treffer des Wörterbuchs sind deshalb ungeprüft"
)


def _default_methods() -> list[Method]:
    return ["ner", "dictionary"]


class EntitiesRequest(BaseModel):
    text: str | None = Field(
        None,
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description="The text the entities are read from; or node_id instead, whose title, description and keywords "
        "become the text",
    )
    node_id: str | None = Field(None, pattern=NODE_ID_PATTERN, description=NODE_ID_HELP)
    repository: str | None = Field(None, max_length=300, description=REPOSITORY_HELP)
    methods: list[Method] = Field(
        default_factory=_default_methods,
        min_length=1,
        description="ner needs the spaCy model, dictionary needs archives; a way that cannot work is left out",
    )
    link: bool = Field(True, description="Look up the article behind each entity in the archives")
    archives: list[str] = Field(default_factory=list, description="Archive ids to ask; empty asks all of them")
    max_entities: int = Field(
        50,
        ge=1,
        le=200,
        description="Upper bound; it applies before the article check, so fewer may come back when terms of the "
        "dictionary turn out to sit behind a disambiguation page",
    )

    @model_validator(mode="after")
    def _text_or_node(self) -> EntitiesRequest:
        if not self.text and not self.node_id:
            raise ValueError("text oder node_id ist erforderlich")
        if self.text and self.node_id:
            raise ValueError("text oder node_id, nicht beides: der Knoten liefert den Text")
        if self.repository and not self.node_id:
            raise ValueError("repository gilt für node_id; ohne node_id fehlt der Knoten")
        return self


class EntityIds(BaseModel):
    gnd: str | None = Field(
        description="GND number from the article's Normdaten block; URI https://d-nb.info/gnd/<gnd>"
    )
    gnd_kind: str | None = Field(
        description="Kind of the GND record as the Normdaten block names it: Person, Sachbegriff, Geografikum, "
        "Körperschaft, Werk, ..."
    )
    viaf: str | None = Field(description="VIAF number from the same block; URI https://viaf.org/viaf/<viaf>")
    wikidata: str | None = Field(
        description="Wikidata number from the local index (compendium wikidata build); missing without the index "
        "or for an article the dump does not know; URI http://www.wikidata.org/entity/<wikidata>"
    )
    dbpedia: str = Field(description="DBpedia URI built from the title, not checked against DBpedia")
    same_as: list[str] = Field(description="Every identifier above as a URI, in the order GND, VIAF, Wikidata, DBpedia")


class EntityArticle(BaseModel):
    title: str
    archive: str
    project: str
    url: str
    lead: str
    kind: str | None = Field(description="Person, Organisation, Vorhaben, Netzwerk or Werk, read from the lead")
    ids: EntityIds | None = Field(
        None, description="GND, VIAF, Wikidata and DBpedia, from local data only; null for articles outside Wikipedia"
    )


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
    note: str | None = Field(
        None,
        description="What a reader should know about how the entities came about: with link=false the dictionary "
        "cannot tell an article from a disambiguation page, so its terms are unchecked",
    )
    node: NodeInput | None = Field(None, description="The node whose title, description and keywords were read")
    text: str | None = Field(
        None, description="The text read from node_id - start and end count in it; null when the request sent one"
    )


def _article_kind(source: Source) -> str | None:
    """What the lead reveals: an actor kind, ``Werk`` for a single work, or nothing for a subject."""
    return classify_entity(source) or ("Werk" if is_work(source) else None)


def _ids(title: str, html: str, wikidata: WikidataIndex | None) -> EntityIds:
    found = identifiers(title, html, wikidata)
    return EntityIds(
        gnd=found.gnd,
        gnd_kind=found.gnd_kind,
        viaf=found.viaf,
        wikidata=found.wikidata,
        dbpedia=found.dbpedia,
        same_as=found.same_as,
    )


def _link(archives: list[ZimArchive], mention: Mention, wikidata: WikidataIndex | None = None) -> EntityArticle | None:
    """The article of this name with its lead, kind and identifiers (``article_of``); a disambiguation page is none."""
    found = article_of(archives, mention)
    if found is None:
        return None
    archive, article = found
    source = archive.to_source(article, is_primary=False)
    return EntityArticle(
        title=source.title,
        archive=archive.id,
        project=source.project,
        url=source.url,
        lead=source.lead_text[:400],
        kind=_article_kind(source),
        ids=_ids(article.title, article.html, wikidata) if source.project == "wikipedia" else None,
    )


def _recognise(
    text: str, methods: list[Method], registry: ZimRegistry, model_path: str
) -> tuple[list[Method], list[Mention]]:
    """Run the ways that can work here, and say which those were."""
    ran: list[Method] = []
    mentions: list[Mention] = []
    if "ner" in methods:
        nlp = load_spacy(model_path)
        if nlp is not None:
            ran.append("ner")
            mentions.extend(mentions_from_ner(nlp, text))
    if "dictionary" in methods and registry.archives:
        ran.append("dictionary")
        mentions.extend(mentions_from_titles(registry.archives, text))
    return ran, mentions


def _node_text(info: NodeInfo) -> str:
    """Title, description and keywords of a node, one per line, as the text its entities are read from."""
    lines = [info.title, info.description, ", ".join(info.keywords)]
    return "\n".join(line for line in lines if line)[:MAX_TEXT_CHARS]


@router.post(
    "/entities",
    response_model=EntitiesResponse,
    dependencies=[Depends(rate_limited)],
    summary="Entitäten in einem Text erkennen",
)
def entities(
    payload: Annotated[EntitiesRequest, Body(openapi_examples=EXAMPLES)], request: Request
) -> EntitiesResponse:
    """Recognise the entities of a text and, unless ``link`` is off, name the article behind each.

    Two ways, and ``methods`` picks them. ``ner`` reads the spaCy model and needs no archives at all;
    ``dictionary`` looks for terms that have an article. The answer says under ``methods`` which ways
    really ran, and per entity where it came from (``source``), what it is (``kind``), whether an article
    was found (``linked``) and the article with its lead.

    A linked Wikipedia article carries ``ids``: GND, its kind and VIAF from the Normdaten block of the archive,
    the Wikidata number from the local index (``compendium wikidata build``; ``/health`` says whether it is
    there) and the DBpedia URI built from the title, all as URIs again under ``same_as``. Nothing is asked
    online. Articles of other archives carry no ``ids``.

    ``link: false`` skips the lookup, ``archives`` narrows it to single archives (unknown id: 404).
    ``max_entities`` bounds the result, and it bites before the lookup - so fewer may come back.

    A term of the dictionary whose only article is a disambiguation page is dropped: that way promises
    terms **with** an article. This does not apply to ``ner`` and not with ``link: false``; there ``note``
    says the result is unchecked. When neither way can run - no model and no archives - the answer is 503.

    ``node_id`` instead of ``text`` reads title, description and keywords of a node of an edu-sharing repository,
    without credentials, and returns that text under ``text``; ``start`` and ``end`` count in it. Not both: 422.
    Unknown or not public node: 404, refused ``repository``: 422, failing repository: 502, none at all: 503.
    """
    settings = request.app.state.settings
    registry = archives_for(request.app.state.registry, payload.archives)
    node, text = None, payload.text
    if payload.node_id:  # no archive is needed for this, so the service is asked directly
        with node_errors():
            info, node = request.app.state.service.read_node(payload.node_id, payload.repository)
        text = _node_text(info)
    ran, mentions = _recognise(text or "", payload.methods, registry, settings.spacy_model)
    if not ran:
        raise HTTPException(
            status_code=503,
            detail="Kein Verfahren verfügbar: für ner fehlt das spaCy-Modell, für dictionary fehlen die Archive",
        )
    found = merge(mentions)[: payload.max_entities]
    wikidata = getattr(request.app.state, "wikidata", None)
    linked = [_link(registry.archives, mention, wikidata) if payload.link else None for mention in found]
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
            if article is not None or mention.source != "dictionary" or not payload.link
        ],
        note=UNCHECKED_NOTE if not payload.link and "dictionary" in ran else None,
        node=node,
        text=text if payload.text is None else None,
    )
