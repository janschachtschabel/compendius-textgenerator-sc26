"""Auswertung M67 (04.10.2026): Regeln für Verneinung und Vorzeichen an den Sätzen, die die Belegprüfung durchließ.

Liest die Rohdaten von mc_belegpruefung.py (JSON-Liste je Thema mit den Aufrufen der Prüfung) und nimmt jeden Satz,
den die Prüfung mit Belegnummer stehen ließ, mit den Absätzen, die er zitiert. Drei Kandidaten für Regeln (Audit
2026-10-03, F01):

- ``neg_absatz``: der Satz verneint (nicht, kein…, nie…), keiner der zitierten Absätze tut es;
- ``neg_satz``: der Satz und der Belegsatz mit den meisten gemeinsamen Wortstämmen unterscheiden sich in der Verneinung;
- ``vorzeichen``: der Satz nennt eine negative Zahl, deren Betrag die Belege nur ohne Vorzeichen nennen.

Ausgabe: Zahlen je Regel und mit ``--bogen=<datei>`` ein gemischter Bogen für die blinde Bewertung - alle Treffer
und eine Zufallsstichprobe der übrigen Sätze, ohne Angabe, welche Regel traf (Schlüssel in ``<datei>.schluessel``).

Usage: python mc_belegpruefung_auswertung.py <m67_roh.json> [--bogen=<datei>] [--stichprobe=150]
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

from app.knowledge.segmentation import split_sentences
from app.synthesis.citations import _MARKER_RE, _OPENERS, _split_claims, _stems

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

NEGATION = {
    "nicht", "kein", "keine", "keinen", "keinem", "keiner", "keines", "nie", "niemals", "nirgends", "nirgendwo",
    "weder", "nichts",
}
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]+")
# a minus before a number that no digit or letter precedes: "-10", "− 3,5", "minus 7"; not "1914–1918"
_NEGATIVE = re.compile(r"(?:(?<![\w.,])[-−–]\s?|\bminus\s)(\d+(?:[.,]\d+)?)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def negates(text: str) -> bool:
    return any(word.lower() in NEGATION for word in _WORD.findall(text))


def closest(claim: str, evidence: list[str]) -> str:
    """The sentence of the cited paragraphs that shares most word stems with the claim."""
    own = _stems(claim)
    sentences = [s for chunk in evidence for s in split_sentences(chunk)] or [""]
    return max(sentences, key=lambda sentence: len(own & _stems(sentence)))


def sign_flipped(claim: str, evidence: list[str]) -> bool:
    joined = " ".join(evidence)
    for value in _NEGATIVE.findall(claim):
        negative = any(v == value for v in _NEGATIVE.findall(joined))
        if not negative and value in _NUMBER.findall(joined):
            return True
    return False


def cited_sentences(rows: list[dict]) -> list[dict]:
    """Every sentence the check kept with an evidence number, with the paragraphs it cites."""
    found = []
    for row in rows:
        for call in row.get("calls", []):
            kept = {s.strip() for p in call["kept"].split("\n\n") for s in _split_claims(p)}
            for paragraph in call["text"].split("\n\n"):
                for sentence in _split_claims(paragraph):
                    if sentence.startswith(_OPENERS) or sentence.strip() not in kept:
                        continue
                    numbers = [n for n in _MARKER_RE.findall(sentence) if n in call["evidence"]]
                    if not numbers:
                        continue
                    claim = _MARKER_RE.sub("", sentence).strip()
                    evidence = [call["evidence"][n] for n in dict.fromkeys(numbers)]
                    found.append({"topic": row["topic"], "claim": claim, "evidence": evidence})
    return found


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    rows = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    sentences = cited_sentences(rows)
    for item in sentences:
        claim, evidence = item["claim"], item["evidence"]
        item["neg_absatz"] = negates(claim) and not any(negates(chunk) for chunk in evidence)
        item["neg_satz"] = negates(claim) != negates(closest(claim, evidence))
        item["vorzeichen"] = sign_flipped(claim, evidence)
    print(f"{len(rows)} Themen, {len(sentences)} Sätze mit Beleg, die die Prüfung stehen ließ")
    print(f"  verneinen: {sum(negates(i['claim']) for i in sentences)}")
    for rule in ("neg_absatz", "neg_satz", "vorzeichen"):
        print(f"  Treffer {rule}: {sum(i[rule] for i in sentences)}")
    if "bogen" not in options:
        return
    # Strata: every hit of the narrow rule, a sample of the hits of the wide rule alone, a sample of the rest; the
    # key keeps the stratum and its size, so the rates can be weighted back (Hajek)
    strata = {
        "neg_absatz": [i for i in sentences if i["neg_absatz"] or i["vorzeichen"]],
        "neg_satz_allein": [i for i in sentences if i["neg_satz"] and not (i["neg_absatz"] or i["vorzeichen"])],
        "rest": [i for i in sentences if not (i["neg_absatz"] or i["neg_satz"] or i["vorzeichen"])],
    }
    sizes = {"neg_absatz": None, "neg_satz_allein": int(options.get("satzstichprobe", 80)),
             "rest": int(options.get("stichprobe", 150))}
    sheet, key = [], []
    for name, items in strata.items():
        size = len(items) if sizes[name] is None else min(sizes[name], len(items))
        for item in random.Random(f"m67-{name}").sample(items, size):
            item["stratum"], item["stratum_size"] = name, len(items)
            sheet.append(item)
    random.Random(1067).shuffle(sheet)
    for number, item in enumerate(sheet, start=1):
        item["id"] = number
        key.append({"id": number, "topic": item["topic"], "stratum": item["stratum"],
                    "stratum_size": item["stratum_size"],
                    **{r: item[r] for r in ("neg_absatz", "neg_satz", "vorzeichen")}})
    blind = [{"id": i["id"], "satz": i["claim"], "belege": i["evidence"]} for i in sheet]
    Path(options["bogen"]).write_text(json.dumps(blind, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(options["bogen"] + ".schluessel").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Bogen: " + ", ".join(f"{sum(1 for i in sheet if i['stratum'] == n)} aus {len(s)} {n}" for n, s in strata.items()))


if __name__ == "__main__":
    main()
