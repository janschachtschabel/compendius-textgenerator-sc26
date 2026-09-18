"""Part 3 for one compendium and the knowledge collection (PLAN.md 6): cached reads, overview, sources, topic.

The builder is the one place the service and the API talk to for collections. Repository answers are
cached for ``ttl_s`` (metadata, listings) so a compendium and its overview endpoint do not read the
same collection twice; a repository failure yields an honest hint in part 3 instead of failing part 1.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import CollectionPart
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient, EduSharingError
from app.sources.wlo.knowledge import KnowledgeOptions, KnowledgeResult, material_sources
from app.sources.wlo.models import CollectionInfo, MaterialRef, SubCollection
from app.sources.wlo.overview import (
    PART_HEADING,
    OverviewOptions,
    SubCollectionContents,
    render_collection_overview,
)

log = logging.getLogger(__name__)

UNAVAILABLE_TEXT = "*Der Sammlungsüberblick konnte nicht erstellt werden, das Repository antwortete nicht: {error}*"


@dataclass(frozen=True)
class CollectionOptions:
    ttl_s: float = 3600.0  # PLAN.md 6.1: one hour per collection
    overview: OverviewOptions = field(default_factory=OverviewOptions)
    knowledge: KnowledgeOptions = field(default_factory=KnowledgeOptions)


@dataclass(frozen=True)
class CollectionTopic:
    """What a collection contributes to topic resolution (PLAN.md 4.2, step 0)."""

    topic: str
    subject: str | None
    context: list[str]


def collection_topic(info: CollectionInfo) -> CollectionTopic:
    return CollectionTopic(
        topic=info.title,
        subject=info.subject_uris[0] if info.subject_uris else None,
        context=list(info.educational_contexts),
    )


def _hydrate[T: (CollectionInfo, MaterialRef, SubCollection)](cls: type[T], data: dict[str, Any]) -> T:
    """Rebuild a frozen record from its cached JSON form (tuples come back as lists)."""
    kwargs: dict[str, Any] = {}
    for spec in dataclasses.fields(cls):
        value = data.get(spec.name)
        if isinstance(value, list) and "tuple" in str(spec.type):
            value = tuple(value)
        kwargs[spec.name] = value
    return cls(**kwargs)


@dataclass(frozen=True)
class CollectionBuilder:
    client: EduSharingClient
    cache: TtlCache | None
    options: CollectionOptions = field(default_factory=CollectionOptions)

    def info(self, collection_id: str) -> CollectionInfo:
        key = f"collection:{collection_id}"
        cached = self.cache.get(key) if self.cache is not None else None
        if isinstance(cached, dict):
            return _hydrate(CollectionInfo, cached)
        info = self.client.collection(collection_id)
        self._remember(key, dataclasses.asdict(info))
        return info

    def references(self, collection_id: str) -> list[MaterialRef]:
        key = f"references:{collection_id}"
        cached = self.cache.get(key) if self.cache is not None else None
        if isinstance(cached, list):
            return [_hydrate(MaterialRef, item) for item in cached]
        refs = self.client.references(collection_id)
        self._remember(key, [dataclasses.asdict(ref) for ref in refs])
        return refs

    def subcollections(self, collection_id: str) -> list[SubCollection]:
        key = f"subcollections:{collection_id}"
        cached = self.cache.get(key) if self.cache is not None else None
        if isinstance(cached, list):
            return [_hydrate(SubCollection, item) for item in cached]
        subs = self.client.subcollections(collection_id)
        self._remember(key, [dataclasses.asdict(sub) for sub in subs])
        return subs

    def overview(self, collection_id: str) -> CollectionPart:
        """Part 3 for the collection; ``CollectionNotFoundError`` propagates, other failures become a hint."""
        info = self.info(collection_id)
        try:
            refs = self.references(collection_id)
            subs = self.subcollections(collection_id)
        except EduSharingError as exc:
            log.warning("collection %s could not be listed: %s", collection_id, exc)
            markdown = f"{PART_HEADING}\n\n{UNAVAILABLE_TEXT.format(error=exc)}\n"
            return CollectionPart(
                available=False, collection_id=collection_id, title=info.title, markdown=markdown, error=str(exc)
            )
        contents: list[SubCollectionContents] = []
        for sub in subs:
            try:
                contents.append(SubCollectionContents(info=sub, refs=tuple(self.references(sub.id))))
            except EduSharingError as exc:  # one broken sub-collection must not hide the others
                log.warning("sub-collection %s could not be listed: %s", sub.id, exc)
                contents.append(SubCollectionContents(info=sub))
        markdown, summary = render_collection_overview(
            info, refs, contents, render_url=self.client.render_url, options=self.options.overview
        )
        return CollectionPart(
            available=True, collection_id=collection_id, title=info.title, summary=summary, markdown=markdown
        )

    def knowledge_sources(self, collection_id: str) -> KnowledgeResult:
        """Sources for part 1 from the reusable materials of a collection (PLAN.md 6.3)."""
        refs = self.references(collection_id)
        return material_sources(self.client, self.cache, refs, options=self.options.knowledge)

    def _remember(self, key: str, value: Any) -> None:
        if self.cache is not None:
            self.cache.set(key, value, ttl_s=self.options.ttl_s)
