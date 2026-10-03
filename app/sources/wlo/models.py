"""Records read from edu-sharing collections (PLAN.md 6.1) and the display names of their licences. A licence only
labels a material: every material counts, whatever its licence (D70).

Field names follow what the WLO repository returned on 2026-09-17 (``tests/fixtures/wlo``): vocabulary
values come as URIs with a ``*_DISPLAYNAME`` twin, the material link sits in ``ccm:wwwurl`` or, for
uploaded files, in the render URL, and a collection member is a reference node with ``originalId``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.spelling import readable
from app.sources.wlo.errors import MalformedAnswerError
from app.synthesis.safe_markdown import one_line

# The id of a node as edu-sharing gives it; only such an id goes into a URL of the repository
NODE_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

LICENSE_LABELS = {
    "CC_0": "CC0 1.0",
    "PDM": "Public Domain Mark",
    "CC_BY": "CC BY",
    "CC_BY_SA": "CC BY-SA",
    "CC_BY_ND": "CC BY-ND",
    "CC_BY_NC": "CC BY-NC",
    "CC_BY_NC_SA": "CC BY-NC-SA",
    "CC_BY_NC_ND": "CC BY-NC-ND",
    "COPYRIGHT_FREE": "frei zugänglich (keine OER-Lizenz)",
    "COPYRIGHT_LICENSE": "urheberrechtlich geschützt",
    "CUSTOM": "eigene Lizenzbedingungen",
    "SCHULFUNK": "Schulfunk (§ 47 UrhG)",
    "UNTERRICHTS_UND_LEHRMEDIEN": "Unterrichts- und Lehrmedien (§ 60b UrhG)",
    "": "ohne Lizenzangabe",
}


def license_label(license_key: str, version: str = "") -> str:
    """Display name of a licence. The CC BY family exists in several versions (the WLO repository holds 3.0 and
    4.0); the version comes from ``ccm:commonlicense_cc_version`` and is never guessed, because a wrong version is
    a wrong attribution."""
    label = LICENSE_LABELS.get(license_key, license_key)
    if version and license_key.startswith("CC_BY"):
        return f"{label} {version}"
    return label


@dataclass(frozen=True)
class SubCollection:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class MaterialRef:
    """One member of a collection: the reference node with the metadata it inherits from the original."""

    id: str
    title: str
    description: str
    url: str
    original_id: str | None
    license_key: str
    mimetype: str | None
    keywords: tuple[str, ...]
    resource_types: tuple[str, ...]
    educational_contexts: tuple[str, ...]
    subjects: tuple[str, ...]
    subject_uris: tuple[str, ...]
    license_version: str = ""
    authors: tuple[str, ...] = ()  # formatted names plus the free-text field, as the contributor entered them

    @property
    def license(self) -> str:
        return license_label(self.license_key, self.license_version)

    @property
    def node_id(self) -> str:
        """The material's own node: ``originalId`` where the repository gave one, else the reference itself.

        The original is what the repository resolves to the real material - its preview knows the material's
        type, the reference node's does not - and it is the id another system can look the material up by.
        """
        return self.original_id or self.id


@dataclass(frozen=True)
class CollectionInfo:
    id: str
    title: str
    description: str
    keywords: tuple[str, ...]
    subject_uris: tuple[str, ...]
    subject_labels: tuple[str, ...]
    educational_contexts: tuple[str, ...]
    collection_type: str
    modified_at: str
    is_topic_page: bool


@dataclass(frozen=True)
class NodeInfo:
    """A material or a collection as the input of a request (D45): what its metadata says about the topic."""

    node_id: str
    kind: str  # "collection" or "material"
    title: str
    description: str
    keywords: tuple[str, ...]
    subject_uris: tuple[str, ...]
    subject_labels: tuple[str, ...]
    educational_contexts: tuple[str, ...]
    url: str  # the material's own address (ccm:wwwurl); empty for a collection


def json_object(value: Any, field: str, *, required: bool = False) -> Mapping[str, Any]:
    """An object of an answer; ``null`` reads as empty unless ``required``, anything else is another shape (A09)."""
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise MalformedAnswerError(field)
    return value


def json_list(value: Any, field: str) -> list[Any]:
    """A list of an answer; ``null`` reads as empty, anything else is another shape (A09)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise MalformedAnswerError(field)
    return value


