"""The QA stages after D55 (M30): the new rules against the templates, the parse, the small models and the LLM.

On part 1 of llm-free for six topics, as /qa asks about it since D55 (the prose of the content blocks, and for the
rules the glossary and the actors of the compendium): the four M29 topics (Optik, Ernst Abbe, Französische
Revolution, Photosynthese) and two that no rule was tuned on (Zellteilung, Weimarer Republik). Per text 20 pairs of
each stage, with time; for the LLM also calls and tokens.

Four steps, since the spaCy model and the two small models live in the image and the b-api key in the .env of the
host (never printed):
- in the image: python /tmp/mc_qa_stufen.py free /tmp/m30_free.json - makes the texts and the pairs of the rules,
  the old templates, the parse and the small models (the models are loaded before the clock starts)
- on the host (project venv, project root): python docs/entwicklung/messung/mc_qa_stufen.py llm <m30_free.json>
  <m30_llm.json>
- then: python docs/entwicklung/messung/mc_qa_stufen.py sheet <m30_free.json> <m30_llm.json> <dir> writes two judging
  sheets (three topics each; the text with glossary and actors, the pairs of rules, parse, models and LLM in a fixed
  shuffled order under neutral ids) and the key apart from them. The old templates are counted, not judged: M29
  and the D55 report show what they ask.
- and: python docs/entwicklung/messung/mc_qa_stufen.py summary <m30_free.json> <m30_llm.json> <out.json> counts
  per stage the pairs, the question openings, the time questions, the seconds and the tokens of the LLM; the
  verdicts are sorted back with mc_richter_auswertung.qa.
"""

from __future__ import annotations

import json
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

TOPICS = ["Optik", "Ernst Abbe", "Französische Revolution", "Photosynthese", "Zellteilung", "Weimarer Republik"]
COUNT, MAX_ANSWER = 20, 300
SEED = 20260926
JUDGED = ("regeln", "parse", "modelle", "llm")
TIME_QUESTION = re.compile(r"^(?:Wann|Seit wann|Bis wann|In welchem Jahr|Was geschah im Jahr)\b")


def rows(pairs: Any) -> list[dict[str, str]]:
    return [{"frage": pair.question, "antwort": pair.answer} for pair in pairs]


def shape(pairs: list[dict[str, str]]) -> dict[str, Any]:
    """What the pairs look like without a judge: how many, how many question openings, how many ask for a time."""
    return {
        "paare": len(pairs),
        "anfaenge": len({pair["frage"].split()[0] for pair in pairs}),
        "zeitfragen": sum(1 for pair in pairs if TIME_QUESTION.match(pair["frage"])),
    }


