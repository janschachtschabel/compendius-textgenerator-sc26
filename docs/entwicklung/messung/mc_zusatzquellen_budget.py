"""M90: Wikibooks and Wikiversity as further archives at the block budget times 1 and 10 - what do they add?

M11 (mc_zusatzquellen.py) measured the same archives at the budgets of the template and 12,000 characters on 20
topics. A further archive gives a compendium the article of the main article's exact title, a redirect of it included
(the twin, D100); Klexikon is one, Wikibooks and Wikiversity are not recommended (D99, M84). Every topic runs in
llm-free, without an LLM, four times: with the block budget times 1 and 10 (BLOCK_BUDGET_FACTOR, D102), each once with
Wikipedia and Klexikon and once with Wikibooks and Wikiversity beside them. Per run the sources and the printed
paragraphs by project; every printed paragraph of Wikibooks or Wikiversity with its block and text, for a blind
judgement, and the paragraphs of Wikipedia and Klexikon it pushed out of the text: printed without the further
archives, not with them. The output holds texts and stays outside the repository.

Topics: the 94 requests of eval/artikelwahl (the directory bound to /artikelwahl) and the nine of M82, or those named.
Where a further archive printed something, a row also keeps the paragraphs it pushed out, with their text.

In the one-off container (kompendium-test/data bound to /archives, the further archives under zusatz/):
  cat mc_zusatzquellen_budget.py | docker compose run --rm --no-deps -T -v <ordner>:/out \\
      -v <repo>/eval/artikelwahl:/artikelwahl:ro api python - /out/<lauf>.json [<thema> ...]
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

BASE = ["/archives/wikipedia_de_all_nopic_2026-01.zim", "/archives/klexikon_de_all_maxi_2026-08.zim"]
FURTHER = [
    "/archives/zusatz/wikibooks_de_all_nopic/wikibooks_de_all_nopic_2026-01.zim",
    "/archives/zusatz/wikiversity_de_all_nopic/wikiversity_de_all_nopic_2026-07.zim",
]
EXTRA_PROJECTS = ("wikibooks", "wikiversity")
M82_TOPICS = (
    "Optik",
    "Photosynthese",
    "Französische Revolution",
    "Dichter aus dem Mittelalter",
    "Komponisten der Klassik",
    "Philosophen der Aufklärung",
    "OER-Förderungen",
    "Inklusion im Sportunterricht",
    "Künstliche Intelligenz im Unterricht",
)
FACTORS = (1, 10)
MARK = re.compile(r"<!--[^>]*-->\n?")
NUMBER_AT_END = re.compile(r"\[(\d+)\]\s*$")


def topics() -> list[str]:
    """The requests of the article choice gold, then the topics of M82 not among them."""
    found: list[str] = []
    for path in sorted(Path("/artikelwahl").glob("hauptartikel*.yaml")):
        for entry in yaml.safe_load(path.read_text(encoding="utf-8"))["anfragen"]:
            if entry["anfrage"] not in found:
                found.append(entry["anfrage"])
    return found + [topic for topic in M82_TOPICS if topic not in found]


def paragraphs(text: str) -> dict[int, str]:
    """The printed paragraphs of a verbatim block by their citation number (a table carries its number below it)."""
    found: dict[int, str] = {}
    previous = ""
    for part in MARK.sub("", text).split("\n\n"):
        number = NUMBER_AT_END.search(part)
        if number:
            found[int(number.group(1))] = part[: number.start()].strip() or previous
        previous = part.strip()
    return found


def summary(result) -> dict:
    """Sources, printed paragraphs by project, the printed paragraphs of the further archives with their text."""
    project_of = {source.source_id: source.project for source in result.sources}
    printed: dict[str, int] = {}
    chars: dict[str, int] = {}
    kept: list[dict] = []  # the paragraphs of Wikipedia and Klexikon in the text
    extra: list[dict] = []
    for section in result.sections:
        texts = paragraphs(section.text)
        for citation in section.citations:
            project = project_of.get(citation.source_id, "?")
            body = texts.get(citation.number, "")
            printed[project] = printed.get(project, 0) + 1
            chars[project] = chars.get(project, 0) + len(body)
            paragraph = {
                "baustein": section.title,
                "projekt": project,
                "artikel": citation.source_title,
                "abschnitt": citation.section_heading,
                "chunk_id": citation.chunk_id,
                "text": body,
            }
            (extra if project in EXTRA_PROJECTS else kept).append(paragraph)
    return {
        "main": result.resolution.title,
        "sources": [
            {"title": s.title, "project": s.project, "primary": s.is_primary} for s in result.sources
        ],
        "printed": printed,
        "chars": chars,
        "extra": extra,
        "kept": kept,
    }


def main() -> None:
    out_path, asked = Path(sys.argv[1]), sys.argv[2:]
    rows = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    done = {(r["topic"], r["factor"]) for r in rows}
    services = {"ohne": cli_service(BASE), "mit": cli_service(BASE + FURTHER)}
    for topic in asked or topics():
        for factor in FACTORS:
            if (topic, factor) in done:
                continue
            row: dict = {"topic": topic, "factor": factor}
            for name, service in services.items():
                start = time.monotonic()
                try:
                    request = GenerateRequest(topic=topic, parts=["world"], preset="llm-free")
                    result = service.generate(request, block_budget_factor=factor)
                except Exception as exc:  # noqa: BLE001 - a measurement records the failure and goes on
                    row[name] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
                    continue
                row[name] = {**summary(result), "s": round(time.monotonic() - start, 1)}
            if "kept" in row.get("ohne", {}) and "kept" in row.get("mit", {}):
                still = {paragraph["chunk_id"] for paragraph in row["mit"]["kept"]}
                pushed = [paragraph for paragraph in row["ohne"]["kept"] if paragraph["chunk_id"] not in still]
                row["verdraengt"] = len(pushed)
                if row["mit"]["extra"]:  # only where a further archive printed something: what it took the place of
                    row["verdraengt_absaetze"] = pushed
            for name in ("ohne", "mit"):
                row.get(name, {}).pop("kept", None)
            rows.append(row)
            extra = len(row.get("mit", {}).get("extra", []))
            print(f"{topic} | x{factor} | further paragraphs {extra} | pushed out {row.get('verdraengt')}", flush=True)
            out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
