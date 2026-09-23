"""WLO subject vocabulary to MEM subject search terms (``config/subjects.yaml``, PLAN.md 4.2, 5.3).

A request names a subject by WLO discipline id, by the full vocabulary URI (``ccm:taxonid`` of a
collection), by label or by an alias ("Mathe"). The catalog turns that into lowercase substrings
of MEM's Schulfach labels; an unknown subject yields no terms, and the search then spans all subjects.
It also names the words by which the topic resolution recognises a meaning of the subject (``kontext``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DISCIPLINE_PREFIX = "http://w3id.org/openeduhub/vocabs/discipline/"


@dataclass(frozen=True)
class Subject:
    id: str
    label: str
    mem_terms: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()  # words of the subject that pick a meaning of an ambiguous topic


class SubjectCatalog:
    def __init__(self, subjects: Sequence[Subject]) -> None:
        self.subjects = tuple(subjects)
        self._by_key: dict[str, Subject] = {}
        for subject in self.subjects:
            for key in (subject.id, subject.label, *subject.aliases):
                self._by_key.setdefault(key.casefold(), subject)

    @classmethod
    def empty(cls) -> SubjectCatalog:
        return cls(())

    @classmethod
    def load(cls, path: Path) -> SubjectCatalog:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        subjects = [
            Subject(
                id=str(entry["id"]),
                label=str(entry["label"]),
                mem_terms=tuple(str(term).casefold() for term in entry.get("mem", [])),
                aliases=tuple(str(alias) for alias in entry.get("aliases", [])),
                context_terms=tuple(str(term).casefold() for term in entry.get("kontext", [])),
            )
            for entry in data.get("subjects", [])
        ]
        ids = [subject.id for subject in subjects]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate subject ids in {path}")
        return cls(subjects)

    def resolve(self, value: str | None) -> Subject | None:
        """The subject for an id, a discipline URI, a label or an alias; ``None`` when unknown."""
        if not value:
            return None
        key = value.strip()
        if key.startswith(DISCIPLINE_PREFIX):
            key = key[len(DISCIPLINE_PREFIX) :]
        return self._by_key.get(key.rstrip("/").casefold())

    def mem_terms(self, value: str | None) -> list[str]:
        subject = self.resolve(value)
        return list(subject.mem_terms) if subject else []

    def context_terms(self, value: str | None) -> list[str]:
        """Words that mark a meaning as belonging to the subject; without ``kontext``, its label and aliases."""
        subject = self.resolve(value)
        if subject is None:
            return []
        return list(subject.context_terms) or [subject.label.casefold(), *(a.casefold() for a in subject.aliases)]
