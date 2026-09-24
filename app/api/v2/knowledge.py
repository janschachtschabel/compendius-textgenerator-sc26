"""Knowledge texts for a topic, without a compendium (docs/umbau.md, U2).

The corpus of a compendium is useful on its own: a caller that wants the sources should not have to ask for a
whole compendium and throw the template away. This endpoint resolves the topic and hands back the articles the
corpus builder would use, with their sections, optionally limited to single archives.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import archives_for, corpus_for_topic, get_service
from app.api.limits import rate_limited
from app.domain.models import Resolution, Source
from app.domain.requests import ARTICLE_CHOICE_HELP, ArticleChoice

router = APIRouter(prefix="/api/v2", tags=["v2"])


class KnowledgeRequest(BaseModel):
    topic: str = Field(
        min_length=1, max_length=300, description="The topic whose articles are returned; not found is a 404"
    )
    archives: list[str] = Field(default_factory=list, description="Archive ids to ask; empty asks every active archive")
    max_articles: int | None = Field(
        None,
        ge=1,
        le=50,
        description="Bound of the extra articles (default CORPUS_MAX_ARTICLES); the topic and its twin in "
        "another archive are always included",
    )
    max_chars: int | None = Field(None, ge=100, description="Cap over all articles; cuts at section borders")
    template_id: str | None = Field(None, description="Its slots steer the full-text search for extra articles")
    article_choice: ArticleChoice | None = Field(None, description=ARTICLE_CHOICE_HELP)


class KnowledgeSection(BaseModel):
    heading: str
    level: int
    text: str


class KnowledgeArticle(BaseModel):
    source_id: str
    archive: str = Field(description="Archive id, as in /api/v2/zim/status")
    project: str
    title: str
    url: str
    origin: str = Field(description="primary | same_topic | linked | search | lookup")
    is_primary: bool
    chars: int
    lead: str
    sections: list[KnowledgeSection]


class KnowledgeResponse(BaseModel):
    topic: str
    resolution: Resolution
    archives: list[str] = Field(description="The archives that were asked")
    articles: list[KnowledgeArticle]
    chars: int
    truncated: bool = Field(description="True when max_chars ended the answer early")
    article_choice: dict[str, Any] | None = Field(
        None,
        description="What article_choice=llm asked and decided: the article the LLM chose (chosen) or why the "
        "rules' one stayed (fallback, note), the full-text hits it dropped (hits_dropped) and the tokens; null when "
        "the rules chose alone",
    )


def _sections(source: Source) -> list[KnowledgeSection]:
    """Every section with text; the lead keeps its empty heading, as in the article."""
    sections = []
    for section in source.sections:
        text = "\n\n".join(paragraph.text for paragraph in section.paragraphs).strip()
        if text:
            sections.append(KnowledgeSection(heading=section.heading, level=section.level, text=text))
    return sections


def _article(source: Source, archive_id: str, sections: list[KnowledgeSection]) -> KnowledgeArticle:
    return KnowledgeArticle(
        source_id=source.source_id,
        archive=archive_id,
        project=source.project,
        title=source.title,
        url=source.url,
        origin=source.origin,
        is_primary=source.is_primary,
        chars=sum(len(section.text) for section in sections),
        lead=source.lead_text[:400],
        sections=sections,
    )


EXAMPLES = {
    "kuerzeste Anfrage": {
        "summary": "Nur ein Thema",
        "value": {"topic": "Optik"},
    },
    "mit den Schaltern": {
        "summary": "Gezielt ein Archiv, begrenzte Artikelzahl, ein Zeichendeckel und die Artikelwahl durch das LLM",
        "description": (
            "archives fragt einzelne Archive (unbekannte id: 404), max_articles begrenzt die zusätzlichen "
            "Artikel, max_chars deckelt den Text über alle Artikel und setzt truncated. article_choice llm lässt "
            "das LLM entscheiden, wo die Regeln unsicher sind, und unpassende Volltexttreffer verwerfen; rule-based "
            "nimmt die Regeln allein. Ohne b-api wählen die Regeln, und article_choice in der Antwort sagt warum."
        ),
        "value": {
            "topic": "Optik",
            "archives": ["wikipedia_de_all_nopic"],
            "max_articles": 6,
            "max_chars": 40000,
            "template_id": "sc26",
            "article_choice": "llm",
        },
    },
}


@router.post(
    "/knowledge",
    response_model=KnowledgeResponse,
    dependencies=[Depends(rate_limited)],
    summary="Wissenstexte zu einem Thema",
)
def knowledge(
    payload: Annotated[KnowledgeRequest, Body(openapi_examples=EXAMPLES)], request: Request
) -> KnowledgeResponse:
    """The articles of a topic, with their sections - no template, no matching, no synthesis.

    What comes back is the corpus as it is: the topic's article, its twin from the simpler project when
    there is one, and the further articles the search found. Each with its sections and their paragraphs.

    ``archives`` asks single archives by id and nothing else (unknown id: 404), ``max_articles`` bounds
    the further articles - topic and twin are always in - and ``max_chars`` caps the text over all
    articles and sets ``truncated`` when it bit. ``template_id`` only decides which search queries look
    for the further articles.

    ``article_choice`` works as in a compendium request, so both name the same articles for a topic: with
    ``llm`` the LLM decides where the rules are unsure and drops the full-text hits that do not fit, and
    ``article_choice`` in the answer says what it did and what it cost.

    A topic the archives do not have is a 404 carrying the resolution, so the answer names the
    alternatives instead of coming back empty.
    """
    service = get_service(request)
    registry = archives_for(service.registry, payload.archives)
    topic, resolution, sources, choice = corpus_for_topic(
        service,
        registry,
        payload.topic,
        template_id=payload.template_id,
        max_articles=payload.max_articles,
        article_choice=payload.article_choice,
    )
    by_file = {archive.file_name: archive.id for archive in registry.archives}
    articles: list[KnowledgeArticle] = []
    total, truncated = 0, False
    for source in sources:
        kept: list[KnowledgeSection] = []
        for section in _sections(source):
            if payload.max_chars is not None and total + len(section.text) > payload.max_chars:
                truncated = True
                break
            kept.append(section)
            total += len(section.text)
        if truncated and not kept:  # nothing of this article fit; listing it empty would say nothing
            break
        articles.append(_article(source, by_file.get(source.zim_file or "", ""), kept))
        if truncated:
            break
    return KnowledgeResponse(
        topic=topic,
        resolution=resolution,
        archives=[archive.id for archive in registry.archives],
        articles=articles,
        chars=total,
        truncated=truncated,
        article_choice=choice,
    )
