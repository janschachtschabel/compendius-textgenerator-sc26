"""Messskript M60 (03.10.2026): die LaTeX-Formeln, die das LLM in Teil 1 schreibt, und wie plain_formulas sie zeigt.

Jan, mit einem Bildschirmfoto der Prüfansicht: „prüfe im ui auch die darstellung von formeln“ - dort stand
„\\(n_1\\sin\\theta_1=n_2\\sin\\theta_2\\)“. Das Skript liest die Texte der Schreibläufe von M59 (best-quality-generated
und best-coverage-generated an den neun Themen von M48, je mit reasoning low und none; die Texte bleiben außerhalb des
Repositorys), macht die Verdopplung der Backslashes durch das Escapen rückgängig, zählt die Formeln zwischen \\( \\)
und \\[ \\], und zeigt jede so, wie D83 sie schreibt; dazu, ob danach noch ein LaTeX-Befehl oder eine Klammer übrig ist.

  python mc_formeln.py <schreiben_runs.json> <out.json>     (aus dem Projektordner, venv)
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.markup.formulas import _FORMULA, plain_formulas

BACKSLASH = chr(92)


def main() -> None:
    runs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    formulas: dict[str, str] = {}
    per_text = Counter()
    for run in runs:
        text = run["text"].replace(BACKSLASH * 2, BACKSLASH)  # the model wrote one backslash, the escaping two
        for match in _FORMULA.finditer(text):
            written, shown = match.group(0), plain_formulas(match.group(0))
            # the escaping of the output put brackets around links before them ("[[Robert Hill|6]]"): the model
            # wrote none of those, and in the service the conversion runs before the escaping
            if written.startswith(BACKSLASH + "[" + BACKSLASH + "["):
                continue
            if written != shown:  # brackets around text are no formula and stay
                formulas[written] = shown
                per_text[(run["topic"], run["variant"])] += 1
    left = [shown for shown in formulas.values() if re.search(r"\\[A-Za-z]|[{}]", shown)]
    result = {
        "note": "M60: die LaTeX-Formeln der 36 Schreibläufe von M59 und wie plain_formulas (D83) sie zeigt",
        "texte_mit_formeln": len(per_text),
        "formeln": sum(per_text.values()),
        "verschieden": len(formulas),
        "mit_rest": len(left),
        "paare": formulas,
    }
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{result['formeln']} Formeln in {result['texte_mit_formeln']} Texten, {len(formulas)} verschiedene, "
          f"{len(left)} mit LaTeX-Rest")


if __name__ == "__main__":
    main()
