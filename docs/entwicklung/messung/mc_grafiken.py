"""Charts of the development docs as plain SVG (project venv, no LLM): the decision paper (07-entscheidungsvorlage.md),
old and new service (01-alt-und-neu.md), and methods, measurements and profiles (09-methoden-und-profile.md).

Reads the raw files in ergebnisse/ and the relevance gold of eval/artikelwahl, and writes prozess.svg,
prozess_optionen.svg, artikelwahl.svg, korpus.svg, zuordnung_guete_zeit.svg, zuordnung_bausteine.svg,
text_schalter.svg, kombinationen.svg, kiwix_quellen.svg and quellen_empfehlung.svg (page 07, the last also on
page 02), qualitaet_zeit_kosten.svg and alt_neu_teile.svg (page 01), profile_matrix.svg, profilvergleich.svg,
profiluebersicht.svg (pages 07 and 09), and endpunkte.svg, profile_verlauf.svg and one verfahren_*.svg per step
(page 09). Numbers no raw file holds are written here with their source: the text switches (measured on
2026-09-18 and 19, 02-weltwissen.md) and the step times of the server (M1, 05-messprotokoll.md). No chart
library, so the files render on GitHub, in Confluence and in a browser alike.
Rounding half up, German number format.

Usage: python mc_grafiken.py <ergebnisse-dir> <bilder-dir>
"""

from __future__ import annotations

import json
import math
import sys
import textwrap
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DIR, OUT = Path(sys.argv[1]), Path(sys.argv[2])
LABELS = Path(__file__).resolve().parents[3] / "eval" / "artikelwahl" / "korpus_labels.yaml"
FONT = "Segoe UI, Helvetica Neue, Arial, sans-serif"
INK, MUTED, GRID, PAPER, PANEL = "#1f2933", "#52606d", "#dde2e8", "#ffffff", "#f3f6fa"
OLD, LOCAL, LLM = "#9aa5b1", "#2f6db5", "#d9822b"
TINT = {LOCAL: "#9dbde6", LLM: "#f2c28f", "#7a5aa6": "#c3b2dc", MUTED: "#bcc4ce"}  # lighter part of a bar: the span of runs
FITS, RELATED, UNFIT = "#3a8f5c", "#a9ccb4", "#c8553d"
CHAR_WIDTH = 0.56  # average glyph width per font size, for layout checks
SLOTS = {"fachinhalte": "Fachinhalte", "entwicklung_ausblick": "Entwicklung & Ausblick",
         "systematik": "Gliederung & Systematik", "gesellschaftlicher_kontext": "Gesellschaftlicher Kontext",
         "themendefinition": "Themendefinition", "praxis": "Praxis", "beruf_wirtschaft": "Beruf & Wirtschaft",
         "bildung": "Bildung", "querschnitt": "Querschnitt & Bezüge", "regularien": "Regularien & Rahmensetzung"}


def load(name: str) -> dict:
    return json.loads((DIR / name).read_text(encoding="utf-8"))


def de(value: float, places: str = "1") -> str:
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{rounded:,}".replace(",", "X").replace(".", ",").replace("X", ".")


def secs(value: float, small: str = "0.01") -> str:
    return de(value, small if value < 5 else "1")


def esc(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self, width: int, height: int, title: str) -> None:
        self.width, self.height, self.title = width, height, title
        self.items = [f'<rect width="{width}" height="{height}" fill="{PAPER}"/>']

    def text(self, x: float, y: float, content: object, size: float = 12, fill: str = INK, anchor: str = "start",
             weight: str = "normal", limit: float | None = None) -> None:
        width = len(str(content)) * size * CHAR_WIDTH
        if limit is not None and width > limit:
            print(f"  zu breit ({width:.0f} > {limit:.0f} px): {content}")
        self.items.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
                          f'text-anchor="{anchor}" font-weight="{weight}">{esc(content)}</text>')

    def rect(self, x: float, y: float, w: float, h: float, fill: str, rx: float = 0, stroke: str = "none",
             sw: float = 1, dash: str | None = None) -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="{rx}" '
                          f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{extra}/>')

    def line(self, x1: float, y1: float, x2: float, y2: float, stroke: str = GRID, sw: float = 1,
             dash: str | None = None) -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
                          f'stroke-width="{sw}"{extra}/>')

    def circle(self, cx: float, cy: float, r: float, fill: str, stroke: str = "none", sw: float = 1) -> None:
        self.items.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" '
                          f'stroke-width="{sw}"/>')

    def arrow(self, x: float, y1: float, y2: float) -> None:
        self.line(x, y1, x, y2 - 6, MUTED, 1.5)
        self.items.append(f'<polygon points="{x - 5:.1f},{y2 - 7:.1f} {x + 5:.1f},{y2 - 7:.1f} {x:.1f},{y2:.1f}" '
                          f'fill="{MUTED}"/>')

    def legend(self, x: float, y: float, entries: list[tuple[str, str]], size: float = 12) -> None:
        for color, label in entries:
            self.rect(x, y - 10, 12, 12, color, 2)
            self.text(x + 18, y, label, size, MUTED)
            x += 18 + len(label) * size * CHAR_WIDTH + 22

    def save(self, name: str) -> None:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
                f'viewBox="0 0 {self.width} {self.height}" font-family="{FONT}" role="img" '
                f'aria-label="{esc(self.title)}"><title>{esc(self.title)}</title>')
        (OUT / name).write_text(head + "\n".join(self.items) + "</svg>\n", encoding="utf-8", newline="\n")
        print(f"{name}: {self.width} x {self.height}")


def prozess() -> None:
    """Teil 1 from the request to the document, with the switch, the profiles that use it and the time of every step
    (release 2.17.0, M82)."""
    steps = [
        ("1", "Hauptartikel finden", "Thema bereinigen, im Archivindex auflösen", False,
         ["Schalter article_choice: rule-based, llm oder llm-thorough",
          "llm-free: rule-based; balanced: llm; die übrigen: llm-thorough",
          "Zeit: rund 0,03 s; mit LLM Frage N, rund 2 s, 310 Tokens (M82)"]),
        ("2", "Korpus bauen", "bis 12 Artikel, höchstens 400 Absätze", False,
         ["Einstellungen: max_articles (12), ZIM_PROFILE (standard)",
          "mit LLM die Artikel aus Übersicht und Teilen des Themas (N, D63)",
          "Zeit: 0,9 s auf dem Server (M45); N zählt zu Schritt 1"]),
        ("3", "Absätze zuordnen", "10 Inhaltsbausteine des Templates SC26", False,
         ["Schalter matcher: hybrid_light, bm25, char_tfidf, lexicon_only, llm",
          "llm-free, balanced: hybrid_light; ab best-quality: llm",
          "Zeit: 0,2 bis 0,7 s; llm rund 10 s, rund 160 Tokens je Absatz (M82)"]),
        ("4", "Text bauen", "Absätze wörtlich, mit Belegnummer", False,
         ["Schalter extraction: rule-based oder llm; Länge: target_length",
          "alle Profile: rule-based, 30.000 Zeichen (D70)",
          "Zeit: 1,1 s auf dem Server; llm rund 11 s"]),
        ("5", "Umformulieren (je Profil)", "LLM schreibt Bausteine neu, Belegprüfung", True,
         ["Schalter generation: rule-based, llm-fast, llm; dazu enrichment",
          "best-quality-generated (Standard), best-coverage-generated: llm",
          "Zeit: llm rund 10 s, im Median rund 19.000 Tokens mehr (M82)"]),
        ("6", "Zusammensetzen", "mit Teil 2 Lehrpläne und Teil 3 Sammlung", False,
         ["Teil 2 und 3 neben Teil 1 (D93); die LLM-Prüfung von Teil 2 2,5 s",
          "Ergebnis: Markdown und JSON, mit Vorspann und Audit",
          "ohne LLM 2,6 s, im Standard 23 s je Kompendium (M82, Teil 1 und 2)"]),
    ]
    llm_steps = {"1", "2", "3", "4", "5"}
    top, row, box_h = 92, 96, 70
    svg = Svg(840, top + row * len(steps) + 40, "Ablauf von Teil 1 mit Schaltern, Profilen und Zeiten")
    svg.text(24, 30, "Teil 1 · Weltwissen: vom Thema zum Kompendium", 17, weight="600")
    svg.rect(24, 44, 300, 30, PANEL, 6, GRID)
    svg.text(174, 64, "Anfrage: topic oder collection_id", 12, MUTED, "middle", limit=290)
    svg.arrow(174, 74, top)
    for index, (number, title, detail, optional, lines) in enumerate(steps):
        y = top + index * row
        fill = PAPER if optional else "#e8f0fa"
        svg.rect(24, y, 300, box_h, fill, 8, LLM if optional else LOCAL, 1.5, "6 4" if optional else None)
        svg.text(40, y + 28, f"{number}  {title}", 14, weight="600", limit=236)
        svg.text(40, y + 50, detail, 11.5, MUTED, limit=276)
        if number in llm_steps:
            svg.rect(284, y + 8, 32, 17, LLM, 8)
            svg.text(300, y + 20.5, "LLM", 10, PAPER, "middle", "600")
        for offset, content in enumerate(lines):
            svg.text(344, y + 20 + offset * 20, content, 12, INK if offset < 2 else MUTED, limit=480)
        if index < len(steps) - 1:
            svg.arrow(174, y + box_h, y + row)
    base = top + row * len(steps) + 14
    svg.legend(24, base + 8, [(LOCAL, "läuft lokal, ohne Tokens"),
                              (LLM, "LLM-Option über die b-api (gpt-6-luna)")])
    svg.save("prozess.svg")


