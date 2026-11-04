"""What a node, a collection and a knowledge collection bring to a request, given as text (D114).

``node_id``, ``collection_id`` and ``knowledge_collection_id`` make the service read an edu-sharing repository. A
caller without one, or one that reads its repository itself, sends the same facts as text: ``material`` for what a
material node brings (D47), ``collection_context`` for a collection with its place in the topic tree (M71), and
``sources`` for the materials of a knowledge collection (D70). The service reads them as it reads the repository's,
so the compendium is the same; ``GET /api/v2/nodes/{node_id}`` returns them as ``text_input``, ready to send.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field

from app.domain.spelling import OneSpelling, readable

TITLE_MAX_CHARS = 300
DESCRIPTION_MAX_CHARS = 20_000  # a repository's descriptions run longer than a caller writes
LIST_MAX_ITEMS = 50
SOURCES_MAX = 30
SOURCE_TEXT_MAX_CHARS = 50_000  # as the text of /qa and /entities


def _visible(value: str) -> str:
    """A text of nothing but spaces or format signs names nothing: a 422, as for ``topic`` (S9)."""
    if not readable(value).strip():
        raise ValueError("ist leer")
    return value


Title = Annotated[str, Field(min_length=1, max_length=TITLE_MAX_CHARS), AfterValidator(_visible)]
Titles = Annotated[list[Title], Field(max_length=LIST_MAX_ITEMS)]

SUBJECTS_HELP = (
    "Subjects as the vocabularies of edu-sharing name them (label, alias or URI of ccm:taxonid), all of equal weight; "
    "an unknown one is a 422 that lists the school subjects. A subject sent along in the request wins"
)
LEVELS_HELP = "Educational levels (e.g. 'Sekundarstufe I'); context words of the resolution, as a node's levels"


class TextInput(OneSpelling):
    model_config = ConfigDict(extra="forbid")


class MaterialText(TextInput):
    """A material as text, in place of ``node_id`` (D47): its title often names a format, so the service looks for
    the article in title and description, as it does for a material node."""

    title: Title = Field(description="The material's title, e.g. 'Stationsarbeit zur Optik'")
    description: str = Field("", max_length=DESCRIPTION_MAX_CHARS, description="Its description")
    keywords: Titles = Field(default_factory=list, description="Its keywords; context words of the resolution")
    subjects: Titles = Field(default_factory=list, description=SUBJECTS_HELP)
    levels: Titles = Field(default_factory=list, description=LEVELS_HELP)
    url: str | None = Field(None, max_length=2_000, description="The material's own address; shown, never fetched")


class CollectionText(TextInput):
    """A collection as text, in place of ``node_id`` or ``collection_id`` for the topic (M71): its title, and where it
    stands in its topic tree. Titles only; the service never reads the collections named here."""

    title: Title = Field(
        description="The collection's title; it becomes the topic. A title that names no subject matter "
        "('Grundlagen', 'Einführung') stands with the nearest informative collection of path"
    )
    path: Titles = Field(
        default_factory=list,
        description="The collections ABOVE it, from the top down, the nearest last, e.g. ['Kernphysik'] for "
        "'Grundlagen' under Kernphysik; without the repository's root and the subject portal (Physik), as the "
        "service reads a node, at most three levels. Without the LLM the rules take the nearest informative title of "
        "it for a neutral title; with the LLM the article choice hears the whole path",
    )
    children: Titles = Field(
        default_factory=list,
        description="Its own sub-collections (BELOW it); with the LLM they tell what the collection covers",
    )
    materials: Titles = Field(
        default_factory=list, description="Titles of its first materials; with the LLM they tell what it is about"
    )
    neighbours: Titles = Field(
        default_factory=list,
        description="The other sub-collections of its parent; with the LLM they are named as NOT meant, to tell the "
        "collection apart from them, never as content",
    )
    subjects: Titles = Field(default_factory=list, description=SUBJECTS_HELP)
    levels: Titles = Field(default_factory=list, description=LEVELS_HELP)
    missing: list[Literal["path", "children", "materials", "neighbours"]] = Field(
        default_factory=list,
        max_length=4,
        description="The parts of the place the repository did not give (GET /api/v2/nodes/{node_id} names them); "
        "without path the LLM hears no place in the tree, as for the node",
    )


class SourceText(TextInput):
    """A text that feeds part 1 as a source, as a material of ``knowledge_collection_id`` does (D70)."""

    title: Title = Field(description="Title of the source; the sources section names it")
    text: Annotated[str, AfterValidator(_visible)] = Field(
        min_length=1,
        max_length=SOURCE_TEXT_MAX_CHARS,
        description="The text: one paragraph per line; lines under 40 characters and consent notices are dropped, "
        "KNOWLEDGE_MAX_CHARS bounds what is kept",
    )
    url: str | None = Field(None, max_length=2_000, description="Its address; shown, never fetched")
    license: str = Field(
        "",
        max_length=100,
        description="Its licence as text, e.g. 'CC BY 4.0'; part 1 passes the text on under CC BY-SA 4.0 only from a "
        "free licence (CC0, Public Domain Mark, CC BY, CC BY-SA), as for the materials of a knowledge collection",
    )
    authors: Titles = Field(default_factory=list, description="Named authors, for the credit")
