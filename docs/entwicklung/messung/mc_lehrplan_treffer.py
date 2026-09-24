"""How well part 2 finds the curriculum elements of a topic (M22): its matches with and without the subject.

Part 2 searches the local MEM cache for the keywords of a topic (the topic, aliases from the lead, titles of
subarticles) and narrows the curricula to the subject when one is known (docs/entwicklung/04). Nobody has yet judged
whether the elements it prints are about the topic. This runs the 20 normal topics of the article gold twice in the
flow of the service - without a subject and with the subject that fits - and draws a sample to judge, with a fixed
seed: per topic up to 5 elements of the run with the subject and up to 5 of those only the run without it prints.
The run with the subject prints a subset of the other, so the two strata estimate the precision of both runs.

The service answers with the first 200 elements in JSON and prints all of them in the text (D23); the sample is drawn
from all, found again by the service's matcher with the keywords and subject terms the service used. The LLM stays
off: part 2 does not use it, and with it the article choice could pick other subarticles, hence other keywords.

It writes counts and the sample (IRI, keyword, stratum, where the keyword was found) to <out.json>, without the
texts of the elements: whether MEM data may be passed on is not settled (docs/entwicklung/04). The texts go only into
the judging sheet <sheet.json>, which belongs outside the repository and does not say from which stratum an element
comes; the notes go into eval/lehrplan/treffer_noten.yaml, and mc_lehrplan_auswertung.py computes the precision.

Usage (project venv, from the project root; needs lehrplan.db in STATE_DIR):
python docs/entwicklung/messung/mc_lehrplan_treffer.py <out.json> <sheet.json>
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

os.environ["LLM_ENABLED"] = "false"  # over the .env
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service
from app.domain.requests import GenerateRequest
from app.sources.lehrplan.matcher import CurriculumMatch, LehrplanMatcher

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
TOPICS = {  # the normal topics of eval/artikelwahl/hauptartikel.yaml and the subject a teacher would name
    "Barockliteratur": "Deutsch",
    "Bruchrechnung": "Mathematik",
    "Demokratie": "Politik",
    "Französische Revolution": "Geschichte",
    "Klimawandel": "Geografie",
    "Optik": "Physik",
    "Photosynthese": "Biologie",
    "Programmiersprache": "Informatik",
    "Säure-Base-Konzepte": "Chemie",
    "Sinfonie": "Musik",
    "Plattentektonik": "Geografie",
    "Ökosystem": "Biologie",
    "Atommodell": "Chemie",
    "Industrielle Revolution": "Geschichte",
    "Elektrischer Strom": "Physik",
    "Wasserkreislauf": "Geografie",
    "Römisches Reich": "Geschichte",
    "Lineare Funktion": "Mathematik",
    "Zelle (Biologie)": "Biologie",
    "Gedicht": "Deutsch",
}
PER_STRATUM = 5
SEED = 22


def run(service: Any, topic: str, subject: str | None) -> tuple[dict[str, Any], dict[str, CurriculumMatch]]:
    """Part 2 as the service builds it, and all its elements by IRI."""
    started = time.perf_counter()
    part = service.generate(GenerateRequest(topic=topic, subject=subject, parts=["curricula"])).curricula
    seconds = time.perf_counter() - started
    assert part is not None and part.available, "part 2 needs the cache lehrplan.db"
    result = LehrplanMatcher(service.curricula.store).match(part.keywords, subject_terms=part.subject_terms)
    matches = {match.hit.iri: match for match in result.matches}
    assert len(matches) == part.summary["matches"], (topic, subject, len(matches), part.summary["matches"])
    return {
        "sekunden": round(seconds, 2),
        "stichwoerter": part.keywords,
        "fachwoerter": part.subject_terms,
        "elemente": len(matches),
        "lehrplaene": part.summary["lehrplaene"],
        "laender": part.summary["laender"],
        "je_stichwort": dict(Counter(match.keyword for match in matches.values()).most_common()),
        "fundort": dict(Counter(match.hit.matched_in for match in matches.values()).most_common()),
    }, matches


def drawn(
    rng: random.Random, iris: set[str], stratum: str, matches: dict[str, CurriculumMatch]
) -> list[dict[str, Any]]:
    chosen = rng.sample(sorted(iris), min(PER_STRATUM, len(iris)))
    return [
        {
            "iri": iri,
            "schicht": stratum,
            "stichwort": matches[iri].keyword,
            "fundort": matches[iri].hit.matched_in,  # label: the element's own text, parent: its heading
            "score": matches[iri].score,
        }
        for iri in chosen
    ]


out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2])
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
service = cli_service(ZIMS)
rng = random.Random(SEED)
results, sheet = [], []
for topic, subject in TOPICS.items():
    without, all_matches = run(service, topic, None)
    with_subject, subject_matches = run(service, topic, subject)
    assert subject_matches.keys() <= all_matches.keys(), topic  # the subject only narrows
    only_without = all_matches.keys() - subject_matches.keys()
    in_subject = drawn(rng, set(subject_matches), "mit_fach", all_matches)
    sample = in_subject + drawn(rng, only_without, "nur_ohne", all_matches)
    shown = [row["iri"] for row in sample]
    rng.shuffle(shown)  # the sheet must not tell the strata apart
    for iri in shown:
        hit = all_matches[iri].hit
        sheet.append(
            {
                "thema": topic,
                "iri": iri,
                "element": hit.label,
                "bereich": hit.parent_label,
                "lehrplan": hit.lehrplan.label,
                "faecher": list(hit.lehrplan.schulfaecher),
            }
        )
    results.append(
        {"thema": topic, "fach": subject, "ohne_fach": without, "mit_fach": with_subject, "stichprobe": sample}
    )
    print(
        f"{topic:24} ohne Fach {without['elemente']:5} | mit {subject:10} {with_subject['elemente']:4} | "
        f"nur ohne {len(only_without):5} | Stichprobe {len(sample)}"
    )

out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
sheet_path.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{len(sheet)} Elemente zum Beurteilen in {sheet_path}")
