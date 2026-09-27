"""The wire contract of POST /api/v2/entities: request, answer and the examples /docs shows (U3, D43, D62).

The endpoint itself - which ways run, the lookup and the identifiers - lives in entities.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import NodeInput
from app.domain.requests import NODE_ID_HELP, NODE_ID_PATTERN, REPOSITORY_HELP, Preset

Method = Literal["ner", "dictionary", "llm"]
LinkCheck = Literal["rule-based", "llm"]
# The ways of each profile (D62), measured on the texts of 40 materials in the service (docs/entwicklung, M36)
PROFILE_METHODS: dict[str, list[Method]] = {
    "llm-free": ["ner", "dictionary"],
    "balanced": ["llm"],
    "best-quality": ["llm"],
    "best-quality-generated": ["llm"],
}
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
    "ohne LLM (llm-free)": {
        "summary": "Die Regeln allein: spaCy-Modell und die Artikeltitel der Archive",
        "description": (
            "ner und dictionary, kein LLM, keine Tokens: am Gold F1 0,38 bei einer Präzision von 0,29 (M36). Ohne "
            "preset gilt das Profil des Servers (PRESET_DEFAULT, ausgeliefert balanced), das ein LLM braucht."
        ),
        "value": {"text": "Alexander von Humboldt reiste 1799 nach Südamerika.", "preset": "llm-free"},
    },
    "mit Prüfung der Verknüpfungen": {
        "summary": "Das LLM nennt die Entitäten und prüft danach jede Verknüpfung",
        "description": (
            "link_check llm, in keinem Profil voreingestellt: Präzision 0,94 statt 0,70, aber ein Drittel der "
            "passenden Entitäten fällt weg (F1 0,76 statt 0,78; D62). Für eine kurze, sichere Liste. Braucht "
            "LLM_ENABLED und B_API_KEY, sonst 503."
        ),
        "value": {
            "text": "Alexander von Humboldt reiste 1799 nach Südamerika.",
            "preset": "balanced",
            "link_check": "llm",
        },
    },
    "alle Parameter": {
        "summary": "Jedes Feld zu einem Text: alle drei Wege, geprüft, in einem Archiv, mit Obergrenze",
        "description": (
            "Die Schalter gewinnen über das Profil: methods nimmt ner (spaCy-Modell), dictionary (Artikeltitel der "
            "Archive) und llm (das LLM nennt Entitäten mit ihrem Artikeltitel) zusammen, link_check llm lässt das "
            "LLM jede Verknüpfung prüfen - in M36 F1 0,73, weniger als llm allein (0,78). link "
            "true schlägt den Artikel hinter jedem Treffer nach, archives beschränkt das auf ein Archiv (unbekannte "
            "id: 404), max_entities begrenzt vor dem Nachschlagen. node_id und repository stehen statt text, nicht "
            "daneben: siehe das Beispiel mit dem Knoten."
        ),
        "value": {
            "text": "Alexander von Humboldt reiste 1799 nach Südamerika und bestieg den Chimborazo.",
            "preset": "balanced",
            "methods": ["ner", "dictionary", "llm"],
            "link_check": "llm",
            "link": True,
            "archives": ["wikipedia_de_all_nopic"],
            "max_entities": 20,
        },
    },
}
METHODS_HELP = (
    "The ways that recognise entities, alone or together. Default: the profile's (preset, else PRESET_DEFAULT): "
    "llm-free takes ner and dictionary, balanced and the best-quality profiles llm. Measured on 2026-09-26 on the "
    "texts of 40 materials against two blind raters, as prototypes (M36, gpt-6-luna) and again through this endpoint "
    "(D62) with the same result.\n\n"
    "- **ner**: the spaCy model finds names of persons, places, organisations and others (PER, LOC, ORG, MISC); needs "
    "the model, no archives. Alone F1 0.30 at a precision of 0.41.\n"
    "- **dictionary**: the titles of articles of the archives that stand in the text, up to four words, the longest "
    "at a place; needs archives. Alone F1 0.35 at a precision of 0.25: everyday words that are a title ('Woche', "
    "'Frage') are linked too. With ner F1 0.38 at a precision of 0.29, in 0.25 s.\n"
    "- **llm**: the LLM of the b-api names the persons, places, organisations, works, events and subject terms the "
    "text is about, each with the title of its Wikipedia article; an entity stands where its word first stands in the "
    "text as a whole word, else inside a longer one, and one whose title is no article of the archives, or a "
    "disambiguation page, is left out. F1 0.78 at a precision of 0.70 and a recall of 0.89 - of 269 linked articles "
    "one meant something else -, about 800 tokens and 4 s. Needs an LLM and archives.\n\n"
    "A way that cannot work here is left out, and when none can the answer is a 503. llm on a server without a "
    "configured LLM (LLM_ENABLED, B_API_KEY) is a 503; while the b-api is not available, or when its answer holds no "
    "readable entry, ner and dictionary take its place, and note and llm.fallback say why. An answer cut off by the "
    "limit of the output keeps its complete entries; on a word both the LLM and a rule found, the LLM's title wins."
)
LINK_CHECK_HELP = (
    "Who checks the links. Default rule-based, in every profile. Acts only with link true.\n\n"
    "- **rule-based**: the lookup alone - a term of dictionary or llm whose title is no article, or a disambiguation "
    "page, is left out.\n"
    "- **llm**: the LLM also grades every linked article in one call, with the text and the beginning of the lead - "
    "2 an entity or term the text is about and the article means it, 1 fitting but minor or an everyday word, 0 "
    "something else - and only the 2s stay. On the names of llm, measured through this endpoint (D62), the precision "
    "rose from 0.70 to 0.94, but the recall fell from 0.89 to 0.64, F1 0.76 instead of 0.78: the check drops a third "
    "of the fitting entities, not only minor ones. So no profile sets it; take it where a short list of sure entities "
    "matters more than a complete one. About 820 tokens and 2 s more (0.8 to 4.2 s). On the links of ner and "
    "dictionary it raised the precision from 0.29 to 0.58, F1 0.51 instead of 0.38 (M36).\n\n"
    "llm on a server without a configured LLM is a 503, and with link false a 422; while the b-api is not available, "
    "or when its answer holds no readable grade, every link stays, and note and llm.fallback say why."
)
PRESET_HELP = (
    "The profile (D41, D53, D62); here it sets methods, and a switch the request sets itself wins. "
    "Without a preset the server's profile applies (PRESET_DEFAULT, shipped balanced). Every profile but llm-free "
    "needs an LLM (LLM_ENABLED, B_API_KEY); on a server without one such a request is a 503 that says so.\n\n"
    "- **llm-free**: ner and dictionary; F1 0.38, no tokens.\n"
    "- **balanced** (default): the LLM names the entities (methods llm); F1 0.78, about 800 tokens and 4 s.\n"
    "- **best-quality**: as balanced. The LLM's check of the links (link_check llm) raised the precision but lowered "
    "F1, so it stays a switch of its own.\n"
    "- **best-quality-generated**: as balanced; what it adds - the LLM writing a compendium - does not act here."
)


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
    preset: Preset | None = Field(None, description=PRESET_HELP)
    methods: list[Method] | None = Field(None, min_length=1, description=METHODS_HELP)
    link_check: LinkCheck = Field("rule-based", description=LINK_CHECK_HELP)
    link: bool = Field(
        True,
        description="true (default): look up the article behind each entity in the archives, with its lead, kind "
        "and identifiers, and drop a term of dictionary or llm whose only article is a disambiguation page. false: no "
        "lookup - faster, and note says the terms of dictionary and llm are unchecked",
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
        "when terms of the dictionary turn out to sit behind a disambiguation page. With methods llm it also sets the "
        "room for the LLM's answer, 24 tokens per entity and at least 1,200",
    )

    @model_validator(mode="after")
    def _text_or_node(self) -> EntitiesRequest:
        if not self.text and not self.node_id:
            raise ValueError("text oder node_id ist erforderlich")
        if self.text and self.node_id:
            raise ValueError("text oder node_id, nicht beides: der Knoten liefert den Text")
        if self.repository and not self.node_id:
            raise ValueError("repository gilt für node_id; ohne node_id fehlt der Knoten")
        if self.link_check == "llm" and not self.link:
            raise ValueError("link_check llm prüft die Verknüpfungen; mit link false gibt es keine")
        return self


class EntityIds(BaseModel):
    gnd: str | None = Field(
        description="GND number: from the article's Normdaten block, else from the local GND index built from the "
        "DNB's dumps (D65); URI https://d-nb.info/gnd/<gnd>"
    )
    gnd_kind: str | None = Field(
        description="Kind of the GND record as the Normdaten block names it: Person, Sachbegriff, Geografikum, "
        "Körperschaft, Werk, ...; from the GND index Sachbegriff or Geografikum"
    )
    gnd_source: str | None = Field(
        description="Where the GND number comes from: normdaten (the article's Normdaten block), wikidata (the one "
        "GND record that names the article's Wikidata item), name (the one GND record that carries the article's "
        "title as a name); null without a GND"
    )
    viaf: str | None = Field(description="VIAF number from the same block; URI https://viaf.org/viaf/<viaf>")
    wikidata: str | None = Field(
        description="Wikidata number from the local index (the Wikidata sync, D64); missing without the index "
        "or for an article the dump does not know; URI http://www.wikidata.org/entity/<wikidata>"
    )
    dbpedia: str = Field(
        description="DBpedia URI: http://dbpedia.org/resource/<title of the English article> when the local index "
        "knows one (D65), else the German chapter's IRI http://de.dbpedia.org/resource/<title>, which no longer "
        "answers (M42); built, not checked against DBpedia"
    )
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
    kind: str = Field(
        description="The spaCy model's label (PER, LOC, ORG, MISC); empty for a term of dictionary or llm"
    )
    source: Method = Field(description="The way that found it: ner, dictionary or llm")
    linked: bool
    article: EntityArticle | None = None


class EntitiesLlm(BaseModel):
    named: int = Field(description="Entities the LLM named whose word stands in the text (methods llm)")
    checked: int = Field(
        description="Linked articles the LLM graded (link_check llm); 0 when it was not asked or did not answer usably"
    )
    dropped: list[str] = Field(description="Articles the check did not grade 2; their entities are not in the answer")
    calls: int = Field(description="Calls to the b-api")
    total_tokens: int
    model: str | None = Field(description="The model that answered")
    prompts: list[str] = Field(description="The prompts that were answered, as id@version")
    fallback: str | None = Field(
        description="Why the LLM did not decide although it was asked: then ner and dictionary found the entities, "
        "or every link stayed. Where naming and check both failed, the first reason; note names each"
    )


class EntitiesResponse(BaseModel):
    methods: list[Method] = Field(
        description="The ways that actually ran; while the b-api is not available ner and dictionary stand in for llm"
    )
    archives: list[str] = Field(description="The archives that were asked")
    entities: list[Entity]
    note: str | None = Field(
        None,
        description="What a reader should know about how the entities came about: with link=false dictionary and llm "
        "cannot tell an article from a disambiguation page, so their terms are unchecked; and why the LLM did not "
        "decide although it was asked",
    )
    llm: EntitiesLlm | None = Field(
        None, description="What the LLM did and cost; null when neither methods nor link_check asked for it"
    )
    node: NodeInput | None = Field(None, description="The node whose title, description and keywords were read")
    text: str | None = Field(
        None, description="The text read from node_id - start and end count in it; null when the request sent one"
    )
