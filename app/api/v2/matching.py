"""Matching endpoints: available strategies and the comparator (PLAN.md 4.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin import require_admin
from app.api.deps import get_service
from app.matching.eval_runner import DEFAULT_MATCHERS, compare_topic, find_gold
from app.matching.registry import list_strategies
from app.service import TopicNotFoundError
from app.templates.manager import TemplateNotFoundError

router = APIRouter(prefix="/api/v2/matching", tags=["matching"])
# The comparator builds a corpus and runs several strategies: a diagnosis tool, not a public endpoint.
admin = APIRouter(prefix="/api/v2/matching", tags=["matching-admin"], dependencies=[Depends(require_admin)])


class CompareRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=300)
    matchers: list[str] = Field(default_factory=lambda: list(DEFAULT_MATCHERS), min_length=1, max_length=8)
    template_id: str | None = None
    target_length: int = Field(12_000, ge=2_000, le=60_000)


@router.get("/strategies")
def matching_strategies() -> list[dict[str, Any]]:
    return list_strategies()


@admin.post("/compare")
def compare(payload: CompareRequest, request: Request) -> dict[str, Any]:
    """Run several strategies on one topic; with a gold file the metrics come along, agreement always."""
    service = get_service(request)
    matchers = list(dict.fromkeys(payload.matchers))
    known = {strategy["id"] for strategy in list_strategies()}
    unknown = [name for name in matchers if name not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unbekannte Strategie(n): {', '.join(unknown)}")
    gold_dir = request.app.state.settings.eval_gold_dir
    try:
        result = compare_topic(
            service,
            payload.topic,
            matchers,
            gold_for=lambda *names: find_gold(gold_dir, *names),
            template_id=payload.template_id,
            target_length=payload.target_length,
        )
    except TopicNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": "Thema in den Archiven nicht gefunden", "resolution": exc.resolution.model_dump()},
        ) from exc
    except TemplateNotFoundError as exc:  # as POST /api/v2/compendium answers it
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    gold: dict[str, Any] | None = None
    if result.gold is not None and result.alignment is not None:
        gold = {
            "topic": result.gold.topic,
            "labeled": len(result.alignment.gold_by_chunk),
            "stale": len(result.alignment.stale),
            "labeled_by": result.gold.labeled_by,
        }
    return {
        "topic": result.topic,
        "resolution": result.resolution.model_dump(),
        "chunks": result.chunks,
        "gold": gold,
        "results": {
            name: {
                "assigned": outcome.assigned,
                "filled_slots": outcome.filled_slots,
                "duration_ms": outcome.duration_ms,
                "metrics": outcome.metrics.model_dump() if outcome.metrics is not None else None,
            }
            for name, outcome in result.results.items()
        },
        "agreement": result.agreement,
    }
