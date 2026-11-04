"""Charts of the fact sheet (steckbrief.md) and of the implementation guide (leitfaden-dienste.md), plain SVG on white:
steckbrief_kontext.svg, steckbrief_funktionen.svg and leitfaden_bapi.svg in bilder/.

Usage: python steckbrief_grafiken.py - the PNG versions for Confluence come from these with a headless browser at
twice the size. Times and tokens are the measured medians of M82 and M91 (docs/entwicklung/05-messprotokoll.md).
Drawing and palette as in grafiken.py and qualitaetsprofil.py, whose Svg class is copied here in short.
"""

from __future__ import annotations

import math
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

HERE = Path(__file__).resolve().parent
OUT = HERE / "bilder"
FONT = "Segoe UI, Helvetica Neue, Arial, sans-serif"
INK, MUTED, GRID, PAPER, PANEL = "#1f2933", "#52606d", "#dde2e8", "#ffffff", "#f3f6fa"
LOCAL, LLM, OLD = "#2f6db5", "#d9822b", "#9aa5b1"
BOX, BOX_LINE = "#e3edf8", "#2f6db5"
CHAR_WIDTH = 0.56


def de(value: float, places: str = "0.1") -> str:
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
    ) -> None:
        width = len(str(content)) * size * CHAR_WIDTH
        if limit is not None and width > limit:
            print(f"  zu breit ({width:.0f} > {limit:.0f} px): {content}")
        self.items.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{esc(content)}</text>'
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

    def arrow(self, points: list[tuple[float, float]], stroke: str = MUTED, dash: str | None = None) -> None:
        (x1, y1), (x2, y2) = points[-2], points[-1]
        angle = math.atan2(y2 - y1, x2 - x1)
        tip = [(x2 - 6 * math.cos(angle), y2 - 6 * math.sin(angle))]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in [*points[:-1], *tip])
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<polyline points="{path}" fill="none" stroke="{stroke}" stroke-width="1.6"{extra}/>')
        left, right = angle + math.radians(150), angle - math.radians(150)
        head = [
            (x2, y2),
            (x2 + 8 * math.cos(left), y2 + 8 * math.sin(left)),
            (x2 + 8 * math.cos(right), y2 + 8 * math.sin(right)),
        ]
        self.items.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in head)}" fill="{stroke}"/>')

    def box(self, x: float, y: float, w: float, h: float, lines: list[str], kind: str = "own") -> None:
        """A labelled box: own (the service), extern (another system, dashed), store (a volume)."""
        fill, stroke, dash = {
            "own": (BOX, BOX_LINE, None),
            "extern": (PAPER, OLD, "4 3"),
            "store": (PANEL, OLD, None),
            "proxy": ("#fbeee0", LLM, None),
        }[kind]
        self.rect(x, y, w, h, fill, 6, stroke, 1.3, dash)
        top = y + h / 2 - (len(lines) - 1) * 8 + 4
        for index, line in enumerate(lines):
            self.text(
                x + w / 2,
                top + index * 16,
                line,
                13 if index == 0 else 11,
                INK if index == 0 else MUTED,
                "middle",
                "700" if index == 0 else "normal",
                limit=w - 12,
            )

    def save(self, name: str) -> None:
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" font-family="{FONT}" role="img" '
            f'aria-label="{esc(self.title)}"><title>{esc(self.title)}</title>'
        )
        (OUT / name).write_text(head + "\n".join(self.items) + "</svg>\n", encoding="utf-8", newline="\n")
        print(f"{name}: {self.width} x {self.height}")


def kontext() -> None:
    svg = Svg(880, 400, "Kompendiale Texte im Kontext: b-api, Ports, Updater und Daten")
    svg.text(24, 32, "Kompendiale Texte im Kontext", 17, weight="700")
    svg.text(
        24,
        52,
        "Ein Image; die API hinter der b-api, die Updater als CronJobs (Helm) oder Schleifen (Compose)",
        12,
        MUTED,
        limit=832,
    )
    svg.box(24, 84, 150, 60, ["Aufrufer", "mit b-api-Schlüssel"], "extern")
    svg.box(220, 84, 160, 60, ["b-api", "Auth, Limits, Abrechnung"], "proxy")
    svg.box(430, 80, 210, 150, ["API", "Port 8000 öffentlich", "Port 9000 intern"])
    svg.box(720, 80, 140, 46, ["LLM", "über die b-api"], "extern")
    svg.box(720, 142, 140, 46, ["edu-sharing", "optional"], "extern")
    svg.box(720, 204, 140, 46, ["Jaeger", "optional"], "extern")
    svg.box(220, 186, 160, 52, ["Prometheus", "liest /metrics :9000"], "extern")
    svg.box(220, 300, 160, 60, ["Volumes", "zim 60 Gi · state 5 Gi"], "store")
    svg.box(430, 300, 210, 60, ["Updater (4)", "CronJobs nachts / Schleife"])
    svg.box(720, 300, 140, 60, ["Quellen", "Kiwix, MEM, DNB …"], "extern")
    svg.arrow([(174, 114), (220, 114)])
    svg.arrow([(380, 114), (430, 114)])
    svg.text(405, 106, "B3", 10.5, MUTED, "middle")
    svg.arrow([(640, 103), (720, 103)])
    svg.arrow([(640, 165), (720, 165)], dash="4 3")
    svg.text(680, 158, "Knoten", 10.5, MUTED, "middle")
    svg.arrow([(640, 227), (720, 227)], dash="4 3")
    svg.text(680, 220, "Spans", 10.5, MUTED, "middle")
    svg.arrow([(380, 212), (430, 212)])
    svg.arrow([(430, 330), (380, 330)])
    svg.text(405, 322, "schreibt", 10.5, MUTED, "middle")
    svg.arrow([(640, 330), (720, 330)])
    svg.arrow([(300, 300), (300, 270), (470, 270), (470, 230)])
    svg.text(385, 264, "liest, lokale Kopie", 10.5, MUTED, "middle")
    svg.text(
        24,
        392,
        "Gestrichelt: optional. edu-sharing nur mit node_id oder Teil 3; sonst reicht Text-Input.",
        11.5,
        MUTED,
        limit=832,
    )
    svg.save("steckbrief_kontext.svg")


