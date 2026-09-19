"""Legacy utilities (PLAN.md 8.1): splitting a text and synonyms, both without an LLM.

``split`` now honours the requested ``chunk_size`` (the old service overwrote it with a setting).
``synonyms`` reads the archives: the titles a word leads to, the alternative names of the article's lead and
the suggestions of the full-text index. Where the old service answered an empty list after a failed LLM call,
this one answers an empty list because the archives know nothing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.api.v1.models import SplitRequest, SplitResponse, SynonymRequest, SynonymResponse
from app.knowledge.chunking import clean, split_text
from app.sources.zim.registry import ZimRegistry

router = APIRouter(prefix="/api/v1/utils", tags=["v1"])

SUGGEST_EXTRA = 5  # ask for a few more than requested: the word itself and duplicates drop out


@router.post("/split", response_model=SplitResponse, dependencies=[Depends(rate_limited)])
def split(payload: SplitRequest) -> SplitResponse:
    """Chunks of at most ``chunk_size`` characters, whole sentences where they fit."""
    if not clean(payload.text):
        raise HTTPException(status_code=400, detail="text required")
    if payload.overlap >= payload.chunk_size:
        raise HTTPException(status_code=400, detail="overlap must be less than chunk_size")
    chunks = split_text(payload.text, chunk_size=payload.chunk_size, overlap=payload.overlap, split_by=payload.split_by)
    return SplitResponse(chunks=chunks)


@router.post("/synonyms", response_model=SynonymResponse, dependencies=[Depends(rate_limited)])
def synonyms(payload: SynonymRequest, request: Request) -> SynonymResponse:
    """Other names of a word from the archives: article title, alternative names of the lead, suggestions."""
    if payload.lang != "de":
        raise HTTPException(status_code=422, detail="Die Archive dieses Dienstes sind deutsch (lang=de)")
    registry = get_service(request).registry
    return SynonymResponse(synonyms=from_archives(registry, payload.word, payload.max_synonyms))


def from_archives(registry: ZimRegistry, word: str, limit: int) -> list[str]:
    """Titles and alternative names around ``word``, the word itself removed, at most ``limit``."""
    found: list[str] = []
    resolution = registry.resolve_topic(word)
    if resolution.title:
        found.append(resolution.title)
        found.extend(resolution.alternatives)
        source = registry.lookup(resolution.title)
        if source is not None:
            found.extend(source.aliases)
    for archive in registry.archives:
        found.extend(archive.suggest(word, limit=limit + SUGGEST_EXTRA))
    lowered = word.strip().lower()
    unique = dict.fromkeys(name.strip() for name in found if name.strip() and name.strip().lower() != lowered)
    return list(unique)[:limit]
