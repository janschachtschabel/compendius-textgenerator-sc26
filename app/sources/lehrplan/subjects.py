"""WLO subject vocabulary to MEM subject search terms (``config/subjects.yaml``, PLAN.md 4.2, 5.3).

A request names a subject by WLO discipline id, by the full vocabulary URI (``ccm:taxonid`` of a
collection), by label or by an alias ("Mathe"). The catalog turns that into lowercase substrings
of MEM's Schulfach labels; an unknown subject yields no terms, and the search then spans all subjects.
It also names the words by which the topic resolution recognises a meaning of the subject (``kontext``).

The subjects a request may name are those of the two vocabularies edu-sharing uses in ``ccm:taxonid``: the school
subjects and the Destatis university subjects, kept as snapshots in ``config/vocabs`` (D51). Only the 37 of
subjects.yaml bring curriculum and context words; any other one of the vocabularies is taken and counts by its
label. A subject a request names is checked (``check``); the subjects a node or a collection brings are not, and an
unknown one there counts for nothing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DISCIPLINE_PREFIX = "http://w3id.org/openeduhub/vocabs/discipline/"
# The snapshots beside subjects.yaml; the school subjects come first and keep a label both share ("Mathematik")
VOCABULARIES = ("discipline.json", "hochschulfaechersystematik.json")


class UnknownSubjectError(ValueError):
    """A subject neither the catalog nor the vocabularies know; ``known`` are the school subjects (a 422)."""

    def __init__(self, value: str, known: Sequence[str], *, university: bool = False) -> None:
        self.value, self.known = value, list(known)
        also = " und die Hochschulfächer der Destatis-Systematik" if university else ""
        super().__init__(
            f"Unbekanntes Fach: {value}. Bekannt sind die Schulfächer {', '.join(self.known)}{also}, jeweils auch "
            "als URI, Kennung oder Kurzform"
        )


@dataclass(frozen=True)
class Term:
    """A concept of a subject vocabulary: its URI, its German label and its alternative labels."""

    uri: str
    label: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Subject:
    id: str
    label: str
    mem_terms: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()  # words of the subject that pick a meaning of an ambiguous topic


class SubjectCatalog:
    def __init__(self, subjects: Sequence[Subject], vocabulary: Sequence[Term] = ()) -> None:
        self.subjects = tuple(subjects)
        self.vocabulary = tuple(vocabulary)
        self._by_key: dict[str, Subject] = {}
        for subject in self.subjects:
            for key in (subject.id, subject.label, *subject.aliases):
                self._by_key.setdefault(key.casefold(), subject)
        # A URI only finds its own concept: the other keys (id, labels) never contain "://"
        self._terms: dict[str, Term] = {}
        for term in self.vocabulary:
            for key in (term.uri, term.uri.rsplit("/", 1)[-1], term.label, *term.aliases):
                self._terms.setdefault(key.casefold(), term)

    @classmethod
    def empty(cls) -> SubjectCatalog:
        return cls(())

    @classmethod
    def load(cls, path: Path) -> SubjectCatalog:
        """subjects.yaml, and the vocabularies edu-sharing uses in ccm:taxonid from ``vocabs/`` beside it."""
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
        return cls(subjects, _vocabulary(Path(path).parent / "vocabs"))

    def resolve(self, value: str | None) -> Subject | None:
        """The subject for an id, a discipline URI, a label or an alias; ``None`` when unknown."""
        if not value:
            return None
        key = value.strip()
        if key.startswith(DISCIPLINE_PREFIX):
            key = key[len(DISCIPLINE_PREFIX) :]
        return self._by_key.get(key.rstrip("/").casefold())

    def term(self, value: str | None) -> Term | None:
        """The vocabulary concept of a URI, an id (the URI's last segment), a German label or an alternative label."""
        if not value or not value.strip():
            return None
        return self._terms.get(value.strip().rstrip("/").casefold())

    def check(self, value: str | None) -> None:
        """Refuse a subject neither the catalog nor the vocabularies know; without either nothing is checked."""
        if not value or not (self.subjects or self.vocabulary) or self.resolve(value) or self.term(value):
            return
        school = [term.label for term in self.vocabulary if term.uri.startswith(DISCIPLINE_PREFIX)]
        known = school or [subject.label for subject in self.subjects]
        raise UnknownSubjectError(value, known, university=len(school) < len(self.vocabulary))

    def mem_terms(self, value: str | None) -> list[str]:
        subject = self.resolve(value)
        return list(subject.mem_terms) if subject else []

    def context_terms(self, value: str | None) -> list[str]:
        """Words that mark a meaning as belonging to the subject; without ``kontext``, its label and aliases."""
        subject = self.resolve(value)
        if subject is None:
            return []
        return list(subject.context_terms) or [subject.label.casefold(), *(a.casefold() for a in subject.aliases)]

    # The subjects of a node or a collection are a multi-valued field: every value weighs the same, whichever the
    # repository names first. The three methods below take all of them.

    def context_terms_of(self, values: Sequence[str]) -> list[str]:
        """The context words of every subject, each once."""
        return list(dict.fromkeys(term for value in values for term in self.context_terms(value)))

    def mem_terms_of(self, values: Sequence[str]) -> list[str]:
        """The curriculum words of every subject, each once; the curriculum search takes any of them."""
        return list(dict.fromkeys(term for value in values for term in self.mem_terms(value)))

    def labels_of(self, values: Sequence[str]) -> list[str]:
        """Names of the subjects: the catalog's label, else the vocabulary's, else a name a caller typed as it is;
        an unknown URI names nothing."""
        labels: list[str] = []
        for value in values:
            subject = self.resolve(value)
            term = self.term(value) if subject is None else None
            if subject is not None:
                labels.append(subject.label)
            elif term is not None:
                labels.append(term.label)
            elif value.strip() and "://" not in value:
                labels.append(value.strip())
        return list(dict.fromkeys(labels))


def _vocabulary(directory: Path) -> list[Term]:
    """Every concept of the SKOS snapshots in ``directory``, top concepts and their narrower ones."""
    terms: list[Term] = []
    for name in VOCABULARIES:
        path = directory / name
        if not path.exists():
            log.warning("subject vocabulary %s not found; subjects are checked without it", path)
            continue
        scheme: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        for concept in _concepts(scheme.get("hasTopConcept", [])):
            label = (concept.get("prefLabel") or {}).get("de")
            if concept.get("id") and label:
                aliases = (concept.get("altLabel") or {}).get("de", [])
                terms.append(Term(str(concept["id"]).rstrip("/"), str(label), tuple(str(alias) for alias in aliases)))
    return terms


def _concepts(nodes: Sequence[Mapping[str, Any]]) -> Iterator[Mapping[str, Any]]:
    for node in nodes:
        yield node
        yield from _concepts(node.get("narrower", []))
