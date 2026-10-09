"""M46 and M47: part 1 of topics through the service in the profiles of D69, with the time of each stage and the
tokens of the audit, those read from the prompt cache included.

Variants: bcg = best-coverage-generated as shipped; bcg-hl = the same with matcher hybrid_light; bqg =
best-quality-generated (M47); every profile under its own name as well (M48: llm-free, balanced, best-quality,
best-quality-generated, best-coverage-generated). The output keeps part 1 of every run for the blind gradings of M47
(mc_abdeckung_boegen.py); it stays outside the repository. A run already in the output is not asked again.

The key comes from B_API_KEY. Per compendium 35,000 (bcg-hl) to 90,000 tokens (bcg).

``--parts=world,curricula`` asks part 2 along (M82, the request as callers send it; part 1 alone by default) and keeps
what part 2 found; ``--warmup`` makes every topic once in llm-free first, not recorded, so the first profile does not
pay for reading the archive (M45, M77).

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
import time
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("B_API_BASE_URL", "https://b-api.staging.openeduhub.net")  # the container brings its own
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import CurriculaPart, SectionStatus  # noqa: E402
from app.domain.requests import PRESETS, GenerateRequest  # noqa: E402
from app.markup.facets import END_MARKER  # noqa: E402
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
}
CONTENT = (SectionStatus.LLM, SectionStatus.EXTRACTIVE, SectionStatus.LLM_SELECTED)
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
    for a in sys.argv[1:]:
        if a.startswith("--variants="):
            variants = a.split("=", 1)[1].split(",")
        if a.startswith("--parts="):
            parts = a.split("=", 1)[1].split(",")
    out_path, topics = Path(args[0]), args[1:]
    if "install" in globals():  # piped in after mc_openai_direkt.py: every call goes to OpenAI direct
        install()  # noqa: F821
    service = cli_service(ZIMS)
    if service.llm is None:
        raise SystemExit("LLM_ENABLED did not reach the settings")
    rows = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    done = {(r["topic"], r["variant"]) for r in rows}
    if "--warmup" in sys.argv:
        for topic in topics:
            if any((topic, variant) not in done for variant in variants):
                service.generate(GenerateRequest(topic=topic, parts=parts, preset="llm-free"))
    for topic in topics:
        for variant in variants:
            if (topic, variant) in done:
                continue
            start = time.monotonic()
            try:
                request = GenerateRequest(topic=topic, parts=parts, **REQUESTS[variant])
                result = service.generate(request)
            except Exception as exc:  # noqa: BLE001 - a measurement records the failure and goes on
                rows.append({"topic": topic, "variant": variant, "error": f"{type(exc).__name__}: {exc}"[:300]})
                out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
                continue
            took = time.monotonic() - start
            content = [s for s in result.sections if s.text and s.status in CONTENT]
            text = "\n\n".join(f"### {s.title}\n\n{MARK.sub('', s.text)}" for s in content)
            marked = sum(marked_model_chars(s.text) for s in content)
            llm = result.audit.llm or {}
            generation = llm.get("generation") or {}
            rows.append({
                "topic": topic, "variant": variant, "s": round(took, 1), "timings": result.audit.timings_ms,
                "heading": result.topic, "main": result.resolution.title, "method": result.resolution.method,
                "tokens": result.audit.llm_tokens, "blocks": len(content),
                "llm_blocks": sum(1 for s in content if s.status is SectionStatus.LLM), "chars": len(text),
                "marked": text.count("[Modellwissen]"), "model_chars": max(model_chars(text), marked),
                "cited": len(re.findall(r"\[\d+(?:, ?\d+)*\]", text)),
                "sources": [source.title for source in result.sources],
                "fallbacks": generation.get("fallbacks"), "prompts": (result.frontmatter.get("llm") or {}).get("prompts"),
                "note": llm.get("note"), "matching_fallbacks": (llm.get("matching") or {}).get("fallbacks"),
                "matching_asked_again": (llm.get("matching") or {}).get("asked_again"),
                "target_length": request.target_length,
                "parts_status": result.parts_status,
                "curricula": _curricula(result.curricula, llm.get("curriculum_check")),
                "text": text,
            })
            tokens = result.audit.llm_tokens or {}
            print(f"{topic} | {variant} | {took:.0f} s | {result.topic} | Artikel {result.resolution.title} | "
                  f"Zeichen {len(text)} | Tokens {tokens.get('total')} cached {tokens.get('cached')}", flush=True)
            out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
