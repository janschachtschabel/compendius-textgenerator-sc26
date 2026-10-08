"""edu-sharing REST client for collections (PLAN.md 6.1): anonymous or Basic, paginated, errors mapped.

Only public read endpoints are used; credentials from the environment are optional. Node ids are the
trust boundary: a request's ``collection_id`` is validated as a UUID before it becomes part of a URL.
Measured on 2026-09-17 against the WLO repository: collection 0.2 s, one page of references 0.4 s,
sub-collections 0.2 s, text content 0.1-2.3 s per node.
"""

from __future__ import annotations

import dataclasses
import hashlib
import http.cookiejar
import json
import logging
from collections.abc import Callable, Collection
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.http_body import ACCEPT_ENCODING, UnreadableAnswerError, read_bounded

# The errors live apart so that the parsers raise them too; the service imports them from here
from app.sources.wlo.errors import CollectionNotFoundError as CollectionNotFoundError
from app.sources.wlo.errors import EduSharingError as EduSharingError
from app.sources.wlo.errors import MalformedAnswerError, TimeUpError
from app.sources.wlo.errors import NodeNotFoundError as NodeNotFoundError
from app.sources.wlo.models import (
    NODE_ID,
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
# Why a listing ended before the repository's last page, as part 3 says it (audit 2026-10-03, F07)
CUT_TIME = "das Zeitbudget der Anfrage war erschöpft"
CUT_PAGES = "eine Liste endet nach {count} Materialien, der Obergrenze des Dienstes"
CUT_REPEATED = "das Repository lieferte eine Seite einer Liste ein zweites Mal"
ATTEMPTS = 2  # the repository occasionally drops a connection; the same request a moment later works
# An answer is read up to this many bytes (audit 2026-10-03, F12). Measured on the staging repository on 2026-10-08:
# a page of 100 references of the Optik collection with all their properties is 895 KB unpacked (148 KB in gzip),
# the texts of its materials stay below 32 KB. Parsed, JSON of many small objects takes 19 times its size, so at
# this bound a faulty repository could still cost a worker some 600 MB per answer; one collection is too few to
# lower it on (review of 2026-10-08)
MAX_ANSWER_BYTES = 32 * 1024 * 1024
_BODY_EXCERPT = 200
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclasses.dataclass(frozen=True)
class ReferenceListing:
    """The materials of a collection as listed, and why the listing ended before the repository's last page."""

    refs: list[MaterialRef]
    cut: str | None = None  # CUT_TIME, CUT_PAGES or CUT_REPEATED; None when the listing is whole


# The seconds the caller's time budget has left (``Deadline.remaining``); spent at zero
Remaining = Callable[[], float]


def spent(remaining: Remaining | None) -> bool:
    """Whether the caller's time budget is spent; without one it never is."""
    return remaining is not None and remaining() <= 0


def validate_node_id(value: str) -> str:
    """Return ``value`` when it is an edu-sharing node id (UUID); raise ``ValueError`` otherwise."""
    if not NODE_ID.match(value or ""):
        raise ValueError(f"keine gültige Knoten-ID: {value!r}")
    return value


def render_url_for(rest_root: str, node_id: str) -> str:
    """Public page of a node (``…/edu-sharing/components/render/{id}``) in the repository of ``rest_root``.

    Only the path is cut at ``/edu-sharing``; a host whose name starts with it stays whole.
    """
    parts = urlsplit(rest_root)
    prefix = parts.path.split("/edu-sharing", 1)[0]
    return f"{parts.scheme}://{parts.netloc}{prefix}/edu-sharing/components/render/{validate_node_id(node_id)}"


def _scope(base_url: str, user: str) -> str:
    """Whose answers a cache entry holds: the repository by its REST root however it is written - scheme and host in
    lower case, the port spelled out, no slash at the end - and the account, by a hash of its name; never the name, a
    password or a token. Staging and production share node ids where one holds a copy of the other, and two
    accounts may see different things (audit 2026-09-29, A03). The address is read as the client reads it: a port
    ``urlsplit`` refuses but httpx takes would otherwise stop the start instead of failing part 3.
    """
    url = httpx.URL(base_url)  # scheme and host in lower case, a default port as None
    port = url.port or _DEFAULT_PORTS.get(url.scheme)
    account = "user-" + hashlib.sha256(user.encode()).hexdigest()[:16] if user else "anonymous"
    return f"{url.scheme}://{url.host}:{port}{url.path.rstrip('/')}|{account}"


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
        self._timeout_s = timeout_s

        def connection(auth: httpx.Auth | None) -> httpx.Client:
            return httpx.Client(
                base_url=self.base_url,
                transport=transport,
                timeout=timeout_s,
                auth=auth,
                cookies=_no_cookies(),
                headers={"Accept": "application/json", "Accept-Encoding": ACCEPT_ENCODING, "User-Agent": USER_AGENT},
            )

        self._client = connection(httpx.BasicAuth(user, password) if user else None)
        # Nodes are read as the public sees them (D45): by a client that never held the credentials, since leaving
        # them out of one request of a shared client still sent whatever state that client kept
        self._public = connection(None)
        # What the cache keys name: the reads with the client's account, and those of node(), which go without one
        self.scope = _scope(self.base_url, user)
        self.public_scope = _scope(self.base_url, "")

    def close(self) -> None:
        self._client.close()
        self._public.close()

    def render_url(self, node_id: str) -> str:
        """Public page of a node in the same repository (``…/edu-sharing/components/render/{id}``)."""
        return render_url_for(self.base_url, node_id)

    def collection(self, collection_id: str, *, remaining: Remaining | None = None) -> CollectionInfo:
        path = f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}"
        payload = self._get(path, remaining=remaining)
        if payload is None:
            raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
        # the checked id, not the answer's, as for a node: part 3 links the collection by it
        return dataclasses.replace(parse_collection(payload), id=collection_id)

    def subcollections(self, collection_id: str, *, remaining: Remaining | None = None) -> list[SubCollection]:
        path = f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}/children/collections"
        payload = self._get(path, remaining=remaining)
        if payload is None:
            raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
        subs = [parse_subcollection(node) for node in json_list(payload.get("collections"), "collections")]
        # its materials are read by its id, which an empty one - or one that is no node id - failed with a
        # ValueError and a 500; a reference without one is left out of a listing too (audit 2026-09-29, A09)
        return [sub for sub in subs if NODE_ID.match(sub.id)]

    def references(self, collection_id: str, *, remaining: Remaining | None = None) -> list[MaterialRef]:
        """All materials referenced by the collection; see ``listing``."""
        return self.listing(collection_id, remaining=remaining).refs

    def listing(
        self, collection_id: str, *, remaining: Remaining | None = None, limit: int | None = None
    ) -> ReferenceListing:
        """The materials referenced by the collection, page by page until the reported total is reached, and why the
        listing ended before it if it did (``ReferenceListing.cut``).

        ``remaining`` gives the seconds left of the caller's time budget: once it is spent, the listing ends after the
        last page that came in time. When not one page came, ``TimeUpError``: an empty list would read as an empty
        collection. With ``limit``, the materials of one page of that size, at most ``limit``: the first titles of a
        collection for its place in the topic tree are one short read (M71, review of 2026-10-08).
        """
        path = f"/collection/v1/collections/-home-/{validate_node_id(collection_id)}/children/references"
        refs: list[MaterialRef] = []
        seen: set[str] = set()
        skip = 0
        size = min(self._page_size, limit) if limit else self._page_size
        for _page in range(MAX_PAGES):
            params = {"maxItems": size, "skipCount": skip, "propertyFilter": "-all-"}
            try:
                payload = self._get(path, params, remaining=remaining)
            except TimeUpError:
                if not refs:
                    raise
                log.warning(
                    "collection %s: listing cut after %d references, the time budget is spent", collection_id, len(refs)
                )
                return ReferenceListing(refs, CUT_TIME)
            if payload is None:
                raise CollectionNotFoundError(f"Sammlung {collection_id} nicht gefunden")
            items = json_list(payload.get("references", payload.get("nodes")), "references")
            known = len(refs)
            for node in items:
                ref = parse_reference(node)
                # the text of a material is read by its id: one that is no node id raised a ValueError (A09)
                if NODE_ID.match(ref.id) and ref.id not in seen:
                    seen.add(ref.id)
                    refs.append(ref)
            total = json_object(payload.get("pagination"), "pagination").get("total")
            if total is not None and not isinstance(total, int):
                raise MalformedAnswerError("pagination.total")
            skip += len(items)
            if limit:
                return ReferenceListing(refs[:limit])
            if not items or len(items) < size or (total is not None and skip >= total):
                return ReferenceListing(refs)
            if len(refs) == known:  # a full page without a new id: the repository ignores skipCount
                log.warning(
                    "collection %s: the page at offset %d repeats earlier references", collection_id, skip - len(items)
                )
                return ReferenceListing(refs, CUT_REPEATED)
        log.warning("collection %s: listing cut after %d pages", collection_id, MAX_PAGES)
        cap = f"{MAX_PAGES * self._page_size:,}".replace(",", ".")  # the service's cap, as the hint reads it
        return ReferenceListing(refs, CUT_PAGES.format(count=cap))

    def node(self, node_id: str, *, remaining: Remaining | None = None) -> NodeInfo:
        """Title, description, keywords, subject and level of a material or a collection (D45).

        Read without credentials, whatever the client carries: the endpoints that take a node have no login, so they
        pass on only what the repository shows the public. A node the public may not see counts as not found.
        ``remaining`` bounds the read as in ``_get``.
        """
        path = f"/node/v1/nodes/-home-/{validate_node_id(node_id)}/metadata"
        payload = self._get(path, {"propertyFilter": "-all-"}, anonymous=True, missing=(403, 404), remaining=remaining)
        if payload is None:
            raise NodeNotFoundError(f"Knoten {node_id} nicht gefunden oder nicht öffentlich in {self.base_url}")
        if not isinstance(payload.get("node"), dict):
            raise EduSharingError("edu-sharing antwortete ohne Knoten")
        return dataclasses.replace(parse_node(payload), node_id=node_id)  # the checked id, not the answer's

    def text_content(self, node_id: str, *, remaining: Remaining | None = None) -> str:
        """Extracted plain text of a material, or an empty string when the node has none (404)."""
        # quiet: the texts of a request are counted in one line (app/sources/wlo/knowledge.py, logging review)
        path = f"/node/v1/nodes/-home-/{validate_node_id(node_id)}/textContent"
        payload = self._get(path, remaining=remaining, quiet=True)
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
        remaining: Remaining | None = None,
        quiet: bool = False,
    ) -> dict[str, Any] | None:
        """The JSON object of the answer, ``None`` for a status in ``missing``; transport failures are retried once,
        other errors raised, among them an answer that is JSON but no object (``null``, a list, a value). ``quiet``
        logs a refused status at DEBUG, for reads whose caller counts the failures in one line.

        ``anonymous`` reads without the client's credentials, over the connection that never had them. ``remaining``
        bounds every attempt, a retry included: none starts once the caller's budget is spent (``TimeUpError``), and
        none waits longer than it. Before, each waited up to the full client timeout (30 s by default), also after the
        budget was gone (audit 2026-09-29, A06).
        """
        client = self._public if anonymous else self._client
        last_error: Exception | None = None
        for _attempt in range(ATTEMPTS):
            timeout = self._timeout_s
            if remaining is not None:
                left = remaining()
                if left <= 0:
                    if last_error is not None:
                        # The caller blames the time budget; the repository had not answered (logging review of
                        # 2026-10-08)
                        log.warning(
                            "%s%s: no answer before the request's time ran out (%s)",
                            self.base_url,
                            path,
                            f"{type(last_error).__name__}: {last_error}",
                        )
                        raise TimeUpError() from last_error
                    raise TimeUpError()
                timeout = min(timeout, left)
            try:
                with client.stream("GET", path, params=params, timeout=timeout) as response:
                    status = response.status_code
                    if status in missing:
                        return None
                    body = read_bounded(response, MAX_ANSWER_BYTES)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            except UnreadableAnswerError as exc:
                log.warning("answer of %s%s: %s", self.base_url, path, exc)
                raise EduSharingError(f"edu-sharing antwortete mit {exc}") from exc
            if status >= 400:
                # on one line: the CR and LF of an error page split a record of the plain format (logging review)
                excerpt = " ".join(body[:_BODY_EXCERPT].decode("utf-8", "replace").split())
                log.log(
                    logging.DEBUG if quiet else logging.WARNING,
                    "HTTP %s from %s%s: %s",
                    status,
                    self.base_url,
                    path,
                    excerpt,
                )
                raise EduSharingError(f"edu-sharing antwortete mit HTTP {status}")
            try:
                data = json.loads(body)
            except (ValueError, RecursionError) as exc:  # also a nesting too deep to read, as the b-api client has it
                log.warning("answer of %s%s is not JSON", self.base_url, path)
                raise EduSharingError("edu-sharing antwortete nicht mit JSON") from exc
            # ``null`` was taken for a missing node and a list failed at ``.get`` (audit 2026-09-29, A09)
            if not isinstance(data, dict):
                log.warning("answer of %s%s is JSON but no object: %s", self.base_url, path, type(data).__name__)
                raise EduSharingError("edu-sharing antwortete nicht mit einem JSON-Objekt")
            return data
        log.warning("%s%s not reachable: %s", self.base_url, path, last_error)
        raise EduSharingError(f"edu-sharing nicht erreichbar ({type(last_error).__name__})") from last_error
