"""Part 2 after D58 on the 20 topics of M22 (M32): bundled heading hits, the LLM check, and Model2Vec (D1).

M22 judged a sample of 175 elements that part 2 printed for the 20 normal topics of the article gold, without and
with the subject a teacher would name (eval/lehrplan/treffer_noten.yaml, a second rater in treffer_noten_zweit.yaml).
D58 bundles the elements only their heading names (all profiles) and lets the LLM rate every element in the
best-quality profiles. This runs the same 40 requests in the flow of the service with preset llm-free - the rules
choose the article, as in M22 - and parts=["curricula"]:

- rules <out.json>: curriculum_check rule-based, LLM off. Per request every element part 2 found, by IRI, with where
  its keyword stood (label or heading: a heading-only element is bundled), and the seconds of the request.
- check <out.json>: curriculum_check=llm. A spy on app.service.check_curriculum records every element the model was
  given and its note (0 = dropped, None = unrated), the calls, tokens and fallbacks; the seconds of the request and
  of part 2. B_API_KEY from .env, never printed.
- m2v <model dir> <out.json>: D1, the cosine of topic and element - its text, and its text with its heading - under
  the service's Model2Vec model, for the elements of the M22 sample; the texts are read from the local cache only.
- evaluate <rules.json> <check.json> <m2v.json> <out.json>: the notes of both raters against all three, with the
  estimator of M22 (per topic from the two strata, then the mean over topics) restricted to what part 2 shows.

IRIs, notes, counts, tokens and seconds only; no texts of elements. Usage (project venv, from the project root;
lehrplan.db in STATE_DIR, the archives of kompendium-test):
python docs/entwicklung/messung/mc_lehrplan_pruefung.py rules <out.json>
python docs/entwicklung/messung/mc_lehrplan_pruefung.py check <out.json>
python docs/entwicklung/messung/mc_lehrplan_pruefung.py m2v <model dir> <out.json>
python docs/entwicklung/messung/mc_lehrplan_pruefung.py evaluate <rules.json> <check.json> <m2v.json> <out.json>
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
M22 = HERE / "ergebnisse" / "m22_lehrplan_treffer.json"
NOTES = [ROOT / "eval" / "lehrplan" / "treffer_noten.yaml", ROOT / "eval" / "lehrplan" / "treffer_noten_zweit.yaml"]
RUNS = ("ohne_fach", "mit_fach")


def topics() -> list[dict[str, Any]]:
    """The 20 topics of M22 with their subject and their sample (IRI and stratum)."""
    return list(json.loads(M22.read_text(encoding="utf-8")))


def service_for(*, llm: bool) -> Any:
    # over the .env; the budget and deadline of a request stay the shipped 60,000 tokens and 120 s
    os.environ["LLM_ENABLED"] = "true" if llm else "false"
    if llm:
        os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from app.cli_common import cli_service

    return cli_service(ZIMS)


def request(topic: str, subject: str | None, check: str) -> Any:
    from app.domain.requests import GenerateRequest

    return GenerateRequest(
        topic=topic, subject=subject, parts=["curricula"], preset="llm-free", curriculum_check=check  # type: ignore[arg-type]
    )


def rules_step(out: Path) -> None:
    from app.sources.lehrplan.matcher import LehrplanMatcher

    service = service_for(llm=False)
    result: dict[str, Any] = {}
    for topic in topics():
        for run in RUNS:
            subject = topic["fach"] if run == "mit_fach" else None
            started = time.perf_counter()
            part = service.generate(request(topic["thema"], subject, "rule-based")).curricula
            seconds = time.perf_counter() - started
            assert part is not None and part.available, "part 2 needs the cache lehrplan.db"
            # all elements, not only the first 200 of the JSON answer, found again with the service's own words
            matches = LehrplanMatcher(service.curricula.store).match(part.keywords, subject_terms=part.subject_terms)
            assert len(matches.matches) == part.summary["matches"], (topic["thema"], run)
            result[f"{topic['thema']}|{run}"] = {
                "sekunden": round(seconds, 2),
                "stichwoerter": part.keywords,
                "elemente": {match.hit.iri: match.hit.matched_in for match in matches.matches},
                "gebuendelt": part.summary["bundled"],
            }
            print(f"{topic['thema']:24} {run:9} {part.summary['matches']:5} Elemente, {part.summary['bundled']:5} gebündelt")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


def check_step(out: Path) -> None:
    import app.service as service_module

    service = service_for(llm=True)
    if service.llm is None or service.llm_unavailable() is not None:
        raise SystemExit(f"LLM nicht verfügbar: {service.llm_unavailable()}")
    seen: list[tuple[list[Any], list[Any], Any]] = []
    original = service_module.check_curriculum

    def spy(job: Any, matches: Any) -> Any:
        kept, report = original(job, matches)
        seen.append((list(matches), kept, report))
        return kept, report

    service_module.check_curriculum = spy
    result: dict[str, Any] = {}
    for topic in topics():
        for run in RUNS:
            subject = topic["fach"] if run == "mit_fach" else None
            seen.clear()
            started = time.perf_counter()
            answer = service.generate(request(topic["thema"], subject, "llm"))
            seconds = time.perf_counter() - started
            given, kept, report = seen[0] if seen else ([], [], None)
            kept_notes = {match.hit.iri: match.note for match in kept}
            result[f"{topic['thema']}|{run}"] = {
                "sekunden": round(seconds, 2),
                "teil2_ms": answer.audit.timings_ms.get("curricula"),
                "elemente": {
                    match.hit.iri: {"fundort": match.hit.matched_in, "note": kept_notes.get(match.hit.iri, 0)}
                    for match in given
                },
                "aufrufe": report.calls if report else 0,
                "tokens": report.total_tokens if report else 0,
                "verworfen": report.dropped if report else 0,
                "beantwortet": report.answered if report else 0,
                "rueckfall": dict(report.fallbacks) if report else {},
            }
            row = result[f"{topic['thema']}|{run}"]
            print(
                f"{topic['thema']:24} {run:9} {len(given):5} geprüft, {row['verworfen']:4} verworfen, "
                f"{row['tokens']:6} Tokens, {seconds:5.1f} s {row['rueckfall'] or ''}",
                flush=True,
            )
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


def m2v_step(model_dir: str, out: Path) -> None:
    import numpy as np
    from model2vec import StaticModel

    from app.settings import get_settings

    sample = [(topic["thema"], row["iri"]) for topic in topics() for row in topic["stichprobe"]]
    database = Path(get_settings().state_dir) / "lehrplan.db"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        iris = sorted({iri for _topic, iri in sample})
        marks = ",".join("?" * len(iris))
        rows = connection.execute(f"SELECT iri, label, parent_label FROM node WHERE iri IN ({marks})", iris)  # noqa: S608
        texts = {iri: (label, parent or "") for iri, label, parent in rows}
    model = StaticModel.from_pretrained(model_dir)

    def cosine(first: str, second: str) -> float:
        vectors = model.encode([first, second])
        a, b = vectors[0], vectors[1]
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) or 1.0))

    result = {}
    for topic, iri in sample:
        label, parent = texts[iri]
        name = re.sub(r"\s*\([^)]*\)\s*$", "", topic)  # "Zelle (Biologie)" as part 2 searches it
        result[f"{topic}|{iri}"] = {"text": cosine(name, label), "mit_bereich": cosine(name, f"{parent}: {label}")}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(result)} Elemente")


def load_notes(path: Path) -> dict[tuple[str, str], int]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["noten"]
    return {(entry["thema"], entry["iri"]): int(entry["note"]) for entry in entries}


def estimate(topic: dict[str, Any], notes: dict[tuple[str, str], int], shown: dict[str, set[str]], least: int) -> Any:
    """M22's estimator for one topic, restricted to the elements part 2 shows: the share of those rated >= ``least``
    in the run without the subject (both strata, weighted by their shown elements) and with it."""
    by_stratum: dict[str, list[int]] = {"mit_fach": [], "nur_ohne": []}
    for row in topic["stichprobe"]:
        run = "mit_fach" if row["schicht"] == "mit_fach" else "ohne_fach"
        if row["iri"] in shown[run]:
            by_stratum[row["schicht"]].append(notes[(topic["thema"], row["iri"])])
    n_with = len(shown["mit_fach"])
    n_only = len(shown["ohne_fach"] - shown["mit_fach"])

    def share(values: list[int]) -> float | None:
        return sum(value >= least for value in values) / len(values) if values else None

    p_with, p_only = share(by_stratum["mit_fach"]), share(by_stratum["nur_ohne"])
    parts = [(n_with, p_with), (n_only, p_only)]
    known = [(n, p) for n, p in parts if p is not None and n]
    without = sum(n * p for n, p in known) / sum(n for n, _ in known) if known else None
    return {"ohne_fach": without, "mit_fach": p_with}


def evaluate_step(rules_file: Path, check_file: Path, m2v_file: Path, out: Path) -> None:
    rules = json.loads(rules_file.read_text(encoding="utf-8"))
    checked = json.loads(check_file.read_text(encoding="utf-8"))
    similarity = json.loads(m2v_file.read_text(encoding="utf-8"))
    raters = [load_notes(path) for path in NOTES]

    def shown_by(variant: str, key: str) -> set[str]:
        if variant == "alle":
            return set(rules[key]["elemente"])
        if variant == "B":
            return {iri for iri, where in rules[key]["elemente"].items() if where == "label"}
        elements = checked[key]["elemente"]
        if variant == "D2 behalten":
            return {iri for iri, row in elements.items() if row["note"] != 0}
        return {
            iri for iri, row in elements.items() if row["note"] != 0 and (row["fundort"] == "label" or row["note"] == 2)
        }

    variants = ("alle", "B", "D2 einzeln", "D2 behalten")
    table: dict[str, Any] = {}
    for variant in variants:
        per_run: dict[str, Any] = {}
        for run in RUNS:
            counted = sum(len(shown_by(variant, f"{topic['thema']}|{run}")) for topic in topics())
            shares = {}
            for index, notes in enumerate(raters, 1):
                for least, name in ((2, "passend"), (1, "mindestens_beruehrt")):
                    values = [
                        estimate(topic, notes, {r: shown_by(variant, f"{topic['thema']}|{r}") for r in RUNS}, least)[run]
                        for topic in topics()
                    ]
                    known = [value for value in values if value is not None]
                    shares[f"{name}_{index}"] = round(statistics.mean(known), 3) if known else None
                    shares[f"themen_{index}"] = len(known)
            per_run[run] = {"elemente": counted, **shares}
        table[variant] = per_run

    sample = [(topic["thema"], row) for topic in topics() for row in topic["stichprobe"]]
    lost: dict[str, Any] = {}
    for variant in variants:
        counts: Counter[str] = Counter()
        for thema, row in sample:
            run = "mit_fach" if row["schicht"] == "mit_fach" else "ohne_fach"
            shown = row["iri"] in shown_by(variant, f"{thema}|{run}")
            for index, notes in enumerate(raters, 1):
                note = notes[(thema, row["iri"])]
                counts[f"note{note}_{'gezeigt' if shown else 'nicht_gezeigt'}_{index}"] += 1
        lost[variant] = dict(sorted(counts.items()))

    agreement: dict[str, Any] = {}
    for index, notes in enumerate(raters, 1):
        pairs = Counter()
        for thema, row in sample:
            run = "mit_fach" if row["schicht"] == "mit_fach" else "ohne_fach"
            element = checked[f"{thema}|{run}"]["elemente"].get(row["iri"])
            if element is not None:
                pairs[f"gutachter {notes[(thema, row['iri'])]} / llm {element['note']}"] += 1
        agreement[f"gutachter_{index}"] = dict(sorted(pairs.items()))

    def auc(scores_pos: list[float], scores_neg: list[float]) -> float | None:
        if not scores_pos or not scores_neg:
            return None
        wins = sum((p > n) + 0.5 * (p == n) for p in scores_pos for n in scores_neg)
        return round(wins / (len(scores_pos) * len(scores_neg)), 3)

    m2v: dict[str, Any] = {}
    for field_name in ("text", "mit_bereich"):
        for index, notes in enumerate(raters, 1):
            two = [similarity[f"{t}|{r['iri']}"][field_name] for t, r in sample if notes[(t, r["iri"])] == 2]
            zero = [similarity[f"{t}|{r['iri']}"][field_name] for t, r in sample if notes[(t, r["iri"])] == 0]
            below = [similarity[f"{t}|{r['iri']}"][field_name] for t, r in sample if notes[(t, r["iri"])] < 2]
            m2v[f"{field_name}_{index}"] = {"auc_2_gegen_0": auc(two, zero), "auc_2_gegen_0_1": auc(two, below)}

    cost: dict[str, Any] = {}
    for run in RUNS:
        rows = [checked[f"{topic['thema']}|{run}"] for topic in topics()]
        cost[run] = {
            "tokens_median": statistics.median(row["tokens"] for row in rows),
            "tokens_max": max(row["tokens"] for row in rows),
            "tokens_summe": sum(row["tokens"] for row in rows),
            "sekunden_median": statistics.median(row["sekunden"] for row in rows),
            "sekunden_max": max(row["sekunden"] for row in rows),
            "regeln_sekunden_median": statistics.median(rules[f"{t['thema']}|{run}"]["sekunden"] for t in topics()),
            "geprueft": sum(len(row["elemente"]) for row in rows),
            "verworfen": sum(row["verworfen"] for row in rows),
            "rueckfall": dict(sum((Counter(row["rueckfall"]) for row in rows), Counter())),
        }

    requests = {
        key: {
            "elemente": len(row["elemente"]),
            "gebuendelt_regeln": rules[key]["gebuendelt"],
            "verworfen": row["verworfen"],
            "beantwortet": row["beantwortet"],
            "tokens": row["tokens"],
            "aufrufe": row["aufrufe"],
            "sekunden": row["sekunden"],
            "sekunden_regeln": rules[key]["sekunden"],
            "rueckfall": row["rueckfall"],
        }
        for key, row in checked.items()
    }
    rows = []
    for thema, row in sample:
        run = "mit_fach" if row["schicht"] == "mit_fach" else "ohne_fach"
        found = checked[f"{thema}|{run}"]["elemente"].get(row["iri"])
        rows.append(
            {
                "thema": thema,
                "iri": row["iri"],
                "schicht": row["schicht"],
                "fundort": rules[f"{thema}|{run}"]["elemente"].get(row["iri"]),  # None: gone since the rules of A
                "llm": found["note"] if found else None,
                "noten": [notes[(thema, row["iri"])] for notes in raters],
                "m2v": similarity[f"{thema}|{row['iri']}"],
            }
        )
    result = {
        "varianten": table,
        "stichprobe": lost,
        "llm_gegen_gutachter": agreement,
        "m2v": m2v,
        "kosten": cost,
        "anfragen": requests,
        "stichprobe_zeilen": rows,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    step, *paths = sys.argv[1:]
    if step == "rules":
        rules_step(Path(paths[0]))
    elif step == "check":
        check_step(Path(paths[0]))
    elif step == "m2v":
        m2v_step(paths[0], Path(paths[1]))
    elif step == "evaluate":
        evaluate_step(Path(paths[0]), Path(paths[1]), Path(paths[2]), Path(paths[3]))
    else:
        raise SystemExit(__doc__)
