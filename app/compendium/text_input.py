"""The text input of a request read as the repository's facts would be (D114): a material and a collection as the
records ``read_node`` and ``collection_tree`` return, the sources as the materials of a knowledge collection."""

from __future__ import annotations

from app.domain.models import ArticleSection, Paragraph, Source, SourceRole
from app.domain.text_input import CollectionText, MaterialText, SourceText
from app.sources.wlo.knowledge import TEXT_HEADING, paragraphs_from_text
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.tree import TreeContext

TEXT_PROJECT = "text_material"  # licences.PROJECT_LABELS names it; the blocks that want materials take it (policy)
TEXT_ORIGIN = "text"


def text_subjects(material: MaterialText | None, collection: CollectionText | None) -> list[str]:
    """The subjects a text input names, each to be known as a request's subject must be (D114)."""
    return [*(material.subjects if material else ()), *(collection.subjects if collection else ())]


def material_node(material: MaterialText) -> NodeInfo:
    """A material as ``read_node`` gives one: the subjects as written, which the catalog resolves as it does URIs."""
    return NodeInfo(
        node_id="",
        kind="material",
        title=material.title,
        description=material.description,
        keywords=tuple(material.keywords),
        subject_uris=tuple(material.subjects),
        subject_labels=tuple(material.subjects),
        educational_contexts=tuple(material.levels),
        url=material.url or "",
    )


def collection_node(collection: CollectionText) -> NodeInfo:
    """A collection as ``read_node`` gives one; its place in the tree comes from ``collection_tree``."""
    return NodeInfo(
        node_id="",
        kind="collection",
        title=collection.title,
        description="",
        keywords=(),
        subject_uris=tuple(collection.subjects),
        subject_labels=tuple(collection.subjects),
        educational_contexts=tuple(collection.levels),
        url="",
    )


def collection_tree(collection: CollectionText, content: bool) -> TreeContext:
    """The place in the topic tree as ``read_tree`` returns it: the path always, the rest only with ``content``, so
    the rules see what they see for a node and the audit shows the same."""
    if not content:
        return TreeContext(path=tuple(collection.path))
    return TreeContext(
        path=tuple(collection.path),
        children=tuple(collection.children),
        materials=tuple(collection.materials),
        neighbours=tuple(collection.neighbours),
    )


def text_sources(items: list[SourceText], max_chars: int) -> tuple[list[Source], int]:
    """Sources of part 1 from the texts of a request, cut into paragraphs as a material's text (D70); with how many
    brought no paragraph worth citing."""
    sources: list[Source] = []
    empty = 0
    for number, item in enumerate(items, start=1):
        paragraphs = paragraphs_from_text(item.text, max_chars)
        if not paragraphs:
            empty += 1
            continue
        section = ArticleSection(
            heading=TEXT_HEADING, path=[TEXT_HEADING], level=2, paragraphs=[Paragraph(text=p) for p in paragraphs]
        )
        sources.append(
            Source(
                source_id=f"text:{number}",
                project=TEXT_PROJECT,
                role=SourceRole.MATERIAL,
                title=item.title,
                url=item.url or "",
                license=item.license,
                authors=list(item.authors),
                authority_score=0.8,  # as a material of a knowledge collection
                is_primary=False,
                origin=TEXT_ORIGIN,
                sections=[section],
            )
        )
    return sources, empty
