"""The model knowledge of prompt section_enrichment v2 against v1 (M31): the six topics of M27 and M28 once more.

M28 found two thirds of the model knowledge of v1 fillers. D56 asks for a checkable fact or nothing. This runs
best-quality-generated on the six topics of M27 through CompendiumService.generate, as M27 did; the article choice
and the assignment ask the b-api the same prompts as then and come back from its cache, so the two versions differ
only in how the blocks were written. Per topic: time, calls, tokens, marked sentences and the part-1 text; the texts
hold Wikipedia text and stay outside the repository.

Two steps (project venv, from the project root; B_API_KEY in .env, never printed):
- python docs/entwicklung/messung/mc_modellwissen_v2.py run <out.json> <texts_dir> --m2v <model directory>
- python docs/entwicklung/messung/mc_modellwissen_v2.py sheet <m27 texts_dir> <texts_dir> <judge_dir>
  writes the blind material of M28 again: per topic the v1 text and the v2 text as A and B in a seeded order, the
  comments and the visible label taken out, the sentences of model knowledge of both in one shuffled list per topic,
  and two keys apart from the judge folder (text -> version, sentence -> version).
- python docs/entwicklung/messung/mc_modellwissen_v2.py evaluate <keys.json> <judge1.json> <judge2.json> <out.json>
  sorts the verdicts of the two judges back onto the versions.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

TOPICS = ["Zellatmung", "Elektrischer Widerstand", "Kolonialismus", "Lineare Gleichung", "Renaissance", "Klimazonen"]
PROFILE = "best-quality-generated"
SEED = 20260926
DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
MARKED = re.compile(r"<!-- f: Evidenzgrad=Modellwissen -->(.*?)<!-- /f -->", re.DOTALL)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LABEL = " [Modellwissen]"


def run_step(out: Path, texts: Path, m2v: str) -> None:
    os.environ["LLM_ENABLED"] = "true"
    os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
    os.environ["LLM_MAX_TOKENS_PER_REQUEST"] = "100000"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from app.cli_common import cli_service
    from app.domain.requests import GenerateRequest
    from app.llm.prompts import get_prompt

    if out.exists():
        raise SystemExit(f"{out} gibt es schon; jeder Lauf bekommt eine eigene Datei")
    texts.mkdir(parents=True, exist_ok=True)
    service = cli_service(ZIMS)
    service.settings.model2vec_path = m2v
    if service.llm is None or service.llm_unavailable() is not None:
        raise SystemExit(f"LLM nicht verfügbar: {service.llm_unavailable()}")
    runs: dict[str, Any] = {"prompt": get_prompt("section_enrichment").tag, "themen": {}}
    for topic in TOPICS:
        started = time.perf_counter()
        result = service.generate(GenerateRequest(topic=topic, preset=PROFILE, parts=["world"]))  # type: ignore[arg-type]
        seconds = round(time.perf_counter() - started, 2)
        tokens = result.audit.llm_tokens or {}
        enrichment = (result.frontmatter.get("llm") or {}).get("enrichment") or {}
        text = "\n\n".join(f"## {section.title}\n\n{section.text}" for section in result.sections if section.text)
        (texts / f"{topic}__{PROFILE}.md").write_text(text, encoding="utf-8")
        runs["themen"][topic] = {
            "hauptartikel": result.resolution.title,
            "sekunden": seconds,
            "aufrufe": tokens.get("calls", 0),
            "tokens": tokens.get("total", 0),
            "modellwissen_saetze": enrichment.get("marked_sentences", 0),
            "prompts": (result.frontmatter.get("llm") or {}).get("prompts"),
        }
        row = runs["themen"][topic]
        print(f"{topic:24} {seconds:6.1f} s {row['tokens']:6} Tok, Modellwissen {row['modellwissen_saetze']}", flush=True)
    out.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")


def blind(text: str) -> str:
    """The text as the judges see it: no comments, no visible label, no trace of which version wrote it."""
    return re.sub(r"[ \t]{2,}", " ", COMMENT.sub("", text.replace(LABEL, "")))


def sheet_step(old_dir: Path, new_dir: Path, judges: Path) -> None:
    judges.mkdir(parents=True, exist_ok=True)
    text_key: dict[str, str] = {}
    sentence_key: dict[str, dict[str, str]] = {}
    sentences: dict[str, list[str]] = {}
    for topic in TOPICS:
        versions = {
            "v1": (old_dir / f"{topic}__{PROFILE}.md").read_text(encoding="utf-8"),
            "v2": (new_dir / f"{topic}__{PROFILE}.md").read_text(encoding="utf-8"),
        }
        order = ["v1", "v2"]
        random.Random(f"{SEED}:{topic}").shuffle(order)
        for label, version in zip(("A", "B"), order, strict=True):
            (judges / f"{topic}__{label}.md").write_text(blind(versions[version]), encoding="utf-8")
            text_key[f"{topic}__{label}"] = version
        marked = [
            (" ".join(found.replace(LABEL, "").split()), version)
            for version, text in versions.items()
            for found in MARKED.findall(text)
        ]
        random.Random(f"{SEED}:{topic}:saetze").shuffle(marked)
        sentences[topic] = [sentence for sentence, _ in marked]
        sentence_key[topic] = {sentence[:60]: version for sentence, version in marked}
        counts = {version: sum(1 for _, v in marked if v == version) for version in versions}
        print(f"{topic:24} A={text_key[f'{topic}__A']} Modellwissen v1 {counts['v1']:2} v2 {counts['v2']:2}")
    (judges / "modellwissen_saetze.json").write_text(json.dumps(sentences, ensure_ascii=False, indent=1), encoding="utf-8")
    keys = judges.parent / f"{judges.name}_schluessel.json"
    keys.write_text(json.dumps({"texte": text_key, "saetze": sentence_key}, ensure_ascii=False, indent=1), encoding="utf-8")


def _signature(text: str) -> str:
    """Letters and digits only: judges escape a formula's backslashes and cut their 60 characters where they like."""
    return re.sub(r"\W", "", text).casefold()


