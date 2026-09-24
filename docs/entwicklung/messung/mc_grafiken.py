"""Charts of the decision paper (docs/entwicklung/07-entscheidungsvorlage.md) as plain SVG (project venv, no LLM).

Reads the raw files in ergebnisse/ and the relevance gold of eval/artikelwahl, and writes prozess.svg,
prozess_optionen.svg, artikelwahl.svg, korpus.svg, zuordnung_guete_zeit.svg, zuordnung_bausteine.svg,
text_schalter.svg and kombinationen.svg. Numbers no raw file holds are written here with their source: the text
switches (measured on 2026-09-18 and 19, 02-weltwissen.md) and the step times of the server (M1,
05-messprotokoll.md). No chart library, so the files render on GitHub, in Confluence and in a browser alike.
Rounding half up, German number format.

Usage: python mc_grafiken.py <ergebnisse-dir> <bilder-dir>
"""

from __future__ import annotations

import json
import math
import statistics
import sys
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
TINT = {LOCAL: "#9dbde6", LLM: "#f2c28f", "#7a5aa6": "#c3b2dc"}  # lighter part of a bar: the span of runs
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
    """Teil 1 from the request to the document, with the switch, its default and the time of every step."""
    steps = [
        ("1", "Hauptartikel finden", "Thema bereinigen, im Archivindex auflösen", False,
         ["Schalter article_choice: rule-based oder llm",
          "Standard: rule-based (D40); llm mit preset balanced oder best-quality",
          "Zeit: rund 0,03 s; LLM nur bei unsicheren Themen, +1,0 bis 2,7 s"]),
        ("2", "Korpus bauen", "bis 12 Artikel, höchstens 400 Absätze", False,
         ["Einstellungen: max_articles (12), ZIM_PROFILE (standard)",
          "Trefferprüfung durch das LLM, wenn article_choice=llm",
          "Zeit: 0,9 s auf dem Server; Trefferprüfung +1,4 s (Median)"]),
        ("3", "Absätze zuordnen", "10 Inhaltsbausteine des Templates SC26", False,
         ["Schalter matcher: hybrid_light, bm25, char_tfidf, lexicon_only, llm",
          "Standard: hybrid_light; llm mit preset best-quality",
          "Zeit: 0,3 s; llm 10 bis 25 s und rund 34.500 Tokens"]),
        ("4", "Text bauen", "Absätze wörtlich, mit Belegnummer", False,
         ["Schalter extraction: rule-based oder llm; Länge: target_length",
          "Standard: rule-based, 12.000 Zeichen",
          "Zeit: 1,1 s auf dem Server; llm rund 11 s"]),
        ("5", "Umformulieren (optional)", "LLM schreibt Bausteine neu, Belegprüfung", True,
         ["Schalter generation: rule-based, llm-fast, llm; dazu enrichment",
          "Standard: rule-based, sources-only",
          "Zeit: llm-fast 9 bis 15 s, llm 16 bis 20 s"]),
        ("6", "Zusammensetzen", "mit Teil 2 Lehrpläne und Teil 3 Sammlung", False,
         ["Teil 2: 0,24 s; Teil 3: 0,16 s aus dem Zwischenspeicher",
          "Ergebnis: Markdown und JSON, mit Vorspann und Audit",
          "Teil 1 ohne LLM: 1,2 bis 2,0 s"]),
    ]
    llm_steps = {"1", "2", "3", "4", "5"}
    top, row, box_h = 92, 96, 70
    svg = Svg(840, top + row * len(steps) + 40, "Ablauf von Teil 1 mit Schaltern, Standardwerten und Zeiten")
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
                              (LLM, "LLM-Option über die b-api (gpt-5.6-luna)")])
    svg.save("prozess.svg")


