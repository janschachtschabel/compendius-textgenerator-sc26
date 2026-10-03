"""Reading the edu-sharing repositories: the collection behind a request, a node from the configured repository or
another allowed one (D45), the knowledge collection of part 1 and the overview of part 3.

A mixin of CompendiumService (app/service.py): it reads the service's ``collections`` and ``settings`` and keeps the
readers of other repositories, which ``close`` closes.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.compendium.errors import NO_REPOSITORY, RepositoryUnavailableError
from app.domain.models import CollectionPart, NodeInput, Source
from app.domain.requests import GenerateRequest
from app.llm.deadline import Deadline
from app.settings import Settings
from app.sources.wlo.client import CollectionNotFoundError, EduSharingClient, EduSharingError, Remaining
from app.sources.wlo.models import CollectionInfo, NodeInfo
from app.sources.wlo.overview import PART_HEADING as COLLECTION_HEADING
from app.sources.wlo.part import CollectionBuilder, CollectionOptions, node_input
from app.sources.wlo.repository import repository_root

log = logging.getLogger(__name__)


class RepositoryReading:
    settings: Settings
    collections: CollectionBuilder | None
    repository_transport: httpx.BaseTransport | None
    _foreign: dict[str, CollectionBuilder]
    _foreign_lock: threading.Lock

    def _collection_info(self, request: GenerateRequest, remaining: Remaining | None = None) -> CollectionInfo | None:
        """The collection behind the request; unreachable repositories only matter when the topic depends on it.
        ``remaining`` bounds the read as every read of the request (audit 2026-10-02, A08)."""
        if not request.collection_id:
            return None
        if self.collections is None:
            if request.topic or request.node_id:  # part 3 says it is unavailable; the topic comes from elsewhere
                return None
            raise RepositoryUnavailableError(NO_REPOSITORY)
        try:
            return self.collections.info(request.collection_id, remaining=remaining)
        except CollectionNotFoundError:
            raise
        except EduSharingError as exc:
            if request.topic or request.node_id:  # the topic comes from the request or from the node
                log.warning("collection %s not readable, continuing without it: %s", request.collection_id, exc)
                return None
            raise

    def read_node(
        self, node_id: str, repository: str | None = None, *, remaining: Remaining | None = None
    ) -> tuple[NodeInfo, NodeInput]:
        """The metadata of a material or a collection (D45), from the configured repository or another allowed one,
        within ``remaining`` where a request's time budget bounds it.

        Raises ``RepositoryNotAllowedError`` for an address outside the allowlist, ``NodeNotFoundError`` for an
        unknown node, ``EduSharingError`` when the repository fails, ``RepositoryUnavailableError`` without one.
        """
        root, builder = self._node_repository(repository)
        info = builder.node(node_id, remaining=remaining)
        return info, node_input(info, root)

    def collection_from_node(self, request: GenerateRequest, remaining: Remaining | None = None) -> GenerateRequest:
        """The request with a collection named as node_id standing for collection_id as well, so it gets part 3 (D77;
        Jan, 2026-10-02: one id for a collection, whichever field carries it). Only where part 3 is asked for and
        collection_id is empty, and only for a node of the configured repository, the one part 3 reads: a material,
        or a node of another repository, stays a node. The node is read once; ``read_node`` finds it cached."""
        node_id = request.node_id
        if not node_id or request.collection_id or "collection" not in request.parts or self.collections is None:
            return request
        _, builder = self._node_repository(request.repository)
        if builder is not self.collections or builder.node(node_id, remaining=remaining).kind != "collection":
            return request
        return request.model_copy(update={"collection_id": node_id})

    def _node_repository(self, repository: str | None) -> tuple[str, CollectionBuilder]:
        """The REST root and the reader of a repository: the configured one, or one without credentials for any other.

        Nodes are read without credentials from either (``EduSharingClient.node``); an empty address names none.
        """
        base = self.settings.edu_sharing_base_url.rstrip("/")
        if not repository:
            if self.collections is None or not base:
                raise RepositoryUnavailableError(f"{NO_REPOSITORY}; repository angeben")
            return base, self.collections
        root = repository_root(repository, self.settings.edu_sharing_allowed_hosts)
        if self.collections is not None and base and urlsplit(root).hostname == urlsplit(base).hostname:
            return root, self.collections
        with self._foreign_lock:
            builder = self._foreign.get(root)
            if builder is None:
                # No credentials: those of the configured repository must never travel to another one
                client = EduSharingClient(
                    root, timeout_s=self.settings.edu_sharing_timeout_s, transport=self.repository_transport
                )
                shared = self.collections  # the same cache and cache time as the configured repository
                options = shared.options if shared is not None else CollectionOptions()
                builder = CollectionBuilder(client=client, cache=shared.cache if shared else None, options=options)
                self._foreign[root] = builder
        return root, builder

    def close(self) -> None:
        """Close the clients of other repositories; the configured one belongs to the app (``close_clients``)."""
        with self._foreign_lock:
            for builder in self._foreign.values():
                builder.client.close()
            self._foreign.clear()

    def _collections_or_fail(self) -> CollectionBuilder:
        if self.collections is None:
            raise RuntimeError("collections are not configured (EDU_SHARING_BASE_URL)")
        return self.collections

    def _probe_knowledge(self, collection_id: str | None, remaining: Remaining | None = None) -> dict[str, Any] | None:
        """Refuse an unknown knowledge collection before the article choice and the corpus spend LLM calls.

        Reads the collection's metadata only (cached); an unknown one is a 404 as for ``collection_id``. A repository
        that fails gives the audit entry right away, so the materials are not asked for as well.
        """
        if not collection_id or self.collections is None:
            return None
        try:
            self.collections.info(collection_id, remaining=remaining)
        except CollectionNotFoundError:
            raise
        except EduSharingError as exc:
            log.warning("knowledge collection %s not readable: %s", collection_id, exc)
            return {"collection_id": collection_id, "error": str(exc), "sources": 0}
        return None

    def _knowledge(
        self,
        collection_id: str,
        sources: list[Source],
        deadline: Deadline | None,
        *,
        depth: int = 0,
        fulltext: bool = False,
    ) -> dict[str, Any]:
        """Add the materials of the knowledge collection to the corpus, with ``depth`` those of its sub-collections,
        with ``fulltext`` their texts (D70).

        An unknown collection is refused as an unknown ``collection_id`` is (404); a repository that fails only goes
        to the audit, since the compendium stands without the materials.
        """
        try:
            remaining = deadline.remaining if deadline is not None else None
            result = self._collections_or_fail().knowledge_sources(
                collection_id, remaining=remaining, depth=depth, fulltext=fulltext
            )
        except CollectionNotFoundError:
            raise
        except EduSharingError as exc:
            log.warning("knowledge collection %s not readable: %s", collection_id, exc)
            return {"collection_id": collection_id, "error": str(exc), "sources": 0}
        sources.extend(result.sources)
        return {
            "collection_id": collection_id,
            "considered": result.considered,
            "sources": len(result.sources),
            "empty": result.empty,
            "failed": result.failed,
            "timed_out": result.timed_out,
            "depth": depth,
            "fulltext": fulltext,
            "collections": result.collections,
        }

    def _collection_part(self, collection_id: str, deadline: Deadline) -> CollectionPart:
        try:
            return self._collections_or_fail().overview(collection_id, remaining=deadline.remaining)
        except CollectionNotFoundError:
            raise
        except EduSharingError as exc:
            log.warning("collection %s overview failed: %s", collection_id, exc)
            markdown = f"{COLLECTION_HEADING}\n\n*Der Sammlungsüberblick ist nicht verfügbar: {exc}*\n"
            return CollectionPart(available=False, collection_id=collection_id, markdown=markdown, error=str(exc))