def prozess_optionen() -> None:
    """Every step of the compendium with its options in a row: quality, time, tokens and the profiles that use it
    (D41, D53). Numbers as on page 09; times of the steps without LLM from the server (M45), an LLM step as surcharge."""
    presets = [(profile, PROFILE_COLOR[profile], code) for profile, code in zip(PROFILES, "lbqg", strict=True)]
    rows = {  # step: [(option, default, llm, profiles, quality, time, tokens)]
        ("1", "Hauptartikel finden", "Thema im Archivindex auflösen"): [
            ("rule-based", False, False, "l", "87 von 94 richtig", "0,03 s", "0"),
            ("llm", True, True, "b", "91 von 94 richtig", "+1 s je Frage", "800 je Frage"),
            ("llm-thorough", False, True, "qg", "93 von 94 richtig", "+1 s je Frage", "800 je Frage"),
        ],
        ("2", "Korpus bauen", "bis 12 Artikel, 400 Absätze"): [
            ("Regeln: Links, Volltexttreffer", False, False, "l", "43 % / 71 % passend", "0,9 s", "0"),
            ("N: Übersicht und Teile vom LLM", True, True, "bqg", "87 % / 93 % passend", "+5 s", "rund 500"),
            ("Rückfall: LLM prüft Nebenartikel", False, True, "", "45 % / 73 % passend", "+1,4 bis 2 s", "750–1.400"),
            ("ZIM_PROFILE=extended", False, False, "", "+1 gefüllter Baustein", "–", "0"),
            ("knowledge_collection_id", False, False, "", "nicht gemessen", "–", "0"),
        ],
        ("3", "Absätze zuordnen", "10 Inhaltsbausteine SC26"): [
            ("hybrid_light", True, False, "lb", "macro-F1 0,45", "0,3 s", "0"),
            ("char_tfidf", False, False, "", "macro-F1 0,40", "0,25 s", "0"),
            ("bm25", False, False, "", "macro-F1 0,36", "0,03 s", "0"),
            ("lexicon_only", False, False, "", "macro-F1 0,35", "0,02 s", "0"),
            ("llm", False, True, "qg", "macro-F1 0,70", "+12,7 s", "170 je Absatz"),
        ],
        ("4", "Text bauen", "Absätze wörtlich, belegt"): [
            ("rule-based", True, False, "lbqg", "jeder Satz wörtlich belegt", "0,8 s", "0"),
            ("extraction=llm", False, True, "", "am Gold kein Gewinn", "+11 s", "14.000–22.400"),
        ],
        ("5", "Umformulieren", "optional, mit Belegprüfung"): [
            ("rule-based", True, False, "lbq", "wörtlich, Lesbarkeit 2,5", "–", "0"),
            ("generation=llm-fast", False, True, "", "2 Bausteine neu, belegt", "9 bis 15 s", "2.300–4.000"),
            ("generation=llm", False, True, "g", "alle neu, Lesbarkeit 4,0", "+8,7 s", "4.300–11.600"),
        ],
        ("6", "Teil 2 und 3", "Lehrplanbezüge, Sammlung"): [
            ("Teil 2: Regeln, gebündelt", True, False, "lb", "70 bis 81 % passend", "0,03 s", "0"),
            ("Teil 2: curriculum_check=llm", False, True, "qg", "74 bis 79 % passend", "+6 bis 8 s", "5.100–9.600"),
            ("Teil 3: Sammlung", False, False, "lbqg", "kein Schalter", "0,16 s", "0"),
        ],
    }
    columns = {"option": 282, "stufe": 580, "guete": 656, "zeit": 868, "tokens": 980}
    width, line_h, pad, top = 1100, 24, 8, 88
    option_w = columns["stufe"] - columns["option"] - 12

    def block_height(options: list[tuple[str, bool, bool, str, str, str, str]]) -> int:
        return max(len(options) * line_h + 2 * pad, 64)  # room for the two lines of the step box

    height = top + sum(block_height(options) for options in rows.values()) + 124
    svg = Svg(width, height, "Ablauf des Kompendiums mit allen Optionen, ihrer Güte, Zeit und ihren Tokens")
    svg.text(20, 30, "Das Kompendium: jeder Schritt mit seinen Optionen", 17, weight="600")
    svg.text(20, 52, "Standard ist das Profil balanced (PRESET_DEFAULT, D53); preset wählt ein Profil, einzelne "
             "Schalter gehen vor. Stand: Release 2.2.2, 28.09.2026.", 12, MUTED, limit=width - 40)
    for key, head in (("option", "Option"), ("stufe", "Profil"), ("guete", "Güte"), ("zeit", "Zeit"),
                      ("tokens", "Tokens")):
        svg.text(columns[key], top - 12, head, 12, MUTED, weight="600")
    y = top
    for (number, title, detail), options in rows.items():
        block = block_height(options)
        svg.rect(20, y + 4, 236, block - 8, "#e8f0fa" if number != "5" else PAPER, 8,
                 LOCAL if number != "5" else LLM, 1.5, None if number != "5" else "6 4")
        middle = y + block / 2
        svg.text(34, middle - 4, f"{number}  {title}", 13.5, weight="600", limit=210)
        svg.text(34, middle + 14, detail, 11, MUTED, limit=214)
        svg.line(268, y, width - 8, y, GRID)
        for index, (option, default, llm, uses, quality, time, tokens) in enumerate(options):
            base = y + (block - len(options) * line_h) / 2 + index * line_h + 16
            svg.circle(columns["option"] - 8, base - 4, 4, LLM if llm else LOCAL)
            svg.text(columns["option"], base, option, 12, INK, weight="600" if default else "normal",
                     limit=option_w - 60 if default else option_w)
            if default:
                label_w = len(option) * 12 * CHAR_WIDTH + 8
                svg.rect(columns["option"] + label_w + 4, base - 11, 52, 15, PANEL, 7, GRID)
                svg.text(columns["option"] + label_w + 30, base - 0.5, "Standard", 9.5, MUTED, "middle")
            for slot, (_, color, code) in enumerate(presets):
                if code in uses:
                    svg.rect(columns["stufe"] + slot * 16, base - 10, 11, 11, color, 2)
            svg.text(columns["guete"], base, quality, 12, INK, limit=columns["zeit"] - columns["guete"] - 12)
            svg.text(columns["zeit"], base, time, 12, INK, limit=columns["tokens"] - columns["zeit"] - 10)
            svg.text(columns["tokens"], base, tokens, 12, INK, limit=width - columns["tokens"] - 12)
        y += block
    svg.line(268, y, width - 8, y, GRID)
    svg.legend(20, y + 30, [(LOCAL, "lokal, ohne Tokens"), (LLM, "über das LLM der b-api")], 11.5)
    svg.legend(330, y + 30, [(color, tag) for tag, color, _ in presets], 11.5)
    for number, note in enumerate((
        "Güte: Hauptartikel von 94 Goldanfragen (M35); gedruckte Absätze aus passenden Artikeln, Sammel- / gewöhnliche "
        "Themen (M37, M39); gefüllte Bausteine (M11);",
        "macro-F1 der gelabelten Absätze (M27, M19); Lesbarkeit für Lehrkräfte, 1 bis 5 (M28); Lehrplanelemente, "
        "einzeln gezeigt (M32).",
        "Zeit: Server ohne LLM (M45; Teil 3 M1, die wählbaren Zuordner M15); mit + der Zuschlag des LLM (M35, M45; "
        "extraction=llm und llm-fast vom 18./19.09.2026).",
        "Tokens je Kompendium, bei der Artikelwahl je Frage an das LLM.",
    )):
        svg.text(20, y + 56 + 16 * number, note, 10.5, MUTED, limit=width - 40)
    svg.save("prozess_optionen.svg")


def artikelwahl() -> None:
    """Main article right per kind of query, old state, rules and rules with LLM (M9, three gold sets)."""
    old = load("m9_aufloesung_alt.json")
    rules = load("m9_aufloesung_regeln.json")["ergebnisse"]
    llm = load("m9_aufloesung_llm.json")["ergebnisse"]
    rows = [(a, r, m) for name in old for a, r, m in zip(old[name], rules[name], llm[name], strict=True)]
    kinds = {"mehrdeutig_mit_fach": "mehrdeutig, Fach als Kontext", "normal": "normale Themen",
             "variante": "Schreibvariante, Mehrzahl", "ohne_eigenen_artikel": "ohne gleichnamigen Artikel",
             "zusatz": "mit Klassen- oder Fachzusatz", "mehrdeutig_ohne_kontext": "mehrdeutig, ohne Kontext"}
    groups = [("alle Anfragen", rows)] + [(label, [r for r in rows if r[0]["art"] == kind])
                                          for kind, label in kinds.items()]
    ways = [("v2.0.0", OLD), ("Regeln (rule-based)", LOCAL), ("Regeln und LLM (llm)", LLM)]
    bar, gap, group_gap, x0, width = 13, 3, 20, 280, 390
    height = 84 + len(groups) * (3 * (bar + gap) + group_gap) + 20
    svg = Svg(760, height, "Hauptartikel richtig je Art der Anfrage")
    svg.text(24, 30, "Hauptartikel richtig, 94 Anfragen in drei Goldsätzen (M9)", 17, weight="600")
    svg.legend(24, 58, [(color, label) for label, color in ways])
    y = 84
    for index in range(0, 101, 25):
        x = x0 + width * index / 100
        svg.line(x, y - 6, x, height - 30, GRID)
        svg.text(x, height - 14, f"{index} %", 11, MUTED, "middle")
    for label, part in groups:
        svg.text(x0 - 12, y + 26, f"{label} ({len(part)})", 12.5, INK, "end",
                 "600" if label == "alle Anfragen" else "normal", limit=x0 - 30)
        for column, (_, color) in enumerate(ways):
            right = sum(r[column]["richtig"] for r in part)
            svg.rect(x0, y, width * right / len(part), bar, color, 2)
            svg.text(x0 + width * right / len(part) + 6, y + bar - 2, f"{right} von {len(part)}", 11, MUTED)
            y += bar + gap
        y += group_gap
    svg.save("artikelwahl.svg")


def korpus() -> None:
    """Relevance of the corpus articles by origin (M8, blind gold) and what links and the LLM check leave (M25)."""
    result = load("m8_artikelwahl.json")
    gold = yaml.safe_load(LABELS.read_text(encoding="utf-8"))["labels"]
    origins = {"primary": "Hauptartikel", "same_topic": "dasselbe Thema aus Klexikon",
               "linked": "verlinkte Unterartikel", "search": "Volltexttreffer je Baustein"}
    articles = [(a["herkunft"], gold[topic][f"{a['projekt']}:{a['titel']}"])
                for topic, corpus in result["korpus"].items() for a in corpus["artikel"]]
    groups = [(label, [n for o, n in articles if o == origin]) for origin, label in origins.items()]
    groups.append(("alle gewählten Artikel", [n for _, n in articles]))
    effect = load("m25_korpus_verlinkung.json")
    variants = (("heute", "bis D48, ohne LLM"), ("ohne unverlinkte Treffer", "LLM-frei (D48)"),
                ("LLM Treffer", "bis D48, mit Trefferprüfung"), ("beides", "ausgewogen (D48)"))
    printed = {key: [sum(t["gedruckt"][key]["nach_note"].get(str(n), 0) for t in effect.values()) for n in (2, 1, 0)]
               for key, _ in variants}
    unlinked = [a["note"] for t in effect.values() for a in t["artikel"]
                if a["herkunft"] == "search" and not a["verlinkt"]]
    x0, width, bar = 280, 300, 22
    svg = Svg(760, 470, "Passen die Artikel des Korpus zum Thema?")
    svg.text(24, 30, "Artikel im Korpus nach Herkunft, blind bewertet (M8, 20 Themen)", 17, weight="600")
    svg.legend(24, 58, [(FITS, "gehört zum Thema"), (RELATED, "verwandt"), (UNFIT, "passt nicht")])
    y = 80
    for label, notes in groups:
        svg.text(x0 - 12, y + 16, f"{label} ({len(notes)})", 12.5, INK, "end",
                 "600" if label.startswith("alle") else "normal", limit=x0 - 30)
        x = x0
        for note, color in ((2, FITS), (1, RELATED), (0, UNFIT)):
            share = notes.count(note) / len(notes)
            svg.rect(x, y, width * share, bar, color)
            if width * share > 34:
                svg.text(x + width * share / 2, y + 15.5, f"{de(100 * share)} %", 11,
                         PAPER if color != RELATED else INK, "middle")
            x += width * share
        y += bar + 12
    y += 22
    svg.text(24, y, "Gedruckte Absätze nach Artikel, Standard, 20 Themen (M25, gpt-6-luna)", 15, weight="600")
    y += 22
    for key, label in variants:
        total = sum(printed[key])
        svg.text(x0 - 12, y + 16, label, 12.5, INK, "end", limit=x0 - 30)
        x = x0
        for count, color in zip(printed[key], (FITS, RELATED, UNFIT), strict=True):
            svg.rect(x, y, width * count / total, bar, color)
            x += width * count / total
        svg.text(x0 + width + 10, y + 16, f"{printed[key][2]} von {total} unpassend", 11.5, MUTED, limit=160)
        y += bar + 12
    svg.text(24, y + 16, f"Von {len(unlinked)} Volltexttreffern ohne Link zum Hauptartikel passten {unlinked.count(0)} "
             "nicht; seit D48 fallen sie weg.", 11.5, MUTED, limit=712)
    svg.save("korpus.svg")


