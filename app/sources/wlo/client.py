"""edu-sharing REST client for collections (PLAN.md 6.1): anonymous or Basic, paginated, errors mapped.

Only public read endpoints are used; credentials from the environment are optional. Node ids are the
trust boundary: a request's ``collection_id`` is validated as a UUID before it becomes part of a URL.
Measured on 2026-09-17 against the WLO repository: collection 0.2 s, one page of references 0.4 s,
sub-collections 0.2 s, text content 0.1-2.3 s per node.
"""

from __future__ import annotations

import dataclasses
import http.cookiejar
import logging
import re
from collections.abc import Callable, Collection
from typing import Any
from urllib.parse import urlsplit

import httpx

# The errors live apart so that the parsers raise them too; the service imports them from here
from app.sources.wlo.errors import CollectionNotFoundError as CollectionNotFoundError
from app.sources.wlo.errors import EduSharingError as EduSharingError
from app.sources.wlo.errors import MalformedAnswerError
from app.sources.wlo.errors import NodeNotFoundError as NodeNotFoundError
from app.sources.wlo.models import (
    CollectionInfo,
    MaterialRef,
    NodeInfo,
    SubCollection,
    json_list,
    json_object,
    parse_collection,
    parse_node,
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


def validate_node_id(value: str) -> str:
    """Return ``value`` when it is an edu-sharing node id (UUID); raise ``ValueError`` otherwise."""
    if not _NODE_ID.match(value or ""):
        raise ValueError(f"keine gültige Knoten-ID: {value!r}")
    return value


def render_url_for(rest_root: str, node_id: str) -> str:
    """Public page of a node (``…/edu-sharing/components/render/{id}``) in the repository of ``rest_root``.

    Only the path is cut at ``/edu-sharing``; a host whose name starts with it stays whole.
    """
    parts = urlsplit(rest_root)
    prefix = parts.path.split("/edu-sharing", 1)[0]
    return f"{parts.scheme}://{parts.netloc}{prefix}/edu-sharing/components/render/{validate_node_id(node_id)}"


def _no_cookies() -> http.cookiejar.CookieJar:
    """A cookie jar that takes none: every request carries its own credentials, or none at all.

    edu-sharing may answer a login with a session cookie. Kept, it rode along on the node reads that go without
    credentials and showed them what the account may see (audit 2026-09-29, A02).
    """
    return http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))


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

        def connection(auth: httpx.Auth | None) -> httpx.Client:
            return httpx.Client(
                base_url=self.base_url,
                transport=transport,
                timeout=timeout_s,
                auth=auth,
                cookies=_no_cookies(),
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            )

        self._client = connection(httpx.BasicAuth(user, password) if user else None)
        # Nodes are read as the public sees them (D45): by a client that never held the credentials, since leaving
        # them out of one request of a shared client still sent whatever state that client kept
        self._public = connection(None)

    def close(self) -> None:
        self._client.close()
        self._public.close()

    def render_url(self, node_id: str) -> str:
        """Public page of a node in the same repository (``…/edu-sharing/components/render/{id}``)."""
        return render_url_for(self.base_url, node_id)

    def collection(self, collection_id: str) -> CollectionInfo:
        payload = self._get(f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}")
        if payload is None:
            raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
        # the checked id, not the answer's, as for a node: part 3 links the collection by it
        return dataclasses.replace(parse_collection(payload), id=collection_id)

    def subcollections(self, collection_id: str) -> list[SubCollection]:
        path = f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}/children/collections"
        payload = self._get(path)
        if payload is None:
            raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
        subs = [parse_subcollection(node) for node in json_list(payload.get("collections"), "collections")]
        # its materials are read by its id, which an empty one failed with a ValueError; a reference without one is
        # left out of a listing too
        return [sub for sub in subs if sub.id]

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
            items = json_list(payload.get("references", payload.get("nodes")), "references")
            known = len(refs)
            for node in items:
                ref = parse_reference(node)
                if ref.id and ref.id not in seen:
                    seen.add(ref.id)
                    refs.append(ref)
            total = json_object(payload.get("pagination"), "pagination").get("total")
            if total is not None and not isinstance(total, int):
                raise MalformedAnswerError("pagination.total")
            skip += len(items)
            if not items or len(items) < self._page_size or (total is not None and skip >= total):
                return refs
            if len(refs) == known:  # a full page without a new id: the repository ignores skipCount
                log.warning(
                    "collection %s: the page at offset %d repeats earlier references", collection_id, skip - len(items)
                )
                return refs
        log.warning("collection %s: listing cut after %d pages", collection_id, MAX_PAGES)
        return refs

    def node(self, node_id: str) -> NodeInfo:
        """Title, description, keywords, subject and level of a material or a collection (D45).

        Read without credentials, whatever the client carries: the endpoints that take a node have no login, so they
        pass on only what the repository shows the public. A node the public may not see counts as not found.
        """
        path = f"/node/v1/nodes/-home-/{validate_node_id(node_id)}/metadata"
        payload = self._get(path, {"propertyFilter": "-all-"}, anonymous=True, missing=(403, 404))
        if payload is None:
            raise NodeNotFoundError(f"Knoten {node_id} nicht gefunden oder nicht öffentlich in {self.base_url}")
        if not isinstance(payload.get("node"), dict):
            raise EduSharingError("edu-sharing antwortete ohne Knoten")
        return dataclasses.replace(parse_node(payload), node_id=node_id)  # the checked id, not the answer's

    def text_content(self, node_id: str) -> str:
        """Extracted plain text of a material, or an empty string when the node has none (404)."""
        payload = self._get(f"/node/v1/nodes/-home-/{validate_node_id(node_id)}/textContent")
        if not payload:
            return ""
        return str(payload.get("text") or payload.get("raw") or "").strip()

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        anonymous: bool = False,
        missing: Collection[int] = (404,),
    ) -> dict[str, Any] | None:
        """The JSON object of the answer, ``None`` for a status in ``missing``; transport failures are retried once,
        other errors raised, among them an answer that is JSON but no object (``null``, a list, a value).

        ``anonymous`` reads without the client's credentials, over the connection that never had them.
        """
        client = self._public if anonymous else self._client
        last_error: Exception | None = None
        for _attempt in range(ATTEMPTS):
            try:
                response = client.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            if response.status_code in missing:
                return None
            if response.status_code >= 400:
                log.warning(
                    "HTTP %s from %s%s: %s", response.status_code, self.base_url, path, response.text[:_BODY_EXCERPT]
                )
                raise EduSharingError(f"edu-sharing antwortete mit HTTP {response.status_code}")
            try:
                data = response.json()
            except ValueError as exc:
                log.warning("answer of %s%s is not JSON", self.base_url, path)
                raise EduSharingError("edu-sharing antwortete nicht mit JSON") from exc
            # ``null`` was taken for a missing node and a list failed at ``.get`` (audit 2026-09-29, A09)
            if not isinstance(data, dict):
                log.warning("answer of %s%s is JSON but no object: %s", self.base_url, path, type(data).__name__)
                raise EduSharingError("edu-sharing antwortete nicht mit einem JSON-Objekt")
            return data
        log.warning("%s%s not reachable: %s", self.base_url, path, last_error)
        raise EduSharingError(f"edu-sharing nicht erreichbar ({type(last_error).__name__})") from last_error
