"""M46 and M47: part 1 of topics through the service in the profiles of D69, with the time of each stage and the
tokens of the audit, those read from the prompt cache included.

Variants: bcg = best-coverage-generated as shipped; bcg-hl = the same with matcher hybrid_light; bqg =
best-quality-generated (M47); every profile under its own name as well (M48: llm-free, balanced, best-quality,
best-quality-generated, best-coverage-generated). The output keeps part 1 of every run for the blind gradings of M47
(mc_abdeckung_boegen.py); it stays outside the repository. A run already in the output is not asked again.

The key comes from B_API_KEY. Per compendium 35,000 (bcg-hl) to 90,000 tokens (bcg).

``--parts=world,curricula`` asks part 2 along (M82, the request as callers send it; part 1 alone by default) and keeps
what part 2 found; ``--warmup`` makes every topic once in llm-free first, not recorded, so the first profile does not
pay for reading the archive (M45, M77). ``--budgets=1,2,4,10`` (M86) runs every variant once per factor on the block
budgets: the paragraphs a block keeps and its characters, in the rules' assignment and in the LLM's; the target length
the writer hears stays the request's. The variant is then named <variant>@<factor>, and the order of the factors
turns round from topic to topic, so no factor always pays a topic's first run. ``--fixed-corpus`` (M86) asks the
questions that build the corpus - the article choice and the articles the LLM names (D63) - once per topic and
gives their answer to the topic's other runs, so the factors compare on one corpus; the answer's tokens count in
every run, and the assignment and the writing stay fresh.

From release 2.19.0 the service widens the budgets itself (BLOCK_BUDGET_FACTOR, default 10, D102); to measure the
factors as M86 did, start the container with -e BLOCK_BUDGET_FACTOR=1.

M89: every profile also as <profile>+ex, with extraction=llm (the AI chooses the sentences); a run keeps what
audit.llm.extraction says and the tokens of its answers per prompt (tokens_by_prompt, the choice under
passage_selection).

Usage (from the project folder): python mc_kompendium_profil.py <out.json> --variants=bcg,bcg-hl,bqg <topic> [...]

In the one-off container with OpenAI direct (M82; the archives from ZIM_PATHS of the container):
  cat mc_openai_direkt.py mc_kompendium_profil.py | docker compose run --rm --no-deps -T -v <ordner>:/out \\
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY api \\
      python - /out/<lauf>.json --variants=<profile> --parts=world,curricula --warmup <thema> [...]
"""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("B_API_BASE_URL", "https://b-api.staging.openeduhub.net")  # the container brings its own
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import CurriculaPart, SectionStatus  # noqa: E402
from app.domain.requests import PRESETS, GenerateRequest  # noqa: E402
from app.markup.facets import END_MARKER  # noqa: E402
from app.matching import llm_assignment, policy  # noqa: E402
from app.synthesis.citations import MODEL_KNOWLEDGE_OPEN  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
# On the development machine the archives of kompendium-test; in the container those of ZIM_PATHS (None)
ZIMS = (
    [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
    if DATA.exists()
    else None
)
REQUESTS = {
    "bcg": {"preset": "best-coverage-generated"},
    "bcg-hl": {"preset": "best-coverage-generated", "matcher": "hybrid_light"},
    "bqg": {"preset": "best-quality-generated"},
    **{name: {"preset": name} for name in PRESETS},
    **{f"{name}+ex": {"preset": name, "extraction": "llm"} for name in PRESETS},  # M89: the AI chooses the sentences
}
CONTENT = (SectionStatus.LLM, SectionStatus.EXTRACTIVE, SectionStatus.LLM_SELECTED)
# What audit.llm.extraction says of the choice of sentences (M89)
EXTRACTION_KEYS = ("requested", "used", "sections", "emptied", "fallbacks", "offered", "sentences", "cut_sentences")
MARK = re.compile(r"<!--[^>]*-->\n?")
# A sentence ends at its punctuation, unless the label of model knowledge follows ("Satz. [Modellwissen]"), then there
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?!\[Modellwissen\])|(?<=\[Modellwissen\])\s+")


