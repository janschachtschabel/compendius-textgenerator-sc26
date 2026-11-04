"""A node of an edu-sharing repository as the service reads it (D45): its metadata and the topic derived from it.

The same reading feeds ``node_id`` in compendium, knowledge, qa and entities; this endpoint shows it before a
request builds anything, so a caller sees which topic, subject and context words a node would bring. Reading a node
needs no archive, so it asks the service directly instead of waiting for the archives to be ready; only the article of
a material needs them, and without them its topic stays empty.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import Field

from app.api.deps import no_unknown_query
from app.api.gates import GatedRoute
from app.api.keys import require_api_key
from app.api.limits import rate_limited
from app.api.responses import PROFILE_REFUSALS
from app.domain.models import NodeInput
from app.domain.requests import NODE_ID_PATTERN, REPOSITORY_HELP
from app.domain.spelling import readable
from app.domain.text_input import (
    DESCRIPTION_MAX_CHARS,
    LIST_MAX_ITEMS,
    TITLE_MAX_CHARS,
    CollectionText,
    MaterialText,
)
from app.knowledge.collection_context import is_neutral, stand_in
from app.knowledge.derived_topic import derive_topic, node_topic
from app.knowledge.main_article import choose_main_article
from app.knowledge.node_article import node_block
from app.llm.deadline import Deadline
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.tree import TreeContext

router = APIRouter(prefix="/api/v2", tags=["v2"], route_class=GatedRoute)

STAGING_REPOSITORY = "https://repository.staging.openeduhub.net/edu-sharing/rest"
STAGING_MATERIAL = "ac66224b-42b0-4676-a53d-71b058dc780b"  # "Stationsarbeit zur Optik" in the staging repository
STAGING_COLLECTION = "9e7ae956-e9df-430f-bace-f3db4b910013"  # the collection "Optik" there


class NodePreview(NodeInput):
    topic: str | None = Field(
        description="The topic a request with this node alone resolves without the LLM: a collection's title, for a "
        'title that names no subject matter ("Grundlagen") the nearest collection above it that does (M71), else its '
        "subject, else its title; for a material the article the rules find in its title and description (D47), "
        "null when they find none or no archive is loaded. With article_choice llm the LLM names a material's article "
        "instead, and a topic sent along leads"
    )
    topic_subjects: list[str] = Field(
        default_factory=list,
        description="The subjects it brings to the article choice and part 2, all of equal weight: one the title "
        "names (label), else every subject of the node (URIs)",
    )
    context: list[str] = Field(
        default_factory=list,
        description="Context words of the resolution: qualifiers of the title, then the levels, then the keywords",
    )
    node_article: dict[str, Any] | None = Field(
        None,
        description="For a material: how the rules found its article - the title's article and the ranked terms of "
        "title and description (D47); null for a collection or without archives",
    )
    text_input: dict[str, MaterialText | CollectionText] = Field(
        description="The node as text (D114), ready to send in place of node_id: {'material': {...}} for a material, "
        "{'collection_context': {...}} for a collection with its place in the topic tree (path, children, materials, "
        "neighbours). A request with it needs no repository and gets the same compendium; the fields of compendium, "
        "knowledge and qa take it as it is"
    )


@router.get(
    "/nodes/{node_id}",
    response_model=NodePreview,
    dependencies=[Depends(rate_limited), Depends(require_api_key), Depends(no_unknown_query)],
    responses={**PROFILE_REFUSALS},
    summary="Knoten eines Repositorys lesen: Metadaten und abgeleitetes Thema",
)
def read_node(
    request: Request,
    node_id: Annotated[
        str,
        Path(
            pattern=NODE_ID_PATTERN,
            description="The node id of a material or a collection, a UUID; anything else is a 422",
            openapi_examples={
                "Material der WLO-Staging": {"summary": "Stationsarbeit zur Optik", "value": STAGING_MATERIAL},
                "Sammlung der WLO-Staging": {"summary": "Optik", "value": STAGING_COLLECTION},
            },
        ),
    ],
    repository: Annotated[
        str | None,
        Query(
            max_length=300,
            description=REPOSITORY_HELP,
            openapi_examples={"WLO-Staging": {"summary": "REST-Wurzel der WLO-Staging", "value": STAGING_REPOSITORY}},
        ),
    ] = None,
) -> NodePreview:
    """Read a material or a collection and say what it would bring to a request with ``node_id``, and hand it out as
    ``text_input`` - the same facts as text, which a request may send instead of ``node_id`` without reading the
    repository (D114): the metadata extraction before the service.

    Title, description, keywords, subjects and educational levels come from the node's metadata
    (``/node/v1/nodes/-home-/{id}/metadata``); ``topic``, ``topic_subjects`` and ``context`` are what the service
    derives from them, as a request with the node alone would without the LLM. For a material the topic is the
    article the rules find in its title and description, and ``node_article`` shows how (D47). Without
    ``repository`` the configured one is asked; another
    one must be an allowed host over https (``EDU_SHARING_REPOSITORIES``). The configured repository is read with
    its account if it has one (D112), any other one without credentials. Refused address: 422, unknown or
    hidden node: 404, failing repository: 502,
    none configured and none named: 503.

    **Profiles.** No profile changes this preview, so it takes no ``preset``: it always shows what the rules derive.
    A request with the node is where the profile acts - in llm-free the rules find a material's article as shown
    here, while in balanced, best-quality, best-quality-generated and best-coverage-generated the LLM names it from
    title, subjects, keywords and description (30 instead of 15 of 31 right, D47), so ``topic`` can differ there.

    **Examples** of ``GET``, from the shortest to every parameter:

    - ``/api/v2/nodes/ac66224b-42b0-4676-a53d-71b058dc780b`` - a material, in the configured repository
    - ``/api/v2/nodes/9e7ae956-e9df-430f-bace-f3db4b910013?repository=<root>`` - a collection, in a repository
      named by its REST root, e.g. ``https://repository.staging.openeduhub.net/edu-sharing/rest``
    """
    service = request.app.state.service
    # REQUEST_TIMEOUT_S as for every compendium read: a slow repository held the preview for the client's whole
    # timeout per read, up to three collections above a neutral one (review of 2026-10-08)
    deadline = Deadline(service.settings.request_time_limit_s)
    info, node = service.read_node(node_id, repository, remaining=deadline.remaining)
    found = derive_topic(None, [node_topic(info)], is_subject=service.subjects.knows)
    topic: str | None = found.normalized.topic
    title = found.normalized.topic
    # the subjects as a caller may write them: the label where the catalog knows it, else the URI (D114)
    named = dict(zip(info.subject_uris, info.subject_labels, strict=False))
    subjects = _titles(
        named[uri] if service.subjects.knows(named.get(uri, "")) else uri
        for uri in info.subject_uris
        if service.subjects.knows(named.get(uri, "")) or service.subjects.knows(uri)
    )  # an unknown one counts for nothing with node_id and would be a 422 as text
    text_input: dict[str, MaterialText | CollectionText]
    if info.kind == "collection":
        # the whole place, as the article choice with the LLM hears it; the rules take its path (M71)
        tree = service.collection_tree(info, None, repository, content=True, remaining=deadline.remaining)
        if is_neutral(title):  # it stands for the collection above it (M71)
            labels = service.subjects.labels_of(found.subjects)
            topic = stand_in(title, tree, labels, is_subject=service.subjects.knows) or title
        place = tree or TreeContext()
        text_input = {
            "collection_context": CollectionText(
                title=_title(info),
                path=_titles(place.path),
                children=_titles(place.children),
                materials=_titles(place.materials),
                neighbours=_titles(place.neighbours),
                subjects=subjects,
                levels=_titles(info.educational_contexts),
                missing=list(place.missing),
            )
        }
    else:
        text_input = {
            "material": MaterialText(
                title=_title(info),
                description=info.description[:DESCRIPTION_MAX_CHARS],
                keywords=_titles(info.keywords),
                subjects=subjects,
                levels=_titles(info.educational_contexts),
                url=info.url[:2_000] or None,
            )
        }
    node_article: dict[str, Any] | None = None
    if info.kind == "material":  # its title is often a format; the rules look for the article (D47)
        topic = None
        if request.app.state.registry.ready:
            chosen = choose_main_article(service.registry, service.subjects, None, [node_topic(info)], node=info)
            topic = chosen.resolution.normalized if chosen.resolution.resolved else None
            node_article = node_block(chosen.node) if chosen.node is not None else None
    return NodePreview(
        **node.model_dump(),
        topic=topic,
        topic_subjects=found.subjects,
        context=found.context,
        node_article=node_article,
        text_input=text_input,
    )


def _titles(values: Iterable[str]) -> list[str]:
    """Titles within the bounds of the text input: the repository holds longer ones than a caller may send."""
    return [title[:TITLE_MAX_CHARS] for title in values if readable(title).strip()][:LIST_MAX_ITEMS]


def _title(info: NodeInfo) -> str:
    """The node's title for the text input; a node without a readable one is named by its id."""
    return next(iter(_titles([info.title])), info.node_id)
