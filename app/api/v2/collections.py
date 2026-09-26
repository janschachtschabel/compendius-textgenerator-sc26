"""Collection endpoint (PLAN.md 8.2): part 3 for one collection, read from the edu-sharing repository."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from app.api.limits import rate_limited
from app.llm.deadline import Deadline
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError, validate_node_id
from app.sources.wlo.part import CollectionBuilder

router = APIRouter(prefix="/api/v2/collections", tags=["collections"])
STAGING_COLLECTION = "9e7ae956-e9df-430f-bace-f3db4b910013"  # the collection "Optik" of the WLO staging


@router.get("/{collection_id}/overview", dependencies=[Depends(rate_limited)])
def collection_overview(
    collection_id: Annotated[
        str,
        Path(
            description="The node id of the collection in the configured repository (EDU_SHARING_BASE_URL), a UUID; "
            "anything else is a 422",
            openapi_examples={"Sammlung der WLO-Staging": {"summary": "Optik", "value": STAGING_COLLECTION}},
        ),
    ],
    request: Request,
) -> dict[str, Any]:
    """Part 3 for one edu-sharing collection: purpose, key figures and one line per node of its tree.

    The same part a compendium request produces with ``parts: ["collection"]``, but on its own and
    without a topic - useful to look at a collection before putting it into a compendium.

    Every node - the collection, each sub-collection, each content - names its kind and its node id, so
    another system can read the tree back from the markdown and look every node up in the repository.

    **Profiles.** No profile changes this endpoint, so it takes no ``preset``: part 3 lists what the repository
    holds, without an LLM in all four profiles (llm-free, balanced, best-quality, best-quality-generated).

    Unknown collection: 404. Repository unreachable: 502; none configured: 503. The endpoint keeps to
    ``REQUEST_TIMEOUT_S``; if it runs out, ``summary.incomplete`` is set and the text says which lists stayed
    short. The answer is cached, so a second call within the hour is free.

    **Example:** ``/api/v2/collections/9e7ae956-e9df-430f-bace-f3db4b910013/overview`` - the collection Optik of
    the WLO staging; the path is the whole request.
    """
    builder: CollectionBuilder | None = request.app.state.collections
    if builder is None:
        raise HTTPException(status_code=503, detail="Kein edu-sharing-Repository konfiguriert (EDU_SHARING_BASE_URL).")
    try:
        validate_node_id(collection_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    deadline = Deadline(request.app.state.settings.request_timeout_s)  # the same budget as a compendium's part 3
    try:
        part = builder.overview(collection_id, expired=lambda: deadline.remaining() <= 0)
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EduSharingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc  # the message names the repository
    if not part.available:  # read, but not listed: inside a compendium a hint, on its own a failed request
        raise HTTPException(status_code=502, detail=part.error or "Die Sammlung ließ sich nicht auflisten")
    return part.model_dump()
