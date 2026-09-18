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

SLOT_ROUTER = Prompt(
    id="slot_router",
    version=1,
    system=(
        "Du ordnest Textabschnitte den Bausteinen eines Kompendium-Templates zu. Wähle für jeden Abschnitt genau "
        "einen der für ihn angebotenen Bausteine, und zwar den, in dem der Abschnitt inhaltlich am besten "
        "aufgehoben ist. Antworte ausschließlich mit einem JSON-Objekt, das Abschnitts-IDs auf Baustein-IDs "
        'abbildet, zum Beispiel {"a1": "sc26_3", "a2": "sc26_10"}. Keine Erklärungen.'
    ),
    user=(
        "Bausteine:\n{slots}\n\n"
        "Abschnitte (jeweils mit den möglichen Bausteinen):\n{chunks}\n\n"
        "Gib das JSON-Objekt zurück."
    ),
)

PROMPTS: dict[str, Prompt] = {p.id: p for p in (SECTION_SYNTHESIS, SLOT_ROUTER)}


def get_prompt(prompt_id: str) -> Prompt:
    return PROMPTS[prompt_id]
