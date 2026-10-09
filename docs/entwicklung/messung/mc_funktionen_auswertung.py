"""Messskript M82 (09.10.2026): die KI-Fragen einzeln ausgewertet, gegen das Gold von eval/ und die Läufe von M59.

Liest die Rohdaten von ``mc_reasoning.py`` aus ergebnisse/m82_funktionen.json (dort als Läufe je Schritt abgelegt) und
vergleicht sie mit M59 in der Einstellung, die seit D81 ausgeliefert wird (ergebnisse/m59_reasoning.json):

- Artikelwahl: richtig je Profil und Art der 94 Goldanfragen, Tokens und Sekunden je Anfrage;
- Zuordnung am Gold: macro- und micro-F1, Tokens und Sekunden je Lauf und Weg;
- Lehrplanprüfung: je Art des Themas, gewichtet mit 1/pi der gepoolten Stichprobe (Hajek, M57/M58): der Anteil
  passender Elemente (Note 2 der Gutachter) unter denen, die die Prüfung einzeln zeigt (Note 2), und unter allen, die
  sie behält; von den passenden der Anteil, den sie behält, und der, den sie einzeln zeigt; nur Themen mit demselben
  Artikel in beiden Läufen;
- Artikel eines Materials: richtig je Art (klar, unscharf, keins);
- /entities an den Materialien: Anteil passender und unpassender unter den benoteten Verknüpfungen (Gutachter 1 von
  eval/entitaeten), von den passenden gefunden; unbenotete zählen nicht (wie M59);
- Themenformulierung: die Formulierung je Eingabe neben der von M59;
- QA-Paare: Note je Profil und Gutachter, Anzahl der Note 2, falsche Antworten, welcher Satz besser war.

Aus dem Projektordner:  python docs/entwicklung/messung/mc_funktionen_auswertung.py
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
ERGEBNISSE = HERE / "ergebnisse"
REPO = HERE.parents[2]
M82 = json.loads((ERGEBNISSE / "m82_funktionen.json").read_text(encoding="utf-8"))
M59 = json.loads((ERGEBNISSE / "m59_reasoning.json").read_text(encoding="utf-8"))


def med(values) -> str:
    values = [v for v in values if v is not None]
    return f"{statistics.median(values):.2f}" if values else "-"


def artikelwahl() -> None:
    print("== Artikelwahl, 94 Goldanfragen von eval/artikelwahl")
    runs = {**M82["artikelwahl"], "M59 balanced none": M59["artikelwahl"]["balanced/none"],
            "M59 best-quality none": M59["artikelwahl"]["best-quality/none"]}
    for name, rows in runs.items():
        by_kind = Counter((r["art"], r["richtig"]) for r in rows)
        kinds = sorted({r["art"] for r in rows})
        print(f"{name}: richtig {sum(r['richtig'] for r in rows)}/{len(rows)} ("
              + ", ".join(f"{k} {by_kind[(k, True)]}/{by_kind[(k, True)] + by_kind[(k, False)]}" for k in kinds)
              + f"); Tokens Median {med([r.get('tokens') for r in rows])}, Sekunden Median "
              f"{med([r['sekunden'] for r in rows])}")
    wrong = {r["anfrage"]: r["titel"] for r in M82["artikelwahl"]["best-quality"] if not r["richtig"]}
    print("   falsch in best-quality:", wrong)


def zuordnung() -> None:
    print("\n== Zuordnung am Gold von eval/gold")
    for run, ways in M82["zuordnung"].items():
        for way, v in ways.items():
            print(f"{run} {way}: macro {v['macro_f1']:.3f}, micro {v['micro_f1']:.3f}, falsch {v.get('misassigned')}, "
                  f"Tokens {v.get('tokens')}, Aufrufe {v.get('calls')}, Rückfall {v.get('fallback')}, "
                  f"{v['seconds']:.0f} s, Absätze {v.get('paragraphs')}")


def lehrplan() -> None:
    print("\n== Lehrplanprüfung (best-quality), gegen die gepoolten Noten von M57/M58")
    pooled = json.loads((ERGEBNISSE / "m57_m58_gepoolt.json").read_text(encoding="utf-8"))
    grade = {(p["thema"], p["iri"]): (p["note"], p["pi"]) for p in pooled["paare"]}
    runs = {
        "M59 none (wie seit D81)": {r["topic"]: r for r in M59["lehrplan"]["none"] if not r.get("error")},
        "M82": {r["topic"]: r for r in M82["lehrplan"]["best-quality"] if not r.get("error")},
    }
    same = sorted(t for t in runs["M82"] if all(t in r and r[t].get("article") == runs["M82"][t].get("article")
                                                for r in runs.values()))
    print(f"Themen {len(runs['M82'])}, mit demselben Artikel in beiden Läufen {len(same)}")
    for name, rows in runs.items():
        tokens = [((r.get("tokens") or {}).get("total") or 0) for r in rows.values()]
        fallbacks = sum(1 for r in rows.values() if (r.get("check") or {}).get("fallback")
                        or (r.get("check") or {}).get("fallbacks"))
        print(f"{name}: Tokens Median {statistics.median(tokens):.0f}, Summe {sum(tokens)}, Sekunden Median "
              f"{statistics.median(r['seconds'] for r in rows.values()):.1f}, Läufe mit Rückfall der Prüfung {fallbacks}")
        for kind in ("einfach", "gruppe", "aspekt"):
            w: Counter[str] = Counter()
            found = graded = 0
            for topic, row in rows.items():
                if topic not in same or row["kind"] != kind:
                    continue
                found += row["elemente"]
                # the rows keep only the elements the pool grades, with the note of the check (as M59 stores them)
                for entry in row["benotet"]:
                    g = grade.get((topic, entry["iri"]))
                    if g is None:
                        continue
                    graded += 1
                    weight, note, fits = 1 / g[1], entry.get("note_llm"), g[0] == 2
                    kept = note in (1, 2)
                    w["kept"] += weight * kept
                    w["kept_fit"] += weight * (kept and fits)
                    w["alone"] += weight * (note == 2)
                    w["alone_fit"] += weight * (note == 2 and fits)
                    w["fit"] += weight * fits
                    w["fit_kept"] += weight * (fits and kept)
                    w["fit_alone"] += weight * (fits and note == 2)

            def share(a: str, b: str) -> str:
                return f"{w[a] / w[b]:.0%}" if w[b] else "-"

            print(f"   {kind:8} passt unter Note 2 {share('alone_fit', 'alone')}, unter allen behaltenen "
                  f"{share('kept_fit', 'kept')}; von den passenden behalten {share('fit_kept', 'fit')}, einzeln "
                  f"{share('fit_alone', 'fit')}; benotet {graded} von {found}")


def knoten() -> None:
    print("\n== Artikel eines Materials (eval/materialwahl, 40)")
    runs = {**M82["knoten"], "M59 balanced low (wie seit D81)": M59["knoten"]["low"]}
    for name, rows in runs.items():
        by = Counter((r["art"], r["richtig"]) for r in rows)
        print(f"{name}: richtig {sum(r['richtig'] for r in rows)}/{len(rows)} ("
              + ", ".join(f"{a} {by[(a, True)]}/{by[(a, True)] + by[(a, False)]}" for a in ("klar", "unscharf", "keins"))
              + f"), Status {dict(Counter(r['status'] for r in rows))}, Sekunden Median "
              f"{med([r['sekunden'] for r in rows])}, Tokens Median "
              f"{med([(r.get('node_article') or {}).get('tokens') for r in rows])}")


def entitaeten() -> None:
    print("\n== /entities an den 40 Materialien (Noten von eval/entitaeten, Gutachter 1)")
    grades: dict[tuple[str, str], list[int]] = {}
    for file in ("noten.yaml", "noten_zweit.yaml"):
        for row in yaml.safe_load((REPO / "eval" / "entitaeten" / file).read_text(encoding="utf-8"))["noten"]:
            grades.setdefault((row["node_id"], row["artikel"]), []).append(row["note"])
    fit = {pair for pair, notes in grades.items() if notes[0] == 2}
    runs = {**M82["entitaeten"], "M59 balanced low (wie seit D81)": M59["entitaeten"]["low"]}
    for name, rows in runs.items():
        found = {(r["node_id"], title) for r in rows for title in r["artikel"]}
        graded = [pair for pair in found if pair in grades]
        c = Counter(grades[pair][0] for pair in graded)
        nodes = {r["node_id"] for r in rows}
        recall = sum(1 for p in fit if p[0] in nodes and p in found) / max(1, sum(1 for p in fit if p[0] in nodes))
        print(f"{name}: {len(found)} Verknüpfungen, benotet {len(graded)} {dict(sorted(c.items()))}, unbenotet "
              f"{len(found) - len(graded)}; passend {c[2] / max(1, len(graded)):.0%}, unpassend "
              f"{c[0] / max(1, len(graded)):.0%}; von den passenden gefunden {recall:.0%}; Tokens Median "
              f"{med([(r.get('llm') or {}).get('total_tokens') for r in rows])}, Sekunden Median "
              f"{med([r['sekunden'] for r in rows])}")


def thema() -> None:
    print("\n== Themenformulierung (die 8 Eingaben von M51)")
    for now, then in zip(M82["thema"], M59["thema"]["none"], strict=False):
        print(f"   {now['text'][:60]!r}: {now['thema']!r} (M59 {then['thema']!r}), {now['tokens']} Tokens, "
              f"{now['sekunden']} s")


def qa() -> None:
    print("\n== QA-Paare (6 Themen à 5, zwei Gutachter, Noten 0 bis 2)")
    key, verdicts = M82["qa"]["schluessel"], M82["qa"]["urteile"]
    for name, rows in M82["qa"]["paare"].items():
        tokens = [((r.get("llm_tokens") or {}).get("total")) for r in rows]
        notes: list[list[int]] = [[] for _ in verdicts]
        wrong = [0 for _ in verdicts]
        for topic, letters in key.items():
            letter = next(letter for letter, variant in letters.items() if variant == name)
            for index, verdict in enumerate(verdicts):
                notes[index].extend(verdict[topic][letter]["noten"])
                wrong[index] += verdict[topic][letter].get("falsch", 0)
        print(f"{name}: Note " + " und ".join(f"{statistics.mean(n):.2f}" for n in notes)
              + ", Note 2 bei " + " und ".join(str(sum(1 for x in n if x == 2)) for n in notes)
              + f" von {len(notes[0])}, falsch {wrong}; Tokens Median {med(tokens)}, Sekunden Median "
              f"{med([r['sekunden'] for r in rows])}")
    for index, verdict in enumerate(verdicts, 1):
        better = Counter(key[t].get(verdict[t].get("besser"), verdict[t].get("besser")) for t in key)
        print(f"Gutachter {index}: besser {dict(better)}")
    same = total = 0
    for topic, letters in key.items():
        for letter in letters:
            pairs = zip(verdicts[0][topic][letter]["noten"], verdicts[1][topic][letter]["noten"], strict=False)
            for a, b in pairs:
                total += 1
                same += a == b
    print(f"gleiche Note bei {same} von {total} Paaren")


if __name__ == "__main__":
    artikelwahl()
    zuordnung()
    lehrplan()
    knoten()
    entitaeten()
    thema()
    qa()
