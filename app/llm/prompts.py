"""Prompt registry (PLAN.md 7): every prompt has an id and a version; both are recorded in the frontmatter.

Prompts are German because the compendia are (D15). Only the user part is a format template; the system
part is used verbatim, so JSON examples there need no escaped braces.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    system: str
    user: str

    @property
    def tag(self) -> str:
        return f"{self.id}@v{self.version}"

    def render(self, **fields: object) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system}, {"role": "user", "content": self.user.format(**fields)}]


SECTION_SYNTHESIS = Prompt(
    id="section_synthesis",
    version=2,  # v2 (2026-09-18): no restating of the task, no conclusions beyond the evidence
    system=(
        "Du formulierst einen Baustein eines kompendialen Textes für Lehrkräfte auf Deutsch. Du verwendest "
        "ausschließlich die nummerierten Belege aus der Anfrage und erfindest nichts hinzu. Jeder Satz endet vor "
        "dem Satzzeichen mit mindestens einer Belegnummer in eckigen Klammern, zum Beispiel: Licht breitet sich "
        "geradlinig aus [2]. Sätze ohne Beleg werden gestrichen. Nenne nur Nummern, die in den Belegen vorkommen. "
        "Schreibe zusammenhängende Absätze in sachlichem Ton: keine Überschriften, keine Aufzählungen, keine "
        "Einleitungs- oder Schlussfloskeln, keine Wiederholung des Bausteintitels, keine Definitionen in Fettdruck. "
        "Die Angaben zu Aufgabe, Inhalt und Abgrenzung des Bausteins steuern nur deine Auswahl aus den Belegen: "
        "Gib sie nicht wieder und schreibe nicht, was nicht in den Baustein gehört. Ziehe keine eigenen "
        "Schlussfolgerungen und verallgemeinere nicht über die Belege hinaus."
    ),
    user=(
        "Thema: {topic}\n"
        "Baustein: {title}\n"
        "Aufgabe des Bausteins: {description}\n"
        "Gehört hinein: {inclusions}\n"
        "Gehört nicht hinein: {exclusions}\n"
        "Unterpunkte:\n{sub_items}\n"
        "Ziellänge: etwa {target_chars} Zeichen.\n\n"
        "Belege:\n{evidence}\n\n"
        "Schreibe jetzt den Baustein."
    ),
)

# enrichment=model-knowledge (docs/umbau.md U4): its own prompt id rather than a version of SECTION_SYNTHESIS,
# so the frontmatter says which of the two wrote a block instead of only that the prompt changed.
SECTION_ENRICHMENT = Prompt(
    id="section_enrichment",
    version=1,  # v1 (2026-09-20): the model may add its own knowledge, but only without an evidence number
    system=(
        "Du formulierst einen Baustein eines kompendialen Textes für Lehrkräfte auf Deutsch. Grundlage sind die "
        "nummerierten Belege aus der Anfrage. Jeder Satz, der aus einem Beleg stammt, endet vor dem Satzzeichen mit "
        "mindestens einer Belegnummer in eckigen Klammern, zum Beispiel: Licht breitet sich geradlinig aus [2]. "
        "Du darfst darüber hinaus gesichertes eigenes Fachwissen ergänzen, wenn es den Baustein verständlicher oder "
        "vollständiger macht. Solche Sätze schreibst du ohne jede Belegnummer — sie werden im Ergebnis als "
        "Modellwissen gekennzeichnet. Setze niemals eine Nummer an einen Satz, den der Beleg nicht hergibt, und "
        "ergänze nichts, dessen du dir nicht sicher bist. Der Baustein bleibt überwiegend belegt: Ergänze höchstens "
        "einen von drei Sätzen aus eigenem Wissen. Nenne nur Nummern, die in den Belegen vorkommen. "
        "Schreibe zusammenhängende Absätze in sachlichem Ton: keine Überschriften, keine Aufzählungen, keine "
        "Einleitungs- oder Schlussfloskeln, keine Wiederholung des Bausteintitels, keine Definitionen in Fettdruck. "
        "Die Angaben zu Aufgabe, Inhalt und Abgrenzung des Bausteins steuern nur deine Auswahl: Gib sie nicht wieder "
        "und schreibe nicht, was nicht in den Baustein gehört."
    ),
    user=SECTION_SYNTHESIS.user,
)

PASSAGE_SELECTION = Prompt(
    id="passage_selection",
    version=1,
    system=(
        "Du wählst für einen Baustein eines kompendialen Textes für Lehrkräfte die passenden Sätze aus nummerierten "
        "Textstellen aus. Du schreibst selbst keinen Text, du nennst nur die Nummern der Sätze. Wähle Sätze, die zur "
        "Aufgabe des Bausteins passen und zu dem, was hineingehört. Lass Sätze weg, die unter „Gehört nicht hinein“ "
        "fallen, nichts zum Thema beitragen oder ohne ihren Zusammenhang unverständlich sind. Wähle so viele Sätze, "
        "wie die Ziellänge braucht, aber keine unpassenden, nur um sie zu erreichen. Nenne die Textstellen in der "
        "Reihenfolge, in der sie im Baustein stehen sollen; innerhalb einer Textstelle bleiben die Sätze in ihrer "
        "Reihenfolge. Antworte ausschließlich mit einem JSON-Objekt wie "
        '{"saetze": ["1.1", "1.2", "3.1"]}; passt kein Satz, antworte {"saetze": []}. Keine Erklärungen.'
    ),
    user=(
        "Thema: {topic}\n"
        "Baustein: {title}\n"
        "Aufgabe des Bausteins: {description}\n"
        "Gehört hinein: {inclusions}\n"
        "Gehört nicht hinein: {exclusions}\n"
        "Unterpunkte:\n{sub_items}\n"
        "Ziellänge: etwa {target_chars} Zeichen.\n\n"
        "Textstellen:\n{passages}\n\n"
        "Gib das JSON-Objekt zurück."
    ),
)

# matcher=llm (D34): the prompt measured against the gold standard on 2026-09-23 (docs/entwicklung/03-matching.md)
PARAGRAPH_ASSIGNMENT = Prompt(
    id="paragraph_assignment",
    version=1,
    system=(
        "Du ordnest Absätze aus Lexikonartikeln den Bausteinen eines Kompendiums für Lehrkräfte zu "
        "(WirLernenOnline). Jeder Absatz gehört in genau einen Baustein oder in keinen. Antworte ausschließlich mit "
        'einem JSON-Objekt, das jede Absatz-ID auf [Baustein-Schlüssel oder "keiner", Sicherheit von 0 bis 1] '
        'abbildet, zum Beispiel {"p1": ["fachinhalte", 0.8], "p2": ["keiner", 0.9]}.'
    ),
    user=(
        "Thema des Kompendiums: {topic}\n\n"
        "Bausteine:\n{blocks}\n\n"
        "{rules}"
        "Absätze:\n{paragraphs}\n\n"
        "Gib das JSON-Objekt zurück."
    ),
)

QA_PAIRS = Prompt(
    id="qa_pairs",
    version=2,  # v2 (2026-09-21): the fixed system text permits the third field the levels ask for
    system=(
        "Du schreibst Frage-Antwort-Paare zu einem Text für Lehrkräfte auf Deutsch. Stütze jede Antwort "
        "ausschließlich auf den Text und erfinde nichts hinzu. Schreibe je Zeile genau ein Paar in der Form "
        "Frage;Antwort - und, wenn die Anfrage Stufen nennt, Frage;Antwort;Stufe. Keine Nummerierung, keine "
        "Aufzählungszeichen, keine weiteren Zeilen. Die Fragen sollen "
        "unterschiedliche Stellen des Textes abdecken."
    ),
    user=("Text:\n{text}\n\nSchreibe {count} Paare, jede Antwort höchstens {max_answer_length} Zeichen.{levels}"),
)

PROMPTS: dict[str, Prompt] = {
    p.id: p for p in (SECTION_SYNTHESIS, SECTION_ENRICHMENT, PASSAGE_SELECTION, PARAGRAPH_ASSIGNMENT, QA_PAIRS)
}


def get_prompt(prompt_id: str) -> Prompt:
    return PROMPTS[prompt_id]
