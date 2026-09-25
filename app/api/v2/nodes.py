"""A node of an edu-sharing repository as the service reads it (D45): its metadata and the topic derived from it.

The same reading feeds ``node_id`` in compendium, knowledge, qa and entities; this endpoint shows it before a
request builds anything, so a caller sees which topic, subject and context words a node would bring. It needs no
archive, so it reads the service directly instead of waiting for the archives to be ready.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import Field

from app.api.deps import node_errors
from app.api.limits import rate_limited
from app.domain.models import NodeInput
from app.domain.requests import NODE_ID_PATTERN, REPOSITORY_HELP
from app.knowledge.main_article import choose_main_article
from app.knowledge.node_article import node_block
from app.sources.wlo.part import derive_topic, node_topic

router = APIRouter(prefix="/api/v2", tags=["v2"])

STAGING_REPOSITORY = "https://repository.staging.openeduhub.net/edu-sharing/rest"
STAGING_MATERIAL = "ac66224b-42b0-4676-a53d-71b058dc780b"  # "Stationsarbeit zur Optik" in the staging repository
STAGING_COLLECTION = "9e7ae956-e9df-430f-bace-f3db4b910013"  # the collection "Optik" there


class NodePreview(NodeInput):
    topic: str | None = Field(
        description="The topic a request with this node alone resolves without the LLM: a collection's title; for a "
        "material the article the rules find in its title and description (D47), null when they find none or no "
        "archive is loaded. With article_choice llm the LLM names a material's article instead, and a topic sent "
        "along leads"
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


@router.get(
    "/nodes/{node_id}",
    response_model=NodePreview,
    dependencies=[Depends(rate_limited)],
    summary="Knoten eines Repositorys lesen: Metadaten und abgeleitetes Thema",
)
def read_node(
    request: Request,
    node_id: Annotated[
        str,
        Path(
            pattern=NODE_ID_PATTERN,
            description="nodeId of a material or collection",
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
    """Read a material or a collection and say what it would bring to a request with ``node_id``.

    Title, description, keywords, subjects and educational levels come from the node's metadata
    (``/node/v1/nodes/-home-/{id}/metadata``); ``topic``, ``subject`` and ``context`` are what the service
    derives from them, as a request with the node alone would without the LLM. For a material the topic is the
    article the rules find in its title and description, and ``node_article`` shows how (D47). Without
    ``repository`` the configured one is asked; another
    one must be an allowed host over https (``EDU_SHARING_REPOSITORIES``). Nodes are read without credentials, so
    only public ones come back. Refused address: 422, unknown or not public node: 404, failing repository: 502,
    none configured and none named: 503.
    """
    service = request.app.state.service
    with node_errors():
        info, node = service.read_node(node_id, repository)
    found = derive_topic(None, [node_topic(info)])
    topic: str | None = found.normalized.topic
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
    )
