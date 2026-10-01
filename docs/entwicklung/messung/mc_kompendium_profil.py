"""M46 and M47: part 1 of topics through the service in the profiles of D69, with the time of each stage and the
tokens of the audit, those read from the prompt cache included.

Variants: bcg = best-coverage-generated as shipped; bcg-hl = the same with matcher hybrid_light; bqg =
best-quality-generated. The output keeps part 1 of every run for the blind gradings of M47
(mc_abdeckung_boegen.py); it stays outside the repository. A run already in the output is not asked again.

The key comes from B_API_KEY. Per compendium 35,000 (bcg-hl) to 90,000 tokens (bcg).

Usage (from the project folder): python mc_kompendium_profil.py <out.json> --variants=bcg,bcg-hl,bqg <topic> [...]
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import SectionStatus  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
REQUESTS = {
    "bcg": {"preset": "best-coverage-generated"},
    "bcg-hl": {"preset": "best-coverage-generated", "matcher": "hybrid_light"},
    "bqg": {"preset": "best-quality-generated"},
}
CONTENT = (SectionStatus.LLM, SectionStatus.EXTRACTIVE, SectionStatus.LLM_SELECTED)
MARK = re.compile(r"<!--[^>]*-->\n?")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    variants = ["bcg"]
    for a in sys.argv[1:]:
        if a.startswith("--variants="):
            variants = a.split("=", 1)[1].split(",")
    out_path, topics = Path(args[0]), args[1:]
    service = cli_service(ZIMS)
    if service.llm is None:
        raise SystemExit("LLM_ENABLED did not reach the settings")
    rows = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    done = {(r["topic"], r["variant"]) for r in rows}
    for topic in topics:
        for variant in variants:
            if (topic, variant) in done:
                continue
            start = time.monotonic()
            try:
                result = service.generate(GenerateRequest(topic=topic, parts=["world"], **REQUESTS[variant]))
            except Exception as exc:  # noqa: BLE001 - a measurement records the failure and goes on
                rows.append({"topic": topic, "variant": variant, "error": f"{type(exc).__name__}: {exc}"[:300]})
                out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
                continue
            took = time.monotonic() - start
            content = [s for s in result.sections if s.text and s.status in CONTENT]
            text = "\n\n".join(f"### {s.title}\n\n{MARK.sub('', s.text)}" for s in content)
            generation = (result.audit.llm or {}).get("generation") or {}
            rows.append({
                "topic": topic, "variant": variant, "s": round(took, 1), "timings": result.audit.timings_ms,
                "heading": result.topic, "main": result.resolution.title, "method": result.resolution.method,
                "tokens": result.audit.llm_tokens, "blocks": len(content),
                "llm_blocks": sum(1 for s in content if s.status is SectionStatus.LLM), "chars": len(text),
                "marked": text.count("[Modellwissen]"), "cited": len(re.findall(r"\[\d+(?:, ?\d+)*\]", text)),
                "fallbacks": generation.get("fallbacks"), "prompts": (result.frontmatter.get("llm") or {}).get("prompts"),
                "text": text,
            })
            tokens = result.audit.llm_tokens or {}
            print(f"{topic} | {variant} | {took:.0f} s | {result.topic} | Artikel {result.resolution.title} | "
                  f"Zeichen {len(text)} | Tokens {tokens.get('total')} cached {tokens.get('cached')}", flush=True)
            out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