def zuordnung_guete_zeit() -> None:
    """Macro-F1 on the gold pool against the time of the matching per topic, log scale (M4, M12 to M15)."""
    tables = load("m4_tabellen.json")
    gold, full = tables["gold"], tables["full"]
    seconds = {**{name: full[name]["ms_mean"] / 1000 for name in full}, **tables["seconds"]}
    local = load("m15_bausteine_lokal.json")
    selectable = [("lexicon_only", "lexicon_only", "lexicon_only", -8, 22, "start"),
                  ("bm25", "bm25", "bm25", 10, 5, "start"),
                  ("char_tfidf", "char_tfidf", "char_tfidf", 12, 18, "start"),
                  ("hybrid_light", "hybrid_light + M2V", "hybrid_light (llm-free, balanced)", 12, -8, "start")]
    others = [("Model2Vec allein", "Model2Vec allein", -8, -8, "end"),
              ("BM25 + Model2Vec", "BM25 + Model2Vec", 6, -10, "start"),
              ("MiniLM-Satzvektoren allein", "MiniLM", 10, 4, "start"),
              ("Frage-Antwort-Modell allein", "Frage-Antwort-Modell", -8, -10, "end"),
              ("Cross-Encoder allein", "Cross-Encoder allein", -10, 18, "end"),
              ("hybrid_light + M2V, Cross-Encoder sortiert um", "Umsortierung durch Cross-Encoder", -8, 16, "end"),
              ("hybrid_light + M2V + Cross-Encoder (fusioniert)", "Cross-Encoder als 4. Ranker", -8, 18, "end")]
    llm_runs = [load("m12_sparvarianten.json")["wege"]["llm_billig"]["macro_f1"],
                load("m12_sparvarianten_rotiert.json")["wege"]["llm_50x400"]["macro_f1"]]
    llm_times = [load("m13_zeit_zuordnung.json")["zusammenfassung"]["llm"]["median_zuordnung_s"],
                 load("m14_zeit_zuordnung.json")["zusammenfassung"]["llm"]["median_zuordnung_s"]]
    left, right, top, bottom = 96, 730, 96, 420
    svg = Svg(760, 490, "Güte gegen Zeit der Zuordnung")
    svg.text(24, 30, "Zuordnung: Güte gegen Rechenzeit je Thema", 17, weight="600")
    svg.legend(24, 56, [(LOCAL, "wählbar, lokal"), (OLD, "gemessen, nicht wählbar"), (LLM, "wählbar, LLM")])

    def px(value: float) -> float:
        return left + (math.log10(value) + 2) / 4 * (right - left)

    def py(value: float) -> float:
        return bottom - (value - 0.25) / 0.55 * (bottom - top)

    for exponent, label in ((-2, "0,01 s"), (-1, "0,1 s"), (0, "1 s"), (1, "10 s"), (2, "100 s")):
        svg.line(px(10**exponent), top, px(10**exponent), bottom)
        svg.text(px(10**exponent), bottom + 18, label, 11, MUTED, "middle")
    for tick in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        svg.line(left, py(tick), right, py(tick))
        svg.text(left - 8, py(tick) + 4, de(tick, "0.1"), 11, MUTED, "end")
    svg.text(left, bottom + 42, "Zeit der Zuordnung je Thema, logarithmisch", 12, MUTED)
    svg.text(left - 8, top - 16, "macro-F1", 12, MUTED, "end")
    for name, label, dx, dy, anchor in others:
        x, y = px(seconds[name]), py(gold[name]["macro"])
        svg.circle(x, y, 5, PAPER, OLD, 2)
        svg.text(x + dx, y + dy, label, 11, MUTED, anchor)
    for name, m4_name, label, dx, dy, anchor in selectable:
        x, y = px(seconds[m4_name]), py(local[f"{name}|gold"]["macro_f1"])
        svg.circle(x, y, 6, LOCAL)
        svg.text(x + dx, y + dy, f"{label} {de(local[f'{name}|gold']['macro_f1'], '0.01')}", 12, INK, anchor,
                 "600" if name == "hybrid_light" else "normal")
    x1, x2 = px(min(llm_times)), px(max(llm_times))
    y1, y2 = py(max(llm_runs)), py(min(llm_runs))
    svg.rect(x1, y1 - 4, x2 - x1, y2 - y1 + 8, LLM, 5)
    svg.text((x1 + x2) / 2, y1 - 12, f"llm {de(min(llm_runs), '0.01')} bis {de(max(llm_runs), '0.01')}", 12, INK,
             "middle", "600")
    svg.text((x1 + x2) / 2, y2 + 22, f"{de(min(llm_times), '0.1')} bis {de(max(llm_times), '0.1')} s", 11, MUTED,
             "middle")
    svg.text(24, 480, "Güte: gelabelte Absätze der Goldthemen. Zeit: lokal alle Absätze (M4), llm ganze Kompendien "
             "(M13, M14).", 11, MUTED, limit=712)
    svg.save("zuordnung_guete_zeit.svg")


def zuordnung_bausteine() -> None:
    """F1 per content block for every matcher value on the same 597 gold paragraphs (M12, M15)."""
    local = load("m15_bausteine_lokal.json")
    runs = [load("m12_sparvarianten.json")["wege"]["llm_billig"],
            load("m12_sparvarianten_rotiert.json")["wege"]["llm_50x400"]]
    columns = [(name, local[f"{name}|gold"]) for name in ("lexicon_only", "bm25", "char_tfidf", "hybrid_light")]
    columns += [("llm, Lauf 1", runs[0]), ("llm, Lauf 2", runs[1])]
    x0, cell_w, cell_h, top = 250, 80, 30, 96
    height = top + (len(SLOTS) + 1) * cell_h + 70
    svg = Svg(760, height, "F1 je Baustein für jeden Wert von matcher")
    svg.text(24, 30, "Zuordnung: F1 je Baustein, dieselben 597 gelabelten Absätze", 17, weight="600")
    svg.text(24, 52, "Die lokalen Verfahren unterscheiden sich nur in kleinen Bausteinen; das LLM hebt fast alle.", 12,
             MUTED, limit=712)
    for index, (name, _) in enumerate(columns):
        x = x0 + index * cell_w + (12 if index >= 4 else 0)
        svg.text(x + cell_w / 2, top - 12, name, 11.5, LLM if name.startswith("llm") else LOCAL, "middle", "600",
                 cell_w + 6)

    def color(value: float) -> tuple[str, str]:
        light, dark = (243, 246, 250), (31, 78, 140)
        mix = [round(a + (b - a) * value) for a, b in zip(light, dark, strict=True)]
        return f"#{mix[0]:02x}{mix[1]:02x}{mix[2]:02x}", PAPER if value > 0.55 else INK

    y = top
    for key, label in SLOTS.items():
        support = columns[0][1]["per_slot"][key]["support"]
        svg.text(x0 - 12, y + 20, f"{label} ({support})", 12.5, INK, "end", limit=x0 - 30)
        for index, (_, data) in enumerate(columns):
            value = data["per_slot"][key]["f1"]
            fill, ink = color(value)
            x = x0 + index * cell_w + (12 if index >= 4 else 0)
            svg.rect(x + 1, y + 1, cell_w - 2, cell_h - 2, fill, 3)
            svg.text(x + cell_w / 2, y + 20, de(value, "0.01"), 12, ink, "middle")
        y += cell_h
    svg.line(x0, y + 4, x0 + 6 * cell_w + 12, y + 4, MUTED)
    svg.text(x0 - 12, y + 26, "macro-F1", 12.5, INK, "end", "600")
    for index, (_, data) in enumerate(columns):
        x = x0 + index * cell_w + (12 if index >= 4 else 0)
        svg.text(x + cell_w / 2, y + 26, de(data["macro_f1"], "0.01"), 12.5, INK, "middle", "600")
    svg.text(24, height - 16, "In Klammern die Zahl der Gold-Absätze: Bausteine mit 2 bis 18 Absätzen streuen "
             "zwischen Läufen um bis zu 0,4.", 11, MUTED, limit=712)
    svg.save("zuordnung_bausteine.svg")


def span_bar(svg: Svg, x: float, y: float, scale: float, low: float, high: float, color: str, bar: float) -> None:
    """A bar up to low, and the span up to high in a lighter tint of the same color."""
    svg.rect(x, y, scale * low, bar, color, 2)
    if high > low:
        svg.rect(x + scale * low, y, scale * (high - low), bar, TINT[color], 2)


def text_schalter() -> None:
    """Time and tokens of the text switches; measured on 2026-09-18 and 19 (02-weltwissen.md, PLAN.md)."""
    options = [  # label, seconds (low, high), tokens (low, high), llm
        ("extraktiv (ohne LLM)", (1.1, 1.1), (0, 0), False),  # M1: building the text on the server
        ("generation=llm-fast", (9, 15), (2_300, 4_000), True),
        ("extraction=llm", (11, 11), (14_000, 22_400), True),  # time: Optik; tokens: the ten gold topics
        ("generation=llm", (16, 20), (10_500, 14_500), True),
        ("extraction + generation llm", (18, 18), (27_205, 37_000), True),  # time: Optik; up to 37,000
    ]
    x0, time_w, tx, token_w, bar, row = 230, 170, 500, 160, 16, 34
    svg = Svg(780, 90 + len(options) * row + 40, "Zeit und Tokens der Text-Schalter")
    svg.text(24, 30, "Text bauen: Zeit und Tokens der Schalter", 17, weight="600")
    svg.text(x0, 62, "Zeit je Kompendium", 12, MUTED)
    svg.text(tx, 62, "Tokens je Kompendium", 12, MUTED)
    y = 76
    for label, (s_low, s_high), (t_low, t_high), llm in options:
        color = LLM if llm else LOCAL
        svg.text(x0 - 12, y + 13, label, 12.5, INK, "end", limit=x0 - 30)
        span_bar(svg, x0, y, time_w / 25, s_low, s_high, color, bar)
        s_label = secs(s_low, "0.1") + (f" bis {secs(s_high)}" if s_high > s_low else "") + " s"
        svg.text(x0 + time_w * s_high / 25 + 6, y + 13, s_label, 11, MUTED, limit=tx - 20 - x0 - time_w * s_high / 25)
        span_bar(svg, tx, y, token_w / 40_000, t_low, t_high, color, bar)
        t_label = "0" if not t_high else de(t_low) + (f" bis {de(t_high)}" if t_high > t_low else "")
        svg.text(tx + token_w * t_high / 40_000 + 6, y + 13, t_label, 11, MUTED,
                 limit=780 - 10 - tx - token_w * t_high / 40_000)
        y += row
    svg.text(24, y + 20, "Heller Teil: Spanne der Messungen. LLM-Werte vom 18./19.09.2026, wenige Themen; "
             "extraktiv: Textbau auf dem Server (M1).", 11, MUTED, limit=752)
    svg.save("text_schalter.svg")


def profile_seconds(timing: dict) -> dict[str, tuple[float, float, float]]:
    """Median and span of part 1 and 2 per profile (M27): llm-free as measured, every LLM profile as llm-free on the
    same topic plus the LLM's phases - hit check, and the matching and writing the profile adds. The local steps of
    some LLM runs were slowed by other work on the machine, the LLM's phases were not."""
    free = timing["laeufe"]["llm-free"]
    values = [row["sekunden"] for row in free.values()]
    result = {"llm-free": (median(values), min(values), max(values))}
    for profile, topics in timing["saetze"].items():
        estimates = []
        for topic in topics:
            run, base = timing["laeufe"][profile][topic]["phasen_ms"], free[topic]["phasen_ms"]
            extra = run.get("hit_check", 0) + max(0, run.get("resolve", 0) - base.get("resolve", 0))
            if profile != "balanced":
                extra += max(0, run.get("match", 0) - base.get("match", 0))
            if profile == "best-quality-generated":
                extra += max(0, run.get("synthesize", 0) - base.get("synthesize", 0))
            estimates.append(free[topic]["sekunden"] + extra / 1000)
        result[profile] = (median(estimates), min(estimates), max(estimates))
    return result


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def kombinationen() -> None:
    """The four profiles (D53): part 1 and 2 per compendium on the server, tokens (M45) and quality (M35, M27, M39,
    M19)."""
    zeit = server_seconds()
    tokens = load("m45_profile_endpunkte.json")["compendium"]["zusammenfassung"]
    per = 1_000_000  # compendia per million tokens; D67 left the daily budget unset
    profiles = [  # label, articles right of 94, macro-F1 at the gold paragraphs, what the text is, color
        ("llm-free", 87, "0,45", "wörtlich", LOCAL),
        ("balanced", 91, "0,50²", "wörtlich", "#7a5aa6"),
        ("best-quality", 93, "0,70", "wörtlich", LLM),
        ("best-quality-generated", 93, "0,70", "vom LLM geschrieben", "#b24c63"),
    ]
    x0, width, bar, row = 200, 180, 20, 70
    svg = Svg(780, 110 + len(profiles) * row + 72, "Die vier Profile")
    svg.text(24, 30, "Die vier Profile im Vergleich", 17, weight="600")
    heads = [(x0, "Teil 1 und 2 je Kompendium"), (x0 + width + 40, "Tokens je Kompendium"), (640, "Güte")]
    for x, head in heads:
        svg.text(x, 64, head, 12, MUTED)
    y = 82
    for label, articles, f1, kind, color in profiles:
        seconds, low, high = zeit[label]
        used = tokens[label]["tokens"]["median"]
        svg.text(x0 - 12, y + 15, label, 12.5, INK, "end", "600")
        svg.rect(x0, y, width * seconds / 40, bar, color, 2)
        svg.text(x0 + width * seconds / 40 + 6, y + 15, f"{de(seconds, '0.1')} s", 11.5, MUTED)
        svg.text(x0, y + bar + 16, f"{de(low, '0.1')} bis {de(high, '0.1')} s", 11, MUTED)
        tx = x0 + width + 40
        svg.rect(tx, y, width * used / 70_000, bar, color, 2)
        svg.text(tx + width * used / 70_000 + 6, y + 15, de(round(used, -2) if used > 5_000 else used), 11.5, MUTED)
        count = "ohne Grenze" if not used else f"{de(per / used)} Kompendien"
        svg.text(tx, y + bar + 16, f"1 Mio. Tokens: {count}", 11, MUTED, limit=220)
        svg.text(640, y + 9, f"Artikel: {articles} von 94", 11.5, INK)
        svg.text(640, y + 27, f"Zuordnung: {f1}", 11.5, INK)
        svg.text(640, y + 45, f"Text: {kind}", 11.5, INK)
        y += row
    notes = (
        "Zeit: Teil 1 und 2 auf dem Server (M45): ohne LLM gemessen, dazu die LLM-Schritte des Profils, gpt-6-luna.",
        "Tokens: Median, je LLM-Profil sechs eigene Themen (M45). Zuordnung: macro-F1 der gelabelten Absätze,",
        "llm-free M27, balanced M39 (² das Gold deckt den Korpus mit N zu zwei Dritteln), die LLM-Zuordnung M19.",
    )
    for number, note in enumerate(notes):
        svg.text(24, y + 18 + 16 * number, note, 11, MUTED, limit=732)
    svg.save("kombinationen.svg")


