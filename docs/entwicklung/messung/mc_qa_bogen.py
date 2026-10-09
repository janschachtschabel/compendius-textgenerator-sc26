"""Messskript M82 (09.10.2026): ein blinder Bogen für die QA-Paare zweier Profile, je Thema als Satz A und B.

Liest zwei Läufe von ``mc_reasoning.py qa`` (die Ausgabe nach JSON-START) und schreibt in <ordner> den Bogen
(qa_bogen.md) und die Anleitung (anleitung.md), den Schlüssel daneben in den Ordner darüber, damit die Gutachter ihn
nicht sehen. Die Reihenfolge je Thema kommt aus der Saat. Ausgewertet wird mit mc_funktionen_auswertung.py, nachdem
Paare, Schlüssel und Urteile in ergebnisse/m82_funktionen.json stehen (qa.paare, qa.schluessel, qa.urteile).

  python docs/entwicklung/messung/mc_qa_bogen.py <profil>=<lauf.txt> <profil>=<lauf.txt> <ordner> [--seed=82]
"""

import json
import random
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

INSTRUCTIONS = """Du bist Fachgutachterin oder Fachgutachter für Unterrichtsmaterial. Die Datei, deren Pfad du bekommst, enthält zu
sechs Themen je zwei Sätze von Frage-Antwort-Paaren (Satz A und Satz B), wie sie eine Lehrkraft für Übungen,
Lernkarten oder Quizfragen zu diesem Thema nutzen würde. Die Sätze stammen aus verschiedenen Verfahren; welches
Verfahren welchen Satz schrieb, ist unbekannt und spielt für dich keine Rolle.

Bewerte jedes Paar für sich mit einer Note:

- **2**: brauchbar, wie es ist. Die Frage ist klar und eindeutig, die Antwort ist sachlich richtig, beantwortet genau
  diese Frage und gehört zum Thema.
- **1**: mit Mängeln brauchbar. Etwa eine unscharfe oder holprige Frage, eine unvollständige, zu lange oder zu
  allgemeine Antwort, eine Frage am Rand des Themas oder eine sehr triviale Frage.
- **0**: unbrauchbar. Die Antwort ist falsch, beantwortet die Frage nicht oder passt nicht zu ihr, die Frage ist
  unverständlich oder hat mit dem Thema nichts zu tun.

Zähle je Satz außerdem die Antworten, die du mit guter Sicherheit für sachlich falsch hältst (**falsch**), und sage
je Thema, welcher Satz einer Lehrkraft insgesamt mehr nützt (**besser**: „A“, „B“ oder „gleich“). Bewerte nach
Inhalt, nicht nach der Zahl der Paare; fehlt ein Satz ganz, ist der andere besser.

Antworte ausschließlich mit einem JSON-Objekt in genau dieser Form, je Satz so viele Noten, wie er Paare hat, ohne
weiteren Text:

{"<Thema>": {"A": {"noten": [2, 1, 2, 0, 2], "falsch": 0}, "B": {"noten": [2, 2, 2, 1, 2], "falsch": 0}, "besser": "B"}, …}
"""


def pairs_of(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8").split("JSON-START", 1)[1])["ergebnis"]
    return {row["topic"]: row.get("pairs") or [] for row in data}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seed = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--seed=")), "82"))
    runs = {name: pairs_of(Path(path)) for name, path in (a.split("=", 1) for a in args[:2])}
    folder = Path(args[2])
    rng = random.Random(seed)
    key: dict[str, dict[str, str]] = {}
    lines: list[str] = []
    first = next(iter(runs.values()))
    for topic in first:
        order = list(runs)
        rng.shuffle(order)
        key[topic] = dict(zip("AB", order, strict=True))
        lines.append(f"## {topic}\n")
        for letter, name in key[topic].items():
            lines.append(f"### Satz {letter}\n")
            pairs = runs[name][topic]
            if not pairs:
                lines.append("*(Keine Paare.)*\n")
            for number, pair in enumerate(pairs, 1):
                lines.append(f"{number}. Frage: {pair['question']}\n   Antwort: {pair['answer']}\n")
        lines.append("")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "qa_bogen.md").write_text("\n".join(lines), encoding="utf-8")
    (folder / "anleitung.md").write_text(INSTRUCTIONS, encoding="utf-8")
    (folder.parent / "qa_schluessel.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(key)} Themen, Bogen und Anleitung in {folder}, Schlüssel in {folder.parent}")


if __name__ == "__main__":
    main()
