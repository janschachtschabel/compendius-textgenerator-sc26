"""Request model shared by API and CLI."""

from __future__ import annotations

from typing import Annotated, Any, Literal, get_args

from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import WithJsonSchema

from app.domain.caller_values import NAMED, listed
from app.domain.spelling import OneSpelling
from app.templates.schema import MAX_SLOTS, SLOT_ID_MAX_CHARS, TEMPLATE_ID_PATTERN

Part = Literal["world", "curricula", "collection"]
# The matching strategies of app/matching/registry.py (STRATEGIES; a test keeps both lists equal). The field stays a
# plain string with the list as its schema: /docs shows the values, and the service still answers an unknown name
# with its own German 422 instead of the validator's English one.
MATCHERS = ("hybrid_light", "bm25", "char_tfidf", "lexicon_only", "llm")
# Archives a request may name, and the length of one name (audit 2026-09-28, SE-15): the largest ZIM profile
# subscribes four, and an id is the stem of a Kiwix file name such as wikipedia_de_all_nopic_2026-01
MAX_ARCHIVES = 20
ARCHIVE_ID_MAX_CHARS = 100
MATCHER_MAX_CHARS = 40  # the longest strategy name has 12 characters
EXISTING_MARKDOWN_MAX_CHARS = 2_000_000  # the largest field of any request; app/api/body_limit.py sizes to it
MatcherName = Annotated[
    str, Field(max_length=MATCHER_MAX_CHARS), WithJsonSchema({"type": "string", "enum": list(MATCHERS)})
]
ArchiveId = Annotated[str, Field(max_length=ARCHIVE_ID_MAX_CHARS)]
BlockId = Annotated[str, Field(max_length=SLOT_ID_MAX_CHARS)]
# One help text for every endpoint that chooses articles (compendium, knowledge); numbers: docs/entwicklung, M9-M13
ARTICLE_CHOICE_HELP = (
    "Who chooses the articles of the topic. Default: the profile's (preset, else PRESET_DEFAULT): llm-free takes "
    "rule-based, balanced llm, best-quality, best-quality-generated and best-coverage-generated llm-thorough.\n\n"
    "- **rule-based**: the rules alone - exact title, the disambiguation page decided by the words of the subject, "
    "inflected forms and genitive phrases, then title suggestions and full-text hits. They say how sure they are "
    "(resolution.method, resolution.confident). No tokens, no extra time.\n"
    "- **llm**: the LLM of the b-api names the overview article of the topic and up to eight articles on its most "
    "important members, parts or aspects (D63); it hears the subject of the request too. The ones the archive has are "
    "the side articles of the corpus instead of the linked sub-articles and full-text hits, and the overview - where "
    "the archive lacks it, the first part found, as measured - replaces the rules' article where the rules missed the "
    "topic: a title suggestion, a full-text hit, a list page. On 25 set-like topics ('deutsche Dichter') "
    "87 instead of 45 % of the printed paragraphs came from fitting articles, on 20 ordinary topics 93 instead of 73 % "
    "(M37, measured again through the service as M39); the question costs about 3.6 s and 480 tokens, the check of "
    "the side articles no longer runs. Without a usable answer, or without a part the archive has, the side articles "
    "of before stay. With a topic and a material the question on both names the article, this one the parts. Where "
    "the rules are unsure otherwise, the LLM chooses among their candidates or names a Wikipedia title, and it drops "
    "the side articles of before that do not fit the topic. Measured on 2026-09-24: main article right in 57 instead "
    "of 55 of 59 queries and in 11 "
    "instead of 9 of 12 held back. Per compendium in the median about 930 tokens and 1.7 s more (90th percentile "
    "3.4 s), when the model checked the full-text hits alone: that took 1.4 s, an unsure article another 1 to 2.6 s. "
    "These numbers are gpt-5.6-luna's; the default gpt-6-luna (D44) chose 90 instead of 91 of 94 and takes a quarter "
    "to three quarters longer per call (M19). Since 2026-09-25 (M25, gpt-6-luna) the check covers the linked "
    "sub-articles too: over 20 topics 5 printed paragraphs from unfit articles were left instead of 12 without the "
    "LLM and 17 with the full-text hits checked alone, and it runs for 20 instead of 15 of those topics, at about "
    "750 tokens per call.\n"
    "- **llm-thorough**: as llm, and the LLM also checks a sure choice of a word with several meanings: a meaning the "
    "rules took from a disambiguation page, or an exact title that has a '(Begriffsklärung)' page (D61). Measured "
    "on 2026-09-26 with gpt-6-luna (M35): main article right in 93 instead of 91 of 94 queries, none of the 44 right "
    "sure choices it checked turned wrong; the model is asked for 64 instead of 18 of the 94, each new question "
    "about 800 tokens and 1 s.\n\n"
    "For a material without a topic (node_id), llm lets the LLM name the article from title, subjects, keywords and "
    "description - 30 of 31 materials right at about 440 tokens, against 15 of 31 by the rules (M23, D47). Either "
    "way, full-text hits without a link to or from the main article stay out of the corpus (M25). llm without a "
    "configured LLM (LLM_ENABLED, B_API_KEY) is a 503; when the b-api is not available for now the rules choose, "
    "and audit.llm.article_choice says why."
)
MATCHER_HELP = (
    "How the paragraphs find their block of the template. Default: the profile's: llm-free and balanced take "
    "hybrid_light, best-quality, best-quality-generated and best-coverage-generated llm. Quality is the "
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
    "without a configured LLM the request is a 503. At LLM_MAX_TOKENS_PER_REQUEST 60 000 four batches run at "
    "once and the others wait for them, so topics of more than 200 paragraphs take a second round; the three "
    "best-* profiles, which choose llm, spend from 180,000 (D59) and leave room for about three times as many. "
    "These numbers are gpt-5.6-luna's; the default gpt-6-luna "
    "(D44) reached 0.70 and takes a quarter to three quarters longer per call (M19).\n\n"
    "An unknown name is a 422. GET /api/v2/matching/strategies lists the same strategies."
)
EXTRACTION_HELP = (
    "Who picks the passages of part 1. Default: the profile's, rule-based in all five.\n\n"
    "- **rule-based**: the paragraphs the matching assigned, their first sentences.\n"
    "- **llm**: the LLM chooses sentences by number among the best candidates of every block; the wording stays the "
    "source's. Measured for one topic (Optik) on 2026-09-19: 10 calls, about 16 500 tokens and 11 s.\n\n"
    "llm without a configured LLM is a 503; when the b-api is not available for now it falls back to rule-based."
)
GENERATION_HELP = (
    "Who writes the blocks of part 1. Default: the profile's: llm in best-quality-generated and "
    "best-coverage-generated, rule-based in the others.\n\n"
    "- **rule-based**: verbatim excerpts, every paragraph with its citation number.\n"
    "- **llm-fast**: the LLM writes the blocks of LLM_FAST_SECTIONS from their evidence; measured on 2026-09-18 for "
    "four topics: 2 to 3 calls, 2 300 to 4 000 tokens, 9 to 15 s.\n"
    "- **llm**: the LLM writes every content block; 8 to 10 calls, 10 500 to 14 500 tokens, 16 to 20 s.\n\n"
    "Every written sentence needs a valid citation, unless enrichment lets the model add knowledge of its own, marked "
    "as model knowledge. The LLM writes about the topic as asked, not about the article it resolved to, and the "
    "heading names that topic (D72). Where the topic is a text - more than six words or 60 characters, a sentence or a "
    "question - or a node_id or collection_id without a topic stands in for it, the model first words the topic "
    "from it (prompt topic_wording, audit.llm.topic_wording): close to its words and with its aspect, a node or "
    "collection sent along with a topic showing how the topic is meant; without a usable answer the topic stays as "
    "asked (for a material: its article, for a collection: its title). "
    "llm-fast and llm without a configured LLM are a 503; when the "
    "b-api is not available for now it falls back to rule-based."
)
CURRICULUM_CHECK_HELP = (
    "Who judges the curriculum elements part 2 found (D58). Default: the profile's: rule-based in llm-free and "
    "balanced, llm in best-quality, best-quality-generated and best-coverage-generated. Acts only when parts holds "
    "curricula.\n\n"
    "- **rule-based**: the keyword rules alone (M22). An element that names the topic only in its heading is counted "
    "with its area instead of being listed. No tokens. Over the 20 topics of M22, 70 to 81 % of the listed elements "
    "fit and 5 to 9 % do not; a quarter of the fitting ones stand only in a bundle line (M32).\n"
    "- **llm**: the LLM of the b-api reads every element the rules found, with its area and curriculum, and rates it: "
    "fits, touches the topic, does not fit. What does not fit leaves part 2; an element only its heading names stands "
    "on its own when the model rates it fitting. 74 to 79 % of the listed elements fit, 5 to 9 % do not, and no "
    "element two raters called fitting was dropped (M32). About 75 to 80 tokens per element: in the median 7,800 to "
    "9,600 tokens and 6 s more per compendium. It spends from the budget of the request: in the three best-* "
    "profiles 180,000 tokens (LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY, D59): on the widest topic of M32, "
    "Demokratie without a subject, all 819 elements next to matcher llm on its 382 paragraphs and next to the "
    "writing of best-quality-generated (M33); set on its own in llm-free or balanced it spends from 60,000 "
    "(LLM_MAX_TOKENS_PER_REQUEST). "
    "What the budget leaves unrated keeps the rules' decision. Needs LLM_ENABLED, else "
    "the request is a 503; while the b-api is not available the rules decide and audit.llm.curriculum_check "
    "says why."
)
ENRICHMENT_HELP = (
    "Whether the writing LLM may add knowledge of its own beyond the sources. Default: the profile's: "
    "model-knowledge in best-quality-generated, model-knowledge-full in best-coverage-generated, sources-only in the "
    "others.\n\n"
    "- **sources-only**: every sentence has to be covered by its evidence; anything else is dropped.\n"
    "- **model-knowledge**: the model may add knowledge of its own - a checkable fact or nothing (prompt "
    "section_enrichment v4, D56; up to half of a block's sentences since D70); such sentences carry no citation "
    "number, are marked Evidenzgrad=Modellwissen in the markup - with model_knowledge_label they also end with the "
    "visible label [Modellwissen] (D76) - and are counted per block. Since D72 a block the "
    "sources have nothing for is written from the model's knowledge as well, every sentence marked, and since "
    "2026-10-02 so is one whose written text cites none of its evidence, instead of falling back to verbatim "
    "paragraphs.\n"
    "- **model-knowledge-full**: every content block is written about the topic as asked, qualifiers included "
    "('Ernährung im Leistungssport', not its article 'Ernährung'): evidence where it meets the topic, model knowledge "
    "for the rest, a block without evidence as well (prompt section_coverage, D69). Marked like model-knowledge; the "
    "target length is a floor, not a ceiling, and the heading names the topic as asked.\n\n"
    "Needs generation llm or llm-fast; with rule-based generation, or without a usable b-api, the answer reports "
    "sources-only."
)
MODEL_KNOWLEDGE_CHECK_HELP = (
    "Whether the LLM checks the sentences of model knowledge it wrote (07, point 12a, D73). Default: the profile's: "
    "rule-based in every profile (D74).\n\n"
    "- **rule-based**: no check; the sentences stay as written, marked as model knowledge.\n"
    "- **llm**: after a block is written, a second call reads its sentences marked as model knowledge, with the block "
    "around them, and strikes what it holds for wrong or invented or corrects it where it knows the right fact for "
    "sure - dates, numbers, names, places, bodies, laws and attributions, where M48 found six of the eight light "
    "errors of best-coverage-generated (prompt model_knowledge_check). A corrected sentence keeps its mark; a block "
    "of model knowledge alone that loses every sentence falls back to the rules: verbatim paragraphs where it has "
    "evidence, else it stays empty. audit.llm.model_knowledge_check "
    "counts what the check read, struck and corrected. One call per block with model knowledge, in parallel. "
    "Measured in best-coverage-generated on nine topics, the same runs before and after the check, two blind judges "
    "(M53): light errors per text 1.1 instead of 1.6, fit, use and completeness unchanged, readability 3.9 instead "
    "of 4.0, the one serious error kept; of 2,419 sentences 17 struck and 14 corrected, every correction right "
    "afterwards, but most struck sentences were right or unclear to the judges; about 27,000 tokens and 5 s more "
    "per text. Too little for its cost to switch it on in a profile (Jan, D74).\n\n"
    "Acts only where the LLM writes with enrichment model-knowledge or model-knowledge-full; without a usable b-api "
    "the sentences stay unchecked and the audit says why."
)
PRESET_HELP = (
    "The profile of docs/entwicklung/07-entscheidungsvorlage.md (D41, D53, D58, D69). It sets article_choice, matcher, "
    "extraction, generation, enrichment, model_knowledge_check and curriculum_check; a switch the request sets itself "
    "wins. Without a preset "
    "the server's profile applies (PRESET_DEFAULT, shipped best-quality-generated; llm-free on a server without an "
    "LLM, D68). Every "
    "profile but llm-free needs an LLM (LLM_ENABLED, B_API_KEY); on a server without one a request that names such a "
    "profile is a 503 that says so. Numbers: gold standard "
    "and measurements with gpt-6-luna (M19, M25, M27 to M35, M39, M52); times for part 1 and 2 of one compendium on "
    "the development machine, those of M52 for part 1 at the 30,000 target characters of D70. M52 graded the five "
    "profiles as they run since D72 on nine topics of three kinds: with an article of their own ('Optik'), a group "
    "without one ('Dichter aus dem Mittelalter') and a topic with an aspect ('OER-Förderungen'), two blind judges, "
    "1 to 5. In every "
    "profile the prompts hear the topic as asked, not the article it resolved to (D72), and the heading and topic of "
    "the answer name it (D75); the searches in the archives and the curricula keep the article (resolution).\n\n"
    "- **llm-free**: the rules choose the articles, hybrid_light assigns the paragraphs, the text stays verbatim. "
    "Main article right in 87 of 94 gold queries (M35), macro-F1 0.45 at the labelled paragraphs, about 1.6 s, "
    "no tokens. "
    "Full-text hits without a link to or from the main article stay out: 12 instead of 25 printed paragraphs from "
    "unfit articles over 20 topics (M25). /qa asks with the rules from the spaCy parse, the glossary and the actors "
    "filling up: 58 of 95 pairs flawless for both of two judges since D60 (M34; 48 of 96 before, M30), 0.3 s per "
    "text. Part 2 by the keyword rules, an element only its heading names counted "
    "with its area: 70 to 81 % of the listed elements fit (M32). Fit 3.0 for a topic with an article of its own, "
    "1.5 for a group, 1.0 for an aspect; part 1 1.7 s (M52).\n"
    "- **balanced**: as llm-free, but the LLM names the overview article and the parts of every topic, "
    "which become its side articles, and decides where the rules are unsure about the article (article_choice llm, "
    "D63). Of the printed paragraphs 87 instead of 43 % came from fitting articles on 25 set-like topics such as "
    "'deutsche Dichter', 93 instead of 71 % on 20 ordinary ones (M39). 91 of 94 main articles right as before "
    "('Lichtlehre' now Optik, 'Ursachen des Ersten Weltkriegs' now Julikrise, M39); about 4.2 s for part 1 and 2 "
    "and 480 tokens. The gold of the matching no longer covers it: 243 of its 643 labels sit on side articles the "
    "named ones replace (M39; macro-F1 0.45 as llm-free before D63). For a material without a topic the LLM names "
    "the article: 30 instead of 15 of 31 right (D47). /qa and the check of part 2 as llm-free (D57, D58). Fit 3.7 "
    "for a topic with an article of its own, 2.8 for a group, 1.2 for an aspect; part 1 5.0 s and 530 tokens "
    "(M52).\n"
    "- **best-quality**: balanced plus the LLM checking the sure choice of a word with several meanings too "
    "(article_choice llm-thorough, D61) and assigning every paragraph (matcher llm). 93 of 94 (M35, as before with "
    "the question of D63), macro-F1 0.70 before D63; "
    "about 14 s and 26 000 tokens, about 170 per paragraph; a checked word adds about 800 tokens and 1 s. Its "
    "requests spend from 180,000 tokens "
    "(LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY, D59) instead of the 60,000 of the others, at which topics of more "
    "than 200 paragraphs took a second round of calls. /qa lets the LLM write the pairs: 99 of "
    "120 flawless, about 2 400 tokens per text (M30). The LLM also checks the curriculum elements of part 2 "
    "(curriculum_check llm): 74 to 79 % fit, none fitting dropped, about 6 s and 8,000 to 10,000 tokens more (M32). "
    "Fit 4.2 for a topic with an article of its own, 3.8 for a group, 1.7 for an aspect; part 1 16 s and 59,900 "
    "tokens, most of them for the matching (M52).\n"
    "- **best-quality-generated** (default): best-quality plus the LLM writing every block (generation llm), which "
    "may add knowledge of its own for up to half of a block's sentences (D70), marked as model knowledge and without a "
    "citation number (enrichment model-knowledge). For text people read directly. Two blind judges preferred its "
    "text in 11 of 12 "
    "ratings (readability 4.0 instead of 2.5 of 5); under the first prompt two thirds of the added model knowledge "
    "were filler sentences (M28); the second asks for a checkable fact or nothing (D56) and added 50 instead of 82 "
    "such sentences over six topics, 13 instead of 50 of them fillers (M31). /qa and part 2 as best-quality. Since "
    "D72 it writes about the topic as asked and fills a block the sources have nothing for from the model's "
    "knowledge, marked; a topic that is a text, or a node_id or collection_id without a topic, is worded by the "
    "model first. Fit 4.8 for a topic with an article of its own, 4.7 for a group, 4.2 for an aspect, use 4.1, "
    "completeness 4.2, readability 3.9, no serious error, 62 % of the text model knowledge; part 1 30 s and 84,000 "
    "tokens (M52). Before D72, writing about the article the choice found and leaving such blocks empty, it kept a "
    "group at 3.0 and an aspect at 1.7 (M48).\n"
    "- **best-coverage-generated** (D69): best-quality-generated, but the LLM writes every content block about the "
    "topic as asked, qualifiers included ('OER-Förderungen', not the article 'Open Educational Resources' it resolves "
    "to), and fills it completely: evidence where it meets the topic, knowledge of its own for the rest and for a "
    "block the sources have nothing for, marked as model knowledge (enrichment model-knowledge-full). target_length is "
    "a floor here, not a ceiling. For topics with an aspect, or where the archives hold little; of all profiles its "
    "text carries the most model knowledge no source covers. On eight topics with an aspect two blind judges rated the "
    "fit to the topic 4.8 instead of 1.8 of 5 for best-quality-generated and the completeness 5.0 instead of 1.7, with "
    "no serious error (M47). Fit 5.0 for a topic with an article of its own, a group and an aspect, use 4.8, "
    "completeness 4.9, readability 4.2, 0.11 serious errors per text, 83 % of the text model knowledge; part 1 38 s "
    "and 103,300 tokens, 60,200 of them read from the prompt cache, and about 59,000 characters, as the target is a "
    "floor (M52). A request can let a second call check its model knowledge (model_knowledge_check llm, M53). /qa "
    "and part 2 as best-quality. A topic that is a text, or a node_id or collection_id without a topic, is worded "
    "by the model first (D72).\n\n"
    "Which to choose (M52): a topic with an article of its own - balanced for a verbatim text with a citation for "
    "every sentence, best-quality-generated for a readable one; a group or a topic with an aspect - "
    "best-coverage-generated (fit 5.0) or, shorter and with less model knowledge, best-quality-generated (4.7 and "
    "4.2), as the verbatim profiles print one member or the umbrella term the article choice finds.\n\n"
    "When the b-api is not available for now, the LLM steps fall back to the rules and audit.llm says why."
)
Extraction = Literal["rule-based", "llm"]  # who picks the sentences of part 1 (PLAN.md 4.7, D33)
Generation = Literal["rule-based", "llm-fast", "llm"]  # who writes the blocks of part 1 (PLAN.md 4.7, D33)
# Whether the writing LLM may go beyond the sources (docs/umbau.md U4); without an LLM writing, it cannot
Enrichment = Literal["sources-only", "model-knowledge", "model-knowledge-full"]
ArticleChoice = Literal["rule-based", "llm", "llm-thorough"]  # who decides an unsure article choice (D35, D61)
LLM_ARTICLE_CHOICES = frozenset({"llm", "llm-thorough"})
CurriculumCheck = Literal["rule-based", "llm"]  # who judges the curriculum elements of part 2 (D58)
# who checks the sentences of model knowledge a writing LLM added (07, point 12a, D73)
ModelKnowledgeCheck = Literal["rule-based", "llm"]
# the five profiles (D41, D53, D69)
Preset = Literal["llm-free", "balanced", "best-quality", "best-quality-generated", "best-coverage-generated"]
_VERBATIM = {
    "extraction": "rule-based",
    "generation": "rule-based",
    "enrichment": "sources-only",
    "model_knowledge_check": "rule-based",
}
PRESETS: dict[str, dict[str, str]] = {  # the switches each preset sets, in the order of Preset
    "llm-free": {
        "article_choice": "rule-based",
        "matcher": "hybrid_light",
        "curriculum_check": "rule-based",
        **_VERBATIM,
    },
    "balanced": {"article_choice": "llm", "matcher": "hybrid_light", "curriculum_check": "rule-based", **_VERBATIM},
    "best-quality": {"article_choice": "llm-thorough", "matcher": "llm", "curriculum_check": "llm", **_VERBATIM},
    # Jan, 2026-09-25: everything by the LLM, the text completed from its own knowledge and rewritten to read well;
    # extraction stays rule-based, which brought no gain at the gold standard (decision paper, step 4)
    "best-quality-generated": {
        "article_choice": "llm-thorough",
        "matcher": "llm",
        "curriculum_check": "llm",
        "extraction": "rule-based",
        "generation": "llm",
        "enrichment": "model-knowledge",
        "model_knowledge_check": "rule-based",
    },
    # Jan, 2026-10-01 (D69): as best-quality-generated, but every block about the topic as asked and filled completely,
    # from the model's own knowledge where the sources say nothing - for topics with an aspect ("OER-Förderungen")
    "best-coverage-generated": {
        "article_choice": "llm-thorough",
        "matcher": "llm",
        "curriculum_check": "llm",
        "extraction": "rule-based",
        "generation": "llm",
        "enrichment": "model-knowledge-full",
        # M53 brought light errors per text from 1.6 to 1.1 for about 27,000 tokens more; Jan: too little (D74)
        "model_knowledge_check": "rule-based",
    },
}
# Their requests spend from LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY instead of LLM_MAX_TOKENS_PER_REQUEST (D59)
BEST_QUALITY_PRESETS = frozenset({"best-quality", "best-quality-generated", "best-coverage-generated"})
# The length of part 1 a profile asks for when the request names none (Jan, 2026-10-01, D70: compendium texts may be
# long and complete); for now the same in every profile
PRESET_TARGET_LENGTH: dict[str, int] = {
    "llm-free": 30_000,
    "balanced": 30_000,
    "best-quality": 30_000,
    "best-quality-generated": 30_000,
    "best-coverage-generated": 30_000,
}


