"""M48: blind sheets for the comparison of the five profiles (D70) - per topic the five profiles of
mc_kompendium_profil.py as A to E in a seeded random order, without citation numbers and model knowledge labels, cut
to the blocks 1-4 and 8-10 of sc26 as in M47. One sheet per kind of topic (simple, group, aspect); the sheets, the key
and the instructions go into one folder outside the repository; the instructions are those below.

Usage: python mc_profilvergleich_boegen.py <runs.json> <folder> [--variants=a,b,c] [--seed=48]
  --variants: the variants of the runs to compare, in their order (M49: three); default the five profiles of M48
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

PROFILES = ("llm-free", "balanced", "best-quality", "best-quality-generated", "best-coverage-generated")
KINDS = {
    "einfach": ("Optik", "Photosynthese", "Französische Revolution"),
    "Sammelthema": ("Dichter aus dem Mittelalter", "Komponisten der Klassik", "Philosophen der Aufklärung"),
    "Aspekt": ("OER-Förderungen", "Inklusion im Sportunterricht", "Künstliche Intelligenz im Unterricht"),
}
KEPT = ("1 · ", "2 · ", "3 · ", "4 · ", "8 · ", "9 · ", "10 · ")
LETTERS = "ABCDE"
COUNT_WORDS = {2: "zwei", 3: "drei", 4: "vier", 5: "fünf"}
NO_TEXT = "*(Kein Text: Das Verfahren lieferte zu diesem Thema nichts.)*"
INSTRUCTIONS = """Du bist Fachgutachterin oder Fachgutachter für Unterrichtsmaterial. Die Datei, deren Pfad du bekommst, enthält zu
drei Themen je fünf Texte (A bis E). Jeder Text ist ein Auszug aus einem Kompendium für Lehrkräfte: die Bausteine 1
bis 4 (Themendefinition, Gliederung, Fachinhalte, gesellschaftlicher Kontext) und 8 bis 10 (Bildung, Regularien,
Praxis). Ein Baustein fehlt, wenn ein Verfahren nichts für ihn fand. Die Texte stammen aus verschiedenen Verfahren;
welches Verfahren welchen Text schrieb, ist unbekannt und spielt für dich keine Rolle. Belegnummern und
Kennzeichnungen wurden entfernt.

Lies jedes Thema ganz und bewerte jeden Text für sich:

1. **passung** (1 bis 5): Behandelt der Text genau das angefragte Thema? Bei einem Begriff wie „Optik“ das Fachgebiet
   selbst. Bei einer Gruppe wie „Dichter aus dem Mittelalter“ die Gruppe: mehrere ihrer Vertreter und was sie
   verbindet, nicht nur einen von ihnen und nicht die Epoche oder den Oberbegriff allgemein. Bei einem Thema mit Aspekt
   wie „OER-Förderungen“ genau diesen Aspekt: die Förderung offener Bildungsmaterialien, nicht offene
   Bildungsmaterialien allgemein. 5 = durchgehend genau beim Thema, 4 = überwiegend, 3 = etwa zur Hälfte, 2 = nur am
   Rand, 1 = behandelt den Oberbegriff, einen einzelnen Teil oder etwas anderes.
2. **nutzen** (1 bis 5): Wie viel konkrete, brauchbare Information zum Thema bekommt eine Lehrkraft? 5 = viele konkrete,
   fachlich tragfähige Aussagen (Begriffe, Beispiele, Zusammenhänge, Fakten), 1 = fast nur allgemeine Sätze ohne Gehalt.
3. **vollstaendigkeit** (1 bis 5): Füllt der Text jeden der sieben Bausteine gehaltvoll mit dem, was dort zum Thema
   gehört? Ein fehlender Baustein zählt wie ein leerer. 5 = jeder Baustein deckt seine Aufgabe für das Thema gut ab,
   3 = einige Bausteine sind dünn, leer oder verfehlen ihre Aufgabe, 1 = die meisten Bausteine sind leer, dünn oder
   handeln von etwas anderem.
