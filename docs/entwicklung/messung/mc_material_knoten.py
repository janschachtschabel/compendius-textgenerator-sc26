"""The article of node input as the service now chooses it (M25, D47), on the materials of M21 and a second sample.

M21 and M23 compared ways to find the article of a real material outside the service; D47 built two of them into it:
the rules over title and description without an LLM, and the question to the LLM with article_choice llm. This
measures them in the service's own flow (choose_main_article, as compendium and /knowledge call it) on a gold of
materials (eval/materialwahl/materialien.yaml, and materialien_m25.yaml, drawn with another seed and labelled before
any of these ways ran on it), read anew and anonymously from their repository:

- K0  the title as the topic, as node input worked until D47 (derive_topic and the rules)
- R   a material alone, llm-free: the rules over title and description
- L   a material alone, article_choice llm: the LLM names the article
- B   the term a teacher would type (``begriff``), alone, llm-free
- BR  the term with the material, llm-free: the term leads, the rules name the material's article
- BL  the term with the material, article_choice llm: one question hears both

Per way the article, whether the gold accepts it, seconds and tokens; for BR and BL the material's own article and
whether it joined the corpus (it links with the main article), with its note from --noten when M23 judged it. Titles
and numbers only. --auswertung <out.json> prints the tables of an earlier run without asking anything.

The runs of M25 (2026-09-25, gpt-6-luna) are ergebnisse/m25_knoten_materialien.json (gold 1, with --noten
eval/materialwahl/kompendium_noten.yaml) and m25_knoten_materialien_m25.json (gold 2), both from the second run, whose
LLM answers came mostly from the b-api cache; m25_knoten_materialien_m25_vor_korrektur.json is the first run on gold 2,
before the two fixes it led to, with the model's own times.

Usage (project venv, from the project root; L and BL need B_API_KEY in .env, the key is never printed):
python docs/entwicklung/messung/mc_material_knoten.py <gold.yaml> <out.json> [--noten <noten.yaml>]
python docs/entwicklung/messung/mc_material_knoten.py --auswertung <out.json>
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml

WAYS = ("K0", "R", "L", "B", "BR", "BL")
ARTS = ("klar", "unscharf", "keins")


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def table(rows: list[dict[str, Any]]) -> list[str]:
    """Per kind of material and way: right, wrong, none, precision, recall and F1 of the main article."""
    lines = []
    for art in ARTS:
        group = [row for row in rows if row["art"] == art]
        if not group:
            continue
        lines.append(f"== {art} ({len(group)})")
        for way in WAYS:
            done = [row["wege"][way] for row in group if way in row["wege"]]
            if not done:
                continue
            right = sum(1 for way_row in done if way_row["titel"] and way_row["richtig"])
            wrong = sum(1 for way_row in done if way_row["titel"] and not way_row["richtig"])
            none = len(done) - right - wrong
            precision = right / (right + wrong) if right + wrong else 0.0
            recall = right / len(done)
            tokens = [way_row["tokens"] for way_row in done if way_row["tokens"]]
            seconds = statistics.median(way_row["sekunden"] for way_row in done)
            spend = f", Tokens Median {statistics.median(tokens):.0f}" if tokens else ""
            lines.append(
                f"  {way:3} richtig {right:2}, falsch {wrong:2}, keins {none:2} | P {precision:.2f} R {recall:.2f} "
                f"F1 {f1(precision, recall):.2f} | {seconds:.2f} s{spend}"
            )
    return lines


def materials(rows: list[dict[str, Any]]) -> list[str]:
    """For a term with a material: the material's own articles, whether they joined, and their M23 notes."""
    lines = []
    for way in ("BR", "BL"):
        done = [row["wege"][way] for row in rows if way in row["wege"]]
        named = [way_row for way_row in done if way_row.get("material")]
        added = [way_row for way_row in named if way_row.get("dazu")]
        notes = [way_row.get("note_material") for way_row in added]
        judged = [note for note in notes if note is not None]
        shares = " ".join(f"Note {note}: {judged.count(note)}" for note in (2, 1, 0))
        lines.append(
            f"  {way}: Material-Artikel anders als der Hauptartikel {len(named)} von {len(done)}, dazugenommen "
            f"{len(added)} | beurteilt {len(judged)}: {shares}"
        )
    return lines


def report(rows: list[dict[str, Any]]) -> None:
    for line in [*table(rows), "", "Begriff mit Material:", *materials(rows)]:
        print(line)


