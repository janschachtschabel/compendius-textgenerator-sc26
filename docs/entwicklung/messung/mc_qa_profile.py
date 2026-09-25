"""The pairs of /qa per profile (M29): the free parse of llm-free against the LLM of the other profiles.

On the part-1 texts of the four compendia of the measurement of 2026-09-22 (docs/umbau.md: Optik, Ernst Abbe,
Französische Revolution, Photosynthese), made by the profile llm-free, as /qa asks about them (the prose of the
content blocks, without the generated ones). Per text 20 pairs asked of parse-based and of llm (gpt-6-luna), with
time and, for the LLM, calls and tokens.

Two steps, since the spaCy model lives in the image and the b-api key in the .env of the host (never printed):
- in the image: python /tmp/mc_qa_profile.py parse /tmp/m29_parse.json  - makes the texts and the parse pairs
- on the host (project venv, project root): python docs/entwicklung/messung/mc_qa_profile.py llm <m29_parse.json> <m29_llm.json>
- then: python docs/entwicklung/messung/mc_qa_profile.py sheet <m29_parse.json> <m29_llm.json> <sheet.json> <key.json> writes the judging
  sheet without the methods - per text the source and the pairs of both in a fixed shuffled order under neutral
  ids - and the key from id to method apart from it, so the judges do not know which stage wrote a pair.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

TOPICS = ["Optik", "Ernst Abbe", "Französische Revolution", "Photosynthese"]
COUNT, MAX_ANSWER = 20, 300
SEED = 20260929


def rows(pairs: Any) -> list[dict[str, str]]:
    return [{"frage": pair.question, "antwort": pair.answer} for pair in pairs]


def parse_step(out: Path) -> None:
    from app.api.v2.qa import _text_of_compendium
    from app.cli_common import cli_service
    from app.domain.requests import GenerateRequest
    from app.knowledge.recognise import load_spacy
    from app.synthesis.qa_parse import parse_based_pairs

    service = cli_service(None)
    nlp = load_spacy(service.settings.spacy_model)
    if nlp is None:
        raise SystemExit("spaCy-Modell fehlt")
    result: dict[str, Any] = {}
    for topic in TOPICS:
        compendium = service.generate(GenerateRequest(topic=topic, preset="llm-free", parts=["world"]))
        text = _text_of_compendium(compendium)
        started = time.perf_counter()
        pairs = parse_based_pairs(text[:50_000], limit=COUNT, max_answer_length=MAX_ANSWER, nlp=nlp)
        seconds = time.perf_counter() - started
        result[topic] = {"text": text, "parse": {"paare": rows(pairs), "sekunden": round(seconds, 3)}}
        print(f"{topic:25} Zeichen {len(text):6} parse {len(pairs):2} in {seconds:.2f} s", flush=True)
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
        started = time.perf_counter()
        answer = llm.qa.pairs(
            texts[topic]["text"], count=COUNT, max_answer_length=MAX_ANSWER, budget=budget, deadline=Deadline(120)
        )
        seconds = time.perf_counter() - started
        written = answer if isinstance(answer, list) else []
        result[topic] = {
            "paare": rows(written),
            "sekunden": round(seconds, 2),
            "tokens": budget.used,
            "ausfall": None if isinstance(answer, list) else repr(answer),
        }
        print(f"{topic:25} llm {len(written):2} in {seconds:.1f} s, {budget.used} Tokens", flush=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


def sheet_step(parse_file: Path, llm_file: Path, sheet_file: Path, key_file: Path) -> None:
    parsed = json.loads(parse_file.read_text(encoding="utf-8"))
    written = json.loads(llm_file.read_text(encoding="utf-8"))
    sheet, key = [], {}
    for number, topic in enumerate(TOPICS, 1):
        items = [("parse", row) for row in parsed[topic]["parse"]["paare"]]
        items += [("llm", row) for row in written[topic]["paare"]]
        random.Random(f"{SEED}:{topic}").shuffle(items)
        entries = []
        for index, (method, row) in enumerate(items, 1):
            pair_id = f"{number}-{index:02d}"
            key[pair_id] = method
            entries.append({"id": pair_id, **row})
        sheet.append({"thema": topic, "text": parsed[topic]["text"], "paare": entries})
    sheet_file.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    key_file.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sum(len(t['paare']) for t in sheet)} Paare im Bogen")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    step, *paths = sys.argv[1:]
    if step == "parse":
        parse_step(Path(paths[0]))
    elif step == "llm":
        llm_step(Path(paths[0]), Path(paths[1]))
    else:
        sheet_step(*(Path(path) for path in paths))