def _version_of(sentence: str, known: dict[str, str]) -> str | None:
    """The version a judged sentence came from, by as much of its beginning as both sides have (at most 45)."""
    judged = _signature(sentence)
    for prefix, version in known.items():
        own = _signature(prefix)
        length = min(len(own), len(judged), 45)
        if length >= 20 and own[:length] == judged[:length]:
            return version
    return None


def evaluate_step(keys_file: Path, judge_files: list[Path], out: Path) -> None:
    """Means of the text scores per version, preferences, and the judged sentences of model knowledge per version."""
    keys = json.loads(keys_file.read_text(encoding="utf-8"))
    judges = [json.loads(path.read_text(encoding="utf-8")) for path in judge_files]
    scores: dict[str, dict[str, list[float]]] = {}
    errors: dict[str, int] = {}
    preferred: dict[str, int] = {}
    for judge in judges:
        for topic, rating in judge["themen"].items():
            for label in ("A", "B"):
                version = keys["texte"][f"{topic}__{label}"]
                sheet = rating[label]
                for field in ("lesbarkeit", "zusammenhang", "passend_zum_thema", "fuellsaetze"):
                    scores.setdefault(version, {}).setdefault(field, []).append(float(sheet[field]))
                errors[version] = errors.get(version, 0) + len(sheet.get("fachfehler") or [])
            choice = rating["vorzug"]
            winner = keys["texte"][f"{topic}__{choice}"] if choice in ("A", "B") else "gleich"
            preferred[winner] = preferred.get(winner, 0) + 1
    sentences: dict[str, dict[str, Any]] = {}
    unmatched = 0
    for number, judge in enumerate(judges, 1):
        for topic, rated in judge["modellwissen"].items():
            for row in rated:
                version = _version_of(row["satz"], keys["saetze"].get(topic, {}))
                if version is None:
                    unmatched += 1
                    continue
                entry = sentences.setdefault(version, {"saetze": 0})
                entry["saetze"] += 1
                for field in ("korrekt", "nutzen"):
                    key = f"g{number}_{field}_{row[field]}"
                    entry[key] = entry.get(key, 0) + 1
    result = {
        "mittel": {v: {f: round(sum(x) / len(x), 2) for f, x in fields.items()} for v, fields in scores.items()},
        "fachfehler_summe": errors,
        "vorzug": preferred,
        "modellwissen": sentences,
        "nicht_zugeordnet": unmatched,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    step, *args = sys.argv[1:]
    if step == "run":
        run_step(Path(args[0]), Path(args[1]), args[args.index("--m2v") + 1])
    elif step == "sheet":
        sheet_step(Path(args[0]), Path(args[1]), Path(args[2]))
    else:
        evaluate_step(Path(args[0]), [Path(args[1]), Path(args[2])], Path(args[3]))