def one_material(
    service: Any, entry: dict[str, Any], info: Any, accepted: set[str], notes: dict[tuple[str, str], int]
) -> dict[str, dict[str, Any]]:
    """The six ways for one material, each timed; ``accepted`` are the gold's titles as the archive names them."""
    from app.knowledge.main_article import choose_main_article
    from app.llm.deadline import Deadline
    from app.sources.wlo.part import derive_topic, node_topic

    derived = [node_topic(info)]
    term = entry.get("begriff")
    slots = service.templates.get(service.settings.template_default).content_slots()
    ways: dict[str, dict[str, Any]] = {}

    def choose(topic: str | None, node: Any, llm: bool) -> tuple[Any, float]:
        started = time.perf_counter()
        job = service.article_choice_job("llm", Deadline(service.settings.request_timeout_s))[2] if llm else None
        chosen = choose_main_article(
            service.registry, service.subjects, topic, derived if node else [], node=node, job=job
        )
        return chosen, round(time.perf_counter() - started, 2)

    def record(way: str, chosen: Any, seconds: float) -> dict[str, Any]:
        title = chosen.resolution.title if chosen.resolution.resolved else None
        node = chosen.node
        ways[way] = {
            "titel": title,
            "richtig": title in accepted,
            "sekunden": seconds,
            "tokens": sum(r.total_tokens for r in (chosen.choice, node) if r is not None),
            "weg": node.way if node is not None else None,
            "rueckfall": node.fallback if node is not None else None,
            "genannt": node.named if node is not None else None,
        }
        return ways[way]

    found = derive_topic(None, derived)
    started = time.perf_counter()
    old = service.registry.resolve_topic(
        found.normalized.topic,
        context=found.context,
        query=found.normalized.query,
        terms=service.subjects.context_terms_of(found.subjects),
    )
    seconds = round(time.perf_counter() - started, 2)
    ways["K0"] = {"titel": old.title, "richtig": old.title in accepted, "sekunden": seconds, "tokens": 0}
    record("R", *choose(None, info, llm=False))
    record("L", *choose(None, info, llm=True))
    if not term:
        return ways
    record("B", *choose(term, None, llm=False))
    for way, llm in (("BR", False), ("BL", True)):
        chosen, seconds = choose(term, info, llm)
        row = record(way, chosen, seconds)
        material = chosen.material if chosen.material != row["titel"] else None
        added = None
        if row["titel"] and material:
            corpus = service.registry.build_corpus(chosen.resolution, slots, 12, material=material)
            added = next((source.title for source in corpus if source.origin == "node"), None)
        row.update(material=material, dazu=added is not None, note_material=notes.get((entry["node_id"], added or "")))
    return ways


def measure(gold_path: Path, out_path: Path, notes_path: Path | None) -> None:
    os.environ["LLM_ENABLED"] = "true"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from materialwege import canonical

    from app.cli_common import cli_service
    from app.sources.wlo.client import EduSharingClient, EduSharingError

    data = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
    service = cli_service(
        [str(data / "wikipedia_de_all_nopic_2026-01.zim"), str(data / "klexikon_de_all_maxi_2026-08.zim")]
    )
    assert service.llm is not None, "LLM_ENABLED did not reach the settings"
    notes = (
        {(e["node_id"], e["artikel"]): e["note"] for e in yaml.safe_load(notes_path.read_text("utf-8"))["noten"]}
        if notes_path
        else {}
    )
    readers: dict[str, EduSharingClient] = {}
    rows: list[dict[str, Any]] = []
    for entry in yaml.safe_load(gold_path.read_text(encoding="utf-8"))["materialien"]:
        reader = readers.setdefault(entry["repository"], EduSharingClient(entry["repository"], timeout_s=30))
        try:
            info = reader.node(entry["node_id"])
        except EduSharingError as exc:  # a material gone since the gold was drawn is reported, not measured
            print(f"{entry['node_id'][:8]} nicht lesbar: {str(exc)[:100]}")
            continue
        accepted = canonical(service.registry.primary_archive, entry["akzeptiert"])
        ways = one_material(service, entry, info, accepted, notes)
        rows.append({"node_id": entry["node_id"], "titel": entry["titel"], "art": entry["art"], "wege": ways})
        states = " ".join(f"{way}:{'+' if r['richtig'] else ('-' if r['titel'] else 'x')}" for way, r in ways.items())
        print(f"{entry['art']:8} {entry['titel'][:40]:40} {states}", flush=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    report(rows)


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if sys.argv[1] == "--auswertung":
        report(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
        return
    gold_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    if out_path.exists():
        raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
    notes_path = Path(sys.argv[sys.argv.index("--noten") + 1]) if "--noten" in sys.argv else None
    measure(gold_path, out_path, notes_path)


if __name__ == "__main__":
    main()