BALANCED, GENERATED = "#7a5aa6", "#b24c63"
PROFILES = ("llm-free", "balanced", "best-quality", "best-quality-generated")
PROFILE_COLOR = {"llm-free": LOCAL, "balanced": BALANCED, "best-quality": LLM, "best-quality-generated": GENERATED}


def m45(section: str, profile: str, field: str) -> float:
    """Median of a field of M45 (28.09.2026, release 2.2.2): one endpoint, one profile."""
    return load("m45_profile_endpunkte.json")[section]["zusammenfassung"][profile][field]["median"]


LLM_PHASES = {"balanced": ("resolve",), "best-quality": ("resolve", "match", "curricula"),
              "best-quality-generated": ("resolve", "match", "synthesize", "curricula")}


def server_seconds() -> dict[str, tuple[float, float, float]]:
    """Part 1 and 2 per profile on the server (M45): llm-free as the server measured it; an LLM profile as the
    server's llm-free time on the same topic plus the phases its LLM works in, measured in the development container
    against llm-free there (the LLM dominates and is the same b-api). Median, lowest, highest."""
    dev, server = load("m45_profile_endpunkte.json"), load("m45_server_llm_free.json")
    local = server["compendium"]["laeufe"]["llm-free"]
    free = dev["compendium"]["laeufe"]["llm-free"]
    values = [row["sekunden"] for row in local.values()]
    result = {"llm-free": (median(values), min(values), max(values))}
    for profile, phases in LLM_PHASES.items():
        estimates = []
        for topic, row in dev["compendium"]["laeufe"][profile].items():
            run, base = row["phasen_ms"], free[topic]["phasen_ms"]
            extra = sum(max(0, run.get(phase, 0) - base.get(phase, 0)) for phase in phases)
            estimates.append(local[topic]["sekunden"] + extra / 1000)
        result[profile] = (median(estimates), min(estimates), max(estimates))
    return result


def tokens_text(value: float) -> str:
    return "0" if not value else de(round(value, -2) if value >= 5_000 else round(value, -1), "1")


