"""Request model shared by API and CLI."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import WithJsonSchema

Part = Literal["world", "curricula", "collection"]
# The matching strategies of app/matching/registry.py (STRATEGIES; a test keeps both lists equal). The field stays a
# plain string with the list as its schema: /docs shows the values, and the service still answers an unknown name
# with its own German 422 instead of the validator's English one.
MATCHERS = ("hybrid_light", "bm25", "char_tfidf", "lexicon_only", "llm")
MatcherName = Annotated[str, WithJsonSchema({"type": "string", "enum": list(MATCHERS)})]
# One help text for every endpoint that chooses articles (compendium, knowledge); numbers: docs/entwicklung, M9-M13
ARTICLE_CHOICE_HELP = (
    "Who chooses the articles of the topic. Default: the profile's (preset, else PRESET_DEFAULT): llm-free takes "
    "rule-based, every other profile llm.\n\n"
    "- **rule-based**: the rules alone - exact title, the disambiguation page decided by the words of the subject, "
    "inflected forms and genitive phrases, then title suggestions and full-text hits. They say how sure they are "
    "(resolution.method, resolution.confident). No tokens, no extra time.\n"
    "- **llm**: the rules first; where they are unsure, the LLM of the b-api chooses among their candidates or names "
    "a Wikipedia title, and it drops the side articles of the corpus - full-text hits and linked sub-articles - that "
    "do not fit the topic. Measured on 2026-09-24: main article right in 57 instead of 55 of 59 queries and in 11 "
    "instead of 9 of 12 held back. Per compendium in the median about 930 tokens and 1.7 s more (90th percentile "
    "3.4 s), when the model checked the full-text hits alone: that took 1.4 s, an unsure article another 1 to 2.6 s. "
    "These numbers are gpt-5.6-luna's; the default gpt-6-luna (D44) chose 90 instead of 91 of 94 and takes a quarter "
    "to three quarters longer per call (M19). Since 2026-09-25 (M25, gpt-6-luna) the check covers the linked "
    "sub-articles too: over 20 topics 5 printed paragraphs from unfit articles were left instead of 12 without the "
    "LLM and 17 with the full-text hits checked alone, and it runs for 20 instead of 15 of those topics, at about "
    "750 tokens per call.\n\n"
    "For a material without a topic (node_id), llm lets the LLM name the article from title, subjects, keywords and "
    "description - 30 of 31 materials right at about 440 tokens, against 15 of 31 by the rules (M23, D47). Either "
    "way, full-text hits without a link to or from the main article stay out of the corpus (M25). llm without a "
    "configured LLM (LLM_ENABLED, B_API_KEY) is a 503; when the b-api is not available for now the rules choose, "
    "and audit.llm.article_choice says why."
)
MATCHER_HELP = (
    "How the paragraphs find their block of the template. Default: the profile's: llm-free and balanced take "
    "hybrid_light, best-quality and best-quality-generated llm. Quality is the "
    "macro-F1 over the ten content blocks at the gold standard (eval/gold); times are for part 1 of one compendium, "
    "measured on 2026-09-24.\n\n"
    "- **hybrid_light** (default): heading lexicon, BM25 and character TF-IDF together, plus Model2Vec vectors when "
    "MODEL2VEC_PATH is set; the policy then decides per paragraph. 0.43, the matching takes about 0.3 s, no tokens.\n"
    "- **bm25**: Okapi BM25 alone. 0.36, under 0.1 s.\n"
    "- **char_tfidf**: character TF-IDF, which carries German compounds. 0.40, about 0.25 s.\n"
    "- **lexicon_only**: the heading lexicon without a ranker; a paragraph only gets a block its heading names. "
    "0.35, under 0.1 s.\n"
    "- **llm**: the LLM of the b-api assigns every paragraph to a block or to none, 50 paragraphs of 400 characters "
    "per call. 0.69 and 0.72 in two runs, about 180 tokens per paragraph and 34 500 per compendium; part 1 took "
    "12.0 and 22.7 s instead of 1.2 and 1.8 s in the median of two measurements, the b-api answering at different "
    "speeds. Where the model gives no answer, or the b-api is not available for now, hybrid_light decides; "
    "without a configured LLM the request is a 503. At the "
    "default LLM_MAX_TOKENS_PER_REQUEST of 60 000 four batches run at once and the others wait for them, so topics "
    "of more than 200 paragraphs take a second round. These numbers are gpt-5.6-luna's; the default gpt-6-luna "
    "(D44) reached 0.70 and takes a quarter to three quarters longer per call (M19).\n\n"
    "An unknown name is a 422. GET /api/v2/matching/strategies lists the same strategies."
)
EXTRACTION_HELP = (
    "Who picks the passages of part 1. Default: the profile's, rule-based in all four.\n\n"
    "- **rule-based**: the paragraphs the matching assigned, their first sentences.\n"
    "- **llm**: the LLM chooses sentences by number among the best candidates of every block; the wording stays the "
    "source's. Measured for one topic (Optik) on 2026-09-19: 10 calls, about 16 500 tokens and 11 s.\n\n"
    "llm without a configured LLM is a 503; when the b-api is not available for now it falls back to rule-based."
)
GENERATION_HELP = (
    "Who writes the blocks of part 1. Default: the profile's: llm in best-quality-generated, rule-based in the "
    "others.\n\n"
    "- **rule-based**: verbatim excerpts, every paragraph with its citation number.\n"
    "- **llm-fast**: the LLM writes the blocks of LLM_FAST_SECTIONS from their evidence; measured on 2026-09-18 for "
    "four topics: 2 to 3 calls, 2 300 to 4 000 tokens, 9 to 15 s.\n"
    "- **llm**: the LLM writes every content block; 8 to 10 calls, 10 500 to 14 500 tokens, 16 to 20 s.\n\n"
    "Every written sentence needs a valid citation. llm-fast and llm without a configured LLM are a 503; when the "
    "b-api is not available for now it falls back to rule-based."
)
ENRICHMENT_HELP = (
    "Whether the writing LLM may add knowledge of its own beyond the sources. Default: the profile's: "
    "model-knowledge in best-quality-generated, sources-only in the others.\n\n"
    "- **sources-only**: every sentence has to be covered by its evidence; anything else is dropped.\n"
    "- **model-knowledge**: the model may add knowledge of its own; such sentences carry no citation number, are "
    "marked in the text as Evidenzgrad=Modellwissen and counted per block.\n\n"
    "Needs generation llm or llm-fast; with rule-based generation, or without a usable b-api, the answer reports "
    "sources-only."
)
PRESET_HELP = (
    "The profile of docs/entwicklung/07-entscheidungsvorlage.md (D41, D53). It sets article_choice, matcher, "
    "extraction, generation and enrichment; a switch the request sets itself wins. Without a preset the server's "
    "profile applies (PRESET_DEFAULT, shipped balanced). Every profile but llm-free needs an LLM (LLM_ENABLED, "
    "B_API_KEY); on a server without one such a request is a 503 that says so. Numbers: gold standard and "
    "measurements of "
    "2026-09-24 with gpt-5.6-luna; the default gpt-6-luna (D44) chose 90 of 94 and takes a quarter to "
    "three quarters longer per call (M19).\n\n"
    "- **llm-free**: the rules choose the articles, hybrid_light assigns the paragraphs, the text stays verbatim. "
    "Main article right in 86 of 94 gold queries, macro-F1 0.43, part 1 in about 1.4 s, no tokens. Full-text hits "
    "without a link to or from the main article stay out: 12 instead of 25 printed paragraphs from unfit articles "
    "over 20 topics (M25).\n"
    "- **balanced**: as llm-free, but the LLM decides where the rules are unsure about the article and drops the "
    "side articles that do not fit (article_choice llm). 91 of 94, 5 instead of 12 printed paragraphs from unfit "
    "articles over 20 topics (M25), macro-F1 0.43; about 1.7 s and 930 tokens more when it checked the full-text "
    "hits alone, and the check of the side articles now runs for 20 instead of 15 of those topics at about 750 "
    "tokens. For a material without a topic the LLM names the article: 30 instead of 15 of 31 right (D47).\n"
    "- **best-quality**: balanced plus the LLM assigning every paragraph (matcher llm). 91 of 94, macro-F1 0.69 "
    "to 0.72; part 1 about 14 to 24 s and about 35 400 tokens. Topics of more than 200 paragraphs take a second "
    "round of calls at LLM_MAX_TOKENS_PER_REQUEST 60 000; about 100 000 avoids it.\n"
    "- **best-quality-generated**: best-quality plus the LLM writing every block (generation llm), which may add "
    "knowledge of its own, marked as Evidenzgrad=Modellwissen and without a citation number (enrichment "
    "model-knowledge). For text people read directly. The writing alone took 16 to 20 s and 10 500 to 14 500 tokens "
    "with gpt-5.6-luna on four topics (2026-09-18).\n\n"
    "When the b-api is not available for now, the LLM steps fall back to the rules and audit.llm says why."
)
Extraction = Literal["rule-based", "llm"]  # who picks the sentences of part 1 (PLAN.md 4.7, D33)
Generation = Literal["rule-based", "llm-fast", "llm"]  # who writes the blocks of part 1 (PLAN.md 4.7, D33)
# Whether the writing LLM may go beyond the sources (docs/umbau.md U4); without an LLM writing, it cannot
Enrichment = Literal["sources-only", "model-knowledge"]
ArticleChoice = Literal["rule-based", "llm"]  # who decides an unsure article choice (D35)
Preset = Literal["llm-free", "balanced", "best-quality", "best-quality-generated"]  # the four profiles (D41, D53)
_VERBATIM = {"extraction": "rule-based", "generation": "rule-based", "enrichment": "sources-only"}
PRESETS: dict[str, dict[str, str]] = {  # the switches each preset sets, in the order of Preset
    "llm-free": {"article_choice": "rule-based", "matcher": "hybrid_light", **_VERBATIM},
    "balanced": {"article_choice": "llm", "matcher": "hybrid_light", **_VERBATIM},
    "best-quality": {"article_choice": "llm", "matcher": "llm", **_VERBATIM},
    # Jan, 2026-09-25: everything by the LLM, the text completed from its own knowledge and rewritten to read well;
    # extraction stays rule-based, which brought no gain at the gold standard (decision paper, step 4)
    "best-quality-generated": {
        "article_choice": "llm",
        "matcher": "llm",
        "extraction": "rule-based",
        "generation": "llm",
        "enrichment": "model-knowledge",
    },
}
UNKNOWN_SUBJECT_HELP = (
    "; one outside the two subject vocabularies of edu-sharing (school subjects, Destatis university subjects; "
    "config/vocabs) is a 422 that lists the school subjects"
)
NODE_ID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _default_parts() -> list[Part]:
    return ["world", "curricula", "collection"]


NODE_ID_HELP = (
    "A material or collection of an edu-sharing repository (D45), read without credentials, so only what is public. "
    "A collection's title becomes the topic. A material's title often names a format ('Stationsarbeit zur Optik'), "
    "so its article comes from its title and description (D47): without the LLM the rules take the title's article "
    "when the terms of title and description name it too, else the first term when the title names it, else none - "
    "a 404 that asks for a topic. On 31 real materials that was 15 right, 8 wrong and 8 without an article, against "
    "5, 13 and 13 with the title as the topic (M23). With article_choice llm the LLM names the article from title, "
    "subjects, keywords and description instead: 30 of 31 right, about 440 tokens. A topic sent along leads: the "
    "material then adds its own article as a source (origin node) when it links with the main article, and with "
    "article_choice llm one question hears topic and material together and may overrule the topic. The subjects "
    "count all alike - subjects and levels are multi-valued fields, and no value weighs more for coming first - and "
    "levels and keywords become context words; a subject sent along wins, and so does one the title names "
    "('Physik: Optik'). GET /api/v2/nodes/{node_id} shows beforehand what a node brings. Unknown or not public: 404."
)
REPOSITORY_HELP = (
    "The repository of node_id, e.g. https://repository.staging.openeduhub.net/edu-sharing/rest; default: the "
    "configured one (EDU_SHARING_BASE_URL), and without one a 503. Only allowed hosts over https "
    "(EDU_SHARING_REPOSITORIES), anything else is a 422; a repository that fails is a 502."
)


class GenerateRequest(BaseModel):
    """``topic``, ``collection_id`` or ``node_id`` is required; a topic sent along wins (PLAN.md 4.2, D12, D45)."""

    model_config = ConfigDict(extra="forbid")  # a field the service does not know is a 422, not a silent miss

    topic: str | None = Field(
        None,
        min_length=1,
        max_length=300,
        description="Topic; default: the article of node_id (for a material from its title and description, D47), "
        "else the title of collection_id",
    )
    collection_id: str | None = Field(
        None,
        pattern=NODE_ID_PATTERN,
        description="edu-sharing collection for part 3; its title is the topic without topic and node_id, its levels "
        "add context words, its subjects count, all alike, where no other is given",
    )
    knowledge_collection_id: str | None = Field(
        None,
        pattern=NODE_ID_PATTERN,
        description="Collection whose reusable materials feed part 1 as sources, so parts has to hold world (else a "
        "422); an unknown one is a 404, as for collection_id, while a failing repository only shows in "
        "audit.knowledge",
    )
    node_id: str | None = Field(None, pattern=NODE_ID_PATTERN, description=NODE_ID_HELP)
    repository: str | None = Field(None, max_length=300, description=REPOSITORY_HELP)
    parts: list[Part] = Field(
        default_factory=_default_parts,
        min_length=1,
        description="Parts to generate: world (part 1), curricula (part 2), collection (part 3, needs collection_id)",
    )
    subject: str | None = Field(
        None,
        max_length=100,
        description="Subject for part 2: WLO discipline id, vocabulary URI, label or alias" + UNKNOWN_SUBJECT_HELP,
    )
    language: str = Field("de", pattern="^de$", description="Only 'de' today; any other value is a 422")
    template_id: str | None = Field(None, description="Template id; default from settings")
    preset: Preset | None = Field(None, description=PRESET_HELP)
    matcher: MatcherName | None = Field(None, description=MATCHER_HELP)
    article_choice: ArticleChoice | None = Field(None, description=ARTICLE_CHOICE_HELP)
    extraction: Extraction | None = Field(None, description=EXTRACTION_HELP)
    generation: Generation | None = Field(None, description=GENERATION_HELP)
    enrichment: Enrichment | None = Field(None, description=ENRICHMENT_HELP)
    target_length: int = Field(
        12_000,
        ge=2_000,
        le=60_000,
        description="Steers the length of part 1: the value is shared over the content blocks by "
        "weight, and a block stops at a paragraph boundary once it holds one and a half times its "
        "share. It is a steer, not a cap - a block is never shorter than its first paragraph, so a "
        "small value does not make a small compendium. Measured for one topic on 2026-09-21: 2 000 "
        "gave 25 784 characters, 12 000 gave 32 523, and from 20 000 on nothing grew because the "
        "sources were exhausted - more sources raise that ceiling",
    )
    empty_slot_policy: Literal["omit", "note"] | None = Field(
        None,
        description="What happens to a block the corpus has nothing for, overriding the template: "
        "omit leaves it out of the document, note keeps the heading and says the sources carry "
        "nothing about it",
    )
    existing_markdown: str | None = Field(
        None,
        max_length=2_000_000,
        description="An earlier compendium: blocks marked redaktionell-geprüft are kept word for word",
    )
    regenerate_sections: list[str] | None = Field(
        None,
        description="With an earlier compendium (existing_markdown): only these blocks are made anew, every other "
        "one is kept. Blocks are named by their id, as the markers of the document name them (sc26_3); a name the "
        "template does not have is a 422 that lists its blocks, and so is the field without existing_markdown",
    )
    facets_visible: bool | None = Field(None, description="Override FACETS_VISIBLE")
    frontmatter_in_markdown: bool = Field(
        True,
        description="Whether the markdown opens with the YAML frontmatter. It carries the AI Act "
        "disclosure, the review status and the snapshot of the archives, so a document meant to stand "
        "on its own keeps it. Off starts the text at the heading; the frontmatter field of the answer "
        "holds the same data either way",
    )
    max_articles: int | None = Field(
        None,
        ge=1,
        le=50,
        description="Articles the corpus may hold; default CORPUS_MAX_ARTICLES. Topic and twin are always in",
    )

    @model_validator(mode="before")
    @classmethod
    def _no_mode(cls, data: Any) -> Any:
        # An unknown field is a 422 anyway; the former mode gets its own message, which says what replaced it
        if isinstance(data, dict) and "mode" in data:
            raise ValueError("mode gibt es nicht mehr: extraction und generation ersetzen es (PLAN.md D33)")
        return data

    @model_validator(mode="after")
    def _preset_fills_the_open_switches(self) -> GenerateRequest:
        # A switch the request sets wins; the preset only fills what it left open (D41)
        if self.preset:
            for name, value in PRESETS[self.preset].items():
                if getattr(self, name) is None:
                    setattr(self, name, value)
        return self

    @model_validator(mode="after")
    def _topic_or_collection(self) -> GenerateRequest:
        if not self.topic and not self.collection_id and not self.node_id:
            raise ValueError("topic, collection_id oder node_id ist erforderlich")
        if self.repository and not self.node_id:
            raise ValueError("repository gilt für node_id; ohne node_id fehlt der Knoten")
        if self.regenerate_sections is not None and not self.existing_markdown:
            raise ValueError("regenerate_sections gilt für existing_markdown; ohne den früheren Text bleibt nichts")
        if self.knowledge_collection_id and "world" not in self.parts:
            raise ValueError("knowledge_collection_id speist Teil 1; ohne world in parts bliebe sie ungelesen")
        # Without a collection part 3 drops out (as with the default parts); it must not be the only part
        if not self.collection_id and not {"world", "curricula"} & set(self.parts):
            raise ValueError("parts enthält nur collection; Teil 3 braucht collection_id")
        return self


def with_profile(request: GenerateRequest, default: Preset) -> GenerateRequest:
    """The request with every switch set: by its own preset (the validator did that) or else by the server's
    profile (PRESET_DEFAULT, D53); a switch the request set itself stays."""
    if request.preset is not None:
        return request
    filled = {name: value for name, value in PRESETS[default].items() if getattr(request, name) is None}
    return request.model_copy(update={"preset": default, **filled})
