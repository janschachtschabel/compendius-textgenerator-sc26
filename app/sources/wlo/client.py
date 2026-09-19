"""edu-sharing REST client for collections (PLAN.md 6.1): anonymous or Basic, paginated, errors mapped.

Only public read endpoints are used; credentials from the environment are optional. Node ids are the
trust boundary: a request's ``collection_id`` is validated as a UUID before it becomes part of a URL.
Measured on 2026-09-17 against the WLO repository: collection 0.2 s, one page of references 0.4 s,
sub-collections 0.2 s, text content 0.1-2.3 s per node.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import httpx

from app.sources.wlo.models import (
    CollectionInfo,
    MaterialRef,
    SubCollection,
    parse_collection,
    parse_reference,
    parse_subcollection,
)

log = logging.getLogger(__name__)

USER_AGENT = "compendious-text-fastapi/2.0 (+https://wirlernenonline.de; Kompendium-Sammlungsueberblick)"
DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 200  # 20,000 references at the default page size; beyond that the listing is cut
ATTEMPTS = 2  # the repository occasionally drops a connection; the same request a moment later works
_NODE_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_BODY_EXCERPT = 200


class EduSharingError(RuntimeError):
    """The repository could not be reached or refused the request."""


class CollectionNotFoundError(EduSharingError):
    """No collection with this id (HTTP 404)."""


def validate_node_id(value: str) -> str:
    """Return ``value`` when it is an edu-sharing node id (UUID); raise ``ValueError`` otherwise."""
    if not _NODE_ID.match(value or ""):
        raise ValueError(f"keine gültige Knoten-ID: {value!r}")
    return value


class EduSharingClient:
    def __init__(
        self,
        base_url: str,
        *,
        user: str = "",
        password: str = "",
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._page_size = max(1, page_size)
        self._client = httpx.Client(
            base_url=self.base_url,
            transport=transport,
            timeout=timeout_s,
            auth=httpx.BasicAuth(user, password) if user else None,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )

    def close(self) -> None:
        self._client.close()

    def render_url(self, node_id: str) -> str:
        """Public page of a node in the same repository (``…/edu-sharing/components/render/{id}``)."""
        host = self.base_url.split("/edu-sharing", 1)[0]
        return f"{host}/edu-sharing/components/render/{validate_node_id(node_id)}"

    def collection(self, collection_id: str) -> CollectionInfo:
        payload = self._get(f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}")
        if payload is None:
            raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
        return parse_collection(payload)

    def subcollections(self, collection_id: str) -> list[SubCollection]:
        path = f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}/children/collections"
        payload = self._get(path)
        if payload is None:
            raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
        return [parse_subcollection(node) for node in payload.get("collections") or []]

    def references(self, collection_id: str, *, expired: Callable[[], bool] | None = None) -> list[MaterialRef]:
        """All materials referenced by the collection, page by page until the reported total is reached.

        ``expired`` tells whether the caller's time budget is spent; the listing then ends after the current page.
        """
        path = f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}/children/references"
        refs: list[MaterialRef] = []
        seen: set[str] = set()
        skip = 0
        for _page in range(MAX_PAGES):
            if refs and expired is not None and expired():
                log.warning(
                    "collection %s: listing cut after %d references, the time budget is spent", collection_id, len(refs)
                )
                return refs
            params = {"maxItems": self._page_size, "skipCount": skip, "propertyFilter": "-all-"}
            payload = self._get(path, params)
            if payload is None:
                raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
            items = payload.get("references") or payload.get("nodes") or []
            known = len(refs)
            for node in items:
                ref = parse_reference(node)
                if ref.id and ref.id not in seen:
                    seen.add(ref.id)
                    refs.append(ref)
            total = (payload.get("pagination") or {}).get("total")
            skip += len(items)
            if not items or len(items) < self._page_size or (total is not None and skip >= total):
                return refs
            if len(refs) == known:  # a full page without a new id: the repository ignores skipCount
                log.warning("collection %s: the page at offset %d repeats earlier references", collection_id, skip)
                return refs
        log.warning("collection %s: listing cut after %d pages", collection_id, MAX_PAGES)
        return refs

    def text_content(self, node_id: str) -> str:
        """Extracted plain text of a material, or an empty string when the node has none (404)."""
        payload = self._get(f"/node/v1/nodes/-home-/{validate_node_id(node_id)}/textContent")
        if not payload:
            return ""
        return str(payload.get("text") or payload.get("raw") or "").strip()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Parsed JSON, ``None`` for 404; transport failures are retried once, other errors raised."""
        last_error: Exception | None = None
        for _attempt in range(ATTEMPTS):
            try:
                response = self._client.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                log.warning(
                    "HTTP %s from %s%s: %s", response.status_code, self.base_url, path, response.text[:_BODY_EXCERPT]
                )
                raise EduSharingError(f"HTTP {response.status_code} vom Repository")
            try:
                data: dict[str, Any] = response.json()
            except ValueError as exc:
                log.warning("answer of %s%s is not JSON", self.base_url, path)
                raise EduSharingError("Antwort des Repositorys ist kein JSON") from exc
            return data
        log.warning("%s%s not reachable: %s", self.base_url, path, last_error)
        raise EduSharingError(f"edu-sharing nicht erreichbar ({type(last_error).__name__})") from last_error
