"""Readable summaries of the measurements M9 to M13, computed from their raw files in ergebnisse/ (no service, no LLM).

Writes m9_artikelwahl.txt, m10_volltexttreffer.txt, m11_zusatzquellen.txt, m12_zuordnung.txt and m13_laufzeit.txt
next to the raw files, so every number the pages of docs/entwicklung quote can be traced to a file. Rounding half up,
German number format; the 90th percentile by nearest rank, as mc_zeit_artikelwahl.py computes it.

Usage: python mc_zusammenfassung.py <ergebnisse-dir>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DIR = Path(sys.argv[1])
GOLD_SETS = {"hauptartikel.yaml": "Hauptgold", "hauptartikel_validierung.yaml": "Validierung",
             "hauptartikel_test.yaml": "zurückgehaltener Test"}
KINDS = {
    "normal": "normale Themen", "zusatz": "mit Klassen-, Stufen- oder Fachzusatz",
    "mehrdeutig_mit_fach": "mehrdeutig, Fach als Kontext", "mehrdeutig_ohne_kontext": "mehrdeutig, ohne Kontext",
    "variante": "Schreibvariante, Abkürzung, Mehrzahl", "ohne_eigenen_artikel": "ohne gleichnamigen Artikel zum Thema",
}
METHODS = {"title": "Titel oder Weiterleitung", "variant": "Schreibvariante oder Grundform",
           "suggestion": "Titelvorschlag des Archivs", "search": "Volltextsuche",
           "disambiguation": "Begriffsklärung, nach Fachwörtern gewählt", "llm": "vom LLM gewählt"}
NOTES = (2, 1, 0)  # belongs to the topic, related, does not fit (blind labels of M8)
SLOTS = {"themendefinition": "Themendefinition", "systematik": "Gliederung & Systematik",
         "fachinhalte": "Fachinhalte", "gesellschaftlicher_kontext": "Gesellschaftlicher Kontext",
         "entwicklung_ausblick": "Entwicklung & Ausblick", "beruf_wirtschaft": "Beruf & Wirtschaft",
         "bildung": "Bildung", "regularien": "Regularien & Rahmensetzung", "praxis": "Praxis",
         "querschnitt": "Querschnitt & Bezüge"}


def load(name: str) -> dict:
    return json.loads((DIR / name).read_text(encoding="utf-8"))


def de(value: float, places: str = "1") -> str:
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{rounded:,}".replace(",", "X").replace(".", ",").replace("X", ".")


def seconds(value: float) -> str:
    return f"{de(value, '0.01')} s"


def paragraphs(count: int) -> str:
    return "1 Absatz" if count == 1 else f"{count} Absätze"


def p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]


def table(header: Iterable[str], rows: Iterable[Iterable[object]]) -> list[str]:
    header = list(header)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return [*lines, ""]


def write(name: str, sources: str, lines: list[str]) -> None:
    head = [f"Erzeugt von mc_zusammenfassung.py aus {sources}. Aufbau und Deutung: Messprotokoll "
            "(docs/entwicklung/05-messprotokoll.md).", ""]
    (DIR / name).write_text("\n".join(head + lines).rstrip() + "\n", encoding="utf-8")
    print(f"{name}: {len(lines)} Zeilen")


def m9() -> None:
    old = load("m9_aufloesung_alt.json")
    rules = load("m9_aufloesung_regeln.json")["ergebnisse"]
    llm_file = load("m9_aufloesung_llm.json")
    llm = llm_file["ergebnisse"]
    rows = [(name, a, r, m) for name in GOLD_SETS for a, r, m in zip(old[name], rules[name], llm[name], strict=True)]
    assert all(a["anfrage"] == r["anfrage"] == m["anfrage"] for _, a, r, m in rows)

    lines = ["## Hauptartikel richtig", ""]
    body = []
    for name, label in GOLD_SETS.items():
        mine = [row for row in rows if row[0] == name]
        body.append([label, len(mine), *(sum(row[i]["richtig"] for row in mine) for i in (1, 2, 3)),
                     sum(row[3]["llm_gefragt"] for row in mine)])
    body.append(["**alle**", *(f"**{sum(row[i] for row in body)}**" for i in range(1, 6))])
    lines += table(["Goldsatz", "Anfragen", "alter Stand (c03dafe)", "Regeln", "Regeln und LLM", "LLM gefragt"], body)
    lines += ["Der zurückgehaltene Test lief zuerst mit 7, 8 und 9 richtigen. Die Dateien zeigen den Stand nach den",
              "zwei Korrekturen, die er anstieß; seitdem ist auch er nicht mehr unabhängig.", ""]

    lines += ["## Nach Art der Anfrage, alle drei Goldsätze", ""]
    body = []
    for kind, label in KINDS.items():
        mine = [row for row in rows if row[1]["art"] == kind]
        body.append([label, len(mine), *(sum(row[i]["richtig"] for row in mine) for i in (1, 2, 3))])
    lines += table(["Art der Anfrage", "Anfragen", "alter Stand", "Regeln", "Regeln und LLM"], body)

    lines += ["## Wie die Regeln auflösen und wie sicher sie sind", ""]
    body = []
    for method, label in METHODS.items():
        mine = [row[2] for row in rows if row[2]["methode"] == method]
        if mine:
            sure = [r for r in mine if r["sicher"]]
            unsure = [r for r in mine if not r["sicher"]]
            body.append([label, f"{sum(r['richtig'] for r in sure)} von {len(sure)}",
                         f"{sum(r['richtig'] for r in unsure)} von {len(unsure)}"])
    sure = [row[2] for row in rows if row[2]["sicher"]]
    unsure = [row[2] for row in rows if not row[2]["sicher"]]
    body.append(["**alle**", f"**{sum(r['richtig'] for r in sure)} von {len(sure)}**",
                 f"**{sum(r['richtig'] for r in unsure)} von {len(unsure)}**"])
    lines += table(["Weg der Regeln", "sicher: richtig", "unsicher: richtig"], body)
    lines += ["Mit `article_choice=llm` entscheidet das LLM genau die unsicheren Anfragen.", ""]

    asked = [row for row in rows if row[3]["llm_gefragt"]]
    kept = [row for row in asked if row[3]["titel"] == row[2]["titel"]]
    changed = [row for row in asked if row[3]["titel"] != row[2]["titel"]]
    lines += ["## Das LLM", "",
              f"{len(asked)} Aufrufe, {de(llm_file['tokens'], '1')} Tokens, "
              f"{de(llm_file['tokens'] / len(asked), '1')} je Aufruf. Das LLM behielt den Artikel der Regeln "
              f"{len(kept)}-mal ({sum(r[3]['richtig'] for r in kept)} davon richtig) und wählte "
              f"{len(changed)}-mal einen anderen:", ""]
    lines += [f"- {r[3]['anfrage']}: {r[2]['titel']} -> {r[3]['titel']} "
              f"({'richtig' if r[3]['richtig'] else 'falsch'}, vorher {'richtig' if r[2]['richtig'] else 'falsch'})"
              for r in changed] + [""]

    def listing(title: str, picked: list[tuple], columns: Callable[[tuple], str]) -> list[str]:
        return [f"## {title} ({len(picked)})", ""] + [f"- {columns(row)}" for row in picked] + [""]

    lines += listing("Durch die Regeln richtig, im alten Stand falsch",
                     [row for row in rows if row[2]["richtig"] and not row[1]["richtig"]],
                     lambda row: f"{row[1]['anfrage']}: {row[1]['titel']} -> {row[2]['titel']}")
    lines += listing("Durch das LLM richtig", [row for row in rows if row[3]["richtig"] and not row[2]["richtig"]],
                     lambda row: f"{row[1]['anfrage']}: {row[2]['titel']} -> {row[3]['titel']}")
    lines += listing("Im alten Stand richtig, jetzt falsch",
                     [row for row in rows if row[1]["richtig"] and not row[3]["richtig"]],
                     lambda row: f"{row[1]['anfrage']}: {row[1]['titel']} -> {row[3]['titel']}")
    lines += listing("Weiterhin falsch", [row for row in rows if not row[3]["richtig"]],
                     lambda row: f"{row[1]['anfrage']} -> {row[3]['titel']} (erwartet: "
                                 f"{', '.join(row[1]['akzeptiert'])}; Regeln sicher: "
                                 f"{'ja' if row[2]['sicher'] else 'nein'})")
    write("m9_artikelwahl.txt", "m9_aufloesung_alt.json, m9_aufloesung_regeln.json und m9_aufloesung_llm.json",
          lines)


def m10() -> None:
    hits = load("m10_trefferfilter.json")
    alone, corpus = load("m10_treffer_llm_allein.json"), load("m10_treffer_llm_korpus.json")
    effect = load("m10_treffer_wirkung.json")
    by_note = Counter(h["note"] for h in hits)
    lines = ["## Die Volltexttreffer der 20 Themen nach Gold", "",
             f"{len(hits)} Treffer: gehört zum Thema {by_note[2]}, verwandt {by_note[1]}, "
             f"passt nicht {by_note[0]}.", ""]

    def split(keep: Callable[[dict], bool], rows: list[dict], note_key: str) -> list[str]:
        kept = Counter(r[note_key] for r in rows if keep(r))
        dropped = Counter(r[note_key] for r in rows if not keep(r))
        return [", ".join(str(kept[n]) for n in NOTES), ", ".join(str(dropped[n]) for n in NOTES)]

    filters: list[tuple[str, Callable[[dict], bool], list[dict], str]] = [
        ("heute: Themenstamm in Titel oder Einleitung", lambda r: True, hits, "note"),
        ("Themenstamm im Titel oder im ersten Satz", lambda r: r["stamm_im_titel"] or r["stamm_im_ersten_satz"],
         hits, "note"),
        ("alle Themenwörter in Titel und Einleitung", lambda r: r["alle_woerter"], hits, "note"),
        ("Model2Vec-Ähnlichkeit zur Einleitung des Hauptartikels ≥ 0,7", lambda r: r["m2v"] >= 0.7, hits, "note"),
        ("im Hauptartikel verlinkt", lambda r: r["verlinkt"], hits, "note"),
        ("LLM, Treffer allein benotet: nicht 0", lambda r: r["llm"] != 0, alone["treffer"], "gold"),
        ("LLM, mit dem ganzen Korpus benotet: nicht 0", lambda r: r["llm"] != 0, corpus["treffer"], "gold"),
    ]
    lines += table(["Filter", "behalten: gehört, verwandt, passt nicht", "verworfen: gehört, verwandt, passt nicht"],
                   [[label, *split(keep, rows, key)] for label, keep, rows, key in filters])

    lines += ["## Note des LLM gegen Gold", ""]
    for label, data in (("Treffer allein benotet", alone), ("mit dem ganzen Korpus benotet", corpus)):
        pairs = Counter((t["gold"], t["llm"]) for t in data["treffer"])
        lines += [f"{label}: {data['calls']} Aufrufe, {de(data['tokens'], '1')} Tokens.", ""]
        lines += table(["Gold / LLM", "2", "1", "0"], [[g, *(pairs[(g, n)] for n in NOTES)] for g in NOTES])
    dropped = [t for t in corpus["treffer"] if t["llm"] == 0]
    lines += [f"Mit dem ganzen Korpus mit 0 benotet ({len(dropped)}):", ""]
    lines += [f"- {t['thema']}: {t['titel']} (Gold {t['gold']}, in M8 {paragraphs(t['gedruckt_m8'])} gedruckt)"
              for t in dropped] + [""]

    lines += ["## Wirkung auf das gedruckte Kompendium, Standard, 20 Themen", ""]
    body = []
    for key, label in (("heute", "heute"), ("ohne_0_treffer", "ohne die mit 0 benoteten Treffer")):
        printed = Counter()
        for topic in effect.values():
            printed.update({int(n): c for n, c in topic[key]["gedruckt"].items()})
        body.append([label, de(sum(t[key]["absaetze"] for t in effect.values()), "1"),
                     ", ".join(str(printed[n]) for n in NOTES),
                     sum(t[key]["bausteine_gefuellt"] for t in effect.values())])
    lines += table(["", "Absätze im Korpus", "gedruckt aus Artikeln: gehört, verwandt, passt nicht",
                    "gefüllte Inhaltsbausteine"], body)
    changed = [(name, t) for name, t in effect.items() if t["heute"] != t["ohne_0_treffer"]]
    lines += ["Themen, die sich ändern:", ""]
    for name, t in changed:
        now, without = t["heute"], t["ohne_0_treffer"]
        lines.append(f"- {name}: Absätze {now['absaetze']} -> {without['absaetze']}, gefüllte Bausteine "
                     f"{now['bausteine_gefuellt']} -> {without['bausteine_gefuellt']}, gedruckt aus unpassenden "
                     f"Artikeln {now['gedruckt'].get('0', 0)} -> {without['gedruckt'].get('0', 0)}")
    write("m10_volltexttreffer.txt", "m10_trefferfilter.json, m10_treffer_llm_allein.json, "
          "m10_treffer_llm_korpus.json und m10_treffer_wirkung.json", lines)


def m11() -> None:
    same_title = load("m11_zusatzquellen.json")
    search = load("m11_zusatzsuche.json")
    topics = search["themen"]
    hits = [h for t in topics.values() for h in t["treffer"]]

    def printed(way: str) -> int:
        return sum(sum(t["gedruckt_zusatz"][way].values()) for t in topics.values())

    def filled(way: str) -> int:
        return sum(t["bausteine_gefuellt"][way] for t in topics.values())

    twins = [(name, q) for name, t in same_title["erweitert"].items() for q in t["zusatzquellen"]]
    lines = ["## Überblick, 20 Themen, Standard", ""]
    lines += table(["Weg", "Seiten aus Wikibooks und Wikiversity", "davon verworfen", "gedruckt",
                    "gefüllte Inhaltsbausteine"], [
        ["nur Wikipedia und Klexikon", 0, "", "",
         sum(t["bausteine_gefuellt"] for t in same_title["standard"].values())],
        ["heute: gleicher Titel", len(twins), "", sum(q["gedruckt"] for _, q in twins),
         sum(t["bausteine_gefuellt"] for t in same_title["erweitert"].values())],
        ["Volltextsuche, 3 je Archiv", len(hits), "", printed("mit"), filled("mit")],
        ["Volltextsuche mit Trefferprüfung", len(hits), sum(h["verworfen"] for h in hits), printed("geprueft"),
         filled("geprueft")],
    ])
    lines += [f"Gleicher Titel: {'; '.join(f'{n}: {q['projekt']} *{q['titel']}*, {q['absaetze']} Absätze, '
                                         f'{q['gedruckt']} gedruckt' for n, q in twins)}.", ""]
    for name, _ in twins:
        lines.append(f"{name}: ohne den Zwilling {same_title['standard'][name]['gedruckt']} gedruckte Absätze, "
                     f"mit ihm {same_title['erweitert'][name]['gedruckt']}.")
    projects = Counter(h["projekt"] for h in hits)
    hungarian = [n for n, t in topics.items() if any("Ungarisch-Lesebuch" in h["titel"] for h in t["treffer"])]
    lines += ["", f"Treffer: {projects['wikibooks']} aus Wikibooks, {projects['wikiversity']} aus Wikiversity. "
              f"{sum('Ungarisch-Lesebuch' in h['titel'] for h in hits)} Wikibooks-Treffer stammen aus dem "
              f"Ungarisch-Lesebuch, in {len(hungarian)} Themen ({', '.join(hungarian)}). Die Trefferprüfung "
              f"verwarf {sum(h['verworfen'] for h in hits)} Seiten und "
              f"{sum(len(t['verworfen_sonst']) for t in topics.values())} "
              f"Wikipedia-Treffer; {de(search['tokens'], '1')} Tokens.", ""]

    lines += ["## Je Thema", ""]
    lines += table(["Thema", "gefüllt: ohne, mit, mit Prüfung", "gedruckt aus Zusatzseiten: mit, mit Prüfung"],
                   [[name, ", ".join(str(t["bausteine_gefuellt"][w]) for w in ("ohne", "mit", "geprueft")),
                     f"{sum(t['gedruckt_zusatz']['mit'].values())}, {sum(t['gedruckt_zusatz']['geprueft'].values())}"]
                    for name, t in topics.items()])
    lines += ["## Seiten, aus denen gedruckt wurde", ""]
    lines += [f"- {name}: {h['projekt']} *{h['titel']}*, gedruckt ohne Prüfung {h['gedruckt_mit']}, "
              f"mit Prüfung {h['gedruckt_geprueft']}{', von der Prüfung verworfen' if h['verworfen'] else ''}"
              for name, t in topics.items() for h in t["treffer"] if h["gedruckt_mit"] or h["gedruckt_geprueft"]]
    write("m11_zusatzquellen.txt", "m11_zusatzquellen.json und m11_zusatzsuche.json", lines)


def m12() -> None:
    local, llm = load("m12_beschreibungen_lokal.json"), load("m12_beschreibungen_llm.json")
    lines = ["## Schärfere Bausteinbeschreibungen (V1) gegen sc26 (V0)", ""]
    body = []
    for key, value in [*local.items(), *llm.items()]:
        variant, pool = key.split("|")
        body.append([variant, pool, de(value["macro_f1"], "0.001"), de(value["micro_f1"], "0.001"),
                     f"{de(100 * value['top2'])} %", de(value["covered"], "0.1"), value["misassigned"],
                     seconds(value["seconds_per_topic"]), de(value["tokens"], "1")])
    lines += table(["Variante", "Pool", "macro-F1", "micro-F1", "richtig unter Top 2", "belegte Bausteine",
                    "falsch zugeordnet", "Sekunden je Thema", "Tokens"], body)
    lines += ["V0 LLM kam überwiegend aus dem Zwischenspeicher der b-api (dieselben Prompts wie M5); seine Sekunden",
              "sind keine Modellzeit. V1 lief neu.", ""]

    first, second = load("m12_sparvarianten.json"), load("m12_sparvarianten_rotiert.json")
    runs = [("Regeln (`hybrid_light`)", "Regeln", "1", first["wege"]["rules"]),
            ("Regeln (`hybrid_light`)", "Regeln", "2", second["wege"]["rules"]),
            ("25 Absätze zu 700 Zeichen", "25×700", "1", first["wege"]["llm"]),
            ("25 Absätze zu 700 Zeichen", "25×700", "2", second["wege"]["llm_25x700"]),
            ("50 Absätze zu 400 Zeichen (D36)", "50×400", "1", first["wege"]["llm_billig"]),
            ("50 Absätze zu 400 Zeichen (D36)", "50×400", "2", second["wege"]["llm_50x400"]),
            ("nur das Zweifelsband, 25 zu 700", "Zweifelsband", "1", first["wege"]["llm_zweifel"])]
    body = []
    for label, _, run, value in runs:
        per_topic = value.get("seconds_per_topic")
        cached = label.startswith("25") and run == "1"
        body.append([label, run, de(value["macro_f1"], "0.001"), de(value["micro_f1"], "0.001"),
                     f"{value['misassigned']} von {value['assigned']}", value["llm_paragraphs"],
                     de(value["tokens"], "1"),
                     de(value["tokens"] / value["llm_paragraphs"], "1") if value["llm_paragraphs"] else "–",
                     f"{de(value['seconds'], '0.1')} s" + (", Zwischenspeicher" if cached else ""),
                     seconds(statistics.median(per_topic.values())) if per_topic else "–"])
    lines += ["## LLM-Zuordnung auf dem Goldpool", ""]
    lines += table(["Weg", "Lauf", "macro-F1", "micro-F1", "falsch zugeordnet", "Absätze beim LLM", "Tokens",
                    "Tokens je Absatz", "Sekunden, zehn Themen", "Sekunden je Thema, Median"], body)
    zone = first["zweifelsband"]
    lines += ["Lauf 2 dreht jeden Pool zur Hälfte (--rotieren): andere Stapel, kein Zwischenspeicher. Das "
              f"Zweifelsband umfasst {zone['angeboten']} von {zone['alle']} Absätzen. Die Zeiten sind Wandzeit auf dem "
              "Goldpool (rund 60 Absätze je Thema, vier Stapel parallel), nicht die eines ganzen Kompendiums "
              "(M13).", ""]
    lines += ["## F1 je Baustein", ""]
    slots = first["wege"]["rules"]["per_slot"]
    lines += table(["Baustein", "Gold-Absätze", *(f"{short}, Lauf {run}" for _, short, run, _ in runs)],
                   [[SLOTS[s], slots[s]["support"], *(de(v["per_slot"][s]["f1"], "0.01") for *_, v in runs)]
                    for s in SLOTS])
    write("m12_zuordnung.txt", "m12_beschreibungen_lokal.json, m12_beschreibungen_llm.json, m12_sparvarianten.json "
          "und m12_sparvarianten_rotiert.json", lines)


def m13() -> None:
    old1, old2 = load("m13_zeit_alt.json"), load("m13_zeit_alt_zweiter_lauf.json")
    mixed, rules2 = load("m13_zeit_neu.json"), load("m13_zeit_neu_regeln_zweiter_lauf.json")
    runs = [("v2.0.0 (c03dafe), Regeln", "erster Lauf", old1["zusammenfassung"]["rule-based"]),
            ("v2.0.0 (c03dafe), Regeln", "zweiter Lauf", old2["zusammenfassung"]["rule-based"]),
            ("neu (f9accb7), `rule-based`", "im Wechsel mit `llm`", mixed["zusammenfassung"]["rule-based"]),
            ("neu (f9accb7), `rule-based`", "eigener Lauf", rules2["zusammenfassung"]["rule-based"]),
            ("neu (f9accb7), `article_choice=llm`", "im Wechsel mit `rule-based`", mixed["zusammenfassung"]["llm"])]
    lines = ["## Teil 1 je Kompendium, 30 Themen", ""]
    lines += table(["Stand und Weg", "Lauf", "Median", "90. Perzentil", "Mittel", "Tokens", "LLM gefragt",
                    "Trefferprüfungen"],
                   [[label, run, seconds(s["median_s"]), seconds(s["p90_s"]), seconds(s["mittel_s"]),
                     de(s["tokens"], "1"), s["llm_gefragt"], s["treffer_geprueft"]] for label, run, s in runs])
    lines += ["Im Wechsellauf las der LLM-Durchgang die Archivseiten eines Themas unmittelbar vor oder nach den",
              "Regeln; der Dateicache verzerrt den Vergleich zwischen Prozessen. Belastbar sind die Phasen des Audits:",
              ""]

    llm_runs = [r for r in mixed["laeufe"] if r["weg"] == "llm"]
    phase = {"hit": [r["phasen_ms"]["hit_check"] / 1000 for r in llm_runs],
             "both": [(r["phasen_ms"]["hit_check"] + r["phasen_ms"]["resolve"]) / 1000 for r in llm_runs]}
    asked = sorted(r["phasen_ms"]["resolve"] / 1000 for r in llm_runs if r["gefragt"])
    lines += table(["Phase mit `article_choice=llm`", "Median", "90. Perzentil", "Maximum"], [
        [f"Trefferprüfung ({len(llm_runs)} Themen)", seconds(statistics.median(phase["hit"])),
         seconds(p90(phase["hit"])), seconds(max(phase["hit"]))],
        [f"Auflösung, wenn die Regeln unsicher sind ({len(asked)} Themen, ab {seconds(asked[0])})",
         seconds(statistics.median(asked)), "", seconds(asked[-1])],
        ["Auflösung und Trefferprüfung zusammen, je Thema", seconds(statistics.median(phase["both"])),
         seconds(p90(phase["both"])), seconds(max(phase["both"]))],
    ])
    tokens = [r["tokens"] for r in llm_runs]
    dropped = [t for r in llm_runs for t in r["treffer_verworfen"]]
    lines += [f"Tokens: {de(sum(tokens), '1')}, je Thema Median {de(statistics.median(tokens), '1')} "
              f"({de(min(tokens), '1')} bis {de(max(tokens), '1')}). Die Trefferprüfung verwarf {len(dropped)} "
              f"Treffer in {sum(bool(r['treffer_verworfen']) for r in llm_runs)} Themen.", ""]

    old_by = {r["thema"]: r for r in old2["laeufe"]}
    rules_by = {r["thema"]: r for r in rules2["laeufe"]}
    lines += ["## Je Thema", ""]
    lines += table(["Thema", "v2.0.0", "Regeln", "mit LLM", "Weg", "v2.0.0, 2. Lauf", "Regeln, eigener Lauf",
                    "`llm`, Wechsellauf", "Tokens", "verworfene Treffer"],
                   [[r["thema"], old_by[r["thema"]]["titel"], rules_by[r["thema"]]["titel"], r["titel"],
                     METHODS.get(r["methode"], r["methode"]), seconds(old_by[r["thema"]]["sekunden"]),
                     seconds(rules_by[r["thema"]]["sekunden"]), seconds(r["sekunden"]), de(r["tokens"], "1"),
                     ", ".join(r["treffer_verworfen"])] for r in llm_runs])

    matching = load("m13_zeit_zuordnung.json")
    lines += ["## `matcher=llm` gegen `hybrid_light`, fünf ganze Kompendien, `article_choice=rule-based`", ""]
    body = []
    for r in matching["laeufe"]:
        body.append([r["thema"], f"`{r['weg']}`", seconds(r["sekunden"]), seconds(r["phasen_ms"]["match"] / 1000),
                     r["absaetze"] or "", r["rueckfall"] if r["absaetze"] else "", de(r["tokens"], "1")])
    lines += table(["Thema", "Weg", "Teil 1", "davon Zuordnung", "Absätze beim LLM", "davon Rückfall", "Tokens"], body)
    summary = matching["zusammenfassung"]
    offered, fallback, spent = summary["llm"]["absaetze"], summary["llm"]["rueckfall"], summary["llm"]["tokens"]
    per_paragraph = spent / (offered - fallback)
    lines += table(["Weg", "Teil 1, Median", "Zuordnung, Median", "Teil 1, Maximum", "Tokens, fünf Themen"],
                   [[f"`{way}`", seconds(s["median_s"]), seconds(s["median_zuordnung_s"]), seconds(s["max_s"]),
                     de(s["tokens"], "1")] for way, s in summary.items()])
    lines += [f"Rückfall: {fallback} von {de(offered, '1')} Absätzen ({de(100 * fallback / offered)} %); das Audit "
              "des Laufs nannte als Grund jedes Mal das erschöpfte Token-Budget der Anfrage (60.000, Messprotokoll "
              "M13). Je entschiedenem Absatz "
              f"{de(per_paragraph, '1')} Tokens; hätte das LLM alle Absätze entschieden, wären es hochgerechnet "
              f"{de(round(per_paragraph * offered / 5, -3), '1')} Tokens je Kompendium statt "
              f"{de(round(spent / 5, -2), '1')}."]
    write("m13_laufzeit.txt", "m13_zeit_alt.json, m13_zeit_alt_zweiter_lauf.json, m13_zeit_neu.json, "
          "m13_zeit_neu_regeln_zweiter_lauf.json und m13_zeit_zuordnung.json", lines)


for step in (m9, m10, m11, m12, m13):
    step()