def default_preset(configured: Preset, llm_configured: bool) -> Preset:
    """The profile of a request that names none (D68): PRESET_DEFAULT, shipped best-quality-generated (D82), while an
    LLM is configured, llm-free while none is - so that the service always answers at least with the rules. A profile
    the request names itself is its wish either way, and one that needs the missing LLM is still refused."""
    return configured if llm_configured else "llm-free"


UNKNOWN_SUBJECT_HELP = (
    "; one outside the two subject vocabularies of edu-sharing (school subjects, Destatis university subjects; "
    "config/vocabs) is a 422 that lists the school subjects"
)
NODE_ID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _default_parts() -> list[Part]:
    return ["world", "curricula", "collection"]


def not_blank(value: str | None) -> str | None:
    """A topic of blanks is none: min_length counted them, and " " went on to the archives and came back as a 404
    "Thema in den Archiven nicht gefunden", where a text of blanks is a 422 (audit 2026-09-29, S9)."""
    if value is not None and not value.strip():
        raise ValueError("besteht nur aus Leerraum")
    return value


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
    "('Physik: Optik'). GET /api/v2/nodes/{node_id} shows beforehand what a node brings. Unknown or not public: 404. "
    "In a compendium a collection of the configured repository counts as collection_id as well, where that is empty: "
    "it gets part 3 (D77)."
)
# D77: a collection in node_id stands for collection_id, so either field gives part 3 its collection
PART_3_NEEDS_A_COLLECTION = "Teil 3 braucht eine Sammlung: collection_id oder eine Sammlung als node_id"
REPOSITORY_HELP = (
    "The repository of node_id, e.g. https://repository.staging.openeduhub.net/edu-sharing/rest; default: the "
    "configured one (EDU_SHARING_BASE_URL), and without one a 503. Only allowed hosts over https "
    "(EDU_SHARING_REPOSITORIES), anything else is a 422; a repository that fails is a 502."
)


