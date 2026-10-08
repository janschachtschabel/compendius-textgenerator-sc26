"""Messskript M61 (03.10.2026): die Formeln der Wikipedia-Artikel, die der Parser bis D84 verwarf.

Jan: „formeln aus wikipedia sollten erhalten bleiben - bitte integrieren“. Das Archiv hält jede Formel als MathML mit
ihrem LaTeX als alttext, dazu ein Bild mit demselben Text als alt; der Parser übersprang beides, und im Text blieben
Löcher („Ihr Formelzeichen ist das .“). Zwei Schritte:

  sammeln '<titel.json>'   im Einmal-Container mit den Archiven und dem Image vor D84 (ohne LLM):
      cat mc_formeln_archiv.py | docker compose run --rm --no-deps -T -v <ordner>:/m61:ro api python - sammeln \
          /m61/titel.json > formeln.txt
      je Artikel das HTML, die Formeln (alttext, ob sie allein in einem <dd> steht) und die Absätze des alten Parsers
  auswerten <formeln.txt> <ergebnis.json>   mit der venv dieses Projekts (der Parser und plain_latex von D84):
      wie viele Formeln plain_latex schreibt, welche Befehle den Rest draußen halten, und die Absätze vorher und
      nachher - Löcher (ein Leerzeichen vor einem Satzzeichen, leere Klammern, doppelte Leerzeichen) und Beispiele;
      dazu, wie viele Gleichungen (Formeln mit =, ≈, <, >, ≤, ≥ oder →) in einem Absatz stehen, den die Segmentierung
      in den Korpus nimmt (mindestens 40 Zeichen, kein Fragment wie eine Einleitung mit Doppelpunkt)

Die Titel: 82 Schulartikel aus Mathematik, Physik und Chemie, dazu die Goldthemen (Optik, Klimawandel, …). Das HTML
bleibt außerhalb des Repositorys; das Ergebnis enthält Zählungen, Formeln und kurze Absatzpaare.
"""

import difflib
import html
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ALTTEXT = re.compile(r'alttext="([^"]*)"')
ELEMENT = re.compile(r'<span class="mwe-math-element[^"]*">')
# a hole: a space (also the no-break space before a formula) before a full stop, comma, semicolon or colon, an empty
# pair of brackets, or a double space
EQUATION = re.compile("[=≈<>≤≥→]")  # a formula that states something, not a single letter
HOLE = re.compile("[ " + chr(0xA0) + "][.,;:](?![0-9])|[(][ " + chr(0xA0) + "]*[)]|  ")


def sammeln(titles):
    from app.wiring import build_registry
    from app.settings import get_settings

    wiki = build_registry(get_settings()).primary_archive
    out = {}
    for title in titles:
        article = wiki.read_article(title)
        if article is None:
            out[title] = None
            continue
        page = article.html
        display = [page[max(0, m.start() - 12) : m.start()].endswith("<dd>") for m in ELEMENT.finditer(page)]
        parsed = wiki.parse(article)
        out[title] = {"resolved": article.title, "html": page, "display": sum(display), "formulas": len(display),
                      "paragraphs": [p.text for s in parsed.sections for p in s.paragraphs]}
    print("JSON-START")
    print(json.dumps(out, ensure_ascii=False))


def auswerten(source, target):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from app.knowledge.segmentation import MIN_TEXT_CHARS, _is_fragment
    from app.sources.zim.html import parse_article
    from app.markup import formulas

    def in_corpus(paragraph):
        text = paragraph.strip()
        return len(text) >= MIN_TEXT_CHARS and not _is_fragment(text)

    data = json.loads(Path(source).read_text(encoding="utf-8").split("JSON-START\n", 1)[1])
    written, why, pairs, out_examples = [], Counter(), [], []
    holes = Counter()
    articles, added = {}, {}
    equations = Counter()
    for title, value in data.items():
        if not value:
            continue
        shown_here = []
        for latex in (html.unescape(m.group(1)) for m in ALTTEXT.finditer(value["html"])):
            shown = formulas.plain_latex(latex)
            if shown is not None:
                written.append((title, latex, shown))
                shown_here.append(shown)
                continue
            unknown = set()
            formulas._Formula(latex, unknown=unknown).text()
            why.update(unknown or {"zu lang" if len(latex) > formulas.MAX_ALTTEXT_CHARS else "leer"})
            out_examples.append({"artikel": title, "latex": latex[:300]})
        before = value["paragraphs"]
        parsed = parse_article(value["html"], value["resolved"])
        after = [p.text for s in parsed.sections for p in s.paragraphs]
        counts = {"vorher": sum(len(HOLE.findall(p)) for p in before), "nachher": sum(len(HOLE.findall(p)) for p in after)}
        corpus = " ".join(p for p in after if in_corpus(p))
        found = [s for s in set(shown_here) if EQUATION.search(s)]
        equations.update({"gleichungen": len(found), "im_korpus": sum(1 for s in found if s in corpus)})
        equations.update({"absaetze_im_korpus_vorher": sum(map(in_corpus, before)), "absaetze_im_korpus_nachher": sum(map(in_corpus, after))})
        holes.update(counts)
        articles[title] = {"formeln": value["formulas"], "abgesetzt": value["display"], "absaetze": len(after),
                           "loecher": counts}
        # a formula of its own line is a paragraph of its own now: the paragraphs pair up where the texts match
        for kind, a0, a1, b0, b1 in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
            if kind == "replace" and a1 - a0 == b1 - b0:
                pairs += [(title, old, new) for old, new in zip(before[a0:a1], after[b0:b1], strict=True)]
            elif kind in ("replace", "insert"):
                added[title] = added.get(title, 0) + (b1 - b0) - (a1 - a0)
    total = len(written) + sum(1 for _ in out_examples)
    rng = random.Random(61)
    result = {
        "note": "M61 (03.10.2026): die Formeln der Schulartikel im Wikipedia-Archiv (2026-01), wie plain_latex (D84) sie "
        "schreibt, und die Absätze des Parsers vor und nach D84 (mc_formeln_archiv.py)",
        "artikel": len(articles), "artikel_mit_formeln": sum(1 for a in articles.values() if a["formeln"]),
        "formeln": total, "geschrieben": len(written), "draussen": len(out_examples), "warum_draussen": why.most_common(),
        "abgesetzt": sum(a["abgesetzt"] for a in articles.values()),
        "geaenderte_absaetze": len(pairs), "neue_absaetze": sum(added.values()), "loecher": dict(holes),
        "korpus": dict(equations),
        "je_artikel": articles,
        "formel_stichprobe": [{"artikel": t, "latex": latex, "text": shown} for t, latex, shown in rng.sample(written, 60)],
        "draussen_beispiele": out_examples[:45],
        "absatz_stichprobe": [{"artikel": t, "vorher": old[:400], "nachher": new[:400]} for t, old, new in rng.sample(pairs, 20)],
    }
    Path(target).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{total} Formeln in {result['artikel_mit_formeln']} von {result['artikel']} Artikeln, {len(written)} "
          f"geschrieben, {len(out_examples)} draußen {why.most_common(8)}; Löcher {dict(holes)}, "
          f"{len(pairs)} Absätze geändert, {sum(added.values())} neu; Korpus {dict(equations)}")


if __name__ == "__main__" or sys.argv[1] in ("sammeln", "auswerten"):
    if sys.argv[1] == "sammeln":
        sammeln(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    else:
        auswerten(sys.argv[2], sys.argv[3])
