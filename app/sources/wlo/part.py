"""Part 3 for one compendium and the knowledge collection (PLAN.md 6): cached reads, overview, sources, topic.

The builder is the one place the service and the API talk to for collections. Repository answers are
cached for ``ttl_s`` (metadata, listings) so a compendium and its overview endpoint do not read the
same collection twice; a repository failure yields an honest hint in part 3 instead of failing part 1.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.domain.models import CollectionPart, NodeInput
from app.knowledge.topic import NormalizedTopic, normalize_topic
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient, EduSharingError, render_url_for
from app.sources.wlo.knowledge import KnowledgeOptions, KnowledgeResult, material_sources
from app.sources.wlo.models import CollectionInfo, MaterialRef, NodeInfo, SubCollection
from app.sources.wlo.overview import (
    PART_HEADING,
    OverviewOptions,
    SubCollectionContents,
    render_collection_overview,
)

log = logging.getLogger(__name__)

# Part of the cache keys of records: bump it when a cached record gains or changes a field, so entries written
# by an earlier version are not read (they expire by their TTL). 2: MaterialRef with licence version and authors.
CACHE_FORMAT = 2
UNAVAILABLE_TEXT = "*Der Sammlungsüberblick konnte nicht erstellt werden: {error}*"


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


def node_topic(info: NodeInfo) -> CollectionTopic:
    """What a node contributes to topic resolution (D45): its title, its first subject, levels and keywords.

    Levels and keywords go in as context words. The rules weigh context words at a disambiguation page only when the
    subject brings no words of its own, and the LLM choice sees none, so with a known subject they do not steer the
    choice yet. The title of a material often names its format rather than a lexicon topic („Stationsarbeit zur
    Optik“); a caller who knows better sends ``topic`` along, which wins.
    """
    return CollectionTopic(
        topic=info.title,
        subject=info.subject_uris[0] if info.subject_uris else None,
        context=[*info.educational_contexts, *info.keywords],
    )


@dataclass(frozen=True)
class DerivedTopic:
    """The topic a request resolves, with the subject and the context words that go into the resolution."""

    normalized: NormalizedTopic
    subject: str | None
    context: list[str]


def derive_topic(topic: str | None, derived: Sequence[CollectionTopic], subject: str | None = None) -> DerivedTopic:
    """One derivation for compendium, knowledge and the node preview (D12, D45).

    The topic: the one sent along, else the first title of ``derived`` (a node before a collection), normalised. The
    subject: the one sent along, then a subject the topic names („Physik: Optik“), then the first of ``derived``. The
    context words: the topic's qualifiers, then those of every entry of ``derived``.
    """
    normalized = normalize_topic(topic or (derived[0].topic if derived else ""))
    context = [*normalized.context, *(word for found in derived for word in found.context)]
    subject = subject or normalized.subject or next((found.subject for found in derived if found.subject), None)
    return DerivedTopic(normalized=normalized, subject=subject, context=context)


def node_input(info: NodeInfo, root: str) -> NodeInput:
    """The node as the answers show it: what was read, from which repository, and where to see it."""
    return NodeInput(
        node_id=info.node_id,
        repository=root,
        kind=info.kind,
        title=info.title,
        description=info.description,
        keywords=list(info.keywords),
        subjects=list(info.subject_labels),
        educational_contexts=list(info.educational_contexts),
        url=info.url or None,
        render_url=render_url_for(root, info.node_id),
    )


def _hydrate[T: (CollectionInfo, MaterialRef, NodeInfo, SubCollection)](cls: type[T], data: dict[str, Any]) -> T:
    """Rebuild a frozen record from its cached JSON form (tuples come back as lists)."""
    kwargs: dict[str, Any] = {}
    for spec in dataclasses.fields(cls):
        if spec.name not in data and spec.default is not dataclasses.MISSING:
            continue  # written before the field existed; the default applies
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
        key = f"collection:v{CACHE_FORMAT}:{collection_id}"
        cached = self.cache.get(key) if self.cache is not None else None
        if isinstance(cached, dict):
            return _hydrate(CollectionInfo, cached)
        info = self.client.collection(collection_id)
        self._remember(key, dataclasses.asdict(info))
        return info

    def node(self, node_id: str) -> NodeInfo:
        """The metadata of a material or a collection, cached like a collection's; the key names the repository."""
        key = f"node:v{CACHE_FORMAT}:{urlsplit(self.client.base_url).hostname}:{node_id}"
        cached = self.cache.get(key) if self.cache is not None else None
        if isinstance(cached, dict):
            return _hydrate(NodeInfo, cached)
        info = self.client.node(node_id)
        self._remember(key, dataclasses.asdict(info))
        return info

    def references(self, collection_id: str, *, expired: Callable[[], bool] | None = None) -> list[MaterialRef]:
        key = f"references:v{CACHE_FORMAT}:{collection_id}"
        cached = self.cache.get(key) if self.cache is not None else None
        if isinstance(cached, list):
            return [_hydrate(MaterialRef, item) for item in cached]
        refs = self.client.references(collection_id, expired=expired)
        if expired is not None and expired():  # possibly cut short: not kept for the next hour's requests
            return refs
        self._remember(key, [dataclasses.asdict(ref) for ref in refs])
        return refs

    def subcollections(self, collection_id: str) -> list[SubCollection]:
        key = f"subcollections:v{CACHE_FORMAT}:{collection_id}"
        cached = self.cache.get(key) if self.cache is not None else None
        if isinstance(cached, list):
            return [_hydrate(SubCollection, item) for item in cached]
        subs = self.client.subcollections(collection_id)
        self._remember(key, [dataclasses.asdict(sub) for sub in subs])
        return subs

    def overview(self, collection_id: str, *, expired: Callable[[], bool] | None = None) -> CollectionPart:
        """Part 3 for the collection; ``CollectionNotFoundError`` propagates, other failures become a hint.

        ``expired`` tells whether the request's time budget is spent: a listing then ends after its current page,
        further sub-collections are not listed, and the text says that the lists may be incomplete.
        """
        info = self.info(collection_id)
        try:
            refs = self.references(collection_id, expired=expired)
            subs = self.subcollections(collection_id)
        except EduSharingError as exc:
            log.warning("collection %s could not be listed: %s", collection_id, exc)
            markdown = f"{PART_HEADING}\n\n{UNAVAILABLE_TEXT.format(error=exc)}\n"
            return CollectionPart(
                available=False, collection_id=collection_id, title=info.title, markdown=markdown, error=str(exc)
            )
        contents: list[SubCollectionContents] = []
        for sub in subs:
            if expired is not None and expired():
                contents.append(SubCollectionContents(info=sub))  # named, but its materials are not listed
                continue
            try:
                contents.append(SubCollectionContents(info=sub, refs=tuple(self.references(sub.id, expired=expired))))
            except EduSharingError as exc:  # one broken sub-collection must not hide the others
                log.warning("sub-collection %s could not be listed: %s", sub.id, exc)
                contents.append(SubCollectionContents(info=sub))
        markdown, summary = render_collection_overview(
            info,
            refs,
            contents,
            render_url=self.client.render_url,
            options=self.options.overview,
            incomplete=expired is not None and expired(),
        )
        return CollectionPart(
            available=True, collection_id=collection_id, title=info.title, summary=summary, markdown=markdown
        )

    def knowledge_sources(self, collection_id: str, *, expired: Callable[[], bool] | None = None) -> KnowledgeResult:
        """Sources for part 1 from the reusable materials of a collection (PLAN.md 6.3); ``expired`` see
        ``material_sources``."""
        refs = self.references(collection_id, expired=expired)
        return material_sources(self.client, self.cache, refs, options=self.options.knowledge, expired=expired)

    def _remember(self, key: str, value: Any) -> None:
        if self.cache is not None:
            self.cache.set(key, value, ttl_s=self.options.ttl_s)
