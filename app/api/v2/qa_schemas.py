"""What POST /api/v2/qa accepts and answers with - the wire contract, and nothing that acts on it.

Split out of app/api/v2/qa.py so the endpoint module can be read as one thing. The contract changes for
its own reasons (a new field, a new bound, a clearer help text) and those reasons have nothing to do
with which stage produced the pairs, which is why the two live apart.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import NodeInput, Resolution
from app.domain.requests import (
    NODE_ID_HELP,
    NODE_ID_PATTERN,
    REPOSITORY_HELP,
    UNKNOWN_SUBJECT_HELP,
    ArticleChoice,
    Preset,
)

Method = Literal["rule-based", "parse-based", "models", "llm"]
# The method of each profile (D53): llm-free the free and fast parse, every profile with an LLM the LLM
PROFILE_METHODS: dict[str, Method] = {
    "llm-free": "parse-based",
    "balanced": "llm",
    "best-quality": "llm",
    "best-quality-generated": "llm",
}
LEVEL_PROPERTY = "Bildungsstufe"  # the one level vocabulary the project owns (config/facets.yaml)
MAX_TEXT_CHARS = 50_000  # bounds the request body and the text a topic yields; both end up in the same code


class QaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a field the service does not know is a 422, not a silent miss

    text: str | None = Field(
        None,
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description="The text the pairs are made from - the markdown of a compendium you already "
        "have, or any other text",
    )
    topic: str | None = Field(
        None,
        min_length=1,
        max_length=300,
        description="Instead of a text: part 1 of the compendium for this topic is made first and the "
        "pairs are asked about it. That costs a compendium generation - hand the text over instead when "
        "you already have one",
    )
    node_id: str | None = Field(None, pattern=NODE_ID_PATTERN, description=NODE_ID_HELP)
    repository: str | None = Field(None, max_length=300, description=REPOSITORY_HELP)
    subject: str | None = Field(
        None,
        max_length=100,
        description="With topic or node_id: the subject that decides the article, as in a compendium request (WLO "
        "discipline id, vocabulary URI, label or alias)" + UNKNOWN_SUBJECT_HELP,
    )
    preset: Preset | None = Field(
        None,
        description="The profile (D53): it picks the method of the pairs when the request names none - llm-free "
        "parse-based, every other profile llm -, and with topic or node_id the part 1 they are made from, as in a "
        "compendium request. Default: PRESET_DEFAULT, shipped balanced",
    )
    article_choice: ArticleChoice | None = Field(
        None,
        description="With topic or node_id: who chooses the article, rule-based or llm, as in a compendium request; "
        "llm also names the article of a material without a topic (D47). A preset sets it",
    )
    method: Method | None = Field(
        None,
        description="Default: the profile's (preset, else PRESET_DEFAULT): llm-free takes parse-based, every other "
        "profile llm (D53). rule-based needs nothing: four question templates over the "
        "sentence openings, and the answer is the whole sentence. parse-based swaps the sentence subject "
        "for a question word using the spaCy parse that is loaded anyway - four times as many sentences "
        "yield a question and the answer is the subject itself, at about 4 ms per sentence once warm. models uses "
        "the two German models baked into the image (question generator plus extractive answers) and is "
        "the most accurate and by far the slowest. llm lets the b-api write the pairs; with a topic or node, part 1 "
        "and the pairs share one token budget and one deadline (LLM_MAX_TOKENS_PER_REQUEST, REQUEST_TIMEOUT_S), so "
        "a part 1 that spent them leaves the pairs to the templates. parse-based and models fall back to rule-based "
        "when they cannot run, and note says why; llm without a configured LLM is a 503, and while the b-api is not "
        "available it falls back as well",
    )
    count: int = Field(5, ge=1, le=50, description="Upper bound of the pairs")
    max_answer_length: int = Field(300, ge=50, le=2000, description="Characters per answer; longer ones are cut")
    levels: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Educational levels to spread the pairs over. Optional; without them nothing changes. "
        "Written as the Bildungsstufe vocabulary writes it - the label (Sekundarstufe I), an alternative label "
        "(Sekundarstufe 1) or the concept URI - or as config/facets.yaml writes it (Elementar, Primar, Sek I, "
        "Sek II, Hochschule, Berufliche Bildung, Erwachsenenbildung). Only the llm stage can assign one; the "
        "other stages return the pairs without a level and say so in note. With node_id and the llm stage, the "
        "levels of the node count when none are sent (those without a counterpart left out), and its title and "
        "keywords become the focus of the questions (D47); note says so",
    )

    @model_validator(mode="after")
    def _text_or_topic(self) -> QaRequest:
        if self.text is not None and not self.text.strip():
            raise ValueError("text enthält nur Leerraum; ohne Sätze entstehen keine Paare")
        if not self.text and not self.topic and not self.node_id:
            raise ValueError("text, topic oder node_id ist erforderlich")
        if self.text and (self.topic or self.node_id):
            raise ValueError("text oder topic/node_id, nicht beides: ein Thema macht erst Teil 1 und fragt ihn ab")
        if self.repository and not self.node_id:
            raise ValueError("repository gilt für node_id; ohne node_id fehlt der Knoten")
        # They decide the article of part 1; a text of the caller's is asked as it is. preset goes with a text as
        # well: it picks the method of the pairs (D53)
        for name in ("subject", "article_choice"):
            if getattr(self, name) is not None and not (self.topic or self.node_id):
                raise ValueError(f"{name} gilt nur mit topic oder node_id; ein text wird abgefragt, wie er ist")
        return self


class Pair(BaseModel):
    question: str
    answer: str
    level: str | None = Field(None, description=f"The {LEVEL_PROPERTY} the llm stage assigned, if any")


class QaResponse(BaseModel):
    method: Method = Field(description="The stage that produced the pairs; llm falls back to rule-based")
    topic: str | None = Field(None, description="The resolved topic, when one was asked for")
    resolution: Resolution | None = None
    node: NodeInput | None = Field(None, description="The node the topic came from (node_id)")
    chars: int = Field(description="Characters of the text the pairs were made from")
    pairs: list[Pair]
    note: str | None = Field(
        None,
        description="What a reader should know about how the pairs came about: why the LLM did not write them, "
        "or that the spaCy model for checking the question subjects is missing",
    )