# A sentence of model knowledge in the markup, whether or not the label follows it (D76: only on request)
MODEL_SPAN = re.compile(re.escape(MODEL_KNOWLEDGE_OPEN) + r"(.*?)" + re.escape(END_MARKER), re.DOTALL)


def model_chars(text: str) -> int:
    """Characters in sentences labelled as model knowledge (M48: the share the model wrote from its own knowledge)."""
    return sum(len(sentence) for sentence in SENTENCE_END.split(text) if "[Modellwissen]" in sentence)


def marked_model_chars(raw: str) -> int:
    """Characters of the sentences the markup marks as model knowledge (M82): since D76 the label comes only with
    model_knowledge_label, so model_chars found none."""
    return sum(len(MARK.sub("", span)) for span in MODEL_SPAN.findall(raw))


BUDGET = {"factor": 1}  # M86: the factor on the block budgets of the run in progress
_cut_to_budgets = policy.cut_to_budgets


def scaled_cut(template, candidates):  # the signature of policy.cut_to_budgets
    """The block budgets times BUDGET["factor"]: paragraphs and characters a block keeps (M86)."""
    factor = BUDGET["factor"]
    if factor != 1:
        slots = [
            slot
            if slot.is_generated
            else slot.model_copy(
                update={
                    "budget": slot.budget.model_copy(
                        update={
                            "max_chunks": slot.budget.max_chunks * factor,
                            "target_chars": slot.budget.target_chars * factor,
                        }
                    )
                }
            )
            for slot in template.slots
        ]
        template = template.model_copy(update={"slots": slots})
    return _cut_to_budgets(template, candidates)


policy.cut_to_budgets = llm_assignment.cut_to_budgets = scaled_cut
CORPUS_QUESTIONS = ("article_choice", "topic_articles")  # M86: the questions whose answers decide the corpus


def fix_corpus() -> None:
    """The corpus questions answer once per wording; a later run asking the same gets the same answer (M86)."""
    from app.llm.client import BApiClient

    answers = {}
    asked = BApiClient.chat

    def chat(self, messages, **kwargs):  # the signature of BApiClient.chat
        prompt = (kwargs.get("prompt") or "").split("@")[0]
        if prompt not in CORPUS_QUESTIONS:
            return asked(self, messages, **kwargs)
        key = (prompt, json.dumps(list(messages), ensure_ascii=False, sort_keys=True))
        if key not in answers:
            answers[key] = asked(self, messages, **kwargs)
        return answers[key]

    BApiClient.chat = chat


TALLY: dict[str, int] = {}  # M89: the tokens of the run in progress per prompt
TALLY_LOCK = threading.Lock()  # the blocks ask in parallel


def tally_tokens() -> None:
    """Every answer's tokens per prompt, for the run in progress (M89: what the choice of sentences costs); answers
    of the fixed corpus count in every run, as in the audit."""
    from app.llm.client import BApiClient

    asked = BApiClient.chat

    def chat(self, messages, **kwargs):  # the signature of BApiClient.chat
        answer = asked(self, messages, **kwargs)
        prompt = (kwargs.get("prompt") or "").split("@")[0] or "?"
        with TALLY_LOCK:
            TALLY[prompt] = TALLY.get(prompt, 0) + (getattr(answer, "total_tokens", 0) or 0)
        return answer

    BApiClient.chat = chat


