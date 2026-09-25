"""Matching endpoint: the strategies this build offers (PLAN.md 4.5).

The comparator (``POST /api/v2/matching/compare``) left the API on 2026-09-25 (D50): no caller needed it in
production, and ``compendium eval`` runs the same comparison on the gold standard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.matching.registry import list_strategies

router = APIRouter(prefix="/api/v2/matching", tags=["matching"])


@router.get("/strategies")
def matching_strategies() -> list[dict[str, Any]]:
    """The matching strategies this build offers, with cost and hardware.

    Matching assigns passages to the blocks of a template. All strategies but ``llm`` run locally and
    cost nothing; ``llm`` lets the LLM of the b-api assign every passage and falls back on the default
    strategy where it cannot. The extraction and generation switches of POST /api/v2/compendium come
    after the matching.
    """
    return list_strategies()