def prozess_optionen() -> None:
    """The steps of part 1 with every option in a row: quality, time, tokens and the presets that use it (D41)."""
    presets = [("llm-free", LOCAL, "l"), ("balanced", "#7a5aa6", "b"), ("best-quality", LLM, "q")]
    rows = {  # step: [(option, default, llm, presets, quality, time, tokens)]
        ("1", "Hauptartikel finden", "Thema im Archivindex auflösen"): [
            ("rule-based", True, False, "l", "86 von 94 richtig", "0,03 s", "0"),
            ("llm", False, True, "bq", "91 von 94 richtig", "+1,0 bis 2,7 s", "rund 950"),
        ],
        ("2", "Korpus bauen", "bis 12 Artikel, 400 Absätze"): [
            ("Profil standard", True, False, "lbq", "26 von 358 unpassend", "0,9 s", "0"),
            ("Trefferprüfung", False, True, "bq", "10 von 356 unpassend", "+1,4 s", "rund 890"),
            ("Profil extended", False, False, "", "+1 gefüllter Baustein", "–", "0"),
            ("knowledge_collection_id", False, False, "", "nicht gemessen", "–", "0"),
        ],
        ("3", "Absätze zuordnen", "10 Inhaltsbausteine SC26"): [
            ("hybrid_light", True, False, "lb", "macro-F1 0,43", "0,3 s", "0"),
            ("char_tfidf", False, False, "", "macro-F1 0,40", "0,25 s", "0"),
            ("bm25", False, False, "", "macro-F1 0,36", "0,03 s", "0"),
            ("lexicon_only", False, False, "", "macro-F1 0,35", "0,02 s", "0"),
            ("llm", False, True, "q", "macro-F1 0,69 bis 0,72", "10 bis 25 s", "rund 34.500"),
        ],
        ("4", "Text bauen", "Absätze wörtlich, belegt"): [
            ("rule-based", True, False, "lbq", "jeder Satz wörtlich belegt", "1,1 s", "0"),
            ("extraction=llm", False, True, "", "+14 richtige Absätze, 59 %", "rund 11 s", "14.000–22.400"),
        ],
        ("5", "Umformulieren", "optional, mit Belegprüfung"): [
            ("rule-based", True, False, "lbq", "Text bleibt wörtlich", "–", "0"),
            ("generation=llm-fast", False, True, "", "2 Bausteine neu, belegt", "9 bis 15 s", "2.300–4.000"),
            ("generation=llm", False, True, "", "alle Bausteine neu, belegt", "16 bis 20 s", "10.500–14.500"),
        ],
        ("6", "Zusammensetzen", "mit Teil 2 und Teil 3"): [
            ("Teil 2 und Teil 3", True, False, "lbq", "kein Schalter", "0,24 / 0,16 s", "0"),
        ],
    }
    columns = {"option": 282, "stufe": 488, "guete": 560, "zeit": 752, "tokens": 858}
    line_h, pad, top = 24, 8, 88
    def block_height(options: list[tuple[str, bool, bool, str, str, str, str]]) -> int:
        return max(len(options) * line_h + 2 * pad, 64)  # room for the two lines of the step box

    height = top + sum(block_height(options) for options in rows.values()) + 96
    svg = Svg(960, height, "Ablauf von Teil 1 mit allen Optionen, ihrer Güte, Zeit und ihren Tokens")
    svg.text(20, 30, "Teil 1: jeder Schritt mit seinen Optionen", 17, weight="600")
    svg.text(20, 52, "Standard ist die Stufe llm-free (D40); preset wählt eine Stufe, einzelne Schalter gehen vor "
             "(D41).", 12, MUTED, limit=920)
    for key, head in (("option", "Option"), ("stufe", "Stufe"), ("guete", "Güte"), ("zeit", "Zeit"),
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
        svg.line(268, y, 952, y, GRID)
        for index, (option, default, llm, uses, quality, time, tokens) in enumerate(options):
            base = y + (block - len(options) * line_h) / 2 + index * line_h + 16
            svg.circle(columns["option"] - 8, base - 4, 4, LLM if llm else LOCAL)
            svg.text(columns["option"], base, option, 12, INK, weight="600" if default else "normal",
                     limit=140 if default else 196)
            if default:
                width = len(option) * 12 * CHAR_WIDTH + (8 if default else 0)
                svg.rect(columns["option"] + width + 4, base - 11, 52, 15, PANEL, 7, GRID)
                svg.text(columns["option"] + width + 30, base - 0.5, "Standard", 9.5, MUTED, "middle")
            for slot, (_, color, code) in enumerate(presets):
                if code in uses:
                    svg.rect(columns["stufe"] + slot * 16, base - 10, 11, 11, color, 2)
            svg.text(columns["guete"], base, quality, 12, INK, limit=186)
            svg.text(columns["zeit"], base, time, 12, INK, limit=100)
            svg.text(columns["tokens"], base, tokens, 12, INK, limit=94)
        y += block
    svg.line(268, y, 952, y, GRID)
    svg.legend(20, y + 30, [(LOCAL, "lokal, ohne Tokens"), (LLM, "über das LLM der b-api")], 11.5)
    svg.legend(430, y + 30, [(color, f"Stufe {tag}") for tag, color, _ in presets], 11.5)
    svg.text(20, y + 56, "Güte: Hauptartikel von 94 Goldanfragen (M9); gedruckte Absätze aus unpassenden Artikeln in "
             "20 Themen (M10); gefüllte Bausteine (M11);", 10.5, MUTED, limit=920)
    svg.text(20, y + 72, "macro-F1 am Goldstandard (M12, M15); Text (M3, 19.09.). Zeit: Server (M1, M3) oder "
             "Entwicklungsrechner (M13, M14). Tokens je Kompendium.", 10.5, MUTED, limit=920)
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
    """Relevance of the corpus articles by origin (M8, blind gold) and the effect of the hit check (M10)."""
    result = load("m8_artikelwahl.json")
    gold = yaml.safe_load(LABELS.read_text(encoding="utf-8"))["labels"]
    origins = {"primary": "Hauptartikel", "same_topic": "dasselbe Thema aus Klexikon",
               "linked": "verlinkte Unterartikel", "search": "Volltexttreffer je Baustein"}
    articles = [(a["herkunft"], gold[topic][f"{a['projekt']}:{a['titel']}"])
                for topic, corpus in result["korpus"].items() for a in corpus["artikel"]]
    groups = [(label, [n for o, n in articles if o == origin]) for origin, label in origins.items()]
    groups.append(("alle gewählten Artikel", [n for _, n in articles]))
    effect = load("m10_treffer_wirkung.json")
    printed = {key: [sum(t[key]["gedruckt"].get(str(n), 0) for t in effect.values()) for n in (2, 1, 0)]
               for key in ("heute", "ohne_0_treffer")}
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
    svg.text(24, y, "Gedruckte Absätze nach Artikel, Standard, 20 Themen (M10)", 15, weight="600")
    y += 22
    for key, label in (("heute", "ohne Trefferprüfung"), ("ohne_0_treffer", "mit Trefferprüfung (llm)")):
        total = sum(printed[key])
        svg.text(x0 - 12, y + 16, label, 12.5, INK, "end", limit=x0 - 30)
        x = x0
        for count, color in zip(printed[key], (FITS, RELATED, UNFIT), strict=True):
            svg.rect(x, y, width * count / total, bar, color)
            x += width * count / total
        svg.text(x0 + width + 10, y + 16, f"{printed[key][2]} von {total} unpassend", 11.5, MUTED, limit=160)
        y += bar + 12
    svg.text(24, y + 16, "Unpassend sind vor allem Volltexttreffer; die Trefferprüfung verwirft 11 von 16 davon und "
             "keinen passenden.", 11.5, MUTED, limit=712)
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
                  ("hybrid_light", "hybrid_light + M2V", "hybrid_light (Standard)", 12, -8, "start")]
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
        ("extraktiv (Standard)", (1.1, 1.1), (0, 0), False),  # M1: building the text on the server
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