def funktionen() -> None:
    rows = (
        ("Kompendium, Teil 1 und 2", 2.9, 27.5, "89.000"),
        ("Fragen und Antworten (Thema)", 3.4, 8.7, "3.200"),
        ("Fragen und Antworten (Text)", 0.5, 5.8, "8.200"),
        ("Entitäten (1.500 Zeichen)", 2.4, 5.8, "1.200"),
        ("Wissenstexte", 0.6, 3.6, "750"),
        ("Lehrplansuche (Thema)", 0.6, 4.4, "4.900"),
    )
    svg = Svg(880, 410, "Funktionen: Laufzeit und Tokens je Aufruf, llm-free und Standard")
    svg.text(24, 32, "Funktionen: Sekunden je Aufruf", 17, weight="700")
    svg.text(
        24,
        52,
        "Median allein (M82, M91); Tokens im Standard (best-quality-generated), unter 1 Cent je Kompendium",
        12,
        MUTED,
        limit=832,
    )
    for x, color, label in ((24, LOCAL, "llm-free (0 Tokens)"), (190, LLM, "Standard")):
        svg.rect(x, 72, 12, 10, color, 2)
        svg.text(x + 18, 81, label, 11.5, MUTED)
    left, right, top, row = 250, 760, 104, 42

    def x(seconds: float) -> float:
        return left + seconds / 30 * (right - left)

    for seconds in (0, 10, 20, 30):
        svg.items.append(
            f'<line x1="{x(seconds):.1f}" y1="{top - 6}" x2="{x(seconds):.1f}" '
            f'y2="{top + len(rows) * row}" stroke="{GRID}"/>'
        )
        svg.text(x(seconds), top + len(rows) * row + 16, f"{seconds} s", 11, MUTED, "middle")
    for index, (name, free, standard, tokens) in enumerate(rows):
        y = top + index * row
        svg.text(left - 12, y + 19, name, 12.5, anchor="end", limit=220)
        svg.rect(left, y + 2, x(free) - left, 12, LOCAL, 2)
        svg.text(x(free) + 6, y + 12, f"{de(free)} s", 11)
        svg.rect(left, y + 17, x(standard) - left, 12, LLM, 2)
        svg.text(x(standard) + 6, y + 27, f"{de(standard)} s · {tokens} Tokens", 11)
    svg.text(24, 400, "Fünf Kompendien zugleich im Standard: 36 bis 86 s (Testserver); Frist 300 s.", 11.5, MUTED)
    svg.save("steckbrief_funktionen.svg")


def bapi() -> None:
    svg = Svg(880, 430, "Die zwei Rollen der b-api: Proxy für Dienste und Proxy für LLM")
    svg.text(24, 32, "Die b-api: Proxy für Dienste und für LLM", 17, weight="700")
    svg.text(
        24,
        52,
        "Ein Schlüssel je Kunde; die b-api prüft, begrenzt, rechnet ab und reicht ihn an den Dienst weiter",
        12,
        MUTED,
        limit=832,
    )
    svg.box(24, 140, 140, 70, ["Kunde / App", "Bearer-Schlüssel"], "extern")
    svg.rect(230, 84, 230, 300, "#fbeee0", 8, LLM, 1.3)
    svg.text(345, 108, "b-api", 15, weight="700", anchor="middle")
    svg.box(
        250,
        124,
        190,
        96,
        ["Dienst-Proxy", "ein Eintrag je Dienst", "prüft Schlüssel, Limits,", "Nutzung, Logs"],
        "proxy",
    )
    svg.box(
        250,
        260,
        190,
        104,
        ["LLM-Proxy", "/api/v1/llm/<provider>/…", "/api/v1/llm/router/…", "Routen mit Reserve"],
        "proxy",
    )
    svg.box(590, 130, 180, 90, ["Ihr Dienst", "Port 8000 öffentlich", "Port 9000 Proben, Metriken"])
    svg.box(590, 270, 210, 84, ["Anbieter", "OpenAI, academiccloud, …", "Route: eine Parameterfamilie"], "extern")
    svg.box(800, 140, 64, 70, ["Logs", "trace_id"], "store")
    svg.arrow([(164, 175), (250, 175)])
    svg.text(197, 167, "Schlüssel", 10.5, MUTED, "middle")
    svg.arrow([(440, 165), (590, 165)])
    svg.text(515, 157, "forwardApiKey", 10.5, MUTED, "middle")
    svg.text(515, 184, "X-B3-*, X-Request-ID", 10.5, MUTED, "middle")
    svg.arrow([(680, 220), (680, 242), (400, 242), (400, 260)])
    svg.text(690, 236, "LLM-Aufruf mit dem Kundenschlüssel", 10.5, MUTED)
    svg.arrow([(440, 312), (590, 312)])
    svg.arrow([(770, 175), (800, 175)], dash="4 3")
    svg.text(
        24,
        412,
        "Der Dienst prüft den Schlüssel nicht selbst, speichert und loggt ihn nie und ist nur über die b-api"
        " erreichbar (NetworkPolicy).",
        11.5,
        MUTED,
        limit=832,
    )
    svg.save("leitfaden_bapi.svg")


OUT.mkdir(parents=True, exist_ok=True)
for chart in (kontext, funktionen, bapi):
    chart()
