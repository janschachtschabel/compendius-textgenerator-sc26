"""The article a material is about (D47): what node input builds its compendium on when no topic names it.

The title of a material often names its format or source rather than its subject ("Zahnrad und Riemen -
Experiment:", "21./22. April 1946"). M21 and M23 measured ways to find the article on 40 real materials of the WLO
production (eval/materialwahl/materialien.yaml); of the 31 with a clear subject topic:

- the title as the topic, as node input did until M25: 5 right, 13 wrong, 13 without an article (F1 0.20);
- the rules below, over the terms of title and description, without an LLM: 15 right, 8 wrong, 8 without an article
  (F1 0.56), and no article for the two materials without a subject topic;
- the LLM naming the German Wikipedia article from title, subjects, keywords and description: 30 of 31 right
  (F1 0.97) at about 440 tokens.

The terms are the articles the dictionary of /entities finds in title and description, ranked as M21 ranked them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob, Usage, read_object
from app.knowledge.linking import article_of
from app.knowledge.recognise import mentions_from_titles, merge
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.prompts import get_prompt
from app.sources.wlo.models import NodeInfo
from app.sources.zim.archive import ZimArchive

MAX_ENTITIES = 10  # the ranked terms that count; the ten terms per topic of the old service (M2)
TEXT_CHARS = 2000  # of the description, for the terms
PROMPT_CHARS = 1500  # of the description, for the model
OUTPUT_TOKENS = 80  # one or two titles
TITLE_SCORE, TEXT_SCORE, KEYWORD_BONUS = 3.0, 1.0, 2.0
# Words that say what a material is, not what it is about; never a term of its own (M21)
FORMAT_WORDS = frozenset(
    "arbeitsblatt arbeitsblätter arbeitsheft experiment versuch lernvideo erklärvideo video videos kurs online-kurs "
    "landkarte karte quiz test übung übungen stationsarbeit stationenlernen unterrichtsreihe unterrichtseinheit "
    "unterrichtsmaterial präsentation tafelbild lernpfad lückentext kreuzworträtsel suchsel simulation app "
    "interview podcast projektideen gruppenpuzzle fachportal abschlussarbeit klassenarbeit teil variante "
    "experimentiervideo lehrvideo stummes oer mint-app".split()
)


@dataclass
class NodeArticleReport(Usage):
    """How the article of a material was found (D47), for the audit; the usage counts the question to the LLM."""

    way: str = "rules"  # llm: the model named it; rules: the title and the terms of the material
    title_article: str | None = None  # what the rules make of the title
    entities: list[str] = field(default_factory=list)  # the ranked terms of title and description
    named: str | None = None  # the article the model named; "" for a material without a subject topic
    material: str | None = None  # the material's own article, when a topic came along
    added: bool = False  # the material's own article joined the corpus: it links with the main article
    fallback: str | None = None  # why the model's answer did not decide


def node_block(report: NodeArticleReport) -> dict[str, Any]:
    """What the audit, /knowledge and a 404 say about the article of a material (D47)."""
    return {
        "way": report.way,
        "title_article": report.title_article,
        "entities": list(report.entities),
        "named": report.named,
        "material": report.material,
        "added": report.added,
        "fallback": report.fallback,
        "tokens": report.total_tokens,
    }


def ranked_entities(archives: Sequence[ZimArchive], title: str, description: str, keywords: Sequence[str]) -> list[str]:
    """The articles of the terms in title and description, the most telling first (M21 S3).

    Each mention counts 3 in the title and 1 in the description, 2 more when it is a keyword; a tie goes to the term
    mentioned first. Format words and disambiguation pages are no terms.
    """
    text = f"{title}\n{description[:TEXT_CHARS]}"
    keys = {keyword.casefold() for keyword in keywords}
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    for mention in merge(mentions_from_titles(archives, text)):
        if mention.text.casefold() in FORMAT_WORDS:
            continue
        found = article_of(archives, mention)
        if found is None:
            continue
        name = found[1].title
        score = TITLE_SCORE if mention.start < len(title) else TEXT_SCORE
        if mention.text.casefold() in keys or name.casefold() in keys:
            score += KEYWORD_BONUS
        scores[name] = scores.get(name, 0.0) + score
        first_seen.setdefault(name, mention.start)
    ranked = sorted(scores, key=lambda name: (-scores[name], first_seen[name]))
    return ranked[:MAX_ENTITIES]


def rule_article(title_article: str | None, entities: Sequence[str], title: str) -> str | None:
    """Which article the rules build on (M23): the title's, when the terms name it too; else the first term, when
    the title names it; else none - the caller then has to send a topic."""
    if title_article is not None and title_article in entities:
        return title_article
    if entities and entities[0].lower() in title.lower():
        return entities[0]
    return None


def ask_topic(
    job: ArticleChoiceJob, info: NodeInfo, report: NodeArticleReport, topic: str | None = None
) -> tuple[str, str] | None:
    """The model's answer: the article to build on and, with a topic, the material's own - "" where it names none.

    Without a topic the model hears title, subjects, keywords and description as measured (``node_topic``); with one
    it hears the teacher's topic first (``node_topic_with_topic``). ``None`` when it gave no usable answer; the report
    gets the cost and the reason.
    """
    prompt = get_prompt("node_topic_with_topic" if topic else "node_topic")
    fields = {
        "title": info.title,
        "subjects": ", ".join(info.subject_labels) or "keine",
        "keywords": ", ".join(info.keywords) or "keine",
        "description": info.description[:PROMPT_CHARS],
    }
    if topic:
        fields["topic"] = topic
    report.way = "llm"
    answer = budgeted_chat(
        job.client,
        prompt.render(**fields),
        max_output_tokens=OUTPUT_TOKENS,
        budget=job.budget,
        what="Thema des Materials",
        deadline=job.deadline,
    )
    report.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        report.fallback = answer.reason
        return None
    data = read_object(answer.text)
    if data is None:
        report.fallback = UNREADABLE
        return None
    named = str(data.get("titel") or "").strip()
    own = str(data.get("material") or "").strip() if topic else ""
    report.named, report.material = named, own or None
    return named, own
