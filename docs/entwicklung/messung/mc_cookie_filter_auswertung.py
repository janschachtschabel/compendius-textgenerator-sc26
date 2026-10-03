"""Auswertung M68 (04.10.2026): welche Zeilen echter Materialtexte der Filter gegen Cookie-Hinweise verwirft.

Liest die Texte von mc_cookie_filter.py und geht sie Zeile für Zeile durch wie ``paragraphs_from_text``
(app/sources/wlo/knowledge.py): Zeilen ab 40 Zeichen, die der Filter trifft, mit Material, Länge und Anfang. Mit
``--zeilen=<datei>`` schreibt es die getroffenen Zeilen für die Bewertung (Hinweis oder Inhalt) in eine Datei;
``--filter=neu`` nimmt den Filter des Arbeitsstands statt des alten Musters.

Usage: python mc_cookie_filter_auswertung.py <texte.json> [--zeilen=<datei>] [--filter=alt|neu]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.sources.wlo import knowledge
from app.sources.wlo.knowledge import MIN_PARAGRAPH_CHARS, readable

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

OLD = re.compile(r"cookie|consent|store and/or access information|datenschutzeinstellungen", re.IGNORECASE)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    texts = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    if options.get("filter") == "neu":
        def hits(line: str) -> bool:
            return knowledge.is_consent_notice(line)
    else:
        def hits(line: str) -> bool:
            return bool(OLD.search(line))
    rows = []
    for node_id, entry in texts.items():
        for raw in entry["text"].splitlines():
            line = readable(" ".join(raw.split()))
            if len(line) >= MIN_PARAGRAPH_CHARS and hits(line):
                rows.append({"node": node_id, "wort": entry["word"], "titel": entry["title"], "zeichen": len(line),
                             "zeile": line[:400]})
    with_text = [e for e in texts.values() if e["text"]]
    print(f"{len(texts)} Materialien, {len(with_text)} mit Text, {len(rows)} getroffene Zeilen in "
          f"{len({r['node'] for r in rows})} Materialien, {sum(r['zeichen'] for r in rows)} Zeichen")
    for word in dict.fromkeys(e["word"] for e in texts.values()):
        mine = [r for r in rows if r["wort"] == word]
        print(f"  {word}: {len(mine)} Zeilen, {sum(r['zeichen'] for r in mine)} Zeichen")
    if "zeilen" in options:
        numbered = [{"id": n, **row} for n, row in enumerate(rows, start=1)]
        Path(options["zeilen"]).write_text(json.dumps(numbered, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
