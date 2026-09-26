"""The wire contract of POST /api/v2/entities: request, answer and the examples /docs shows (U3, D43).

The endpoint itself - which ways run, the lookup and the identifiers - lives in entities.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import NodeInput
from app.domain.requests import NODE_ID_HELP, NODE_ID_PATTERN, REPOSITORY_HELP

Method = Literal["ner", "dictionary"]
MAX_TEXT_CHARS = 50_000  # a request body is caller input; recognition is linear in the text length
EXAMPLES = {
    "aus einem Text": {
        "summary": "Namen und Begriffe eines Textes, mit Artikel und Kennungen",
        "value": {"text": "Alexander von Humboldt reiste 1799 nach Südamerika."},
    },
    "aus einem Knoten des Repositorys": {
        "summary": "Titel, Beschreibung und Schlagwörter eines Materials der WLO-Staging",
        "description": (
            "node_id nennt ein Material oder eine Sammlung. Gelesen wird ohne Zugangsdaten, also nur Öffentliches; "
            "die Antwort gibt den gelesenen Text unter text zurück, start und end zählen darin."
        ),
        "value": {
            "node_id": "ac66224b-42b0-4676-a53d-71b058dc780b",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
        },
    },
    "alle Parameter": {
        "summary": "Jedes Feld zu einem Text: beide Verfahren, Nachschlagen in einem Archiv, eine Obergrenze",
        "description": (
            "methods ner (spaCy-Modell) und dictionary (Artikeltitel der Archive), link true schlägt den Artikel "
            "hinter jedem Treffer nach, archives beschränkt das auf ein Archiv (unbekannte id: 404), max_entities "
            "begrenzt vor dem Nachschlagen. node_id und repository stehen statt text, nicht daneben: siehe das "
            "Beispiel mit dem Knoten."
        ),
        "value": {
            "text": "Alexander von Humboldt reiste 1799 nach Südamerika und bestieg den Chimborazo.",
            "methods": ["ner", "dictionary"],
            "link": True,
            "archives": ["wikipedia_de_all_nopic"],
            "max_entities": 20,
        },
    },
}


def _default_methods() -> list[Method]:
    return ["ner", "dictionary"]


class EntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a field the service does not know is a 422, not a silent miss

    text: str | None = Field(
        None,
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description="The text the entities are read from; or node_id instead, whose title, description and keywords "
        "become the text",
    )
    node_id: str | None = Field(None, pattern=NODE_ID_PATTERN, description=NODE_ID_HELP)
    repository: str | None = Field(None, max_length=300, description=REPOSITORY_HELP)
    methods: list[Method] = Field(
        default_factory=_default_methods,
        min_length=1,
        description="The ways that recognise entities, one or both (default both): ner - the spaCy model finds "
        "names of persons, places, organisations and others (PER, LOC, ORG, MISC), and needs the model; dictionary "
        "- the titles of articles of the archives found in the text, and needs archives. A way that cannot work "
        "here is left out, and when neither can the answer is a 503",
    )
    link: bool = Field(
        True,
        description="true (default): look up the article behind each entity in the archives, with its lead, kind "
        "and identifiers, and drop a dictionary term whose only article is a disambiguation page. false: no "
        "lookup - faster, and note says the terms of the dictionary are unchecked",
    )
    archives: list[str] = Field(
        default_factory=list,
        description="Archive ids to ask, as GET /api/v2/zim/status lists them; empty (the default) asks every "
        "active archive, an unknown id is a 404",
    )
    max_entities: int = Field(
        50,
        ge=1,
        le=200,
        description="Upper bound, 1 to 200, default 50; it applies before the article check, so fewer may come back "
        "when terms of the dictionary turn out to sit behind a disambiguation page",
    )

    @model_validator(mode="after")
    def _text_or_node(self) -> EntitiesRequest:
        if not self.text and not self.node_id:
            raise ValueError("text oder node_id ist erforderlich")
        if self.text and self.node_id:
            raise ValueError("text oder node_id, nicht beides: der Knoten liefert den Text")
        if self.repository and not self.node_id:
            raise ValueError("repository gilt für node_id; ohne node_id fehlt der Knoten")
        return self


class EntityIds(BaseModel):
    gnd: str | None = Field(
        description="GND number from the article's Normdaten block; URI https://d-nb.info/gnd/<gnd>"
    )
    gnd_kind: str | None = Field(
        description="Kind of the GND record as the Normdaten block names it: Person, Sachbegriff, Geografikum, "
        "Körperschaft, Werk, ..."
    )
    viaf: str | None = Field(description="VIAF number from the same block; URI https://viaf.org/viaf/<viaf>")
    wikidata: str | None = Field(
        description="Wikidata number from the local index (compendium wikidata build); missing without the index "
        "or for an article the dump does not know; URI http://www.wikidata.org/entity/<wikidata>"
    )
    dbpedia: str = Field(description="DBpedia URI built from the title, not checked against DBpedia")
    same_as: list[str] = Field(description="Every identifier above as a URI, in the order GND, VIAF, Wikidata, DBpedia")


class EntityArticle(BaseModel):
    title: str
    archive: str
    project: str
    url: str
    lead: str
    kind: str | None = Field(description="Person, Organisation, Vorhaben, Netzwerk or Werk, read from the lead")
    ids: EntityIds | None = Field(
        None, description="GND, VIAF, Wikidata and DBpedia, from local data only; null for articles outside Wikipedia"
    )


class Entity(BaseModel):
    text: str
    start: int
    end: int
    kind: str = Field(description="The model's label (PER, LOC, ORG, MISC); empty for a term of the archives")
    source: Method
    linked: bool
    article: EntityArticle | None = None


class EntitiesResponse(BaseModel):
    methods: list[Method] = Field(description="The ways that actually ran")
    archives: list[str] = Field(description="The archives that were asked")
    entities: list[Entity]
    note: str | None = Field(
        None,
        description="What a reader should know about how the entities came about: with link=false the dictionary "
        "cannot tell an article from a disambiguation page, so its terms are unchecked",
    )
    node: NodeInput | None = Field(None, description="The node whose title, description and keywords were read")
    text: str | None = Field(
        None, description="The text read from node_id - start and end count in it; null when the request sent one"
    )
