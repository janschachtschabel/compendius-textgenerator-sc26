"""M47: blind sheets for the gradings of best-coverage-generated (D69) - per topic the three variants of
mc_kompendium_profil.py as A, B, C in a seeded random order, without citation numbers and model knowledge labels, cut
to the blocks 1-4 and 8-10 of sc26 (definition, structure, content, context; education, regulations, practice). The
sheets, the key and the instructions go into one folder outside the repository; the instructions are those below.

Usage: python mc_abdeckung_boegen.py <runs.json> <folder> <topics_per_sheet>
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

KEPT = ("1 · ", "2 · ", "3 · ", "4 · ", "8 · ", "9 · ", "10 · ")
INSTRUCTIONS = """Du bist Fachgutachterin oder Fachgutachter für Unterrichtsmaterial. Die Datei, deren Pfad du bekommst, enthält zu
mehreren Themen je drei Texte (A bis C). Jeder Text ist ein Auszug aus einem Kompendium für Lehrkräfte: die Bausteine 1
bis 4 (Themendefinition, Gliederung, Fachinhalte, gesellschaftlicher Kontext) und 8 bis 10 (Bildung, Regularien,
Praxis). Die Texte stammen aus verschiedenen Verfahren; welches Verfahren welchen Text schrieb, ist unbekannt und spielt
für dich keine Rolle. Belegnummern und Kennzeichnungen wurden entfernt.

Lies jedes Thema ganz und bewerte jeden Text für sich:

1. **passung** (1 bis 5): Behandelt der Text genau das angefragte Thema, einschließlich seines Aspekts? Bei „OER-Förderungen“
   ist die Förderung offener Bildungsmaterialien gemeint, nicht offene Bildungsmaterialien allgemein; bei „Inklusion im
   Sportunterricht“ die Inklusion im Sportunterricht, nicht Inklusion oder Sportunterricht allgemein.
   5 = durchgehend genau beim Thema, 4 = überwiegend, 3 = etwa zur Hälfte, 2 = nur am Rand, 1 = behandelt den Oberbegriff
   oder etwas anderes.
2. **nutzen** (1 bis 5): Wie viel konkrete, brauchbare Information zum Thema bekommt eine Lehrkraft? 5 = viele konkrete,
   fachlich tragfähige Aussagen (Begriffe, Beispiele, Zusammenhänge, Fakten), 1 = fast nur allgemeine Sätze ohne Gehalt.
3. **vollstaendigkeit** (1 bis 5): Füllt der Text jeden seiner Bausteine gehaltvoll mit dem, was dort zum Thema gehört?
   5 = jeder Baustein deckt seine Aufgabe für das Thema gut ab, 3 = einige Bausteine sind dünn, leer oder verfehlen ihre
   Aufgabe, 1 = die meisten Bausteine sind leer, dünn oder handeln von etwas anderem.
4. **fehler**: Aussagen, die du für sachlich falsch oder erfunden hältst, etwa ein Programm, das es nicht gibt, eine
   falsche Jahreszahl, eine falsche Zuordnung. Je Fund ein kurzes wörtliches Zitat (höchstens 20 Wörter), der Grund und die
   Schwere: „schwer“ (würde eine Lehrkraft in die Irre führen) oder „leicht“ (ungenau, missverständlich). Liste nur, was du
   mit guter Sicherheit für falsch hältst; Unsicheres lässt du weg.

Bewerte unabhängig von der Länge und vom Stil. Antworte ausschließlich mit einem JSON-Objekt in genau dieser Form, ohne
weiteren Text:

{"<Thema>": {"A": {"passung": 4, "nutzen": 3, "vollstaendigkeit": 4, "fehler": [{"zitat": "…", "grund": "…", "schwere": "leicht"}]},
             "B": {…}, "C": {…}}, …}
"""


def main() -> None:
    rows = [r for r in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) if "text" in r]
    folder, per_sheet = Path(sys.argv[2]), int(sys.argv[3])
    folder.mkdir(parents=True, exist_ok=True)
    by_topic: dict[str, list[dict]] = {}
    for row in rows:
        by_topic.setdefault(row["topic"], []).append(row)
    rng = random.Random(47)
    key: dict[str, dict[str, str]] = {}
    topics = list(by_topic)
    sheets = 0
    for start in range(0, len(topics), per_sheet):
        sheets += 1
        parts: list[str] = []
        for topic in topics[start : start + per_sheet]:
            runs = by_topic[topic]
            rng.shuffle(runs)
            key[topic] = {}
            parts.append(f"## Thema: {topic}\n")
            for letter, run in zip("ABC", runs, strict=True):
                key[topic][letter] = run["variant"]
                text = re.sub(r"\s*\[(?:\d+(?:,\s*\d+)*|Modellwissen)\]", "", run["text"])
                blocks = [b.strip() for b in re.split(r"(?m)^### ", text) if b.strip()]
                kept = [b for b in blocks if b.startswith(KEPT)]
                parts.append(f"### Text {letter}\n\n" + "\n\n".join("#### " + b for b in kept) + "\n")
        (folder / f"bogen_{sheets}.md").write_text("\n".join(parts), encoding="utf-8")
    (folder / "schluessel.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "anleitung.md").write_text(INSTRUCTIONS, encoding="utf-8")
    print(f"{len(by_topic)} Themen, {sum(len(v) for v in key.values())} Texte, {sheets} Bögen")


if __name__ == "__main__":
    main()
