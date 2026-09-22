"""What POST /api/v2/qa accepts and answers with - the wire contract, and nothing that acts on it.

Split out of app/api/v2/qa.py so the endpoint module can be read as one thing. The contract changes for
its own reasons (a new field, a new bound, a clearer help text) and those reasons have nothing to do
with which stage produced the pairs, which is why the two live apart.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.models import Resolution

Method = Literal["rule-based", "models", "llm"]
LEVEL_PROPERTY = "Bildungsstufe"  # the one level vocabulary the project owns (config/facets.yaml)
MAX_TEXT_CHARS = 50_000  # bounds the request body and the text a topic yields; both end up in the same code


class QaRequest(BaseModel):
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
    method: Method = Field(
        "rule-based",
        description="rule-based needs nothing and is the default; models uses the two German models baked "
        "into the image (question generator plus extractive answers); llm lets the b-api write the pairs. "
        "Both fall back to rule-based when they cannot run, and note says why",
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
        "other stages return the pairs without a level and say so in note",
    )

    @model_validator(mode="after")
    def _text_or_topic(self) -> QaRequest:
        if not self.text and not self.topic:
            raise ValueError("text oder topic ist erforderlich")
        return self


class Pair(BaseModel):
    question: str
    answer: str
    level: str | None = Field(None, description=f"The {LEVEL_PROPERTY} the llm stage assigned, if any")


class QaResponse(BaseModel):
    method: Method = Field(description="The stage that produced the pairs; llm falls back to rule-based")
    topic: str | None = Field(None, description="The resolved topic, when one was asked for")
    resolution: Resolution | None = None
    chars: int = Field(description="Characters of the text the pairs were made from")
    pairs: list[Pair]
    note: str | None = Field(
        None,
        description="What a reader should know about how the pairs came about: why the LLM did not write them, "
        "or that the spaCy model for checking the question subjects is missing",
    )