4. **lesbarkeit** (1 bis 5): Liest sich der Text als zusammenhängender Text für Lehrkräfte? 5 = flüssig, jeder Baustein
   gut gegliedert, 3 = verständlich, aber mit Brüchen, Wiederholungen oder Sätzen ohne Zusammenhang, 1 = kaum lesbar:
   Bruchstücke, Listen ohne Bezug, abgerissene Sätze.
5. **fehler**: Aussagen, die du für sachlich falsch oder erfunden hältst, etwa ein Programm, das es nicht gibt, eine
   falsche Jahreszahl, eine falsche Zuordnung. Je Fund ein kurzes wörtliches Zitat (höchstens 20 Wörter), der Grund und die
   Schwere: „schwer“ (würde eine Lehrkraft in die Irre führen) oder „leicht“ (ungenau, missverständlich). Liste nur, was du
   mit guter Sicherheit für falsch hältst; Unsicheres lässt du weg.

Passung, Nutzen und Vollständigkeit bewertest du unabhängig von Länge und Stil; den Stil bewertet nur die Lesbarkeit.
Antworte ausschließlich mit einem JSON-Objekt in genau dieser Form, ohne weiteren Text:

{"<Thema>": {"A": {"passung": 4, "nutzen": 3, "vollstaendigkeit": 4, "lesbarkeit": 3, "fehler": [{"zitat": "…", "grund": "…", "schwere": "leicht"}]},
             "B": {…}, "C": {…}, "D": {…}, "E": {…}}, …}
"""


def excerpt(text: str) -> str:
    """The blocks 1-4 and 8-10, without citation numbers and model knowledge labels."""
    text = re.sub(r"\s*\[(?:\d+(?:,\s*\d+)*|Modellwissen)\]", "", text)
    blocks = [b.strip() for b in re.split(r"(?m)^### ", text) if b.strip()]
    return "\n\n".join("#### " + b for b in blocks if b.startswith(KEPT))


def instructions(count: int) -> str:
    """The instructions for ``count`` texts per topic; for five the words of M48."""
    letters = LETTERS[:count]
    text = INSTRUCTIONS.replace("je fünf Texte (A bis E)", f"je {COUNT_WORDS[count]} Texte (A bis {letters[-1]})")
    return text.replace('"B": {…}, "C": {…}, "D": {…}, "E": {…}}', ", ".join(f'"{x}": {{…}}' for x in letters[1:]) + "}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    variants = tuple(options["variants"].split(",")) if "variants" in options else PROFILES
    runs = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    folder = Path(args[1])
    folder.mkdir(parents=True, exist_ok=True)
    found = {(r["topic"], r["variant"]): r for r in runs}
    rng = random.Random(int(options.get("seed", 48)))
    key: dict[str, dict[str, str]] = {}
    for number, (kind, topics) in enumerate(KINDS.items(), start=1):
        parts: list[str] = []
        for topic in topics:
            order = list(variants)
            rng.shuffle(order)
            key[topic] = dict(zip(LETTERS[: len(variants)], order, strict=True))
            parts.append(f"## Thema: {topic}\n")
            for letter, profile in key[topic].items():
                run = found.get((topic, profile), {})  # a profile that found no topic wrote nothing: graded as such
                parts.append(f"### Text {letter}\n\n{excerpt(run['text']) if 'text' in run else NO_TEXT}\n")
        (folder / f"bogen_{number}_{kind}.md").write_text("\n".join(parts), encoding="utf-8")
    (folder / "schluessel.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "anleitung.md").write_text(instructions(len(variants)), encoding="utf-8")
    print(f"{len(key)} Themen, {sum(len(v) for v in key.values())} Texte, {len(KINDS)} Bögen")


if __name__ == "__main__":
    main()
