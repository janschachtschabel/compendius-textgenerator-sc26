"""A node of an edu-sharing repository as the service reads it (D45): its metadata and the topic derived from it.

The same reading feeds ``node_id`` in compendium, knowledge, qa and entities; this endpoint shows it before a
request builds anything, so a caller sees which topic, subject and context words a node would bring. It needs no
archive, so it reads the service directly instead of waiting for the archives to be ready.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import Field

from app.api.deps import node_errors
from app.api.limits import rate_limited
from app.domain.models import NodeInput
from app.domain.requests import NODE_ID_PATTERN, REPOSITORY_HELP
from app.sources.wlo.part import node_topic

router = APIRouter(prefix="/api/v2", tags=["v2"])

STAGING_REPOSITORY = "https://repository.staging.openeduhub.net/edu-sharing/rest"
STAGING_MATERIAL = "ac66224b-42b0-4676-a53d-71b058dc780b"  # "Stationsarbeit zur Optik" in the staging repository


class NodePreview(NodeInput):
    topic: str = Field(description="The topic a request with this node resolves, unless it sends a topic of its own")
    subject: str | None = Field(None, description="The subject URI it brings to the article choice and part 2")
    context: list[str] = Field(
        default_factory=list, description="Context words of the article choice: the levels, then the keywords"
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
        Path(pattern=NODE_ID_PATTERN, description="nodeId of a material or collection", examples=[STAGING_MATERIAL]),
    ],
    repository: Annotated[
        str | None, Query(max_length=300, description=REPOSITORY_HELP, examples=[STAGING_REPOSITORY])
    ] = None,
) -> NodePreview:
    """Read a material or a collection and say what it would bring to a request with ``node_id``.

    Title, description, keywords, subjects and educational levels come from the node's metadata
    (``/node/v1/nodes/-home-/{id}/metadata``); ``topic``, ``subject`` and ``context`` are what the service
    derives from them. Without ``repository`` the configured one is asked; another one must be an allowed host
    over https (``EDU_SHARING_REPOSITORIES``) and is read anonymously. Refused address: 422, unknown node: 404,
    failing repository: 502, none configured and none named: 503.
    """
    with node_errors():
        info, node = request.app.state.service.read_node(node_id, repository)
    derived = node_topic(info)
    return NodePreview(**node.model_dump(), topic=derived.topic, subject=derived.subject, context=derived.context)
