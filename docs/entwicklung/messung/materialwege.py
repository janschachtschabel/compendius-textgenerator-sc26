"""Ways to find the article of a material, shared by the measurements of node input (M21, M23).

The entities of title and description, ranked as M21 ranks them (S3); the question to the LLM which German
Wikipedia article a material is about (S4); and the accepted titles of the gold as the archive names them.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.llm.client import BApiClient

TEXT_CHARS = 2000  # of the description, as the entities text of node input caps it far above
PROMPT_CHARS = 1500
# Words that say what a material is, not what it is about; stripped from title parts and never an entity's winner
FORMAT_WORDS = frozenset(
    "arbeitsblatt arbeitsblätter arbeitsheft experiment versuch lernvideo erklärvideo video videos kurs online-kurs "
    "landkarte karte quiz test übung übungen stationsarbeit stationenlernen unterrichtsreihe unterrichtseinheit "
    "unterrichtsmaterial präsentation tafelbild lernpfad lückentext kreuzworträtsel suchsel simulation app "
    "interview podcast projektideen gruppenpuzzle fachportal abschlussarbeit klassenarbeit teil variante "
    "experimentiervideo lehrvideo stummes oer mint-app".split()
)
SYSTEM = (
    "Du bestimmst für ein Unterrichtsmaterial das fachliche Thema, zu dem ein Kompendium für Lehrkräfte geschrieben "
    'werden soll. Antworte ausschließlich mit einem JSON-Objekt wie {"titel": "..."}: dem genauen Titel des '
    'deutschsprachigen Wikipedia-Artikels zu diesem Thema, oder "", wenn das Material kein fachliches Thema hat. '
    "Keine Erklärungen."
)


def canonical(archive: Any, titles: list[str]) -> set[str]:
    """The accepted titles as the archive names them after a redirect."""
    found = set()
    for title in titles:
        article = archive.read(title)
        found.add(article.title if article is not None else title)
    return found


def entity_ranking(service: Any, title: str, description: str, keywords: list[str]) -> list[tuple[str, float]]:
    # imported here: they load the API and the recogniser, which a measurement without entities (M24) does not need
    from app.api.v2.entities import _link  # the endpoint's own linking
    from app.knowledge.recognise import mentions_from_titles, merge

    text = f"{title}\n{description[:TEXT_CHARS]}"
    keys = {keyword.casefold() for keyword in keywords}
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    for mention in merge(mentions_from_titles(service.registry.archives, text)):
        if mention.text.casefold() in FORMAT_WORDS:
            continue
        article = _link(service.registry.archives, mention)
        if article is None:
            continue
        score = 3.0 if mention.start < len(title) else 1.0
        if mention.text.casefold() in keys or article.title.casefold() in keys:
            score += 2.0
        scores[article.title] = scores.get(article.title, 0.0) + score
        first_seen.setdefault(article.title, mention.start)
    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))


def ask_llm(client: BApiClient, info: Any) -> tuple[str, int]:
    user = (
        f"Titel: {info.title}\nFächer: {', '.join(info.subject_labels) or 'keine'}\n"
        f"Schlagwörter: {', '.join(info.keywords) or 'keine'}\nBeschreibung: {info.description[:PROMPT_CHARS]}\n\n"
        "Gib das JSON-Objekt zurück."
    )
    result = client.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        max_output_tokens=client.completion_limit(60),
    )
    try:
        named = str(json.loads(re.search(r"\{.*\}", result.text, re.S).group(0)).get("titel") or "")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        named = ""
    return named.strip(), result.total_tokens
