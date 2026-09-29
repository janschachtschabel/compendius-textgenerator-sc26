"""Errors of reading the edu-sharing repository, in a module of their own: the client raises them, and so do the
parsers of its answers (``models.py``), which the client imports."""

from __future__ import annotations


class EduSharingError(RuntimeError):
    """The repository could not be reached, refused the request or answered in a shape the service cannot read."""


class CollectionNotFoundError(EduSharingError):
    """No collection with this id (HTTP 404)."""


class NodeNotFoundError(EduSharingError):
    """No node with this id in the repository (HTTP 404), or none the public may read (HTTP 403)."""


class MalformedAnswerError(EduSharingError):
    """An answer of another shape: a list where an object belongs, an object where a list does, a number where a
    text does. The repository's failure - a 502, a hint in part 3 - not the service's: ``.get`` on a list was an
    AttributeError and a 500 (audit 2026-09-29, A09). The message names the field, never the answer."""

    def __init__(self, field: str) -> None:
        super().__init__(f"edu-sharing antwortete mit unerwartetem Aufbau ({field})")


class TimeUpError(EduSharingError):
    """The request's time budget was spent before the repository answered: no request starts after that, and none
    waits longer than the time left (audit 2026-09-29, A06)."""

    def __init__(self) -> None:
        super().__init__("Zeitbudget der Anfrage erschöpft")