def _node_id(value: Any, field: str) -> str:
    """A node id of an answer, a text; ``null`` reads as none. Where it becomes part of a URL, it is checked there."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MalformedAnswerError(field)
    return value


def _ref_id(node: Mapping[str, Any]) -> str:
    return _node_id(json_object(node.get("ref"), "ref").get("id"), "ref.id")


def _values(props: Mapping[str, Any], key: str, *, verbatim: bool = False) -> list[str]:
    """The values of a property as a reader sees them, in one spelling (app/domain/spelling.py); ``verbatim`` keeps
    an address as the repository holds it, since composing it could change where it leads."""
    value = props.get(key)
    if isinstance(value, list):
        values = [str(item) for item in value if item not in (None, "")]
    elif value in (None, ""):
        values = []
    else:
        values = [str(value)]
    return values if verbatim else [text for text in map(readable, values) if text]


def _first(props: Mapping[str, Any], *keys: str, verbatim: bool = False) -> str:
    for key in keys:
        values = _values(props, key, verbatim=verbatim)
        if values:
            return values[0].strip()
    return ""


# ccm:taxonid holds school and university subjects alike, ccm:oeh_taxonid_university university ones only (Jan,
# 2026-09-25); in 13 records it only repeated ccm:taxonid. It is read anyway for a subject ccm:taxonid lacks, which
# then has no display name.
SUBJECT_FIELDS = ("ccm:taxonid", "ccm:oeh_taxonid_university")


def _subject_uris(props: Mapping[str, Any]) -> tuple[str, ...]:
    """Every subject of the record, each once: those of ccm:taxonid first."""
    return tuple(dict.fromkeys(uri for key in SUBJECT_FIELDS for uri in _values(props, key)))


def _labels(props: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Display names where the repository resolves them, else the last URI segment."""
    display = _values(props, f"{key}_DISPLAYNAME")
    if display:
        return tuple(display)
    return tuple(uri.rstrip("/").rsplit("/", 1)[-1] for uri in _values(props, key))


def _title(node: Mapping[str, Any], props: Mapping[str, Any]) -> str:
    title = readable(str(node.get("title") or "")).strip()
    return one_line(title or _first(props, "cclom:title", "cm:title") or readable(str(node.get("name") or "")))


def parse_collection(payload: Mapping[str, Any]) -> CollectionInfo:
    node = json_object(payload.get("collection", payload), "collection", required=True)
    props = json_object(node.get("properties"), "properties")
    return CollectionInfo(
        id=_ref_id(node),
        title=_title(node, props),
        description=_first(props, "cm:description", "cclom:general_description"),
        keywords=tuple(_values(props, "cclom:general_keyword")),
        subject_uris=_subject_uris(props),
        subject_labels=_labels(props, "ccm:taxonid"),
        educational_contexts=_labels(props, "ccm:educationalcontext"),
        collection_type=_first(props, "ccm:collectiontype"),
        modified_at=str(node.get("modifiedAt") or ""),
        is_topic_page=bool(_values(props, "ccm:page_config_ref")),
    )


def parse_node(payload: Mapping[str, Any]) -> NodeInfo:
    """The answer of ``/node/v1/nodes/-home-/{id}/metadata``; materials and collections share the shape."""
    node = json_object(payload.get("node", payload), "node", required=True)
    props = json_object(node.get("properties"), "properties")
    return NodeInfo(
        node_id=_ref_id(node),
        kind="collection" if "ccm:collection" in json_list(node.get("aspects"), "aspects") else "material",
        title=_title(node, props),
        description=_first(props, "cclom:general_description", "cm:description"),
        keywords=_keywords(props),
        subject_uris=_subject_uris(props),
        subject_labels=_labels(props, "ccm:taxonid"),
        educational_contexts=_labels(props, "ccm:educationalcontext"),
        url=_first(props, "ccm:wwwurl", verbatim=True),
    )


def _keywords(props: Mapping[str, Any]) -> tuple[str, ...]:
    """The keywords of a node, each on one line and once: they become context words and part of a text."""
    return tuple(dict.fromkeys(one_line(word) for word in _values(props, "cclom:general_keyword") if word.strip()))


def _authors(props: Mapping[str, Any]) -> tuple[str, ...]:
    """Names for the attribution: the structured authors (vCard ``FN``); the free-text field only stands in when
    there are none, because it often repeats the same person with extras ("Dieter Welz, Ulm")."""
    names = [one_line(name) for name in _values(props, "ccm:lifecyclecontributer_authorFN") if name.strip()]
    if not names:
        names = [one_line(name) for name in _values(props, "ccm:author_freetext") if name.strip()]
    return tuple(dict.fromkeys(names))


def parse_reference(node: Mapping[str, Any]) -> MaterialRef:
    node = json_object(node, "references", required=True)
    props = json_object(node.get("properties"), "properties")
    content = json_object(node.get("content"), "content")
    url = _first(props, "ccm:wwwurl", verbatim=True) or str(content.get("url") or "")
    return MaterialRef(
        id=_ref_id(node),
        title=_title(node, props),
        description=_first(props, "cclom:general_description", "cm:description"),
        url=url,
        # an originalId that is no node id cannot name the material; the reference's own id does (A09)
        original_id=original if NODE_ID.match(original := _node_id(node.get("originalId"), "originalId")) else None,
        license_key=_first(props, "ccm:commonlicense_key"),
        mimetype=node.get("mimetype") or None,
        keywords=tuple(_values(props, "cclom:general_keyword")),
        resource_types=_labels(props, "ccm:oeh_lrt"),
        educational_contexts=_labels(props, "ccm:educationalcontext"),
        subjects=_labels(props, "ccm:taxonid"),
        subject_uris=_subject_uris(props),
        license_version=_first(props, "ccm:commonlicense_cc_version"),
        authors=_authors(props),
    )


def parse_subcollection(node: Mapping[str, Any]) -> SubCollection:
    node = json_object(node, "collections", required=True)
    props = json_object(node.get("properties"), "properties")
    return SubCollection(
        id=_ref_id(node),
        title=_title(node, props),
        description=_first(props, "cm:description", "cclom:general_description"),
    )
