"""What a collection or a node contributes to the topic of a request (PLAN.md 4.2, step 0; D12, D45)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.knowledge.topic import NormalizedTopic, normalize_topic
from app.sources.wlo.models import CollectionInfo, NodeInfo


@dataclass(frozen=True)
class CollectionTopic:
    """What a collection or a node contributes to topic resolution (PLAN.md 4.2, step 0; D45).

    Subjects and educational levels are multi-valued fields: every value weighs the same, whichever comes first.
    """

    topic: str
    subjects: list[str]
    context: list[str]


def collection_topic(info: CollectionInfo) -> CollectionTopic:
    return CollectionTopic(
        topic=info.title,
        subjects=list(info.subject_uris),
        context=list(info.educational_contexts),
    )


def node_topic(info: NodeInfo) -> CollectionTopic:
    """What a node contributes to topic resolution (D45): its title, all its subjects, levels and keywords.

    Levels and keywords go in as context words. The rules weigh context words at a disambiguation page only when the
    subject brings no words of its own, and the LLM choice sees none, so with a known subject they do not steer the
    choice yet. The title of a material often names its format rather than a lexicon topic („Stationsarbeit zur
    Optik“): for a material it is where the search for the article starts, not the topic itself
    (app/knowledge/main_article.py, D47); a topic sent along leads.
    """
    return CollectionTopic(
        topic=info.title,
        subjects=list(info.subject_uris),
        context=[*info.educational_contexts, *info.keywords],
    )


@dataclass(frozen=True)
class DerivedTopic:
    """The topic a request resolves, with the subjects and the context words that go into the resolution."""

    normalized: NormalizedTopic
    subjects: list[str]  # all of equal weight
    context: list[str]


def derive_topic(
    topic: str | None,
    derived: Sequence[CollectionTopic],
    subject: str | None = None,
    *,
    is_subject: Callable[[str], bool],
) -> DerivedTopic:
    """One derivation for compendium, knowledge and the node preview (D12, D45).

    The topic: the one sent along, else the first title of ``derived`` (a node before a collection), normalised. The
    subjects: the one sent along, else one the topic names („Physik: Optik“), else all subjects of the first entry of
    ``derived`` that has any - every one of equal weight. The context words: the topic's qualifiers, then those of
    every entry of ``derived``.
    """
    normalized = normalize_topic(topic or (derived[0].topic if derived else ""), is_subject=is_subject)
    context = [*normalized.context, *(word for found in derived for word in found.context)]
    named = subject or normalized.subject
    subjects = [named] if named else next((list(found.subjects) for found in derived if found.subjects), [])
    return DerivedTopic(normalized=normalized, subjects=subjects, context=context)
