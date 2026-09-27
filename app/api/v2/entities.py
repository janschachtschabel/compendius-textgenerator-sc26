"""Entities in a text (docs/umbau.md, U3): recognise first, link afterwards.

The two layers stand alone on purpose. Recognition by the model needs no archive, so a service that carries
only the Klexikon - or no archive at all - still answers with the names in the text. Linking uses whatever
archives are loaded and adds the article, its lead and the kind the lead reveals. The answer says which way
found what, so a caller can tell the difference instead of guessing.

The endpoint deliberately does not use ``get_service``, which reports 503 until the archives are loaded: recognition
needs no archive, and a node (``node_id``) is read through the service without one.

The dictionary promises terms that have an article, so a term whose entry turns out to be a disambiguation
page is left out rather than returned unlinked - measured against the real Wikipedia, that removes about half
the noise and costs no real term (docs/umbau.md U3b). The LLM makes the same promise - it names the title of the
article - and is held to it. Recognition by the spaCy model is never filtered this way: it makes no promise about
archives.

Which ways run is the profile's (D62, M36): llm-free the spaCy model and the dictionary, balanced and the
best-quality profiles the LLM naming the entities (app/knowledge/entities_llm.py). The LLM checks the links only when
a request asks for it (``link_check``): measured through this endpoint, the check cost more fitting entities than it
removed minor ones.

A linked Wikipedia article also names its identifiers (D43), all from local data: GND and VIAF from the Normdaten
block the dump keeps, the Wikidata number from the index the Wikidata sync builds (D64), the DBpedia URI built
from the title. No live API is asked; without the index the Wikidata number is simply missing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.deps import archives_for, node_errors
from app.api.limits import rate_limited
from app.api.v2.entities_schemas import (
    EXAMPLES,
    MAX_TEXT_CHARS,
    PROFILE_METHODS,
    EntitiesLlm,
    EntitiesRequest,
    EntitiesResponse,
    Entity,
    EntityArticle,
    EntityIds,
    Method,
)
from app.domain.models import Source
from app.knowledge.entities import classify_entity, is_work
from app.knowledge.entities_llm import EntitiesLlmReport, EntityLlmJob, Link, grade_links, named_mentions
from app.knowledge.identifiers import identifiers
from app.knowledge.linking import article_of
from app.knowledge.recognise import Mention, load_spacy, mentions_from_ner, mentions_from_titles, merge
from app.llm.deadline import Deadline
from app.service import CompendiumService, LlmNotConfiguredError
from app.sources.wikidata.index import WikidataIndex
from app.sources.wlo.models import NodeInfo
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import ZimRegistry

router = APIRouter(prefix="/api/v2", tags=["v2"])

RULE_METHODS: tuple[Method, ...] = ("ner", "dictionary")
WITH_ARTICLE = frozenset({"dictionary", "llm"})  # the ways that promise terms with an article
RULES_USED = "Regelmodus verwendet"
NO_ARCHIVES = "ohne Archive kann das LLM keine Artikel nennen"


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


def _refuse_without_llm(service: CompendiumService, needed: list[str], profile: str, *, defaulted: bool) -> None:
    """What needs an LLM on a server without one is a 503 (D53), as everywhere else."""
    try:
        service.refuse_without_llm(needed, profile, defaulted=defaulted)
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _llm_job(service: CompendiumService, profile: str, report: EntitiesLlmReport) -> EntityLlmJob | None:
    """The budget and deadline of the LLM ways; ``None`` while the LLM is not available, and ``report`` says why."""
    unavailable = service.llm_unavailable()
    if unavailable is not None:
        report.fail(unavailable)
    budget = service.open_budget(profile)
    if unavailable is not None or budget is None or service.llm is None:
        return None
    return EntityLlmJob(service.llm.client, budget, Deadline(service.settings.request_timeout_s))


def _named(
    job: EntityLlmJob | None, text: str, registry: ZimRegistry, report: EntitiesLlmReport, max_entities: int
) -> tuple[list[Mention] | None, str | None]:
    """The entities the LLM names; ``None`` and a note when ner and dictionary have to take its place."""
    if job is None:
        return None, report.fallback  # llm_unavailable names the cause and the fallback itself
    if not registry.archives:
        report.fail(NO_ARCHIVES)
        return None, f"{NO_ARCHIVES}; {RULES_USED}"
    named = named_mentions(job, text, report, max_entities=max_entities)
    if named is None:
        return None, f"Entitäten des LLM entfielen: {report.reason}; {RULES_USED}"
    return named, None


def _checked(
    job: EntityLlmJob | None, text: str, entities: list[Entity], report: EntitiesLlmReport
) -> tuple[list[Entity], str | None]:
    """The entities whose article the LLM grades 2, and those without an article; all of them and a note when the
    LLM gives no usable answer. Each article is shown once, with the first word that names it."""
    first: dict[tuple[str, str], tuple[str, EntityArticle]] = {}
    for entity in entities:
        if entity.article is not None:
            first.setdefault((entity.article.archive, entity.article.title), (entity.text, entity.article))
    if not first:
        return entities, None
    if job is None:
        return entities, report.fallback
    links = [Link(word, article.title, article.lead) for word, article in first.values()]
    grades = grade_links(job, text, links, report)
    if grades is None:
        return entities, f"Prüfung durch das LLM entfiel: {report.reason}; alle Verknüpfungen bleiben"
    kept = {key for key, grade in zip(first, grades, strict=True) if grade == 2}
    report.dropped = [title for (_, title), grade in zip(first, grades, strict=True) if grade != 2]
    return [e for e in entities if e.article is None or (e.article.archive, e.article.title) in kept], None


def _unchecked(ran: list[Method]) -> str | None:
    """With link=false nobody can tell an article from a disambiguation page; say so for the ways that promise one."""
    ways = [method for method in ran if method in WITH_ARTICLE]
    if not ways:
        return None
    return (
        "link=false: ohne Nachschlagen lässt sich nicht erkennen, ob hinter einem Begriff ein Artikel oder eine "
        f"Begriffsklärungsseite steht; die Treffer von {' und '.join(ways)} sind deshalb ungeprüft"
    )


def _llm_answer(report: EntitiesLlmReport | None) -> EntitiesLlm | None:
    if report is None:
        return None
    return EntitiesLlm(
        named=report.named,
        checked=report.checked,
        dropped=report.dropped,
        calls=report.calls,
        total_tokens=report.total_tokens,
        model=report.model,
        prompts=report.prompts,
        fallback=report.fallback,
    )


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

    Three ways, and ``methods`` picks them. ``ner`` reads the spaCy model and needs no archives at all;
    ``dictionary`` looks for terms that have an article; ``llm`` lets the LLM of the b-api name the entities the
    text is about, each with the title of its article. The answer says under ``methods`` which ways really ran, and
    per entity where it came from (``source``), what it is (``kind``), whether an article was found (``linked``)
    and the article with its lead. ``link_check: llm`` lets the LLM grade every link as well, and only what it
    grades 2 stays; ``llm`` in the answer says what the LLM did and cost.

    A linked Wikipedia article carries ``ids``: GND, its kind and VIAF from the Normdaten block of the archive,
    the Wikidata number from the local index (built by the ``wikidata-updater`` sidecar; ``/health`` says whether
    it is there) and the DBpedia URI built from the title, all as URIs again under ``same_as``. Nothing is asked
    online. Articles of other archives carry no ``ids``.

    ``link: false`` skips the lookup, ``archives`` narrows it to single archives (unknown id: 404).
    ``max_entities`` bounds the result, and it bites before the lookup - so fewer may come back.

    A term of dictionary or llm whose only article is a disambiguation page, or that has none, is dropped: these
    ways promise terms **with** an article. This does not apply to ``ner`` and not with ``link: false``; there
    ``note`` says the result is unchecked. When no way can run - no model, no archives, no LLM - the answer is 503.

    ``node_id`` instead of ``text`` reads title, description and keywords of a node of an edu-sharing repository,
    without credentials, and returns that text under ``text``; ``start`` and ``end`` count in it. Not both: 422.
    Unknown or not public node: 404, refused ``repository``: 422, failing repository: 502, none at all: 503.

    **What each profile does here** (D62). ``preset`` sets ``methods`` where the request leaves it open; without it
    the server's profile applies (PRESET_DEFAULT, shipped balanced). Measured on the texts of 40 materials against
    two blind raters, through this endpoint (M36, gpt-6-luna):

    - ``llm-free``: ner and dictionary, no LLM. F1 0.38 at a precision of 0.29, about 0.25 s.
    - ``balanced``, ``best-quality`` and ``best-quality-generated``: the LLM names the entities (methods llm).
      F1 0.78 at a precision of 0.70, about 800 tokens and 4 s.

    No profile sets ``link_check: llm``: the check raised the precision to 0.94 but dropped a third of the fitting
    entities (F1 0.76), for about 820 tokens and 2 s more; a request that wants a short, sure list sets it. A profile
    or switch that needs an LLM on a server without one is a 503 that names llm-free; while the b-api is not
    available ner and dictionary stand in for llm, every link stays, and ``note`` says why. The examples go from a
    text alone over llm-free and the check to one that sets every field a text goes with.
    """
    settings = request.app.state.settings
    service: CompendiumService = request.app.state.service
    registry = archives_for(request.app.state.registry, payload.archives)
    profile = payload.preset or settings.preset_default
    methods = payload.methods or PROFILE_METHODS[profile]
    check = payload.link and payload.link_check == "llm"
    needed = (["methods=llm"] if "llm" in methods else []) + (["link_check=llm"] if check else [])
    _refuse_without_llm(service, needed, profile, defaulted=not payload.preset)
    node, text = None, payload.text or ""
    if payload.node_id:  # no archive is needed for this, so the service is asked directly
        with node_errors():
            info, node = service.read_node(payload.node_id, payload.repository)
        text = _node_text(info)
    report = EntitiesLlmReport() if needed else None
    job = _llm_job(service, profile, report) if report is not None else None
    notes: list[str | None] = []
    named: list[Mention] | None = None
    if "llm" in methods and report is not None:
        named, fallback = _named(job, text, registry, report, payload.max_entities)
        notes.append(fallback)
    rules = [method for method in RULE_METHODS if method in methods or ("llm" in methods and named is None)]
    ran, mentions = _recognise(text, rules, registry, settings.spacy_model)
    if named is not None:
        # on the very word the LLM named, its title wins: the rules would look the word up and may find a
        # disambiguation page where the LLM named the article (review of D62)
        places = {(mention.start, mention.end) for mention in named}
        mentions = [mention for mention in mentions if (mention.start, mention.end) not in places]
        ran.append("llm")
        mentions.extend(named)
    if not ran:
        raise HTTPException(
            status_code=503,
            detail="Kein Verfahren verfügbar: für ner fehlt das spaCy-Modell, für dictionary und llm fehlen die "
            "Archive",
        )
    found = merge(mentions)[: payload.max_entities]
    wikidata = getattr(request.app.state, "wikidata", None)
    linked = [_link(registry.archives, mention, wikidata) if payload.link else None for mention in found]
    entities = [
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
        if article is not None or mention.source not in WITH_ARTICLE or not payload.link
    ]
    if check and report is not None:
        entities, fallback = _checked(job, text, entities, report)
        notes.append(fallback)
    notes.insert(0, None if payload.link else _unchecked(ran))
    return EntitiesResponse(
        methods=ran,
        archives=[archive.id for archive in registry.archives],
        entities=entities,
        note="; ".join(dict.fromkeys(note for note in notes if note)) or None,
        llm=_llm_answer(report),
        node=node,
        text=text if payload.text is None else None,
    )