def _curricula(part: CurriculaPart | None, check: dict | None) -> dict | None:
    """What part 2 found and what its LLM check did, when part 2 was asked for (M82)."""
    if part is None:
        return None
    return {
        "available": part.available,
        "entries": len(part.entries),
        "keywords": len(part.keywords),
        "check": {key: (check or {}).get(key) for key in ("used", "rated", "answered", "dropped", "fallbacks")},
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    variants = ["bcg"]
    parts = ["world"]
    budgets = [1]
    for a in sys.argv[1:]:
        if a.startswith("--variants="):
            variants = a.split("=", 1)[1].split(",")
        if a.startswith("--parts="):
            parts = a.split("=", 1)[1].split(",")
        if a.startswith("--budgets="):
            budgets = [int(factor) for factor in a.split("=", 1)[1].split(",")]
    out_path, topics = Path(args[0]), args[1:]
    if "install" in globals():  # piped in after mc_openai_direkt.py: every call goes to OpenAI direct
        install()  # noqa: F821
    if "--fixed-corpus" in sys.argv:
        fix_corpus()
    tally_tokens()
    service = cli_service(ZIMS)
    if service.llm is None:
        raise SystemExit("LLM_ENABLED did not reach the settings")
    rows = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    done = {(r["topic"], r["variant"]) for r in rows}

    def named(variant: str, factor: int) -> str:
        return variant if budgets == [1] else f"{variant}@{factor}"

    if "--warmup" in sys.argv:
        for topic in topics:
            if any((topic, named(v, f)) not in done for v in variants for f in budgets):
                service.generate(GenerateRequest(topic=topic, parts=parts, preset="llm-free"))
    runs = [
        (topic, variant, factor)
        for number, topic in enumerate(topics)
        for variant in variants
        for factor in (budgets if number % 2 == 0 else budgets[::-1])
    ]
    for topic, variant, factor in runs:
        if (topic, named(variant, factor)) in done:
            continue
        BUDGET["factor"] = factor
        TALLY.clear()
        start = time.monotonic()
        try:
            request = GenerateRequest(topic=topic, parts=parts, **REQUESTS[variant])
            result = service.generate(request)
        except Exception as exc:  # noqa: BLE001 - a measurement records the failure and goes on
            rows.append(
                {
                    "topic": topic,
                    "variant": named(variant, factor),
                    "budget": factor,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }
            )
            out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            continue
        took = time.monotonic() - start
        content = [s for s in result.sections if s.text and s.status in CONTENT]
        text = "\n\n".join(f"### {s.title}\n\n{MARK.sub('', s.text)}" for s in content)
        marked = sum(marked_model_chars(s.text) for s in content)
        llm = result.audit.llm or {}
        generation = llm.get("generation") or {}
        rows.append(
            {
                "topic": topic,
                "variant": named(variant, factor),
                "budget": factor,
                "s": round(took, 1),
                "timings": result.audit.timings_ms,
                "heading": result.topic,
                "main": result.resolution.title,
                "method": result.resolution.method,
                "tokens": result.audit.llm_tokens,
                "blocks": len(content),
                "llm_blocks": sum(1 for s in content if s.status is SectionStatus.LLM),
                "chars": len(text),
                "marked": text.count("[Modellwissen]"),
                "model_chars": max(model_chars(text), marked),
                "cited": len(re.findall(r"\[\d+(?:, ?\d+)*\]", text)),
                "evidence": sum(len(s.chunk_ids) for s in result.sections),  # M86: the paragraphs the blocks kept
                "sources": [source.title for source in result.sources],
                "fallbacks": generation.get("fallbacks"),
                "prompts": (result.frontmatter.get("llm") or {}).get("prompts"),
                "note": llm.get("note"),
                "matching_fallbacks": (llm.get("matching") or {}).get("fallbacks"),
                "matching_asked_again": (llm.get("matching") or {}).get("asked_again"),
                "extraction": {key: (llm.get("extraction") or {}).get(key) for key in EXTRACTION_KEYS},  # M89
                "tokens_by_prompt": dict(TALLY),
                "target_length": request.target_length,
                "parts_status": result.parts_status,
                "curricula": _curricula(result.curricula, llm.get("curriculum_check")),
                "text": text,
            }
        )
        tokens = result.audit.llm_tokens or {}
        print(
            f"{topic} | {named(variant, factor)} | {took:.0f} s | {result.topic} | "
            f"Artikel {result.resolution.title} | Zeichen {len(text)} | Tokens {tokens.get('total')} "
            f"cached {tokens.get('cached')}",
            flush=True,
        )
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
