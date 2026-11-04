"""Charts of the quality profile (docs/uebergabe/qualitaetsprofil.md) as plain SVG on a white background:
qualitaet_karte.svg (scorecard), qualitaet_ausgabe.svg, qualitaet_kosten.svg and qualitaet_tempo.svg.

Usage: python qualitaetsprofil.py - writes into bilder/ next to this script. Every value is a measured one from the
development log (M3, M67, M82, M91) or the load test of 16.10.2026 (lasttest-2026-10-16.json); the grades 1 to 5 are
the proposal of the profile page and follow its thresholds. Drawing and palette as in grafiken.py, whose Svg class is
copied here in short because that script draws its charts on import.
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
LOCAL, LLM = "#2f6db5", "#d9822b"  # llm-free, the profiles with an LLM
GOOD, FAIR, POOR = "#3a8f5c", "#d4a20f", "#c8553d"
CHAR_WIDTH = 0.56

DIMENSIONS = ("Ausgabequalität", "Zuverlässigkeit", "Geschwindigkeit", "Kosten", "Reife")
# Grades of the profile page, section "Scorecard": standard profile (best-quality-generated), llm-free
GRADES = {"Standard": (4, 4, 3, 4, 3), "llm-free": (2, 5, 4, 5, 3)}


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
        self, x: float, y: float, w: float, h: float, fill: str, rx: float = 0, stroke: str = "none", sw: float = 1
    ) -> None:
        self.items.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
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

    def polygon(self, points: list[tuple[float, float]], fill: str, opacity: float, stroke: str) -> None:
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        self.items.append(
            f'<polygon points="{path}" fill="{fill}" fill-opacity="{opacity}" stroke="{stroke}" '
            f'stroke-width="2" stroke-linejoin="round"/>'
        )

    def save(self, name: str) -> None:
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" font-family="{FONT}" role="img" '
            f'aria-label="{esc(self.title)}"><title>{esc(self.title)}</title>'
        )
        (OUT / name).write_text(head + "\n".join(self.items) + "</svg>\n", encoding="utf-8", newline="\n")
        print(f"{name}: {self.width} x {self.height}")


def light(grade: int) -> tuple[str, str]:
    """Color and word of a grade: 4 and 5 green, 3 yellow, 1 and 2 red (thresholds of the profile page)."""
    return (GOOD, "grün") if grade >= 4 else (FAIR, "gelb") if grade == 3 else (POOR, "rot")


def heading(svg: Svg, title: str, subtitle: str) -> None:
    svg.text(24, 32, title, 17, weight="700", limit=svg.width - 48)
    svg.text(24, 52, subtitle, 12, MUTED, limit=svg.width - 48)


def legend(svg: Svg, x: float, y: float) -> None:
    for color, label in ((LLM, "Standard (best-quality-generated)"), (LOCAL, "llm-free")):
        svg.rect(x, y - 9, 12, 10, color, 2)
        svg.text(x + 18, y, label, 11.5, MUTED)
        x += 30 + len(label) * 11.5 * CHAR_WIDTH


def karte() -> None:
    svg = Svg(880, 430, "Qualitätsprofil Kompendiale Texte: Noten der fünf Dimensionen für zwei Profile")
    heading(
        svg,
        "Qualitätsprofil · Kompendiale Texte · Release 2.25.1",
        "Freitext mit Belegen · regelbasiert, statistisch und optional LLM · synchron · Goldstandard vorhanden",
    )
    top, row = 104, 40
    svg.text(24, top - 22, "Dimension", 11.5, MUTED, weight="700")
    svg.text(212, top - 22, "Standard", 11.5, MUTED, weight="700")
    svg.text(318, top - 22, "llm-free", 11.5, MUTED, weight="700")
    for index, dimension in enumerate(DIMENSIONS):
        y = top + index * row
        svg.rect(16, y - 4, 420, row - 6, PANEL if index % 2 == 0 else PAPER, 4)
        svg.text(24, y + 17, dimension, 13, weight="600")
        for x, profile in ((212, "Standard"), (318, "llm-free")):
            grade = GRADES[profile][index]
            color, word = light(grade)
            svg.circle(x + 7, y + 13, 7, color)
            svg.text(x + 20, y + 17, f"{grade} · {word}", 12.5)
    y = top + len(DIMENSIONS) * row
    svg.rect(16, y - 4, 420, row + 10, PAPER, 4, POOR, 1.2)
    svg.text(24, y + 17, "K.-o.-Kriterium", 13, weight="600")
    svg.text(24, y + 34, "Halluzination, Thema verfehlt", 10.5, MUTED)
    svg.text(212, y + 17, "nicht ausgelöst", 12.5)
    svg.text(318, y + 17, "ja, bei Sammel-", 12, POOR, weight="600", limit=112)
    svg.text(318, y + 34, "und Aspektthemen", 12, POOR, weight="600", limit=112)

    cx, cy, radius = 660, 232, 112
    angle = [-math.pi / 2 + i * 2 * math.pi / 5 for i in range(5)]

    def point(i: int, value: float) -> tuple[float, float]:
        return cx + radius * value / 5 * math.cos(angle[i]), cy + radius * value / 5 * math.sin(angle[i])

    for level in range(1, 6):
        svg.polygon([point(i, level) for i in range(5)], PAPER, 0, GRID)
    for i in range(5):
        svg.line(cx, cy, *point(i, 5))
    for profile, color in (("llm-free", LOCAL), ("Standard", LLM)):
        shape = [point(i, grade) for i, grade in enumerate(GRADES[profile])]
        svg.polygon(shape, color, 0.14, color)
        for x, y in shape:
            svg.circle(x, y, 4, color, PAPER, 1.5)
    for i, dimension in enumerate(DIMENSIONS):
        x, y = point(i, 5.9)
        anchor = "middle" if abs(x - cx) < 8 else "start" if x > cx else "end"
        svg.text(x, y + (4 if i else -2), dimension, 12, weight="600", anchor=anchor)
    svg.text(cx + 4, cy - radius * 0.2 - 3, "1", 9.5, MUTED)
    svg.text(cx + 4, cy - radius + 11, "5", 9.5, MUTED)
    legend(svg, 500, 400)
    svg.text(24, 400, "Noten 1 bis 5: grün ab 4, gelb 3, rot bis 2 (Vorschlag).", 11.5, MUTED, limit=440)
    svg.text(24, 418, "Grundlage: Messwerte M3, M67, M91, Lastmessung 16.10.", 11.5, MUTED, limit=440)
    svg.save("qualitaet_karte.svg")


def ausgabe() -> None:
    rows = (
        ("Passung, einfache Themen", 4.8, 4.0),
        ("Passung, Sammelthemen", 4.7, 1.3),
        ("Passung, Themen mit Aspekt", 3.7, 1.0),
        ("Nutzen", 4.0, 2.2),
        ("Vollständigkeit", 3.8, 1.3),
        ("Lesbarkeit", 4.3, 2.1),
    )
    svg = Svg(880, 500, "Ausgabequalität: Noten zweier blinder Gutachter, Standard und llm-free (M91)")
    heading(
        svg,
        "Ausgabequalität: Noten von 1 bis 5",
        "Neun Themen, je zwei blinde Claude-Gutachter, Mittel; Release 2.20.0 mit zehnfachem Bausteinbudget (M91)",
    )
    legend(svg, 24, 82)
    left, right, top, group = 230, 820, 112, 42

    def x(value: float) -> float:
        return left + (value - 1) / 4 * (right - left)

    bottom = top + len(rows) * group
    for value in range(1, 6):
        svg.line(x(value), top - 8, x(value), bottom - 6)
        svg.text(x(value), bottom + 10, value, 11, MUTED, anchor="middle")
    for value, label in ((3, "gelb ab 3"), (4, "grün ab 4")):
        svg.line(x(value), top - 8, x(value), bottom - 6, MUTED, 1.4, "5 4")
        svg.text(x(value) + 4, top - 12, label, 10.5, MUTED)
    for index, (label, standard, free) in enumerate(rows):
        y = top + index * group
        svg.text(left - 12, y + 18, label, 12.5, anchor="end", limit=200)
        for offset, value, color in ((0, standard, LLM), (16, free, LOCAL)):
            svg.rect(x(1), y + offset, x(value) - x(1), 13, color, 2)
            svg.text(x(value) + 6, y + offset + 11, de(value), 11.5)
    y = bottom + 40
    svg.text(24, y, "Treue zur Quelle", 13, weight="700")
    lines = (
        ("Standard:", "0,3 % der belegten Sätze widersprechen ihrem Beleg (M67); 42 % Modellwissen ohne Beleg (M91);"),
        ("", "schwere Fehler 0,11 je Text und Gutachter (M91)."),
        ("llm-free:", "wörtlich zitiert, 432 von 432 Sätzen stehen im genannten Absatz (M3);"),
        ("", "schwere Fehler 0,22 je Text und Gutachter (M91)."),
    )
    for index, (who, line) in enumerate(lines):
        svg.text(24, y + 22 + index * 18, who, 11.5, INK, weight="600")
        svg.text(96, y + 22 + index * 18, line, 11.5, MUTED, limit=760)
    svg.save("qualitaet_ausgabe.svg")


def kosten() -> None:
    # Teil 1 und 2, Median über neun Themen (M91): Tokens, Nutzen, Dauer
    profiles = (
        ("llm-free", 0, 2.2, 2.9, LOCAL, (10, -10, "start")),
        ("balanced", 320, 3.2, 3.8, LLM, (10, 16, "start")),
        ("best-quality", 51_932, 3.2, 14.9, LLM, (0, 24, "middle")),
        ("Standard: best-quality-generated", 89_175, 4.0, 27.5, LLM, (-10, -14, "end")),
        ("best-coverage-generated", 111_716, 4.7, 32.5, LLM, (-14, 4, "end")),
    )
    svg = Svg(880, 412, "Kosten und Nutzen der fünf Profile (M91)")
    heading(
        svg,
        "Kosten gegen Nutzen: die fünf Profile",
        "Tokens je Kompendium (Teil 1 und 2) und Nutzen-Note, Median über neun Themen (M91); Dauer am Punkt",
    )
    left, right, top, bottom = 70, 840, 100, 330

    def x(tokens: float) -> float:
        return left + tokens / 120_000 * (right - left)

    def y(grade: float) -> float:
        return bottom - (grade - 1) / 4 * (bottom - top)

    for grade in range(1, 6):
        svg.line(left, y(grade), right, y(grade))
        svg.text(left - 10, y(grade) + 4, grade, 11, MUTED, anchor="end")
    for tokens in range(0, 120_001, 20_000):
        svg.text(x(tokens), bottom + 18, f"{tokens // 1000} Tsd." if tokens else "0", 11, MUTED, anchor="middle")
    svg.text((left + right) / 2, bottom + 40, "Tokens je Kompendium", 11.5, MUTED, anchor="middle")
    svg.text(left - 10, top - 18, "Nutzen-Note", 11.5, MUTED)
    svg.line(left, y(4), right, y(4), MUTED, 1.4, "5 4")
    svg.text(right, y(4) + 15, "grün ab 4", 10.5, MUTED, anchor="end")
    for name, tokens, grade, seconds, color, (dx, dy, anchor) in profiles:
        svg.circle(x(tokens), y(grade), 7, color, PAPER, 2)
        svg.text(x(tokens) + dx, y(grade) + dy, f"{name} · {de(seconds)} s", 12, weight="600", anchor=anchor)
    svg.text(
        24,
        bottom + 64,
        "Mit gpt-6-luna kostet ein Kompendium im Standard geschätzt unter 1 Cent; "
        "Abrechnung je Schlüssel in der b-api.",
        11.5,
        MUTED,
        limit=770,
    )
    svg.save("qualitaet_kosten.svg")


def tempo() -> None:
    medians = (
        ("llm-free", 2.9, LOCAL),
        ("balanced", 3.8, LLM),
        ("best-quality", 14.9, LLM),
        ("Standard", 27.5, LLM),
        ("best-coverage-generated", 32.5, LLM),
    )
    load = (
        ("llm-free · 1", 6.4, 6.4, LOCAL),
        ("llm-free · 3", 7.1, 11.0, LOCAL),
        ("llm-free · 5", 4.8, 23.9, LOCAL),
        ("Standard · 5 · lokal", 66, 75, LLM),
        ("Standard · 5 · Testserver", 36, 86, LLM),
    )
    svg = Svg(880, 330, "Geschwindigkeit: Dauer je Profil (M91) und unter Last (Lastmessung 16.10.2026)")
    heading(
        svg,
        "Geschwindigkeit: Sekunden je Kompendium",
        "Links allein, Median über neun Themen (M91); rechts mehrere zugleich, schnellste bis langsamste "
        "Anfrage (16.10.)",
    )
    top, row = 92, 40
    left, right = 190, 400
    svg.text(24, top - 14, "allein, Median", 12, weight="700")
    for index, (name, seconds, color) in enumerate(medians):
        y = top + index * row
        svg.text(left - 10, y + 15, name, 12, anchor="end", limit=160)
        width = seconds / 40 * (right - left)
        svg.rect(left, y + 4, width, 14, color, 2)
        svg.text(left + width + 6, y + 15, f"{de(seconds)} s", 11.5)
    left2, right2 = 640, 840

    def x(seconds: float) -> float:
        return left2 + seconds / 90 * (right2 - left2)

    svg.text(440, top - 14, "Profil · Anfragen zugleich, Spanne", 12, weight="700")
    bottom = top + len(load) * row
    for seconds in (0, 30, 60, 90):
        svg.line(x(seconds), top, x(seconds), bottom - 10)
        svg.text(x(seconds), bottom + 6, f"{seconds} s", 11, MUTED, anchor="middle")
    for index, (name, low, high, color) in enumerate(load):
        y = top + index * row
        svg.text(left2 - 10, y + 15, name, 12, anchor="end", limit=190)
        if high - low < 1:
            svg.circle(x(low), y + 11, 5, color)
        else:
            svg.rect(x(low), y + 4, x(high) - x(low), 14, color, 2)

        def fmt(value: float) -> str:  # whole seconds of the server round as measured, without ",0"
            return str(value) if isinstance(value, int) else de(value)

        label = f"{fmt(low)} s" if high == low else f"{fmt(low)} bis {fmt(high)} s"
        nudge = 10 if high == low else 6
        svg.text(x(high) + nudge, y + 15, label, 11.5) if x(high) < 760 else svg.text(
            x(low) - 6, y + 15, label, 11.5, anchor="end"
        )
    svg.text(
        24,
        312,
        "Synchron, Frist 300 s; die LLM-Zeit liegt bei der b-api. Alle 42 Anfragen der Lastmessung "
        "kamen mit HTTP 200 zurück.",
        11.5,
        MUTED,
        limit=832,
    )
    svg.save("qualitaet_tempo.svg")


OUT.mkdir(parents=True, exist_ok=True)
for chart in (karte, ausgabe, kosten, tempo):
    chart()