def timed(call: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    result = call()
    return result, round(time.perf_counter() - started, 3)


def free_step(out: Path) -> None:
    from app.api.v2.qa import _knowledge
    from app.cli_common import cli_service
    from app.domain.requests import GenerateRequest
    from app.knowledge.recognise import load_spacy
    from app.synthesis.qa import rule_based_pairs
    from app.synthesis.qa_models import answer_candidates, load_qa_models, model_pairs
    from app.synthesis.qa_parse import parse_based_pairs
    from app.synthesis.qa_rules import rule_pairs

    service = cli_service(None)
    nlp = load_spacy(service.settings.spacy_model)
    models = load_qa_models(service.settings.qg_model_path, service.settings.qa_model_path)
    if nlp is None or models is None:
        raise SystemExit("spaCy-Modell oder QA-Modelle fehlen")
    nlp("Ein Satz zum Aufwärmen.")

    def by_models(text: str) -> list[Any]:
        prepared = " ".join(text[:50_000].split())
        return model_pairs(answer_candidates(nlp(prepared), prepared), models, count=COUNT, max_answer_length=MAX_ANSWER)

    result: dict[str, Any] = {}
    for topic in TOPICS:
        compendium = service.generate(GenerateRequest(topic=topic, preset="llm-free", parts=["world"]))
        knowledge = _knowledge(compendium)
        stages = {
            "regeln": lambda k=knowledge: rule_pairs(
                k.text, nlp=nlp, count=COUNT, max_answer_length=MAX_ANSWER, topic=k.topic, glossary=k.glossary,
                actors=k.actors,
            ),
            "vorlagen": lambda k=knowledge: rule_based_pairs(k.text, limit=COUNT, max_answer_length=MAX_ANSWER, nlp=nlp),
            "parse": lambda k=knowledge: parse_based_pairs(k.text, limit=COUNT, max_answer_length=MAX_ANSWER, nlp=nlp),
            "modelle": lambda k=knowledge: by_models(k.text),
        }  # fmt: skip
        entry: dict[str, Any] = {
            "titel": knowledge.topic,
            "text": knowledge.text,
            "glossar": knowledge.glossary,
            "akteure": knowledge.actors,
        }
        for name, call in stages.items():
            pairs, seconds = timed(call)
            entry[name] = {"paare": rows(pairs), "sekunden": seconds}
        result[topic] = entry
        counts = " ".join(f"{name} {len(entry[name]['paare']):2} in {entry[name]['sekunden']:5.2f} s" for name in stages)
        print(f"{topic:25} Zeichen {len(knowledge.text):6}  {counts}", flush=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


def llm_step(source: Path, out: Path) -> None:
    os.environ["LLM_ENABLED"] = "true"
    os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
    from app.llm.deadline import Deadline
    from app.main import build_llm
    from app.settings import get_settings

    llm = build_llm(get_settings())
    if llm is None:
        raise SystemExit("LLM nicht konfiguriert")
    texts = json.loads(source.read_text(encoding="utf-8"))
    result: dict[str, Any] = {}
    for topic in TOPICS:
        budget = llm.open_budget()
        answer, seconds = timed(
            lambda t=topic, b=budget: llm.qa.pairs(
                texts[t]["text"], count=COUNT, max_answer_length=MAX_ANSWER, budget=b, deadline=Deadline(120)
            )
        )
        written = answer if isinstance(answer, list) else []
        result[topic] = {
            "paare": rows(written),
            "sekunden": seconds,
            "tokens": budget.used,
            "ausfall": None if isinstance(answer, list) else repr(answer),
        }
        print(f"{topic:25} llm {len(written):2} in {seconds:.1f} s, {budget.used} Tokens", flush=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


def sheet_step(free_file: Path, llm_file: Path, folder: Path) -> None:
    free = json.loads(free_file.read_text(encoding="utf-8"))
    written = json.loads(llm_file.read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    key: dict[str, str] = {}
    sheets: list[list[dict[str, Any]]] = [[], []]
    for number, topic in enumerate(TOPICS, 1):
        entry = free[topic]
        pairs = {name: entry[name]["paare"] for name in JUDGED if name != "llm"} | {"llm": written[topic]["paare"]}
        items = [(name, row) for name in JUDGED for row in pairs[name]]
        random.Random(f"{SEED}:{topic}").shuffle(items)
        entries = []
        for index, (method, row) in enumerate(items, 1):
            pair_id = f"{number}-{index:02d}"
            key[pair_id] = method
            entries.append({"id": pair_id, **row})
        text = entry["text"]
        for heading, block in (("Glossar", entry["glossar"]), ("Akteure", entry["akteure"])):
            if block.strip():
                text += f"\n\n## {heading}\n\n{block}"
        sheets[(number - 1) // 3].append({"thema": topic, "text": text, "paare": entries})
    for index, sheet in enumerate(sheets, 1):
        (folder / f"bogen_{index}.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"bogen_{index}.json: {sum(len(t['paare']) for t in sheet)} Paare")
    (folder.parent / f"{folder.name}_schluessel.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def summary_step(free_file: Path, llm_file: Path, out: Path) -> None:
    """The unjudged side: pairs, openings, time questions and seconds per stage, and the tokens of the LLM."""
    free = json.loads(free_file.read_text(encoding="utf-8"))
    written = json.loads(llm_file.read_text(encoding="utf-8"))
    stages = ("regeln", "vorlagen", "parse", "modelle", "llm")
    result: dict[str, Any] = {"themen": TOPICS, "je_thema": {}, "zusammen": {}}
    for topic in TOPICS:
        row = {name: free[topic][name] for name in stages if name != "llm"} | {"llm": written[topic]}
        result["je_thema"][topic] = {
            name: {**shape(row[name]["paare"]), "sekunden": row[name]["sekunden"]} for name in stages
        } | {"llm_tokens": written[topic]["tokens"], "zeichen": len(free[topic]["text"])}
    for name in stages:
        per_topic = [result["je_thema"][topic][name] for topic in TOPICS]
        result["zusammen"][name] = {
            "paare": sum(p["paare"] for p in per_topic),
            "voll_20": sum(1 for p in per_topic if p["paare"] >= COUNT),
            "zeitfragen": sum(p["zeitfragen"] for p in per_topic),
            "anfaenge_median": statistics.median(p["anfaenge"] for p in per_topic),
            "sekunden_median": statistics.median(p["sekunden"] for p in per_topic),
        }
    result["zusammen"]["llm"]["tokens_median"] = statistics.median(written[t]["tokens"] for t in TOPICS)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["zusammen"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    step, *paths = sys.argv[1:]
    if step == "free":
        free_step(Path(paths[0]))
    elif step == "llm":
        llm_step(Path(paths[0]), Path(paths[1]))
    elif step == "sheet":
        sheet_step(Path(paths[0]), Path(paths[1]), Path(paths[2]))
    else:
        summary_step(Path(paths[0]), Path(paths[1]), Path(paths[2]))
