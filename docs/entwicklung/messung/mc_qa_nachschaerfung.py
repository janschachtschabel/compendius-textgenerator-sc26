"""The QA rules after D60 on the texts of M30 (M34): sharpened questions, the glossary and actors filling up.

M30 judged 96 pairs of the rule stage on part 1 of six compendiums (two blind Claude judges). D60 sharpens the rules
where M30 found them wrong - a second verb joined by "und", a verb of measure asked "Was", a question about nothing -
and lets the glossary and the actors fill up before a sentence is asked a second time (Jan). This runs the rules of
a code state on the same six texts and knowledge as M30 and judges the pairs under the same conditions:

- pairs <m30_free.json> <out.json>: in the image, where spaCy is; PYTHONPATH picks the code state to measure (the
  installed one, or a copy of the working tree). 20 pairs per text as in M30, with kind, origin and whether the
  sentence was asked before.
- sheets <m30 sheets dir> <m30_qa.json> <pairs.json> <out dir>: the M30 sheets with the pairs of the rule stage
  swapped for the new ones - same texts, the pairs of the other stages at their places - numbered anew, and the key.
- evaluate <m30_qa.json> <m30 sheets dir> <old pairs.json> <new pairs.json> <key.json> <out.json> <verdict files>:
  the verdict files are the answers of the two judges, <judge>_<sheet>.json; counts per rule state and kind, and how
  well the judges agree with those of M30 on the pairs of the other stages, which did not change.

The M30 sheets and texts stay outside the repository; the result file holds ids, stages, kinds and verdicts, no texts.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

COUNT, MAX_ANSWER = 20, 300  # as in M30
FILLERS = ("Begriff", "Person", "Akteur")


def pairs_step(free_path: Path, out: Path) -> None:
    from app.knowledge.recognise import load_spacy
    from app.knowledge.segmentation import split_sentences
    from app.synthesis.qa import cut
    from app.synthesis.qa_questions import clause_questions
    from app.synthesis.qa_rules import (
        Candidate,
        _usable,
        actor_candidates,
        choose,
        glossary_candidates,
        is_person,
        template_questions,
    )
    from app.synthesis.qa_words import parse_ready

    free = json.loads(free_path.read_text(encoding="utf-8"))
    nlp = load_spacy("de_core_news_md")
    result: dict[str, Any] = {}
    for topic, entry in free.items():
        text, title = entry["text"], entry["titel"]
        sentences = [s for s in split_sentences(" ".join(text.split())) if _usable(s)]
        person = title if is_person(title, nlp) else ""
        candidates = []
        for index, (sentence, doc) in enumerate(zip(sentences, nlp.pipe([parse_ready(s) for s in sentences]), strict=True)):
            questions = template_questions(sentence, doc) + clause_questions(doc, topic=title, person=person)
            candidates.extend(Candidate(f"s{index}", q.kind, q.text, sentence) for q in questions)
        candidates.extend(glossary_candidates(entry.get("glossar", ""), nlp))
        candidates.extend(actor_candidates(entry.get("akteure", "")))
        seen: set[str] = set()
        rows = []
        for chosen in choose(candidates, COUNT):
            rows.append(
                {
                    "frage": chosen.question,
                    "antwort": cut(chosen.answer, MAX_ANSWER),
                    "art": chosen.kind,
                    "herkunft": chosen.origin,
                    "wiederholt": chosen.origin in seen,
                }
            )
            seen.add(chosen.origin)
        result[topic] = rows
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print({topic: len(rows) for topic, rows in result.items()})


def sheets_step(sheets_dir: Path, m30_path: Path, pairs_path: Path, out_dir: Path) -> None:
    stage = json.loads(m30_path.read_text(encoding="utf-8"))["verfahren_je_id"]
    new_rules = json.loads(pairs_path.read_text(encoding="utf-8"))
    key: dict[str, dict[str, str]] = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for sheet_number in (1, 2):
        sheet = json.loads((sheets_dir / f"bogen_{sheet_number}.json").read_text(encoding="utf-8"))
        for topic_index, topic in enumerate(sheet):
            fresh = list(new_rules[topic["thema"]])
            pairs: list[tuple[dict[str, str], str, str]] = []
            for pair in topic["paare"]:
                if stage[pair["id"]] == "regeln":
                    if fresh:
                        rule = fresh.pop(0)
                        pairs.append(({"stage": "regeln_neu"}, rule["frage"], rule["antwort"]))
                else:
                    pairs.append(({"stage": stage[pair["id"]], "m30": pair["id"]}, pair["frage"], pair["antwort"]))
            pairs += [({"stage": "regeln_neu"}, rule["frage"], rule["antwort"]) for rule in fresh]
            numbered = []
            for number, (origin, question, answer) in enumerate(pairs, start=1):
                pair_id = f"{sheet_number}{topic_index + 1}-{number:02d}"
                key[pair_id] = {**origin, "thema": topic["thema"], "frage": question}
                numbered.append({"id": pair_id, "frage": question, "antwort": answer})
            topic["paare"] = numbered
        target = out_dir / f"bogen_{sheet_number}.json"
        target.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "schluessel.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(Counter(origin["stage"] for origin in key.values()))


def _flawless(verdicts: list[dict[str, Any]]) -> bool:
    return all(verdict["mangelfrei"] for verdict in verdicts)


def evaluate_step(argv: list[str]) -> None:
    m30_path, sheets_dir, old_path, new_path, key_path, out = (Path(a) for a in argv[:6])
    m30 = json.loads(m30_path.read_text(encoding="utf-8"))
    stage, m30_verdicts = m30["verfahren_je_id"], m30["urteile"]
    key = json.loads(key_path.read_text(encoding="utf-8"))
    judges: dict[str, dict[str, Any]] = defaultdict(dict)
    for verdict_file in argv[6:]:
        judge = Path(verdict_file).stem.split("_")[0]
        judges[judge].update(json.loads(Path(verdict_file).read_text(encoding="utf-8")))
    names = sorted(judges)
    judged_m30: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sheet in sheets_dir.glob("bogen_*.json"):
        for topic in json.loads(sheet.read_text(encoding="utf-8")):
            for pair in topic["paare"]:
                verdicts = [m30_verdicts[f"gutachter_{n}"][pair["id"]] for n in (1, 2)]
                judged_m30[(topic["thema"], pair["frage"])] = verdicts

    def rule_state(pairs_path: Path, verdict_of: Any) -> dict[str, Any]:
        pairs = json.loads(pairs_path.read_text(encoding="utf-8"))
        tally: dict[str, Counter[str]] = defaultdict(Counter)
        for topic, rows in pairs.items():
            for row in rows:
                group = (
                    "wiederholung"
                    if row["wiederholt"]
                    else ("fueller" if row["art"] in FILLERS else ("glossar" if row["herkunft"].startswith("g") else "text"))
                )
                verdicts = verdict_of(topic, row["frage"])
                label = "unbewertet" if verdicts is None else ("mangelfrei" if _flawless(verdicts) else "mangel")
                tally[group][label] += 1
                tally["alle"][label] += 1
        return {"paare": sum(len(rows) for rows in pairs.values()), "je_herkunft": {g: dict(c) for g, c in tally.items()}}

    new_by_question = {  # only the new rule pairs: another stage may ask the very same question
        (origin["thema"], origin["frage"]): pair_id for pair_id, origin in key.items() if origin["stage"] == "regeln_neu"
    }
    old_state = rule_state(old_path, lambda topic, question: judged_m30.get((topic, question)))
    new_state = rule_state(
        new_path, lambda topic, question: [judges[n][new_by_question[(topic, question)]] for n in names]
    )
    flaws: Counter[str] = Counter()
    for pair_id, origin in key.items():
        if origin["stage"] == "regeln_neu":
            for name in names:
                if not judges[name][pair_id]["mangelfrei"]:
                    flaws[judges[name][pair_id]["mangel"]] += 1
    # the pairs of the other stages did not change: how the judges of M34 read them next to those of M30
    agreement: dict[str, Any] = {}
    for other in ("llm", "parse", "modelle"):
        ids = [(pair_id, origin["m30"]) for pair_id, origin in key.items() if origin["stage"] == other]
        agreement[other] = {
            "paare": len(ids),
            "mangelfrei_m30": sum(_flawless([m30_verdicts[f"gutachter_{n}"][old] for n in (1, 2)]) for _, old in ids),
            "mangelfrei_m34": sum(_flawless([judges[n][new] for n in names]) for new, _ in ids),
        }
    result = {
        "beschreibung": "M34: Regeln nach D60 auf den sechs Texten von M30, je 20 Paare; die Paare der Regeln in den "
        "Bögen von M30 ersetzt, zwei blinde Claude-Gutachter; ohne Texte und Paare",
        "regeln_vorher_urteile_m30": old_state,
        "regeln_nachher_urteile_m34": new_state,
        "maengel_nachher": dict(flaws),
        "abgleich_andere_verfahren": agreement,
        "verfahren_je_id": {pair_id: origin["stage"] for pair_id, origin in key.items()},
        "urteile": {name: judges[name] for name in names},
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in list(result)[1:5]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    step = sys.argv[1]
    if step == "pairs":
        pairs_step(Path(sys.argv[2]), Path(sys.argv[3]))
    elif step == "sheets":
        sheets_step(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
    elif step == "evaluate":
        evaluate_step(sys.argv[2:])
    else:
        raise SystemExit(f"unknown step {step!r}: pairs, sheets or evaluate")
