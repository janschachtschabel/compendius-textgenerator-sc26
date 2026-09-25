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

# article_choice=llm (D35): the prompt measured against the gold of eval/artikelwahl on 2026-09-23 (M8)
ARTICLE_CHOICE = Prompt(
    id="article_choice",
    version=1,
    system=(
        "Du wählst für ein Unterrichtsthema den Wikipedia-Artikel aus, auf dem ein Kompendium für Lehrkräfte "
        "aufbauen soll. Gesucht ist der Artikel, der das Thema so behandelt, wie es im genannten Schulfach gemeint "
        "ist. Die Kandidaten sind nummeriert, jeweils mit dem Anfang des Artikels. Antworte ausschließlich mit einem "
        'JSON-Objekt wie {"wahl": 3, "titel": ""}. Passt keiner der Kandidaten, antworte mit "wahl": 0 und nenne '
        'unter "titel" den genauen Titel des deutschsprachigen Wikipedia-Artikels, der das Thema behandelt, wenn du '
        'ihn sicher kennst; sonst bleibt "titel" leer. Keine Erklärungen.'
    ),
    user="Thema: {topic}\nSchulfach: {subject}\n\nKandidaten:\n{candidates}\n\nGib das JSON-Objekt zurück.",
)

# article_choice=llm (D35): the prompt of the M8 judge (docs/entwicklung/messung/mc_artikel_richter.py), measured as
# a filter for the full-text hits of the corpus on 2026-09-23
HIT_CHECK = Prompt(
    id="hit_check",
    version=1,
    system=(
        "Du beurteilst, welche Lexikonartikel in ein Kompendium für Lehrkräfte zu einem Unterrichtsthema gehören. "
        "Vergib je Artikel eine Note: 2 = gehört zum Thema (das Thema selbst, ein Teilgebiet, ein Kernbegriff, ein "
        "zentraler Vorgang, ein zentrales Ereignis oder eine Person, deren Bedeutung im Thema liegt); 1 = verwandt "
        "(Nachbarthema, direkter Oberbegriff, Hintergrund, einzelnes Werk als Beispiel, Person mit breiterem Wirken, "
        "allgemeiner Artikel zu einem beteiligten Stoff); 0 = passt nicht (andere Bedeutung, Begriffsklärung, Liste, "
        "Film gleichen Namens, weit entfernter Oberbegriff oder kein erkennbarer Bezug). Antworte ausschließlich mit "
        'einem JSON-Objekt, das jede Artikel-ID auf ihre Note abbildet, zum Beispiel {"a1": 2, "a2": 0}.'
    ),
    user="Thema des Kompendiums: {topic}\n\nArtikel:\n{articles}\n\nGib das JSON-Objekt zurück.",
)

# article_choice=llm for a material without a topic (D47): the question of M21 S4 and M23 KL word for word
# (docs/entwicklung/messung/materialwege.py), which found the article of 30 of 31 materials with a clear topic
NODE_TOPIC = Prompt(
    id="node_topic",
    version=1,
    system=(
        "Du bestimmst für ein Unterrichtsmaterial das fachliche Thema, zu dem ein Kompendium für Lehrkräfte "
        'geschrieben werden soll. Antworte ausschließlich mit einem JSON-Objekt wie {"titel": "..."}: dem genauen '
        'Titel des deutschsprachigen Wikipedia-Artikels zu diesem Thema, oder "", wenn das Material kein fachliches '
        "Thema hat. Keine Erklärungen."
    ),
    user=(
        "Titel: {title}\nFächer: {subjects}\nSchlagwörter: {keywords}\nBeschreibung: {description}\n\n"
        "Gib das JSON-Objekt zurück."
    ),
)

# article_choice=llm for a topic sent along with a material (D47): the teacher's topic leads, the material says how it
# is meant, and the model names the material's own article as well, which joins the corpus when it links with the
# main article
NODE_TOPIC_WITH_TOPIC = Prompt(
    id="node_topic_with_topic",
    version=1,
    system=(
        "Du bestimmst für ein Unterrichtsthema, das eine Lehrkraft zu einem Unterrichtsmaterial angegeben hat, den "
        "Wikipedia-Artikel, auf dem ein Kompendium für Lehrkräfte aufbauen soll. Das Thema der Lehrkraft hat "
        "Vorrang; Titel, Fächer, Schlagwörter und Beschreibung des Materials zeigen, wie es gemeint ist. Antworte "
        'ausschließlich mit einem JSON-Objekt wie {"titel": "...", "material": "..."}: unter "titel" der genaue '
        'Titel des deutschsprachigen Wikipedia-Artikels zum Thema der Lehrkraft, unter "material" der genaue Titel '
        'des Artikels, von dem das Material selbst handelt, oder "", wenn es derselbe ist oder das Material kein '
        "fachliches Thema hat. Keine Erklärungen."
    ),
    user=(
        "Thema der Lehrkraft: {topic}\nTitel des Materials: {title}\nFächer: {subjects}\nSchlagwörter: {keywords}\n"
        "Beschreibung: {description}\n\nGib das JSON-Objekt zurück."
    ),
)

QA_PAIRS = Prompt(
    id="qa_pairs",
    # v2 (2026-09-21): the fixed system text permits the third field the levels ask for
    # v3 (2026-09-25): an optional focus on the material a node names (D47); without a node the text is v2's
    version=3,
    system=(
        "Du schreibst Frage-Antwort-Paare zu einem Text für Lehrkräfte auf Deutsch. Stütze jede Antwort "
        "ausschließlich auf den Text und erfinde nichts hinzu. Schreibe je Zeile genau ein Paar in der Form "
        "Frage;Antwort - und, wenn die Anfrage Stufen nennt, Frage;Antwort;Stufe. Keine Nummerierung, keine "
        "Aufzählungszeichen, keine weiteren Zeilen. Die Fragen sollen "
        "unterschiedliche Stellen des Textes abdecken."
    ),
    user="Text:\n{text}\n\nSchreibe {count} Paare, jede Antwort höchstens {max_answer_length} Zeichen.{levels}{focus}",
)

PROMPTS: dict[str, Prompt] = {
    p.id: p
    for p in (
        SECTION_SYNTHESIS,
        SECTION_ENRICHMENT,
        PASSAGE_SELECTION,
        PARAGRAPH_ASSIGNMENT,
        ARTICLE_CHOICE,
        HIT_CHECK,
        NODE_TOPIC,
        NODE_TOPIC_WITH_TOPIC,
        QA_PAIRS,
    )
}


def get_prompt(prompt_id: str) -> Prompt:
    return PROMPTS[prompt_id]