def qualitaet_zeit_kosten() -> None:
    """The old service against the four profiles (01-alt-und-neu.md): time and tokens per compendium beside the
    quality measures that exist for them. Time and tokens: M45 and, for the old service, M2 (best case: Wikipedia
    answers). The quality numbers come from their measurements, written here with the source."""
    zeit = server_seconds()
    rows = [  # label, color, seconds, tokens, main article right of 94, macro-F1, backed sentences, readability
        ("alter Dienst, bester Fall", OLD, 35.0, 7_913, 55, None, (21, "21 %"), None),  # M2; M17 first term
        ("llm-free", LOCAL, zeit["llm-free"][0], m45("compendium", "llm-free", "tokens"),
         87, (0.45, "0,45"), (100, "100 %"), (2.5, "2,5¹")),  # M35; M27 (gold pool); M3; M28
        ("balanced", BALANCED, zeit["balanced"][0],
         m45("compendium", "balanced", "tokens"), 91, (0.50, "0,50²"), (100, "100 %"), (2.5, "2,5¹")),  # M35/M39
        ("best-quality", LLM, zeit["best-quality"][0],
         m45("compendium", "best-quality", "tokens"), 93, (0.70, "0,70"), (100, "100 %"), (2.5, "2,5")),  # M19; M28
        ("best-quality-generated", GENERATED, zeit["best-quality-generated"][0],
         m45("compendium", "best-quality-generated", "tokens"), 93, (0.70, "0,70"), None, (4.0, "4,0")),
    ]
    label_w, panel_w, gap, bar, row_h = 190, 238, 22, 15, 24
    width = 24 + label_w + 3 * panel_w + 2 * gap + 24
    panel_h = 34 + len(rows) * row_h
    svg = Svg(width, 70 + 2 * panel_h + 30 + 7 * 16, "Güte, Zeit und Kosten: alter Dienst und Profile")
    svg.text(24, 30, "Güte, Zeit und Kosten: alter Dienst und die vier Profile", 17, weight="600")
    svg.text(24, 50, "je Kompendium; ein längerer Balken ist bei Zeit und Tokens teurer, bei der Güte besser", 12, MUTED)
    panels = [  # title, value of a row, scale maximum, text of a row's value
        ("Zeit je Kompendium, Teil 1 und 2", lambda r: r[2], 40, lambda r: f"{secs(r[2], '0.1')} s"),
        ("Tokens je Kompendium, Median", lambda r: r[3], 45_000, lambda r: tokens_text(r[3])),
        ("Hauptartikel richtig, 94 Anfragen", lambda r: r[4], 94, lambda r: f"{r[4]} von 94"),
        ("Zuordnung, macro-F1", lambda r: r[5] and r[5][0], 1, lambda r: r[5][1] if r[5] else "keine Bausteine"),
        ("Sätze von ihrer Quelle gestützt", lambda r: r[6] and r[6][0], 100,
         lambda r: r[6][1] if r[6] else "geprüft, Modellwissen markiert"),
        ("Lesbarkeit für Lehrkräfte, 1 bis 5", lambda r: r[7] and r[7][0], 5, lambda r: r[7][1] if r[7] else "nicht benotet"),
    ]
    for index, (title, value, maximum, label) in enumerate(panels):
        column, line = index % 3, index // 3
        x = 24 + label_w + column * (panel_w + gap)
        y = 70 + line * (panel_h + 14)
        svg.rect(x - 8, y - 4, panel_w + 12, panel_h, PANEL, 4)
        svg.text(x, y + 14, title, 12, INK, weight="600", limit=panel_w)
        for number, row in enumerate(rows):
            ry = y + 28 + number * row_h
            if column == 0:
                svg.text(24 + label_w - 14, ry + 12, row[0], 12, INK, "end", "600", limit=label_w - 16)
            amount = value(row)
            length = (panel_w - 70) * min(amount, maximum) / maximum if amount else 0
            if length:
                svg.rect(x, ry, length, bar, row[1], 2)
            svg.text(x + length + (6 if length else 0), ry + 12, label(row), 11, MUTED if amount else INK,
                     limit=panel_w - length - 6)
    notes = (
        "Zeit: Server, Median (M45: ohne LLM gemessen, dazu die LLM-Schritte, gpt-6-luna). Tokens: Median, "
        "je LLM-Profil sechs eigene Themen (M45).",
        "Alter Dienst: M2 (Wikipedia antwortet; wie ausgeliefert wies Wikipedia ihn ab: 374 s, ein Text ohne Quelle).",
        "Hauptartikel: M17 (alter Weg: der Artikel des ersten Begriffs) und M35. Zuordnung am Goldpool: M27, M19;",
        "² nur auf den Absätzen mit Label, das Gold deckt den Korpus mit N zu zwei Dritteln (M39).",
        "Gestützt: M2 und M3; im wörtlichen Text steht jeder Satz im zitierten Absatz. Lesbarkeit: M28, zwei Claude-Gutachter;",
        "¹ der wörtliche Text wie bei best-quality, nicht eigens benotet.",
    )
    for number, note in enumerate(notes):
        svg.text(24, 70 + 2 * panel_h + 14 + 26 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save("qualitaet_zeit_kosten.svg")


def profile_matrix() -> None:
    """What each profile does in every step and endpoint, with quality, time and tokens (09-profile-und-messwerte.md).
    Time and tokens of the endpoints: M45; the other numbers: their measurements, named in the page's table."""
    zeit = server_seconds()

    def endpoint(section: str, profile: str) -> str:
        seconds = zeit[profile][0] if section == "compendium" else (
            load("m45_server_llm_free.json")[section]["zusammenfassung"]["llm-free"]["sekunden"]["median"]
            if profile == "llm-free" else m45(section, profile, "sekunden"))
        used = m45(section, profile, "tokens")
        shown = de(seconds, "0.01") if seconds < 1 else secs(seconds, "0.1")
        return f"{shown} s · {tokens_text(used)} Tokens"

    free = "Regeln, ohne LLM"
    rows = [  # step or endpoint, then per profile: (what it does, what it achieves, whether an LLM works)
        ("Hauptartikel", [("Regeln", "87 von 94 richtig", False), ("LLM entscheidet unsichere", "91 von 94", True),
                          ("LLM prüft auch sichere", "93 von 94", True), ("wie best-quality", "93 von 94", True)]),
        ("Korpus (Nebenartikel)", [("verlinkte und Volltexttreffer", "passend 43 / 71 %", False),
                                   ("LLM nennt Übersicht und Teile", "passend 87 / 93 %", True),
                                   ("wie balanced", "wie balanced", True), ("wie balanced", "wie balanced", True)]),
        ("Zuordnung", [("hybrid_light mit Model2Vec", "macro-F1 0,45", False),
                       ("wie llm-free", "macro-F1 0,50 auf 2/3 des Korpus", False),
                       ("LLM ordnet jeden Absatz zu", "macro-F1 0,70", True), ("wie best-quality", "macro-F1 0,70", True)]),
        ("Text von Teil 1", [("wörtlich, jeder Satz belegt", "Lesbarkeit 2,5", False), ("wie llm-free", "", False),
                             ("wie llm-free", "Lesbarkeit 2,5", False),
                             ("LLM schreibt, mit Modellwissen", "Lesbarkeit 4,0", True)]),
        ("Kompendium, Teil 1 und 2", [(free, endpoint("compendium", "llm-free"), False),
                                      ("LLM für Artikel und Korpus", endpoint("compendium", "balanced"), True),
                                      ("dazu Zuordnung, Teil-2-Prüfung", endpoint("compendium", "best-quality"), True),
                                      ("dazu Text", endpoint("compendium", "best-quality-generated"), True)]),
        ("Teil 2: Lehrplanbezüge", [("Regeln, Überschriften gebündelt", "passend 70 bis 81 %", False),
                                    ("wie llm-free", "passend 70 bis 81 %", False),
                                    ("LLM prüft jedes Element", "passend 74 bis 79 %", True),
                                    ("wie best-quality", "passend 74 bis 79 %", True)]),
        ("Lehrplansuche", [(free, endpoint("lehrplan_suche", "llm-free"), False), ("wie llm-free", "", False),
                           ("LLM prüft jedes Element", endpoint("lehrplan_suche", "best-quality"), True),
                           ("wie best-quality", "", True)]),
        ("Teil 3: Sammlung", [("edu-sharing, ohne LLM", "0,16 bis 3,5 s", False), ("wie llm-free", "", False),
                              ("wie llm-free", "", False), ("wie llm-free", "", False)]),
        ("Wissenstexte (/knowledge)", [(free, endpoint("knowledge", "llm-free"), False),
                                       ("Artikel und Korpus vom LLM", endpoint("knowledge", "balanced"), True),
                                       ("dazu sichere Artikel geprüft", endpoint("knowledge", "best-quality"), True),
                                       ("wie best-quality", "", True)]),
        ("Entitäten (/entities)", [("spaCy und Artikeltitel", "F1 0,38 · " + endpoint("entities", "llm-free"), False),
                                   ("LLM nennt sie mit Artikel", "F1 0,78 · " + endpoint("entities", "balanced"), True),
                                   ("wie balanced", "F1 0,78", True), ("wie balanced", "F1 0,78", True)]),
        ("Kennungen (Wikidata, GND)", [("lokale Indexe", "Wikidata-Präzision 0,29", False),
                                       ("lokale Indexe", "Wikidata-Präzision 0,70", False),
                                       ("wie balanced", "", False), ("wie balanced", "", False)]),
        ("QA-Paare (/qa)", [("Regeln aus dem Parse", "61 % mangelfrei · " + endpoint("qa", "llm-free").replace(" · 0 Tokens", ""), False),
                            ("wie llm-free", "61 % mangelfrei", False),
                            ("LLM schreibt die Paare", "83 % · " + endpoint("qa", "best-quality"), True),
                            ("wie best-quality", "83 % mangelfrei", True)]),
        ("Material als Eingang", [("Regeln über Titel und Text", "Artikel-F1 0,56 / 0,63", False),
                                  ("LLM wählt den Artikel", "Artikel-F1 0,98 / 0,88", True),
                                  ("wie balanced", "", True), ("wie balanced", "", True)]),
    ]
    label_w, cell_w, row_h, top = 190, 214, 40, 96
    width = 24 + label_w + 4 * cell_w + 24
    svg = Svg(width, top + len(rows) * row_h + 92, "Die vier Profile je Verfahren und Endpunkt")
    svg.text(24, 30, "Die vier Profile je Verfahren und Endpunkt", 17, weight="600")
    svg.legend(24, 56, [(TINT[LOCAL], "Regeln, ohne LLM"), (TINT[LLM], "ein LLM arbeitet")], 12)
    for index, profile in enumerate(PROFILES):
        x = 24 + label_w + index * cell_w
        svg.rect(x + 2, top - 26, cell_w - 4, 20, PROFILE_COLOR[profile], 3)
        svg.text(x + cell_w / 2, top - 12, profile, 12, PAPER, "middle", "600")
    for number, (step, cells) in enumerate(rows):
        y = top + number * row_h
        svg.text(24 + label_w - 12, y + 24, step, 12, INK, "end", "600", limit=label_w - 14)
        for index, (does, achieves, llm) in enumerate(cells):
            x = 24 + label_w + index * cell_w
            svg.rect(x + 2, y + 2, cell_w - 4, row_h - 4, TINT[LLM] if llm else TINT[LOCAL], 3)
            svg.text(x + 9, y + 17, does, 11, INK, limit=cell_w - 14)
            if achieves:
                svg.text(x + 9, y + 32, achieves, 10.5, MUTED, limit=cell_w - 14)
    notes = (
        "Zeit und Tokens: M45, Median je Anfrage; ohne LLM auf dem Server gemessen, mit LLM im Entwicklungscontainer (das LLM "
        "überwiegt), das Kompendium als Server plus LLM-Schritte.",
        "Güte: Hauptartikel M35, Korpus M37/M39 (Sammel- / gewöhnliche Themen), Zuordnung M27/M39/M19, Lesbarkeit M28, Teil 2 M32,",
        "Entitäten M36, Kennungen M43, QA M34/M30, Material M25. Teil 3: M1 und Server. Einzelheiten: Seite 09.",
    )
    for number, note in enumerate(notes):
        svg.text(24, top + len(rows) * row_h + 24 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save("profile_matrix.svg")


SHORT = {"llm-free": "llm-free", "balanced": "balanced", "best-quality": "best-q.", "best-quality-generated": "gen."}


def verfahren(name: str, title: str, measure: str, rows: list[tuple], notes: tuple[str, ...]) -> None:
    """One step of the service (09-methoden-und-profile.md): every measured method with its quality as a bar, time and
    tokens as numbers, and the profiles that use it. A row: label, quality 0..1 or None, quality text, time, tokens,
    and either the profiles using the method or a status such as "nicht eingebaut"."""
    label_w, bar_w, time_x, token_x, profile_x, row_h = 300, 170, 644, 780, 910, 30
    width = profile_x + 4 * 44 + 24
    top = 92
    svg = Svg(width, top + len(rows) * row_h + 26 + 16 * len(notes), title)
    svg.text(24, 30, title, 17, weight="600")
    svg.legend(24, 56, [(PROFILE_COLOR[p], p) for p in PROFILES], 11.5)
    for x, head in ((24 + label_w, measure), (time_x, "Zeit"), (token_x, "Tokens"), (profile_x, "Profile")):
        svg.text(x, top - 10, head, 11.5, MUTED, weight="600")
    for number, (label, quality, quality_text, seconds, tokens, used) in enumerate(rows):
        y = top + number * row_h
        in_use = isinstance(used, tuple)
        if number % 2 == 0:
            svg.rect(20, y - 2, width - 40, row_h, PANEL, 3)
        svg.text(24, y + 17, label, 12, INK if in_use else MUTED, weight="600" if in_use else "normal", limit=label_w - 12)
        x = 24 + label_w
        length = bar_w * quality if quality else 0
        if length:
            svg.rect(x, y + 6, length, 14, LOCAL if in_use else OLD, 2)
        svg.text(x + length + (6 if length else 0), y + 17, quality_text, 11, INK if in_use else MUTED,
                 limit=time_x - x - length - 12)
        svg.text(time_x, y + 17, seconds, 11, MUTED, limit=token_x - time_x - 10)
        svg.text(token_x, y + 17, tokens, 11, MUTED, limit=profile_x - token_x - 10)
        if in_use:
            for index, profile in enumerate(PROFILES):
                if profile in used:
                    svg.rect(profile_x + index * 44, y + 5, 40, 16, PROFILE_COLOR[profile], 3)
                    svg.text(profile_x + index * 44 + 20, y + 17, SHORT[profile], 9.5, PAPER, "middle", "600")
        else:
            svg.text(profile_x, y + 17, used, 11, MUTED, limit=width - profile_x - 24)
    for number, note in enumerate(notes):
        svg.text(24, top + len(rows) * row_h + 20 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save(name)


def verfahren_charts() -> None:
    """The six steps with their methods; numbers as on page 09, each with its measurement."""
    verfahren("verfahren_artikelwahl.svg", "Artikelwahl: den Hauptartikel finden", "richtig bei 94 Goldanfragen", [
        ("alter Weg: LLM nennt Begriffe", 55 / 94, "55 (erster Begriff)", "6 bis 8 s", "1.300 bis 1.500", "alter Dienst"),
        ("v2.0.0: Titel, Weiterleitung, Wortzählung", 66 / 94, "66", "rund 0,03 s", "0", "abgelöst"),
        ("Regeln mit Kontextwörtern des Fachs", 87 / 94, "87", "rund 0,03 s", "0", ("llm-free",)),
        ("Regeln und laya (lokales Modell)", 81 / 94, "81", "+0,45 s; 1,7 GB", "0", "nicht eingebaut (D42)"),
        ("LLM entscheidet unsichere (llm)", 91 / 94, "91", "mit N 2,4 s", "320 je Anfrage", ("balanced",)),
        ("LLM prüft auch sichere (llm-thorough)", 91 / 94, "91 bis 93", "mit N 3,0 s", "748 je Anfrage",
         ("best-quality", "best-quality-generated")),
    ], ("Hauptartikel richtig: drei Goldsätze, 94 Anfragen (M9, M16, M17; die heutigen Werte M82, Release 2.17.0; llm-thorough in M35",
        "und M59 93). Zeit und Tokens je Anfrage samt der Frage N (M82); die Regeln fragen das LLM nur, wo sie unsicher sind."))
    verfahren("verfahren_korpus.svg", "Korpusbau: welche Artikel neben dem Hauptartikel", "gedruckt aus passenden Artikeln", [
        ("alter Weg: Begriffe vom LLM", 0.63, "63 % Sammelthemen", "6 bis 8 s", "rund 1.500", "alter Dienst"),
        ("Regeln: Links, verlinkte Volltexttreffer", 0.43, "43 % / 71 %", "lokal", "0", ("llm-free",)),
        ("dazu LLM prüft die Nebenartikel", 0.45, "45 % / 73 %", "+1,4 bis 2 s", "750 bis 1.400",
         "bis D63 in balanced"),
        ("kleine lokale Modelle für N (LFM2, Qwen3)", None, "kein Gewinn", "4,4 bis 6,3 s", "0", "nicht eingebaut (M40)"),
        ("LLM nennt Übersicht und Teile (N)", 0.87, "87 % / 93 %", "+2 s", "rund 310",
         ("balanced", "best-quality", "best-quality-generated")),
    ], ("Gedruckte Absätze aus passenden Artikeln, zwei Gutachter: 25 Sammel- und Mischthemen / 20 gewöhnliche Themen (M37, M39).",
        "Zeit und Tokens des LLM je Thema: N in M82 (Phase resolve, seit D81 ohne Denken), die Prüfung der Nebenartikel M25 und M37."))
    verfahren("verfahren_zuordnung.svg", "Zuordnung: Absätze auf die Bausteine verteilen", "macro-F1, gelabelte Absätze", [
        ("nur Überschriften-Lexikon", 0.35, "0,35", "0,02 s", "0", "wählbar"),
        ("BM25", 0.36, "0,36", "0,03 s", "0", "wählbar"),
        ("Zeichen-TF-IDF", 0.40, "0,40", "0,25 s", "0", "wählbar"),
        ("Satzvektoren und Cross-Encoder der Testapp", 0.37, "0,29 bis 0,37", "4 bis 73 s", "0", "nicht eingebaut"),
        ("hybrid_light ohne Model2Vec", 0.38, "0,38", "0,3 s", "0", "Rückfall ohne Modell"),
        ("hybrid_light mit Model2Vec", 0.45, "0,45", "0,2 bis 0,7 s", "0", ("llm-free", "balanced")),
        ("LLM nur für unsichere Absätze", 0.54, "0,54", "halbe LLM-Zeit", "halbe Tokens", "verworfen (M12)"),
        ("LLM ordnet jeden Absatz zu", 0.68, "0,66 bis 0,70", "+10 s", "rund 160 je Absatz",
         ("best-quality", "best-quality-generated")),
    ], ("macro-F1 am Goldstandard, gelabelte Absätze (M4, M5, M12, M15, M19, M27; ohne Model2Vec M44: 0,40 auf allen Absätzen).",
        "Zeit je Kompendium; die LLM-Zuordnung in M82 (Phase match; am Gold 0,661 und 0,675), rund 160 Tokens je Absatz (M82)."))
    verfahren("verfahren_lehrplan.svg", "Lehrplanschnipsel auswählen (Teil 2)", "passend, einzeln gezeigt", [
        ("alle Treffer einzeln", 0.63, "62–67 %, 11–17 % unpassend", "0,1 bis 0,7 s", "0", "abgelöst (D58)"),
        ("Überschriften-Treffer gebündelt", 0.71, "70–81 %, 5–9 % unpassend", "0,1 bis 0,4 s", "0",
         ("llm-free", "balanced")),
        ("dazu LLM prüft jedes Element", 0.755, "74–79 %, 5–9 % unpassend", "+2,5 s", "rund 4.100",
         ("best-quality", "best-quality-generated")),
    ], ("Anteil der einzeln gezeigten Elemente, zwei Gutachter, 20 Themen ohne und mit Fach (M22, M32). Gebündelt steht ein Viertel",
        "der passenden nur in einer Sammelzeile; die LLM-Prüfung verwirft keines. Zeit und Tokens: M82 (Teil 2 und die Prüfung an 57 Themen)."))
    verfahren("verfahren_qa.svg", "QA-Paare erzeugen", "mangelfrei bei beiden Gutachtern", [
        ("vier Vorlagen (bis D55)", None, "nicht bewertet, 82 % Jahresfragen", "0,02 s", "0", "abgelöst (D55)"),
        ("Satzanalyse (parse-based)", 0.36, "36 %", "0,17 s", "0", "entfernt (D57)"),
        ("kleine Modelle im Image", 0.21, "21 %", "25 s je Text", "0; 1,3 GB", "entfernt (D57)"),
        ("Regeln aus dem Parse, aufgefüllt", 0.61, "61 % (58 von 95)", "0,5 s", "0", ("llm-free", "balanced")),
        ("LLM schreibt die Paare", 0.83, "83 % (99 von 120)", "5,8 s", "2.400 bis 8.200",
         ("best-quality", "best-quality-generated")),
    ], ("Je 20 verlangte Paare zu sechs Texten, zwei Gutachter (M30, die Regeln nach D60 in M34). Zeit und Tokens: M82 an Texten",
        "von rund 26.500 Zeichen; das LLM brauchte bei 5.000 bis 12.000 Zeichen rund 2.400 Tokens (M30)."))
    verfahren("verfahren_entitaeten.svg", "Entitäten ermitteln (/entities)", "F1 an 40 Materialtexten", [
        ("spaCy allein", 0.30, "0,30", "lokal", "0", "Teil von llm-free"),
        ("Wörterbuch der Artikeltitel allein", 0.35, "0,35", "lokal", "0", "Teil von llm-free"),
        ("spaCy und Wörterbuch", 0.38, "0,38 (Präzision 0,29)", "0,9 bis 2,4 s", "0", ("llm-free",)),
        ("LLM nennt sie mit Artikeltitel", 0.78, "0,78 (Präzision 0,70)", "5,5 bis 5,8 s", "900 bis 1.200",
         ("balanced", "best-quality", "best-quality-generated")),
        ("dazu LLM prüft jede Verknüpfung", 0.76, "0,76 (Präzision 0,94)", "+4,6 s", "+1.900", "Schalter link_check"),
    ], ("F1 der verknüpften Artikel, zwei Gutachter, 40 Materialtexte, durch den Endpunkt (M36). Die Kennungen folgen dem Artikel:",
        "Wikidata-Präzision 0,29 und 0,70, GND 0,31 und 0,70 (M43). Zeit und Tokens: M82 an den Materialtexten und an 1.500 Zeichen."))


def verfahren_text() -> None:
    """Step 4 (text of part 1): the ways the text comes about, readability where it was graded (M28, M31, M45)."""
    verfahren("verfahren_text.svg", "Text von Teil 1: wörtlich oder geschrieben", "Lesbarkeit für Lehrkräfte, 1 bis 5", [
        ("wörtlich, jeder Satz mit Belegnummer", 2.5 / 5, "2,5", "lokal", "0", ("llm-free", "balanced", "best-quality")),
        ("LLM wählt die Sätze aus (extraction=llm)", None, "am Goldstandard kein Gewinn", "+11 s", "14.000 bis 22.400",
         "in keinem Profil"),
        ("LLM schreibt jeden Baustein neu", 4.0 / 5, "4,0; 11 von 12 vorgezogen", "+10,4 s",
         "+19.000 im Median", ("best-quality-generated",)),
    ], ("Lesbarkeit: zwei Claude-Gutachter, sechs Themen (M28); Modellwissen mit Prompt v2 sichtbar markiert: 50 Sätze, 13 Füllsätze,",
        "keiner falsch (M31). Zeit und Tokens des Schreibens M82; extraction=llm gemessen am 18. und 19.09.2026 (02-weltwissen.md)."))


FIVE = (*PROFILES, "best-coverage-generated")
KIND_LABELS = {"einfach": "einfach", "Sammelthema": "Sammelthema", "Aspekt": "mit Aspekt"}


def profile_grades(data: dict, name: str, heading: str, subtitle: str, notes: tuple[str, ...], label: str,
                   overview: bool = False, time_label: str = "Teil 1, Median") -> None:
    """The five profiles on three kinds of topic: fit per kind, use, completeness and readability over all nine topics
    as bars from 1 to 5, time and tokens of part 1 as bars from 0; every column has a scale of its own and names its
    values, the profile is the row. Colored by what a column measures, not by profile: the five profile colors do not
    keep apart for every reader (validate_palette.js, 2026-10-01). ``overview`` (M52) shows the share of the tokens
    read from the prompt cache as the lighter part of their bar and adds the share of model knowledge in the text.
    ``time_label`` names what the time column measured (M82: the request with part 1 and 2)."""
    grades, runs = data["grades"], data["runs"]["alle"]
    label_w, col_w, cost_w, bar_w, top = 200, 100, 120, 62, 128
    row_h = 40 if overview else 34  # the overview names the cached tokens on a second line
    grade_cols = [(("Passung", KIND_LABELS[kind]), kind, "passung") for kind in data["kinds"]]
    grade_cols += [(("Nutzen", "alle Themen"), "alle", "nutzen"),
                   (("Vollständigkeit", "alle Themen"), "alle", "vollstaendigkeit"),
                   (("Lesbarkeit", "alle Themen"), "alle", "lesbarkeit")]
    longest_s = max(runs[p]["seconds"] for p in FIVE)
    longest_t = max(runs[p]["tokens"] for p in FIVE)
    cost_cols = [(("Zeit", time_label), "seconds", longest_s), (("Tokens", "Median"), "tokens", longest_t)]
    if overview:
        cost_cols.append((("Modellwissen", "am Text, Median"), "model_share", 1.0))
    cost_x = 24 + label_w + col_w * len(grade_cols)
    width = cost_x + cost_w * len(cost_cols) + 16
    svg = Svg(width, top + len(FIVE) * row_h + 24 + 16 * len(notes), label)
    svg.text(24, 30, heading, 17, weight="600")
    svg.text(24, 52, subtitle, 12, MUTED, limit=width - 48)
    legend = [(LOCAL, "Güte: Note von 1 bis 5 (volle Spur = 5)"), (MUTED, "Aufwand: Zeit und Tokens, ab 0")]
    if overview:
        legend += [(OLD, "davon aus dem Prompt-Cache"), (LLM, "Modellwissen, ab 0 %")]
    svg.legend(24, 78, legend, 11.5)
    heads = [(24 + label_w + index * col_w, head, col_w) for index, (head, _, _) in enumerate(grade_cols)]
    heads += [(cost_x + index * cost_w, head, cost_w) for index, (head, _, _) in enumerate(cost_cols)]
    for x, (first, second), room in heads:
        svg.text(x, top - 26, first, 11, MUTED, weight="600", limit=room - 6)
        svg.text(x, top - 12, second, 10.5, MUTED, limit=room - 6)
    for number, profile in enumerate(FIVE):
        y = top + number * row_h
        if number % 2 == 0:
            svg.rect(20, y - 4, width - 36, row_h, PANEL, 3)
        svg.text(24, y + 16, profile, 12, INK, weight="600", limit=label_w - 12)
        for index, (_, group, score) in enumerate(grade_cols):
            x = 24 + label_w + index * col_w
            value = grades[group][profile][score]
            length = bar_w * (value - 1) / 4
            svg.rect(x, y + 5, bar_w, 14, GRID, 2)  # the track from 1 to 5, so a 1 reads as a grade, not a gap
            svg.rect(x, y + 5, length, 14, LOCAL, 2)
            svg.text(x + bar_w + 5, y + 16, de(value, "0.1"), 11, INK, limit=col_w - bar_w - 6)
        for index, (_, field, longest) in enumerate(cost_cols):
            x = cost_x + index * cost_w
            value = runs[profile][field]
            length = bar_w * value / longest if longest else 0
            if field == "model_share":
                svg.rect(x, y + 5, bar_w, 14, GRID, 2)  # the track to 100 %
                if length:
                    svg.rect(x, y + 5, max(length, 2), 14, LLM, 2)
                svg.text(x + bar_w + 5, y + 16, f"{de(value * 100, '1')} %", 11, INK, limit=cost_w - bar_w - 6)
                continue
            cached = runs[profile].get("cached", 0) if overview and field == "tokens" else 0
            if length:
                svg.rect(x, y + 5, max(length, 2), 14, MUTED, 2)
                if cached:  # the part read from the prompt cache, from the left of the bar, its amount named below
                    svg.rect(x, y + 5, bar_w * cached / longest, 14, OLD, 2)
            text = f"{de(value, '0.1' if value < 10 else '1')} s" if field == "seconds" else tokens_text(value)
            svg.text(x + length + 5, y + 16, text, 11, INK, limit=cost_w - length - 8)
            if cached:
                svg.text(x, y + 32, f"davon Cache {tokens_text(cached)}", 9.5, MUTED, limit=cost_w - 8)
    for number, note in enumerate(notes):
        svg.text(24, top + len(FIVE) * row_h + 18 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save(name)


TOPIC_NOTES = (
    "Passung: genau beim angefragten Thema, je Art drei Themen (einfach: Optik, Photosynthese, Französische Revolution;",
    "Sammelthema: Dichter aus dem Mittelalter, Komponisten der Klassik, Philosophen der Aufklärung; mit Aspekt: OER-Förderungen,",
    "Inklusion im Sportunterricht, KI im Unterricht). Nutzen, Vollständigkeit, Lesbarkeit: Mittel über alle neun Themen.",
)


def profilvergleich() -> None:
    """The five profiles on three kinds of topic as M48 measured them (D70), before D72."""
    profile_grades(
        load("m48_profilvergleich.json"),
        "profilvergleich.svg",
        "Fünf Profile an drei Arten von Themen",
        "Teil 1, neun Themen, je ein Lauf; Noten zweier blinder Gutachter von 1 bis 5",
        (*TOPIC_NOTES,
         "Zeit und Tokens: Median der neun Läufe auf dem Entwicklungsrechner, Teil 1 mit 30.000 Zielzeichen (M48, 01.10.2026)."),
        "Fünf Profile an drei Arten von Themen (M48)",
    )


def profiluebersicht() -> None:
    """The five profiles as release 2.17.0 runs them (M82): the overview of quality, time and cost."""
    profile_grades(
        load("m82_profiluebersicht.json"),
        "profiluebersicht.svg",
        "Die fünf Profile: Güte, Zeit und Kosten",
        "Release 2.17.0; Teil 1 und 2, neun Themen in drei Arten, je ein Lauf; Noten zweier blinder Gutachter von 1 bis 5 (M82)",
        (*TOPIC_NOTES,
         "Zeit, Tokens und Modellwissen: Median der neun Anfragen mit Teil 1 und 2 im Einmal-Container auf dem Entwicklungsrechner,",
         "Teil 1 mit 30.000 Zielzeichen, gpt-6-luna über OpenAI (M82, 09.10.2026). Tokens aus dem Prompt-Cache zahlt der Anbieter günstiger."),
        "Die fünf Profile: Güte, Zeit und Kosten (M82)",
        overview=True,
        time_label="Teil 1 + 2, Median",
    )


def seconds_text(value: float) -> str:
    return f"{de(value, '0.01') if value < 1 else de(value, '0.1')} s"


def count_text(value: float) -> str:
    return de(value, "1") if float(value).is_integer() else de(value, "0.1")


def endpunkte() -> None:
    """The endpoints beside the compendium on release 2.17.0 (M82, page 09): time and tokens of a request as the
    median, the lighter part up to the longest request, M45 (release 2.2.2) as a circle where it asked the same; what
    came back beside. One color for what is measured, the profile is the row, as in profiluebersicht.svg."""
    now, then = load("m82_endpunkte.json"), load("m45_profile_endpunkte.json")
    blocks = [  # heading, section, rows (label, M82 variant, M45 variant or None), result field, unit
        ("/knowledge: die Artikel eines Themas", "knowledge",
         [("llm-free", "llm-free", "llm-free"), ("balanced", "balanced", "balanced"),
          ("best-quality", "best-quality", "best-quality")], "artikel", "Artikel"),
        ("/lehrplan/search mit Suchwort", "lehrplan_suche",
         [("llm-free", "keyword llm-free", "llm-free"), ("best-quality", "keyword best-quality", "best-quality")],
         "treffer", "Treffer"),
        ("/lehrplan/search mit Thema (mode=topic)", "lehrplan_suche",
         [("llm-free", "topic llm-free", None), ("balanced", "topic balanced", None),
          ("best-quality", "topic best-quality", None)], "treffer", "Treffer"),
        ("/qa mit Text, 20 Paare verlangt", "qa",
         [("llm-free", "text llm-free", "llm-free"), ("best-quality", "text best-quality", "best-quality")],
         "paare", "Paare"),
        ("/qa mit Thema: Teil 1 ohne LLM, dann die Paare", "qa",
         [("llm-free", "topic llm-free", None), ("best-quality", "topic best-quality", None)], "paare", "Paare"),
        ("/entities an 1.500 Zeichen", "entities",
         [("llm-free", "llm-free", "llm-free"), ("balanced", "balanced", "balanced"),
          ("balanced, link_check: llm", "balanced link_check", None)], "entitaeten", "Entitäten"),
        ("/compendium aus einem Material, Teil 1", "material",
         [("llm-free", "llm-free", None), ("balanced", "balanced", None)], "zeichen_teil1", "Zeichen"),
    ]
    notes = (
        "Release 2.17.0 im Einmal-Container des Entwicklungsrechners, gpt-6-luna über OpenAI direkt, nachts (M82, "
        "09.10.2026); je Zeile sechs Anfragen, beim Material drei.",
        "Tokens aus den Zählern des Dienstes (/metrics) je Route. best-quality steht für die drei Profile ab "
        "best-quality, die an diesen Endpunkten gleich arbeiten.",
        "/qa und /entities lesen Teil 1 der llm-free-Kompendien von sechs Themen (rund 26.500 Zeichen, /entities die "
        "ersten 1.500).",
        "Die Lehrplansuche gab bis zu 500 Treffer zurück, in M45 bis zu 50. Entitäten: Die Regeln finden mehr, das LLM "
        "trifft besser (F1 0,38 und 0,78, M36).",
        "Kreis: M45, 28.09.2026, der laufende Entwicklungscontainer über HTTP, das LLM über die b-api.",
    )
    label_w, panel_w, gap, row_h, head_h, top = 250, 250, 70, 22, 26, 128
    time_x = 24 + label_w
    token_x = time_x + panel_w + gap
    result_x = token_x + panel_w + gap
    width = result_x + 190
    rows_end = top + len(blocks) * head_h + sum(len(rows) for _, _, rows, _, _ in blocks) * row_h
    svg = Svg(width, rows_end + 26 + 16 * len(notes), "Die übrigen Endpunkte: Zeit und Tokens je Profil")
    svg.text(24, 30, "Die übrigen Endpunkte: Zeit und Tokens je Profil", 17, weight="600")
    svg.text(24, 52, "Release 2.17.0, Median je Anfrage (M82); der Kreis zeigt M45 (Release 2.2.2), wo es dieselbe "
             "Anfrage gab", 12, MUTED, limit=width - 48)
    entries = [(MUTED, "Median"), (TINT[MUTED], "bis zur längsten Anfrage")]
    svg.legend(24, 78, entries, 11.5)
    x = 24 + sum(18 + len(label) * 11.5 * CHAR_WIDTH + 22 for _, label in entries)
    svg.circle(x + 6, 74, 4.5, PAPER, INK, 1.5)
    svg.text(x + 18, 78, "M45, Release 2.2.2", 11.5, MUTED)
    panels = ((time_x, "Zeit je Anfrage", 20.0, (0, 5, 10, 15, 20), lambda v: f"{v} s"),
              (token_x, "Tokens je Anfrage", 20_000, (0, 5_000, 10_000, 15_000, 20_000), lambda v: de(v)))
    for x, head, maximum, ticks, tick_text in panels:
        svg.text(x, top - 32, head, 11.5, MUTED, weight="600")
        for tick in ticks:
            tx = x + panel_w * tick / maximum
            svg.line(tx, top - 6, tx, rows_end, GRID)
            svg.text(tx, top - 12, tick_text(tick), 10, MUTED, "middle")
    svg.text(result_x, top - 32, "Ergebnis, Median", 11.5, MUTED, weight="600")
    y = top
    for heading, section, rows, field, unit in blocks:
        svg.line(20, y + 2, width - 20, y + 2, GRID)
        svg.text(24, y + 18, heading, 12, INK, weight="600", limit=width - 48)
        y += head_h
        for label, variant, old_variant in rows:
            summary = now[section]["zusammenfassung"][variant]
            old = then[section]["zusammenfassung"][old_variant] if old_variant else None
            svg.text(36, y + 15, label, 11.5, INK, limit=label_w - 16)
            for x, maximum, key, value_text in ((time_x, 20.0, "sekunden", seconds_text),
                                                 (token_x, 20_000, "tokens", lambda v: de(v))):
                stats = summary[key]
                median_w = panel_w * min(stats["median"], maximum) / maximum
                high_w = panel_w * min(stats["max"], maximum) / maximum
                svg.rect(x, y + 5, high_w, 12, TINT[MUTED], 2)
                svg.rect(x, y + 5, median_w, 12, MUTED, 2)
                end = high_w
                if old is not None and old[key]["median"]:
                    ox = x + panel_w * min(old[key]["median"], maximum) / maximum
                    svg.circle(ox, y + 11, 4.5, PAPER, INK, 1.5)
                    end = max(end, ox - x + 5)
                svg.text(x + end + 6, y + 15, value_text(stats["median"]), 11, INK, limit=gap - 8)
            svg.text(result_x, y + 15, f"{count_text(summary[field]['median'])} {unit}", 11.5, INK,
                     limit=width - result_x - 24)
            y += row_h
    for number, note in enumerate(notes):
        svg.text(24, rows_end + 26 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save("endpunkte.svg")


def profile_verlauf() -> None:
    """Time and tokens of the compendium per profile from M45 to M82 (page 09): parts 1 and 2, the median of a request,
    one bar per measurement from light to dark. M45 is outlined: it asked the b-api in the running container, each
    LLM profile on topics of its own; M75, M78 and M82 ran the nine topics of M52 in the one-off container."""
    then = load("m45_profile_endpunkte.json")["compendium"]["zusammenfassung"]
    before = {row["profile"]: row for row in load("m75_tempo.json")["zusammenfassung"] if row["variant"] == "seq"}
    after = {row["profile"]: row for row in load("m78_tempo_nachher.json")["zusammenfassung"]
             if row["concurrency"] == 20}  # its rows with 10 places repeat M75
    now = load("m82_profiluebersicht.json")["runs"]["alle"]
    marks = [  # label, legend, fill, stroke, dash
        ("M45", "M45 · 28.09. · Release 2.2.2", PAPER, OLD, "3 2"),
        ("M75", "M75 · 08.10. · vor D93", TINT[MUTED], "none", None),
        ("M78", "M78 · 08.10. · nach D93", OLD, "none", None),
        ("M82", "M82 · 09.10. · Release 2.17.0", MUTED, "none", None),
    ]
    values = {profile: [(then[profile]["sekunden"]["median"], then[profile]["tokens"]["median"])
                        if profile in then else None,
                        (before[profile]["s"], before[profile]["tokens"]),
                        (after[profile]["s"], after[profile]["tokens"]),
                        (now[profile]["seconds"], now[profile]["tokens"])] for profile in FIVE}
    notes = (
        "Kompendium mit Teil 1 und 2, Median je Anfrage. M75, M78 und M82: die neun Themen von M52 im Einmal-Container, "
        "gpt-6-luna über OpenAI direkt.",
        "M45: der laufende Entwicklungscontainer über HTTP, das LLM über die b-api, je LLM-Profil sechs eigene Themen, "
        "llm-free 18; best-coverage-generated kam mit D69.",
        "Zwischen M45 und M75: 30.000 statt 12.000 Zielzeichen (D70), best-quality-generated schreibt leere Bausteine aus "
        "Modellwissen (D72),",
        "N, Artikelwahl und Lehrplanprüfung fragen ohne Denken (D81). Zwischen M75 und M78: D93, Teil 2 und 3 neben "
        "Teil 1, die Zuordnung in Zeilen,",
        "20 gleichzeitige Aufrufe. M78 lief am Nachmittag, M82 nachts.",
    )
    label_w, panel_w, gap, bar_h, step, group_gap, top = 220, 300, 80, 10, 13, 16, 130
    time_x = 24 + label_w
    token_x = time_x + panel_w + gap
    width = token_x + panel_w + 80
    group_h = len(marks) * step + group_gap
    rows_end = top + len(FIVE) * group_h - group_gap
    svg = Svg(width, rows_end + 30 + 16 * len(notes), "Zeit und Tokens je Profil von M45 bis M82")
    svg.text(24, 30, "Zeit und Tokens je Profil von M45 bis M82", 17, weight="600")
    svg.text(24, 52, "Kompendium mit Teil 1 und 2, Median je Anfrage; zwischen den Messungen änderten sich Code, Themen "
             "und Tageszeit (unten)", 12, MUTED, limit=width - 48)
    x = 24
    for _, legend, fill, stroke, dash in marks:
        svg.rect(x, 68, 12, 12, fill, 2, stroke, 1.2, dash)
        svg.text(x + 18, 78, legend, 11.5, MUTED)
        x += 18 + len(legend) * 11.5 * CHAR_WIDTH + 22
    panels = ((time_x, "Zeit je Anfrage", 40.0, (0, 10, 20, 30, 40), lambda v: f"{v} s"),
              (token_x, "Tokens je Anfrage", 100_000, (0, 25_000, 50_000, 75_000, 100_000), lambda v: de(v)))
    for x, head, maximum, ticks, tick_text in panels:
        svg.text(x, top - 32, head, 11.5, MUTED, weight="600")
        for tick in ticks:
            tx = x + panel_w * tick / maximum
            svg.line(tx, top - 6, tx, rows_end, GRID)
            svg.text(tx, top - 12, tick_text(tick), 10, MUTED, "middle")
    for number, profile in enumerate(FIVE):
        y0 = top + number * group_h
        svg.text(24, y0 + 10, profile, 12, INK, weight="600", limit=label_w - 50)
        if not any(value and value[1] for value in values[profile]):
            svg.text(token_x, y0 + 1.5 * step + 10, "keine Tokens", 11, MUTED)
        for index, ((label, _, fill, stroke, dash), value) in enumerate(zip(marks, values[profile], strict=True)):
            y = y0 + index * step
            svg.text(time_x - 8, y + 9, label, 10, MUTED, "end")
            if value is None:
                svg.text(time_x, y + 9, "gab es noch nicht", 10, MUTED)
                continue
            seconds, tokens = value
            for x, maximum, amount, amount_text in ((time_x, 40.0, seconds, lambda v: f"{de(v, '0.1')} s"),
                                                    (token_x, 100_000, tokens, tokens_text)):
                if x == token_x and not any(item and item[1] for item in values[profile]):
                    continue
                length = panel_w * min(amount, maximum) / maximum
                svg.rect(x, y, length, bar_h, fill, 2, stroke, 1.2, dash)
                svg.text(x + length + 6, y + 9, amount_text(amount), 10, INK)
    for number, note in enumerate(notes):
        svg.text(24, rows_end + 30 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save("profile_verlauf.svg")


def alt_neu_teile() -> None:
    """What the old and the new service deliver for the three parts of the compendium and beside it (01-alt-und-neu.md);
    the numbers as on that page, each with its measurement."""
    missing, old_fill, new_fill = "#f6e1dc", "#eceef1", "#e3edf8"
    rows = [  # part, old service, new service
        ("Teil 1 · Weltwissen", ("LLM nennt Begriffe und schreibt frei aus", "Wikipedia-Einleitungen; 21 % der Sätze gestützt"),
         ("ZIM-Archive, Hauptartikel, Korpus, Zuordnung zu", "10 Bausteinen; jeder Satz wörtlich belegt")),
        ("Teil 2 · Lehrplanbezüge", None, ("MEM-Lehrpläne aus 4 Ländern, lokal gepuffert;", "70 bis 81 % der Schnipsel passend")),
        ("Teil 3 · Sammlungsüberblick", None, ("WLO-Sammlung aus edu-sharing zur Anfragezeit;", "je Inhalt eine Zeile mit nodeId")),
        ("Daneben", ("Linker (Begriffe live bei Wikipedia), QA-Paare", "vom LLM, Hilfsendpunkte für Textteilung u. a."),
         ("Profile, Entitäten mit Wikidata und GND, QA-Paare,", "Wissenstexte, Lehrplansuche, Material als Eingang")),
    ]
    label_w, cell_w, row_h, top = 220, 360, 62, 86
    width = 24 + label_w + 2 * cell_w + 24
    svg = Svg(width, top + len(rows) * row_h + 58, "Die drei Teile: alter und neuer Dienst")
    svg.text(24, 30, "Die drei Teile des Kompendiums: alter und neuer Dienst", 17, weight="600")
    for index, head in enumerate(("alter Dienst v0.2.0", "neuer Dienst 2.2.2")):
        svg.text(24 + label_w + index * cell_w + 8, top - 14, head, 12.5, MUTED, weight="600")
    for number, (part, old, new) in enumerate(rows):
        y = top + number * row_h
        svg.text(24 + label_w - 14, y + 34, part, 12.5, INK, "end", "600", limit=label_w - 16)
        for index, cell in enumerate((old, new)):
            x = 24 + label_w + index * cell_w
            svg.rect(x + 4, y + 4, cell_w - 8, row_h - 8, missing if cell is None else (old_fill if index == 0 else new_fill), 6)
            if cell is None:
                svg.text(x + 18, y + 36, "fehlte", 12, "#a2402f", weight="600")
            else:
                svg.text(x + 18, y + 27, cell[0], 11.5, INK, limit=cell_w - 30)
                svg.text(x + 18, y + 44, cell[1], 11.5, INK, limit=cell_w - 30)
    svg.text(24, top + len(rows) * row_h + 22, "Gestützte Sätze: M2; Lehrplanschnipsel: M32 (einzeln gezeigt, 20 Themen, zwei Gutachter).",
             10.5, MUTED, limit=width - 48)
    svg.text(24, top + len(rows) * row_h + 38, "Einzelheiten und Zahlen: 01-alt-und-neu.md und 09-methoden-und-profile.md.",
             10.5, MUTED, limit=width - 48)
    svg.save("alt_neu_teile.svg")


def signed(value: int, one: str, many: str) -> str:
    """A change with its noun: −7 Absätze, ±0 Bausteine, +1 Absatz, with the minus sign of print."""
    number = "±0" if not value else f"{value:+d}".replace("-", "−")
    return f"{number} {one if abs(value) == 1 else many}"


def kiwix_quellen() -> None:
    """What further Kiwix archives add (M84, page 07): the page of the main article's title - the way another archive
    enters a corpus today -, the hits a search over the archive would bring for collection and aspect topics, and the
    paragraphs part 1 printed from it. Every page carries its label for the topic (m84_einordnung.yaml, Claude,
    unreviewed); a page without one stops the chart."""
    data = load("m84_kiwix_quellen.json")
    labels = yaml.safe_load((DIR / "m84_einordnung.yaml").read_text(encoding="utf-8"))
    archives = (("klexikon", "Klexikon (heute Quelle)"), ("wikibooks", "Wikibooks"), ("wikiversity", "Wikiversity"),
                ("wiktionary", "Wiktionary"), ("wikisource", "Wikisource"), ("wikiquote", "Wikiquote"),
                ("wikivoyage", "Wikivoyage"))
    colors = (("passend", FITS), ("teilweise", RELATED), ("daneben", UNFIT))
    same, search, flow = data["abdeckung"]["gleicher_titel"], data["abdeckung"]["volltextsuche"], data["ablauf"]
    base = flow["standard"]
    standard = (sum(r["gedruckt"] for r in base.values()), sum(r["bausteine_gefuellt"] for r in base.values()))
    panels: list[tuple[str, int, list[tuple[str, dict[str, int], str]]]] = [
        (f"Seite mit dem Titel des Hauptartikels, {len(same)} Themen: so kommt ein Archiv heute in den Korpus", 40, []),
        (f"Volltextsuche, {len(search)} Sammel- und Aspektthemen, je 5 Treffer, behalten wie im Dienst (nicht gebaut)",
         90, []),
        ("Ins Kompendium gedruckte Absätze: 20 Themen, llm-free, das Archiv zu Wikipedia und Klexikon dazu", 20, []),
    ]
    for name, label in archives:
        pages = [title for title, row in same.items() if row[name] and not row[name]["begriffsklaerung"]]
        tags = [labels["gleicher_titel"][name][title] for title in pages]
        panels[0][2].append((label, {kind: tags.count(kind) for kind, _ in colors}, f"{len(pages)} von {len(same)}"))
        hits = [(key, hit["titel"]) for key, row in search.items() for hit in row[name] if hit["behalten"]]
        tags = [labels["volltextsuche"][name][key][title] for key, title in hits]
        fit = {key for key, title in hits if labels["volltextsuche"][name][key][title] == "passend"}
        topics = "Thema" if len(fit) == 1 else "Themen"
        panels[1][2].append((label, {kind: tags.count(kind) for kind, _ in colors},
                             f"{len(hits)} Seiten, passend bei {len(fit)} {topics}"))
        run = flow["standard" if name == "klexikon" else name]
        printed = dict.fromkeys((kind for kind, _ in colors), 0)
        for topic, row in run.items():
            for page in row["seiten"]:
                if page["projekt"] == name:
                    printed[labels["ablauf"][name][topic][page["titel"]]] += page["gedruckt"]
        if name == "klexikon":
            note = "heute im Standard"
        else:
            lines = sum(r["gedruckt"] for r in run.values()) - standard[0]
            blocks = sum(r["bausteine_gefuellt"] for r in run.values()) - standard[1]
            note = f"Text gesamt {signed(lines, 'Absatz', 'Absätze')}, {signed(blocks, 'Baustein', 'Bausteine')}"
        panels[2][2].append((label, printed, f"{sum(printed.values())} · {note}"))
    notes = (
        "Gleicher Titel (auch ein Alias des Hauptartikels): der heutige Weg eines weiteren Archivs in den Korpus.",
        "Volltextsuche: was eine Suche über das Archiv brächte; M11 maß sie für Wikibooks und Wikiversity, "
        "sie kam nicht.",
        f"Gedruckt: Teil 1 mit den Regeln (hybrid_light, 30.000 Zeichen); ohne Zusatz {standard[0]} Absätze, "
        f"{standard[1]} Bausteine.",
        "Farbe nach der Seite, aus der ein Absatz stammt. Einordnung: Claude, ein Gutachter, ungeprüft "
        "(m84_einordnung.yaml).",
        "Gutenberg (11 GB) nicht gemessen: kein Volltextindex, ganze Bücher statt Artikel.",
    )
    x0, scale_w, bar, row_h, head_h, top = 210, 330, 16, 24, 34, 100
    width = x0 + scale_w + 300
    height = top + len(panels) * (head_h + len(archives) * row_h + 12) + 14 + 16 * len(notes)
    svg = Svg(width, height, "Mehrwert weiterer Kiwix-Archive für die Kompendien")
    svg.text(24, 30, "Mehrwert weiterer Kiwix-Archive für die Kompendien (M84)", 17, weight="600")
    svg.text(24, 52, "Deutsche Archive der Wiki-Familie neben der Wikipedia, je Seite eingeordnet nach Passung zum "
             "angefragten Thema", 12, MUTED, limit=width - 48)
    svg.legend(24, 78, [(FITS, "passt als Text zum Thema"), (RELATED, "zum Thema, aber nicht als Text übernehmbar"),
                        (UNFIT, "anderes Thema, andere Sprache oder Fassung")], 11.5)
    y = top
    for heading, maximum, rows in panels:
        svg.line(20, y + 2, width - 20, y + 2, GRID)
        svg.text(24, y + 22, heading, 12.5, INK, weight="600", limit=width - 48)
        y += head_h
        for label, counts, summary in rows:
            svg.text(x0 - 12, y + 13, label, 12, INK, "end", "600" if label.startswith("Klexikon") else "normal",
                     limit=x0 - 30)
            x = x0
            for kind, color in colors:
                w = scale_w * counts[kind] / maximum
                svg.rect(x, y + 1, w, bar, color)
                if w > 22:
                    svg.text(x + w / 2, y + 13, counts[kind], 10.5, PAPER if color != RELATED else INK, "middle")
                x += w
            svg.text(max(x, x0) + 8, y + 13, summary, 11, MUTED, limit=width - max(x, x0) - 30)
            y += row_h
        y += 12
    for number, note in enumerate(notes):
        svg.text(24, y + 14 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save("kiwix_quellen.svg")


def quellen_empfehlung() -> None:
    """The recommendation per source after M84 (D99, pages 02 and 07): use, do not use, not needed or open, each with
    its measured reason, and three observations. Counts come from m84_kiwix_quellen.json and m84_einordnung.yaml; the
    sizes, the TED count and the Gutenberg index from the Kiwix catalog of 2026-10-09 (M84)."""
    data = load("m84_kiwix_quellen.json")
    labels = yaml.safe_load((DIR / "m84_einordnung.yaml").read_text(encoding="utf-8"))
    same, search, flow = data["abdeckung"]["gleicher_titel"], data["abdeckung"]["volltextsuche"], data["ablauf"]
    further = ("wikibooks", "wikiversity", "wiktionary", "wikisource", "wikiquote", "wikivoyage")
    topics = len(same)

    def found(name: str, kind: str | None = None) -> int:
        pages = [title for title, row in same.items() if row[name] and not row[name]["begriffsklaerung"]]
        return len(pages) if kind is None else sum(labels["gleicher_titel"][name][title] == kind for title in pages)

    def printed(run: str, name: str) -> int:
        return sum(p["gedruckt"] for r in flow[run].values() for p in r["seiten"] if p["projekt"] == name)

    def total(run: str, key: str) -> int:
        return sum(r[key] for r in flow[run].values())

    def blocks(run: str) -> int:
        return total(run, "bausteine_gefuellt") - total("standard", "bausteine_gefuellt")

    def fits(key: str, row: dict) -> bool:
        hits = [(name, hit["titel"]) for name in further for hit in row[name] if hit["behalten"]]
        return any(labels["volltextsuche"][name][key][title] == "passend" for name, title in hits)

    mixed = sum(printed(name, name) for name in ("wiktionary", "wikiquote", "wikisource"))
    lost = {run: total(run, "gedruckt") - sum(printed(run, n) for n in ("klexikon", *further))
            for run in ("standard", "alle")}
    aspects = [key for key in search if key.startswith("aspekt:")]
    aspect_fit = sum(fits(key, search[key]) for key in aspects)
    assert found("wikibooks") == found("wikiversity"), "the row says „je“"
    tables = f"{printed('wiktionary', 'wiktionary')} Absätze Deklinationstabellen und Beispielsätze im Text"
    rows = (
        ("Wikipedia, alle Artikel", "nutzen",
         "Leitquelle; aktuell halten: Ausgabe 2026-10 (18,6 GB) liest der Parser gleich, Test online"),
        ("Klexikon", "nutzen",
         f"einfache Sprache; passender Zwilling bei {found('klexikon', 'passend')} von {topics} Themen, "
         f"{printed('standard', 'klexikon')} Absätze im Text"),
        ("Wikibooks, Wikiversity", "nicht nutzen",
         f"gleicher Titel bei je {found('wikibooks')} von {topics} Themen; Suche trifft Kurse, Quiz, "
         "Druckfassungen, Ungarisch"),
        ("Wiktionary", "nicht nutzen",
         f"Wörterbuch: {tables}, {signed(blocks('wiktionary'), 'Baustein', 'Bausteine')}"),
        ("Wikiquote", "nicht nutzen",
         f"Zitatlisten: {printed('wikiquote', 'wikiquote')} Zitate im Text, "
         f"{signed(blocks('wikiquote'), 'Baustein', 'Bausteine')}"),
        ("Wikisource", "nicht nutzen",
         f"historische Texte und Linklisten: {printed('wikisource', 'wikisource')} Listenzeilen im Text"),
        ("Wikivoyage", "nicht nutzen",
         f"Reiseführer: gleicher Titel bei {found('wikivoyage')} von {topics} Themen, im Text nichts"),
        ("Projekt Gutenberg", "nicht nutzen", "11 GB ganze Bücher ohne Volltextindex: der Dienst fände nur Buchtitel"),
        ("Teilarchive der Wikipedia", "nicht nötig",
         "Chemie, Physik, Geschichte und andere stecken in der vollen Wikipedia"),
        ("übriger Katalog", "ungeeignet", "240 TED-Videos, fachfremde Wikis, Satire"),
        ("ZUM-Unterrichten, MiniKlexikon", "offen",
         "nicht bei Kiwix; ob ein eigenes Archiv hülfe, wäre eine eigene Messung"),
    )
    observations = (
        "Kein weiteres Archiv bringt passenden Text: Über den gleichen Titel kommen nur Wörterbuch, Zitate, Linklisten "
        f"und Reiseführer, und für {aspect_fit or 'keines'} der {len(aspects)} Aspektthemen fand die Suche eine "
        "passende Seite.",
        f"In den wörtlichen Profilen setzten Wiktionary, Wikiquote und Wikisource {mixed} Absätze aus Tabellen, "
        f"Zitaten und Listen in den Text; mit allen sechs Archiven fielen {lost['standard'] - lost['alle']} "
        f"Absätze der Wikipedia weg und {-blocks('alle')} Bausteine blieben leer.",
        "Schon heute holt der Klexikon-Zwilling über einen Alias falsche Absätze: Flüsse bei „Elektrischer Strom“, "
        "Gefängniszellen bei „Zelle (Biologie)“; das wird gesondert gemessen.",
    )
    badges = {"nutzen": (FITS, PAPER), "nicht nutzen": (UNFIT, PAPER), "nicht nötig": (GRID, INK),
              "ungeeignet": (GRID, INK), "offen": (TINT[LLM], INK)}
    width, row_h, top = 1000, 27, 96
    badge_x, reason_x = 262, 384
    rule_y = top + len(rows) * row_h + 8
    wrapped = [textwrap.wrap(text, int((width - 64) / (12 * CHAR_WIDTH))) for text in observations]
    height = rule_y + 40 + sum(len(lines) * 17 + 6 for lines in wrapped) + 34
    svg = Svg(width, height, "Quellen des Kompendiums: Empfehlung")
    svg.text(24, 30, "Quellen des Kompendiums: Empfehlung (D99, M84)", 17, weight="600")
    svg.text(24, 52, "Was der Dienst aus den deutschen Archiven von Kiwix nutzt, und warum", 12, MUTED,
             limit=width - 48)
    for x, head in ((24, "Quelle"), (badge_x, "Empfehlung"), (reason_x, "Grund, gemessen in M84")):
        svg.text(x, top - 10, head, 11.5, MUTED, weight="600")
    svg.line(20, top - 4, width - 20, top - 4, GRID)
    for number, (source, verdict, reason) in enumerate(rows):
        y = top + number * row_h
        fill, ink = badges[verdict]
        svg.text(24, y + 17, source, 12.5, INK, weight="600" if verdict == "nutzen" else "normal", limit=badge_x - 34)
        svg.rect(badge_x, y + 4, 106, 19, fill, 9.5)
        svg.text(badge_x + 53, y + 17.5, verdict, 11, ink, "middle", "600")
        svg.text(reason_x, y + 17, reason, 11.5, INK, limit=width - reason_x - 20)
    svg.line(20, rule_y, width - 20, rule_y, GRID)
    svg.text(24, rule_y + 26, "Beobachtungen", 13, INK, weight="600")
    y = rule_y + 46
    for lines in wrapped:
        svg.circle(30, y - 4, 2.5, MUTED)
        for line in lines:
            svg.text(40, y, line, 12, INK, limit=width - 64)
            y += 17
        y += 6
    svg.text(24, y + 14, "Empfehlung entschieden als D99 (Jan, 09.10.2026); Einordnung der Seiten: Claude, ein "
             "Gutachter, ungeprüft (m84_einordnung.yaml).", 10.5, MUTED, limit=width - 48)
    svg.save("quellen_empfehlung.svg")


OUT.mkdir(parents=True, exist_ok=True)
for chart in (prozess, prozess_optionen, artikelwahl, korpus, zuordnung_guete_zeit, zuordnung_bausteine, text_schalter,
              kombinationen, qualitaet_zeit_kosten, profile_matrix, verfahren_charts, verfahren_text, alt_neu_teile,
              profilvergleich, profiluebersicht, endpunkte, profile_verlauf, kiwix_quellen,
              quellen_empfehlung):
    chart()
