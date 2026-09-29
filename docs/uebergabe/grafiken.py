"""Charts of the handover pages (docs/uebergabe) as plain SVG: container.svg (README.md), last_dauer.svg and
last_speicher.svg from the load test of 29.09.2026 (lasttest-2026-09-29.json), and anfrage_teile.svg (aufrufe.md).

Usage: python grafiken.py - writes into bilder/ next to this script.

Drawing and palette follow docs/entwicklung/messung/mc_grafiken.py; its Svg class is copied here in short, since that
script reads its arguments on import. No chart library, so the files render on GitLab, GitHub and in a browser alike.
German number format, rounding half up.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

HERE = Path(__file__).resolve().parent
OUT = HERE / "bilder"
FONT = "Segoe UI, Helvetica Neue, Arial, sans-serif"
MONO = "Consolas, Menlo, monospace"
INK, MUTED, GRID, PAPER, PANEL = "#1f2933", "#52606d", "#dde2e8", "#ffffff", "#f3f6fa"
LOCAL, TINT, OLD = "#2f6db5", "#9dbde6", "#9aa5b1"
CONTAINER_FILL, VOLUME_FILL = "#e3edf8", "#eceef1"
CHAR_WIDTH = {FONT: 0.56, MONO: 0.6}  # average glyph width per font size, for layout checks


def de(value: float, places: str = "1") -> str:
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{rounded:,}".replace(",", "X").replace(".", ",").replace("X", ".")


def esc(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self, width: int, height: int, title: str) -> None:
        self.width, self.height, self.title = width, height, title
        self.items = [f'<rect width="{width}" height="{height}" fill="{PAPER}"/>']

    def text(
        self,
        x: float,
        y: float,
        content: object,
        size: float = 12,
        fill: str = INK,
        anchor: str = "start",
        weight: str = "normal",
        limit: float | None = None,
        family: str = FONT,
    ) -> None:
        width = len(str(content)) * size * CHAR_WIDTH[family]
        if limit is not None and width > limit:
            print(f"  zu breit ({width:.0f} > {limit:.0f} px): {content}")
        face = f' font-family="{MONO}"' if family == MONO else ""
        self.items.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}"{face}>{esc(content)}</text>'
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str,
        rx: float = 0,
        stroke: str = "none",
        sw: float = 1,
        dash: str | None = None,
    ) -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{extra}/>'
        )

    def line(
        self, x1: float, y1: float, x2: float, y2: float, stroke: str = GRID, sw: float = 1, dash: str | None = None
    ) -> None:
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
            f'stroke-width="{sw}"{extra}/>'
        )

    def circle(self, cx: float, cy: float, r: float, fill: str, stroke: str = "none", sw: float = 1) -> None:
        self.items.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
        )

    def arrow(self, points: list[tuple[float, float]], stroke: str = MUTED) -> None:
        """A line through the points with an arrowhead at the last one."""
        (x1, y1), (x2, y2) = points[-2], points[-1]
        angle = math.atan2(y2 - y1, x2 - x1)
        tip = [(x2 - 6 * math.cos(angle), y2 - 6 * math.sin(angle))]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in [*points[:-1], *tip])
        self.items.append(f'<polyline points="{path}" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        left, right = angle + math.radians(150), angle - math.radians(150)
        head = [
            (x2, y2),
            (x2 + 8 * math.cos(left), y2 + 8 * math.sin(left)),
            (x2 + 8 * math.cos(right), y2 + 8 * math.sin(right)),
        ]
        self.items.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in head)}" fill="{stroke}"/>')

    def save(self, name: str) -> None:
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" font-family="{FONT}" role="img" '
            f'aria-label="{esc(self.title)}"><title>{esc(self.title)}</title>'
        )
        (OUT / name).write_text(head + "\n".join(self.items) + "</svg>\n", encoding="utf-8", newline="\n")
        print(f"{name}: {self.width} x {self.height}")


def rounds() -> dict[str, dict[str, Any]]:
    data = json.loads((HERE / "lasttest-2026-09-29.json").read_text(encoding="utf-8"))
    return {entry["scenario"]: entry for group in data["gruppen"] for entry in group["runden"]}


def box(svg: Svg, x: float, y: float, w: float, h: float, lines: list[tuple[str, str]], kind: str) -> None:
    """A labelled box: kind container, volume or extern; lines are (text, style) with style title, text or note."""
    fill, stroke, dash = {
        "container": (CONTAINER_FILL, LOCAL, None),
        "volume": (VOLUME_FILL, OLD, None),
        "extern": (PAPER, OLD, "4 3"),
    }[kind]
    svg.rect(x, y, w, h, fill, 6, stroke, 1.2, dash)
    top = y + 20
    for text, style in lines:
        size, color, weight = {"title": (12.5, INK, "600"), "text": (11, INK, "normal"), "note": (11, MUTED, "normal")}[
            style
        ]
        svg.text(x + 10, top, text, size, color, weight=weight, limit=w - 16)
        top += 17


def container() -> None:
    """The five containers of one image, their volumes and the systems they talk to, with the measured memory."""
    svg = Svg(1000, 560, "Aufbau: fünf Container aus einem Image")
    svg.text(24, 30, "Aufbau: fünf Container aus einem Image", 17, weight="600")
    svg.text(
        24,
        50,
        "Speicher gemessen am 29.09.2026 mit Release 2.5.0 und dem Archivprofil standard; Sidecars im Leerlauf",
        12,
        MUTED,
    )
    for index, (kind, label) in enumerate((("container", "Container"), ("volume", "Volume"), ("extern", "extern"))):
        x = 24 + index * 120
        fill, stroke, dash = {
            "container": (CONTAINER_FILL, LOCAL, None),
            "volume": (VOLUME_FILL, OLD, None),
            "extern": (PAPER, OLD, "4 3"),
        }[kind]
        svg.rect(x, 64, 14, 14, fill, 3, stroke, 1.2, dash)
        svg.text(x + 20, 76, label, 11.5, MUTED)

    box(
        svg,
        24,
        112,
        160,
        80,
        [("Aufrufende Systeme", "title"), ("und Prüfansicht /ui/", "text"), ("HTTPS, X-API-Key", "note")],
        "extern",
    )
    box(
        svg,
        214,
        92,
        556,
        120,
        [
            ("api", "title"),
            ("FastAPI unter uvicorn, WEB_CONCURRENCY=2 Worker, Port 8000", "text"),
            ("Speicher der Prozesse: 2,5 GiB nach dem Start, 3,4 GiB nach dem Aufwärmen", "text"),
            ("Grenze API_MEMORY: Vorgabe 4g, empfohlen 6g · CPU: 2 bis 6 CPU-Sekunden je Anfrage", "text"),
            ("liest Archive und Indexe; schreibt Tagesbudget, Sammlungs-Cache und eigene Templates", "note"),
        ],
        "container",
    )
    box(svg, 800, 92, 176, 56, [("b-api (LLM)", "title"), ("gpt-6-luna, ab balanced", "note")], "extern")
    box(svg, 800, 156, 176, 56, [("edu-sharing (WLO)", "title"), ("Teil 3, Material, Knoten", "note")], "extern")
    svg.arrow([(184, 152), (214, 152)])
    svg.arrow([(770, 120), (800, 120)])
    svg.arrow([(770, 184), (800, 184)])

    box(
        svg,
        24,
        262,
        160,
        72,
        [("prometheus", "title"), ("optional, Profil", "note"), ("monitoring", "note")],
        "container",
    )
    svg.arrow([(184, 298), (199, 298), (199, 198), (214, 198)])
    svg.text(28, 352, "fragt /metrics alle 30 s", 10.5, MUTED)
    box(
        svg,
        214,
        262,
        160,
        72,
        [("Volume zim", "title"), ("14,7 GB Archive", "text"), ("Update-Spitze ~30 GB", "note")],
        "volume",
    )
    box(
        svg,
        394,
        262,
        376,
        72,
        [
            ("Volume state · 0,45 GB", "title"),
            ("lehrplan.db 277 MB, wikidata.db 139 MB, gnd.db 55 MB,", "text"),
            ("Tagesbudget, Sammlungs-Cache, eigene Templates", "note"),
        ],
        "volume",
    )
    svg.arrow([(294, 212), (294, 262)])
    svg.arrow([(582, 212), (582, 262)])
    svg.text(300, 242, "liest", 10.5, MUTED)
    svg.text(588, 242, "liest, schreibt", 10.5, MUTED)

    sidecars = [  # x, width, name, interval, source; the volume they write sits above them
        (214, 160, "zim-updater", "prüft alle 30 Tage", "Kiwix-Katalog"),
        (394, 118, "lehrplan-updater", "prüft alle 7 Tage", "MEM (SPARQL)"),
        (523, 118, "wikidata-updater", "prüft täglich", "Wikimedia-Dumps"),
        (652, 118, "gnd-updater", "prüft täglich", "DNB-Abzüge"),
    ]
    for x, width, name, interval, source in sidecars:
        svg.rect(x, 384, width, 66, CONTAINER_FILL, 6, LOCAL, 1.2)
        svg.text(x + 8, 403, name, 11.5, INK, weight="600", limit=width - 12)
        svg.text(x + 8, 420, "~107 MiB RAM", 11, INK, limit=width - 12)
        svg.text(x + 8, 437, interval, 11, MUTED, limit=width - 12)
        svg.arrow([(x + width / 2, 384), (x + width / 2, 334)])
        svg.arrow([(x + width / 2, 488), (x + width / 2, 450)])
        svg.text(x + width / 2, 502, source, 10.5, MUTED, "middle", limit=width)
    svg.text(24, 404, "vier Sidecars aus", 11, MUTED)
    svg.text(24, 420, "demselben Image laden", 11, MUTED)
    svg.text(24, 436, "neue Daten, prüfen sie", 11, MUTED)
    svg.text(24, 452, "und ersetzen die alten", 11, MUTED)
    svg.text(
        24,
        536,
        "Summe: RAM 3,4 GiB (api) + 0,4 GiB (Sidecars) + System · Platte 16,5 GB im Betrieb, rund 32 GB beim "
        "Wikipedia-Update · Ausgehende Ziele: siehe Tabelle",
        10.5,
        MUTED,
        limit=952,
    )
    svg.save("container.svg")


def dauer() -> None:
    """Seconds per request while several run at once: the span of the requests and their median, per scenario."""
    data = rounds()
    rows = [  # label, rounds, tokens
        ("1 Kompendium, llm-free", ["s1-free-1"], "keine"),
        ("3 Kompendien, llm-free", ["s2-free-3"], "keine"),
        ("5 Kompendien, llm-free (5 Runden)", ["s3-free-5", "soak-a", "soak-b", "soak-c", "soak-d"], "keine"),
        ("5 Kompendien, llm-free, Themen wiederholt", ["wA-m2"], "keine"),
        ("5 Kompendien, balanced", ["s4-bal-5"], None),
        ("5 Kompendien, best-quality", ["s5-best-5"], None),
        ("5 × 10 QA-Paare, llm-free", ["s6-qa-free-5"], "keine"),
        ("3 × 10 QA-Paare, best-quality", ["s7-qa-best-3"], None),
    ]
    label_w, plot_w, token_w, row_h, top = 300, 460, 150, 30, 104
    scale = 50.0
    width = 24 + label_w + plot_w + 24 + token_w + 24
    svg = Svg(width, top + len(rows) * row_h + 92, "Dauer je Anfrage bei gleichzeitigen Anfragen")
    svg.text(24, 30, "Dauer je Anfrage, wenn mehrere gleichzeitig kommen", 17, weight="600")
    svg.text(24, 50, "API mit 2 Workern, gemessen am 29.09.2026; jede Runde mit eigenen Themen", 12, MUTED)
    x0 = 24 + label_w
    svg.rect(x0, 62, 26, 9, TINT, 4)
    svg.text(x0 + 32, 71, "Spanne der Anfragen einer Runde", 11.5, MUTED)
    svg.circle(x0 + 240, 67, 5, LOCAL, PAPER, 2)
    svg.text(x0 + 251, 71, "Median", 11.5, MUTED)
    for tick in range(0, 60, 10):
        x = x0 + plot_w * tick / scale
        svg.line(x, top - 8, x, top + len(rows) * row_h - 6, GRID)
        svg.text(x, top + len(rows) * row_h + 10, f"{tick} s", 10.5, MUTED, "middle")
    svg.text(x0 + plot_w + 24, top - 14, "Tokens je Anfrage", 11.5, MUTED, weight="600")
    for index, (label, names, tokens) in enumerate(rows):
        y = top + index * row_h
        seconds = [float(r["seconds"]) for name in names for r in data[name]["requests"]]
        low, high, middle = min(seconds), max(seconds), statistics.median(seconds)
        svg.text(x0 - 12, y + 9, label, 12, INK, "end", limit=label_w - 16)
        left, right = x0 + plot_w * low / scale, x0 + plot_w * high / scale
        svg.rect(left - 4, y, right - left + 8, 9, TINT, 4)
        svg.circle(x0 + plot_w * middle / scale, y + 4.5, 5, LOCAL, PAPER, 2)
        span = f"{de(low)} s" if low == high else f"{de(low)} bis {de(high)} s"
        svg.text(right + 10, y + 9, span, 11, MUTED, limit=x0 + plot_w + 16 - right)
        if tokens is None:
            used = [r["tokens"] for name in names for r in data[name]["requests"]]
            tokens = f"{de(min(used), '1')} bis {de(max(used), '1')}"
        svg.text(x0 + plot_w + 24, y + 9, tokens, 11.5, INK, limit=token_w)
    notes = (
        "Frist je Anfrage (REQUEST_TIMEOUT_S) 120 s. llm-free: nur Regeln; balanced: das LLM wählt den Artikel; "
        "best-quality: dazu Zuordnung",
        "und Lehrplanprüfung durch das LLM (gpt-6-luna über die Staging-b-api). Wiederholte Themen treffen die Caches "
        "der Worker.",
        "Daten: lasttest-2026-09-29.json; Aufbau und Einzelwerte dort.",
    )
    for number, note in enumerate(notes):
        svg.text(24, top + len(rows) * row_h + 40 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save("last_dauer.svg")


def speicher() -> None:
    """Memory of the API container after each round: the processes, and the page cache on top, against the limits."""
    data = rounds()
    order = [  # round, count, kind
        ("s1-free-1", "1×", "llm-free"),
        ("s2-free-3", "3×", "llm-free"),
        ("s3-free-5", "5×", "llm-free"),
        ("s4-bal-5", "5×", "balanced"),
        ("s5-best-5", "5×", "best-q."),
        ("s6-qa-free-5", "5× QA", "llm-free"),
        ("s7-qa-best-3", "3× QA", "best-q."),
        ("soak-a", "5×", "llm-free"),
        ("soak-b", "5×", "llm-free"),
        ("soak-c", "5×", "llm-free"),
        ("soak-d", "5×", "llm-free"),
    ]
    left, top, plot_h, slot, bar = 70, 96, 300, 74, 40
    scale = 6.5
    width = left + len(order) * slot + 196
    svg = Svg(width, top + plot_h + 118, "Speicher des api-Containers über 47 Anfragen")
    svg.text(24, 30, "Speicher des api-Containers über 47 Anfragen", 17, weight="600")
    svg.text(
        24, 50, "Spitze je Runde, die Runden nacheinander ohne Neustart; 2 Worker, Grenze API_MEMORY=4g", 12, MUTED
    )
    svg.rect(left, 62, 14, 14, LOCAL, 3)
    svg.text(left + 20, 74, "Prozesse (RSS)", 11.5, MUTED)
    svg.rect(left + 140, 62, 14, 14, TINT, 3)
    svg.text(left + 160, 74, "dazu Seiten-Cache der Archive, gibt der Kernel bei Bedarf frei", 11.5, MUTED)

    def py(value: float) -> float:
        return top + plot_h - plot_h * value / scale

    for tick in range(7):
        svg.line(left, py(tick), left + len(order) * slot, py(tick), GRID)
        svg.text(left - 8, py(tick) + 4, f"{tick} GiB", 10.5, MUTED, "end")
    for index, (name, count, kind) in enumerate(order):
        entry = data[name]
        x = left + index * slot + (slot - bar) / 2
        rss, usage = entry["peak_rss_gib"], entry["peak_usage_gib"]
        svg.rect(x, py(rss), bar, py(0) - py(rss), LOCAL, 2)
        svg.rect(x, py(usage), bar, py(rss) - py(usage) - 2, TINT, 2)
        svg.text(x + bar / 2, py(rss) + 15, de(rss, "0.1"), 10.5, PAPER, "middle", "600")
        svg.text(x + bar / 2, py(0) + 16, count, 10.5, INK, "middle")
        svg.text(x + bar / 2, py(0) + 30, kind, 10.5, MUTED, "middle")
    for value, label in ((4, "Grenze heute: API_MEMORY=4g"), (6, "empfohlen: API_MEMORY=6g")):
        svg.line(left, py(value), left + len(order) * slot + 6, py(value), INK, 1.2, "5 4")
        svg.text(left + len(order) * slot + 12, py(value) + 4, label, 11, INK, limit=180)
    first, last = left, left + 7 * slot
    svg.line(first + 4, py(0) + 40, last - 4, py(0) + 40, MUTED)
    svg.text((first + last) / 2, py(0) + 54, "Lastrunden: Kompendien und QA-Paare", 10.5, MUTED, "middle")
    svg.line(last + 4, py(0) + 40, left + len(order) * slot - 4, py(0) + 40, MUTED)
    svg.text((last + left + len(order) * slot) / 2, py(0) + 54, "vier Runden, 20 neue Themen", 10.5, MUTED, "middle")
    notes = (
        "Die Prozesse wachsen beim Aufwärmen (Caches je Worker) und bleiben dann bei 3,4 GiB; der Seiten-Cache füllt "
        "die Grenze bis 4,0 GiB.",
        "Mit drei Workern: 4,3 GiB nach 15 Anfragen, 1,5 bis 1,6 GiB je Worker. Daten: lasttest-2026-09-29.json.",
    )
    for number, note in enumerate(notes):
        svg.text(24, py(0) + 82 + 16 * number, note, 10.5, MUTED, limit=width - 48)
    svg.save("last_speicher.svg")


def anfrage_teile() -> None:
    """Which fields of a compendium request feed which part, and where each part stands in the answer."""
    svg = Svg(1000, 486, "Eine Kompendium-Anfrage: Eingaben, Teile, Antwort")
    svg.text(24, 30, "Eine Kompendium-Anfrage: Eingaben, Teile, Antwort", 17, weight="600")
    svg.text(24, 50, "POST /api/v2/compendium; parts wählt die Teile, fehlende Felder nehmen die Vorgaben", 12, MUTED)
    columns = ((24, 300, "In der Anfrage"), (364, 250, "Teil des Kompendiums"), (674, 302, "In der Antwort"))
    for x, _, title in columns:
        svg.text(x, 84, title, 12.5, MUTED, weight="600")
    rows = [  # height, request fields, part lines, answer fields
        (
            104,
            [
                ("topic", "Thema, z. B. Photosynthese"),
                ("node_id", "oder ein Material, eine Sammlung"),
                ("knowledge_collection_id", ""),
                ("", "Materialien als weitere Quellen"),
                ("preset", "Profil, target_length, template_id"),
            ],
            ("Teil 1 · Weltwissen", "Wikipedia und Klexikon lokal,", "dazu die Materialien", 'parts: "world"'),
            [
                (".sections[].title", "die Bausteine"),
                (".sections[].text", "ihr Text mit Belegnummern"),
                (".sources[]", "die Belege je Nummer"),
            ],
        ),
        (
            70,
            [("topic", "liefert die Stichwörter"), ("subject", "grenzt auf ein Fach ein")],
            ("Teil 2 · Lehrplanbezüge", "MEM-Lehrpläne, lokal", "", 'parts: "curricula"'),
            [(".curricula.markdown", "Text von Teil 2"), (".curricula.entries[]", "Treffer als Liste")],
        ),
        (
            70,
            [("collection_id", "Sammlung in edu-sharing;"), ("", "ihr Titel ist das Thema, fehlt topic")],
            ("Teil 3 · Sammlungsüberblick", "Inhalte der Sammlung zur Anfragezeit", "", 'parts: "collection"'),
            [(".collection.markdown", "Text von Teil 3"), (".collection.summary", "Zahlen zur Sammlung")],
        ),
    ]
    y = 96
    for height, fields, part, answers in rows:
        svg.rect(24, y, 300, height, PANEL, 6)
        for number, (field, text) in enumerate(fields):
            line_y = y + 20 + 17 * number
            if field:
                svg.text(34, line_y, field, 11, INK, weight="600", family=MONO)
            if text:
                offset = 34 + (len(field) + 1) * 11 * 0.6 if field else 34
                svg.text(offset, line_y, text, 11, MUTED, limit=324 - offset - 6)
        svg.rect(364, y, 250, height, CONTAINER_FILL, 6, LOCAL, 1.2)
        svg.text(376, y + 21, part[0], 12.5, INK, weight="600", limit=230)
        svg.text(376, y + 39, part[1], 11, INK, limit=230)
        if part[2]:
            svg.text(376, y + 56, part[2], 11, INK, limit=230)
        svg.text(376, y + height - 10, part[3], 11, MUTED, family=MONO, limit=230)
        svg.rect(674, y, 302, height, PANEL, 6)
        for number, (field, text) in enumerate(answers):
            svg.text(684, y + 20 + 17 * number, field, 11, INK, weight="600", family=MONO)
            svg.text(
                684 + (len(field) + 1) * 11 * 0.6,
                y + 20 + 17 * number,
                text,
                11,
                MUTED,
                limit=966 - 684 - (len(field) + 1) * 6.6,
            )
        svg.arrow([(324, y + height / 2), (364, y + height / 2)])
        svg.arrow([(614, y + height / 2), (674, y + height / 2)])
        y += height + 14
    svg.rect(24, y + 6, 300, 88, PANEL, 6)
    svg.text(34, y + 26, "parts", 11, INK, weight="600", family=MONO)
    svg.text(34 + 6 * 6.6, y + 26, "welche Teile, Vorgabe alle drei;", 11, MUTED)
    svg.text(34, y + 43, "Teil 3 entfällt ohne collection_id", 11, MUTED)
    svg.text(34, y + 60, "frontmatter_in_markdown", 11, INK, weight="600", family=MONO)
    svg.text(34, y + 77, "false: Text beginnt mit der Überschrift", 11, MUTED)
    svg.rect(674, y + 6, 302, 88, CONTAINER_FILL, 6, LOCAL, 1.2)
    svg.text(684, y + 26, ".markdown", 11, INK, weight="600", family=MONO)
    svg.text(684 + 10 * 6.6, y + 26, "das ganze Kompendium:", 11, INK)
    svg.text(684, y + 43, "Frontmatter, Teil 1, 2 und 3 in einem Text", 11, INK, limit=286)
    svg.text(684, y + 60, ".parts_status", 11, INK, weight="600", family=MONO)
    svg.text(684 + 14 * 6.6, y + 60, "ok, empty, incomplete je Teil", 11, MUTED, limit=196)
    svg.text(684, y + 77, ".audit.llm_tokens", 11, INK, weight="600", family=MONO)
    svg.text(684 + 18 * 6.6, y + 77, "Tokens und LLM-Aufrufe", 11, MUTED, limit=170)
    svg.arrow([(489, y - 14), (489, y + 50), (674, y + 50)])
    svg.text(497, y + 42, "alle Teile in einem Text", 10.5, MUTED)
    svg.save("anfrage_teile.svg")


OUT.mkdir(parents=True, exist_ok=True)
for chart in (container, dauer, speicher, anfrage_teile):
    chart()
