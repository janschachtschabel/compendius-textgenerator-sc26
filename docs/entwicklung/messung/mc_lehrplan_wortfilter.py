"""Messskript M58, Häufigkeitsfilter (03.10.2026): Teil 2 ohne Suchwörter, die im ganzen Lehrplan-Cache zu oft treffen.

Jans Punkt 2 zu M57: allgemeine Nebenwörter („Musik“, „Gruppe“, „Teile“) fluten Teil 2. Der Cache selbst zeigt, welches
Wort allgemein ist: Es trifft Tausende Elemente. ``zaehlen`` zählt je Suchwort die Treffer im ganzen Cache (Wortgrenzen
wie im Dienst, ohne Grenze von 200), im Einmal-Container; ``auswerten`` streicht offline jedes Element, das ein Wort
über der Schwelle fand, außer dem Titel des Artikels selbst, und rechnet gepoolt wie mc_lehrplan_gepoolt.py:

  cat mc_lehrplan_wortfilter.py | docker compose run --rm --no-deps -T api python - zaehlen "$(cat woerter.json)"
  python mc_lehrplan_wortfilter.py auswerten <m57_out.txt> ergebnisse/m58_wortfrequenzen.json \
      ergebnisse/m57_m58_gepoolt.json

Die Rohausgabe von M57 (alle Elemente je Lauf) liegt außerhalb des Repositorys.
"""

import json
import sys
from pathlib import Path


def zaehlen(words):
    from app.main import build_registry, build_service
    from app.settings import get_settings
    from app.sources.lehrplan.matcher import LehrplanMatcher
    from app.templates.manager import TemplateManager

    settings = get_settings()
    service = build_service(settings, build_registry(settings), TemplateManager())
    matcher = LehrplanMatcher(service.curricula.store)
    out = {}
    for word in json.loads(words):
        result = matcher.match([word])
        out[word] = {"treffer": len(result.matches), "label": sum(1 for m in result.matches if m.hit.matched_in == "label")}
    print("JSON-START")
    print(json.dumps(out, ensure_ascii=False))


def _bundled(entry):
    return entry.get("matched_in") == "parent" and entry.get("note") != 2


def auswerten(m57_out, frequencies, pooled):
    freq = {k: v["treffer"] for k, v in json.loads(Path(frequencies).read_text(encoding="utf-8")).items()}
    pairs = {(p["thema"], p["iri"]): (p["note"], p["pi"]) for p in json.loads(Path(pooled).read_text(encoding="utf-8"))["paare"]}
    runs = json.loads(Path(m57_out).read_text(encoding="utf-8").split("JSON-START\n", 1)[1])

    def evaluate(preset, kind, limit):
        weight = fit = unfit = lost = all_fit = 0.0
        emptied = capped = 0
        for r in runs:
            if r["preset"] != preset or r["kind"] != kind or "error" in r:
                continue
            title = (r.get("keywords") or [""])[0].casefold()
            shown = [e for e in r["entries"] if not _bundled(e)]
            kept = [e for e in shown if limit is None or e["keyword"].casefold() == title or freq.get(e["keyword"], 0) <= limit]
            # gestrichene Elemente ließen andere hinter der Grenze von 200 nachrücken, die niemand benotet hat
            capped += len(kept) < len(shown) and (r["summary"].get("total_hits") or 0) > len(r["entries"])
            emptied += bool(shown) and not kept
            graded = [(pairs[(r["topic"], e["iri"])], e in kept) for e in shown if (r["topic"], e["iri"]) in pairs]
            for (g, pi), k in graded:
                if g == 2:
                    all_fit += 1 / pi
                    lost += (not k) / pi
            rows = [(g, 1 / pi) for (g, pi), k in graded if k]
            if rows:
                total, w = sum(x for _, x in rows), min(6, len(kept))
                weight += w
                fit += w * sum(x for g, x in rows if g == 2) / total
                unfit += w * sum(x for g, x in rows if g == 0) / total
        return fit / weight, unfit / weight, (lost / all_fit if all_fit else 0.0), emptied, capped

    print("passend / unpassend, Anteil der passenden Elemente, die wegfielen, Themen ohne Element, Läufe mit Nachrückern")
    for preset in ("llm-free", "balanced", "best-quality"):
        for kind in ("einfach", "gruppe", "aspekt"):
            cells = []
            for limit in (None, 1000, 500):
                f, u, lost, emptied, capped = evaluate(preset, kind, limit)
                label = "heute" if limit is None else f"über {limit}"
                cells.append(f"{label}: {f:3.0%} / {u:3.0%}, weg {lost:3.0%}, leer {emptied}, nachrückend {capped}")
            print(f"{preset:12} {kind:8} " + " | ".join(cells))


if __name__ == "__main__":
    if sys.argv[1] == "zaehlen":
        zaehlen(sys.argv[2])
    else:
        auswerten(*sys.argv[2:5])