def kombinationen() -> None:
    """The three recommended combinations: time of part 1, tokens and quality (M9, M12 to M15)."""
    rules = load("m13_zeit_neu_regeln_zweiter_lauf.json")["zusammenfassung"]["rule-based"]["median_s"]
    llm_article = [r for r in load("m13_zeit_neu.json")["laeufe"] if r["weg"] == "llm"]
    extra = statistics.median((r["phasen_ms"]["hit_check"] + r["phasen_ms"]["resolve"]) / 1000 for r in llm_article)
    article_tokens = statistics.median(r["tokens"] for r in llm_article)
    matcher = [load(f"{m}_zeit_zuordnung.json")["zusammenfassung"]["llm"]["median_s"] for m in ("m13", "m14")]
    m14 = load("m14_zeit_zuordnung.json")["laeufe"]
    matcher_tokens = statistics.mean(r["tokens"] for r in m14 if r["weg"] == "llm")
    budget = 2_000_000  # LLM_DAILY_TOKEN_BUDGET
    combos = [  # label, time low, time high, tokens, articles right of 94, macro-F1, color
        ("LLM-frei", rules, rules, 0, 86, "0,43", LOCAL),
        ("ausgewogen", rules + extra, rules + extra, article_tokens, 91, "0,43", "#7a5aa6"),
        ("beste Qualität", matcher[0] + extra, matcher[1] + extra, matcher_tokens + article_tokens, 91,
         "0,69 bis 0,72", LLM),
    ]
    x0, width, bar, row = 150, 200, 20, 70
    svg = Svg(760, 110 + len(combos) * row + 40, "Die drei empfohlenen Kombinationen")
    svg.text(24, 30, "Die drei empfohlenen Kombinationen im Vergleich", 17, weight="600")
    heads = [(x0, "Teil 1 je Kompendium"), (x0 + width + 30, "Tokens je Kompendium"), (620, "Güte")]
    for x, head in heads:
        svg.text(x, 64, head, 12, MUTED)
    y = 82
    for label, low, high, tokens, articles, f1, color in combos:
        svg.text(x0 - 12, y + 15, label, 13.5, INK, "end", "600")
        span_bar(svg, x0, y, width / 30, low, high, color, bar)
        time_label = f"{secs(low)} s" if high == low else f"{secs(low)} bis {secs(high)} s"
        svg.text(x0 + width * high / 30 + 6, y + 15, time_label, 11.5, MUTED)
        tx = x0 + width + 30
        svg.rect(tx, y, width * tokens / 40_000, bar, color, 2)
        svg.text(tx + width * tokens / 40_000 + 6, y + 15, de(round(tokens, -2) if tokens > 5_000 else tokens), 11.5,
                 MUTED)
        daily = "ohne Grenze" if not tokens else f"rund {de(budget / tokens)} je Tag"
        svg.text(tx, y + bar + 16, f"Tagesbudget 2 Mio.: {daily}", 11, MUTED)
        svg.text(620, y + 9, f"Artikel: {articles} von 94", 11.5, INK)
        svg.text(620, y + 27, f"Zuordnung: {f1}", 11.5, INK)
        y += row
    svg.text(24, y + 18, "Zeit: Mediane auf dem Entwicklungsrechner (M13, M14); beste Qualität als Summe, "
             "nicht zusammen gemessen.", 11, MUTED, limit=712)
    svg.save("kombinationen.svg")


OUT.mkdir(parents=True, exist_ok=True)
for chart in (prozess, prozess_optionen, artikelwahl, korpus, zuordnung_guete_zeit, zuordnung_bausteine, text_schalter,
              kombinationen):
    chart()