class RequestModel(OneSpelling):
    """The body of a request: a field the service does not know is a 422, not a silent miss, and its text is read in
    one spelling - umlauts composed, invisible format signs gone (app/domain/spelling.py).

    Up to three unknown fields are named one problem each, where they stand. More are one problem that names three:
    pydantic reported every one on its own, and 1.3 million of them held a worker for 19 s (audit 2026-09-28, SE-15).
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _few_unknown_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            known = cls.model_fields  # a class property of 0.3 us: over a million keys a third of a second
            unknown = [str(key) for key in data if key not in known]
            if len(unknown) > NAMED:
                raise ValueError(f"Unbekannte Felder: {listed(unknown)}")
        return data

    @field_validator("topic", check_fields=False)  # the topic of a compendium, of /knowledge and of /qa
    @classmethod
    def _topic_not_blank(cls, value: str | None) -> str | None:
        return not_blank(value)


class GenerateRequest(RequestModel):
    """``topic``, ``collection_id`` or ``node_id`` is required; a topic sent along wins (PLAN.md 4.2, D12, D45)."""

    VERBATIM_FIELDS = frozenset({"existing_markdown"})  # an earlier compendium keeps its reviewed blocks as they are

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
        "add context words, its subjects count, all alike, where no other is given. A collection given as node_id "
        "counts as collection_id as well, where this field is empty (D77)",
    )
    knowledge_collection_id: str | None = Field(
        None,
        pattern=NODE_ID_PATTERN,
        description="Collection whose materials feed part 1 as sources, whatever their licence (D70), so parts has to "
        "hold world (else a 422); an unknown one is a 404, as for collection_id, while a failing repository only shows "
        "in audit.knowledge. By default a material brings its description; its full text comes with "
        "knowledge_fulltext, the materials of the sub-collections with knowledge_depth. The collection's own "
        "compendium text is never read: this service writes it",
    )
    knowledge_depth: int = Field(
        0,
        ge=0,
        le=5,
        description="How deep the sub-collections of knowledge_collection_id feed part 1 as well (D70): 0 only the "
        "collection's own materials, 1 those of its sub-collections too, and so on; each collection is read once, "
        "each material counts once, KNOWLEDGE_MAX_MATERIALS bounds them all. Needs knowledge_collection_id",
    )
    knowledge_fulltext: bool = Field(
        False,
        description="Read the full text of each material of knowledge_collection_id as well, not only its "
        "description (D70): more knowledge for part 1, and a repository request per material, a few at a time "
        "within the request's time budget. Needs knowledge_collection_id",
    )
    node_id: str | None = Field(None, pattern=NODE_ID_PATTERN, description=NODE_ID_HELP)
    repository: str | None = Field(None, max_length=300, description=REPOSITORY_HELP)
    parts: list[Part] = Field(
        default_factory=_default_parts,
        min_length=1,
        max_length=len(get_args(Part)),
        description="Parts to generate, default all three: world (part 1, the compendium text), curricula (part 2, "
        "the curriculum elements), collection (part 3, the materials of collection_id, or of a collection given as "
        "node_id (D77); without a collection it drops out, and as the only part it is then refused)",
    )
    subject: str | None = Field(
        None,
        max_length=100,
        description="The subject: its words decide an ambiguous topic, and it narrows part 2 to its curricula. WLO "
        "discipline id, vocabulary URI, label or alias; default: one the topic names ('Physik: Optik'), else the "
        "subjects of node_id or collection_id" + UNKNOWN_SUBJECT_HELP,
    )
    language: str = Field("de", pattern="^de$", description="Only 'de' today; any other value is a 422")
    template_id: str | None = Field(
        None,
        pattern=TEMPLATE_ID_PATTERN,
        description="The template of part 1: sc26 (13 blocks, the shipped TEMPLATE_DEFAULT) or standard (6 blocks) "
        "ship with the image, custom ones come from PUT /api/v2/templates/{id}; GET /api/v2/templates lists them, "
        "an unknown id is a 404",
    )
    preset: Preset | None = Field(None, description=PRESET_HELP)
    matcher: MatcherName | None = Field(None, description=MATCHER_HELP)
    article_choice: ArticleChoice | None = Field(None, description=ARTICLE_CHOICE_HELP)
    curriculum_check: CurriculumCheck | None = Field(None, description=CURRICULUM_CHECK_HELP)
    extraction: Extraction | None = Field(None, description=EXTRACTION_HELP)
    generation: Generation | None = Field(None, description=GENERATION_HELP)
    enrichment: Enrichment | None = Field(None, description=ENRICHMENT_HELP)
    model_knowledge_check: ModelKnowledgeCheck | None = Field(None, description=MODEL_KNOWLEDGE_CHECK_HELP)
    target_length: int = Field(
        30_000,
        ge=2_000,
        le=60_000,
        description="Steers the length of part 1: the value is shared over the content blocks by "
        "weight, and a block stops at a paragraph boundary once it holds one and a half times its "
        "share. It is a steer, not a cap - a block is never shorter than its first paragraph, so a "
        "small value does not make a small compendium. Default: the profile's, 30 000 in every profile (D70, "
        "until then 12 000); the writing LLM takes its share as the length to aim at, in "
        "best-coverage-generated as the length to reach at least. Measured for one topic on 2026-09-21: 2 000 "
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
        max_length=EXISTING_MARKDOWN_MAX_CHARS,
        description="An earlier compendium: blocks marked redaktionell-geprüft are kept word for word",
    )
    regenerate_sections: list[BlockId] | None = Field(
        None,
        max_length=MAX_SLOTS,
        description="With an earlier compendium (existing_markdown): only these blocks are made anew, every other "
        "one is kept. Blocks are named by their id, as the markers of the document name them (sc26_3); a name the "
        "template does not have is a 422 that lists its blocks, and so is the field without existing_markdown",
    )
    facets_visible: bool | None = Field(
        None,
        description="true: the facets of each block stand in the text as visible [Facette: Wert] labels; false: "
        "only in the markers of the markup. Default: the server's FACETS_VISIBLE, shipped false",
    )
    frontmatter_in_markdown: bool = Field(
        True,
        description="Whether the markdown opens with the YAML frontmatter. It carries the AI Act "
        "disclosure, the review status and the snapshot of the archives, so a document meant to stand "
        "on its own keeps it. Off starts the text at the heading; the frontmatter field of the answer "
        "holds the same data either way",
    )
    model_knowledge_label: bool = Field(
        False,
        description="Whether every sentence of model knowledge ends with the visible label [Modellwissen] (D56). Off "
        "by default since D76 (Jan, 2026-10-02: a finished text goes to end customers without it), in the markdown "
        "and in the text of each section, blocks kept from existing_markdown included. The comments around such a "
        "sentence (Evidenzgrad=Modellwissen) stay either way, so the markup still tells it, and the review page shows "
        "it with 'Herkunft je Absatz'",
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
        # A switch the request sets wins; the preset only fills what it left open (D41), the length as well (D70)
        if self.preset:
            for name, value in PRESETS[self.preset].items():
                if getattr(self, name) is None:
                    setattr(self, name, value)
            if "target_length" not in self.model_fields_set:
                self.target_length = PRESET_TARGET_LENGTH[self.preset]
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
        if (self.knowledge_depth or self.knowledge_fulltext) and not self.knowledge_collection_id:
            raise ValueError(
                "knowledge_depth und knowledge_fulltext gelten für knowledge_collection_id; ohne sie ist "
                "nichts zu lesen"
            )
        # Without a collection part 3 drops out (as with the default parts); it must not be the only part. A node may
        # be the collection (D77): only reading it tells, so the service decides that one
        if not self.collection_id and not self.node_id and not {"world", "curricula"} & set(self.parts):
            raise ValueError(f"parts enthält nur collection; {PART_3_NEEDS_A_COLLECTION}")
        return self


def with_profile(request: GenerateRequest, default: Preset) -> GenerateRequest:
    """The request with every switch set: by its own preset (the validator did that) or else by the server's
    profile (PRESET_DEFAULT, D53); a switch the request set itself stays."""
    if request.preset is not None:
        return request
    filled: dict[str, object] = {
        name: value for name, value in PRESETS[default].items() if getattr(request, name) is None
    }
    if "target_length" not in request.model_fields_set:
        filled["target_length"] = PRESET_TARGET_LENGTH[default]
    return request.model_copy(update={"preset": default, **filled})
