"""v2 endpoints: compendium generation and templates (archives: zim.py, matching: matching.py).

Reading templates is open; writing and deleting them sit behind ``ADMIN_TOKEN`` like the archive
endpoints, because a template decides what every following compendium looks like (docs/umbau.md U6).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request

from app.api.admin import require_admin
from app.api.deps import get_service
from app.api.limits import rate_limited
from app.api.v2.routes_examples import BUILTIN_TEMPLATES, EXAMPLES, TEMPLATE_EXAMPLES, TEMPLATE_ID_HELP
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


@router.post(
    "/compendium",
    response_model=Compendium,
    dependencies=[Depends(rate_limited)],
    summary="Kompendium erzeugen",
)
def generate_compendium(
    payload: Annotated[GenerateRequest, Body(openapi_examples=EXAMPLES)], request: Request
) -> Compendium:
    """Generate the compendium for a topic, a node or a collection: the requested parts, made the way the profile
    and the switches say.

    **What it makes.** ``parts`` picks the parts: ``world`` is part 1, the compendium text itself; ``curricula``
    is part 2, the curriculum elements, each block of them naming its curriculum, federal state, school level and
    grade; ``collection`` is part 3, the materials of an edu-sharing collection, and needs ``collection_id``.
    ``topic``, ``node_id`` or ``collection_id`` names what it is about, and a topic sent along leads. ``subject``
    helps choose an ambiguous article and narrows part 2 to the curricula of that subject.

    **What each profile does.** ``preset`` picks one of the four profiles of the decision paper (D53, D58, D59);
    without it the server's applies (PRESET_DEFAULT, shipped balanced), and a switch the request sets itself wins
    over the profile's. Quality, time and tokens per profile are in the help text of ``preset``.

    - ``llm-free``: no LLM anywhere. The rules choose the articles, ``hybrid_light`` assigns the paragraphs, the
      text stays verbatim with its citations, and part 2 lists what the keyword rules find - an element only its
      heading names is counted with its area. No tokens.
    - ``balanced``: as llm-free, but the LLM decides where the rules are unsure about the article and drops the
      side articles that do not fit (``article_choice llm``). Part 2 as in llm-free.
    - ``best-quality``: balanced, and the LLM also checks a sure choice of a word with several meanings
      (``article_choice llm-thorough``), assigns every paragraph to its block (``matcher llm``) and rates every
      curriculum element of part 2, dropping what does not fit (``curriculum_check llm``). The text stays
      verbatim.
    - ``best-quality-generated``: best-quality, and the LLM writes every block from its evidence (``generation
      llm``) and may add knowledge of its own, marked ``[Modellwissen]`` (``enrichment model-knowledge``).

    The LLM steps of a request spend from one token budget and one deadline: LLM_MAX_TOKENS_PER_REQUEST (60,000)
    in llm-free and balanced, LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY (180,000) in the two best-quality profiles
    (D59), and REQUEST_TIMEOUT_S. What the budget, the time or an unavailable b-api leaves undone the rules do, and
    ``audit.llm`` says what really ran. Without ``world`` there is no part 1, no matching and no writing: only the
    article choice and, in the best-quality profiles, the check of part 2 can call on the LLM.

    **The switches**, each defaulting to the profile's:

    - ``article_choice``: who picks the articles - ``rule-based`` the rules alone, ``llm`` the model where the rules
      are unsure, and it drops side articles that do not fit; ``llm-thorough`` also where they are sure of a word
      with several meanings. ``resolution`` says how the article was found.
    - ``matcher``: how the paragraphs find their block - ``hybrid_light``, ``bm25``, ``char_tfidf`` and
      ``lexicon_only`` run locally, ``llm`` lets the model assign every paragraph. Quality and cost of each: the
      help text of the field and ``GET /api/v2/matching/strategies``; an unknown name is a 422.
    - ``extraction``: who picks the sentences - ``rule-based`` the policy's paragraphs, ``llm`` the model among the
      best candidates; the wording stays the source's.
    - ``generation``: who writes the blocks - ``rule-based`` verbatim excerpts, ``llm-fast`` the model the main
      ones, ``llm`` every one; every sentence carries its citation.
    - ``enrichment``: ``sources-only``, or ``model-knowledge`` - the writing model may add knowledge of its own.
    - ``curriculum_check``: who judges the elements of part 2 - ``rule-based`` the keyword rules, ``llm`` the model.

    **How long it gets.** ``target_length`` is shared over the blocks by weight and steers upwards until
    the sources run out. It is a steer, not a cap: a block is never shorter than its first paragraph.

    **What else.** ``template_id`` picks the template (``GET /api/v2/templates``), ``max_articles`` the size of
    the corpus, and ``knowledge_collection_id`` adds the reusable materials of a collection to the sources of part
    1. ``facets_visible`` and ``empty_slot_policy`` override the settings and the template. ``existing_markdown``
    with ``regenerate_sections`` makes only the named blocks anew and keeps the rest word for word.
    ``frontmatter_in_markdown: false`` starts the text at the heading instead of the YAML block - the same data
    stays in the ``frontmatter`` field. ``language`` is ``de``, the only one so far.

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

    The examples run from the shortest request over one per profile to one that sets every field.
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
def get_template(
    template_id: Annotated[str, Path(description=TEMPLATE_ID_HELP, openapi_examples=BUILTIN_TEMPLATES)],
    request: Request,
) -> dict[str, Any]:
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
def put_template(
    template_id: Annotated[str, Path(description=TEMPLATE_ID_HELP)],
    payload: Annotated[Template, Body(openapi_examples=TEMPLATE_EXAMPLES)],
    request: Request,
) -> dict[str, Any]:
    """Store a custom template under this id; the version counts up on every write.

    The id in the path and the id in the body have to agree: silently renaming what the caller sent would
    put a template somewhere they did not ask for. Built-in templates are read-only (409). ``version`` and
    ``builtin`` are the server's: it counts the one and keeps the other false for what a caller writes. The
    examples go from the smallest template - an id, a name, one block - to one that sets every field; the fields
    of a block are explained under ``slots``. ``GET /api/v2/templates/sc26`` shows a full built-in one to start
    from. No profile changes a template; which blocks the LLM writes is ``generation`` of a compendium request.
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
def delete_template(template_id: Annotated[str, Path(description=TEMPLATE_ID_HELP)], request: Request) -> None:
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
