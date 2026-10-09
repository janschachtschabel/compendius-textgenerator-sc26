"""M88: evaluation of the articles N named (mc_n_bedeutung.py) with the blind judgements of two graders
(mc_n_bedeutung_boegen.py): how often an article of another meaning comes, how it came, how the named titles resolve
and change from run to run, and what each variant does to the corpus and to the printed paragraphs. Writes the counts
and the judgements without article texts (for ergebnisse/) and prints the tables.

Usage: python mc_n_bedeutung_auswertung.py <out.json> --fragen=a.json,b.json,c.json --titel=titel.json
           --varianten=a.json,b.json,c.json --schluessel=schluessel.json --urteile=<folder>
  The folder holds urteile_A/bogen_<n>_A.json and urteile_B/bogen_<n>_B.json, the two graders' answers per sheet,
  each grader in a folder of its own.
"""

import itertools
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

LABELS = ("passt", "randthema", "andere_bedeutung", "passt_nicht")
KINDS = {  # the kinds of request, as the gold files and M82 name them, in the groups of the tables
    "normal": "gewöhnliches Thema",
    "zusatz": "gewöhnliches Thema",
    "variante": "gewöhnliches Thema",
    "ohne_eigenen_artikel": "gewöhnliches Thema",
    "mehrdeutig_mit_fach": "mehrdeutiges Wort mit Fach",
    "mehrdeutig_ohne_kontext": "mehrdeutiges Wort ohne Kontext",
    "sammelthema": "Sammelthema",
    "aspekt": "Thema mit Aspekt",
}
GROUPS = tuple(dict.fromkeys(KINDS.values()))
VARIANTS = ("heute", "klammer", "anfang", "verlinkt", "mehrdeutig", "fachfremd", "uebersicht")
# Claude's reading of every pair at least one grader judged another meaning (09.10.2026), from the answers of the
# runs, the traces of the archive and the graders' notes: whether the archive answered N's title with another
# meaning (archiv) or N named another meaning itself (ki), the kind, and what happened
CAUSES = {
    ("Delta (Fach: Geografie)", "Delta"): (
        "archiv",
        "Übersicht ohne Klammerzusatz",
        "„Delta (Geografie)“ fehlt im Archiv; ohne Klammer (V1a, M49) ist „Delta“ der griechische Buchstabe",
    ),
    ("Fall (Fach: Deutsch)", "Instrumentalmusik"): (
        "archiv",
        "Weiterleitung",
        "„Instrumental“ leitet zur Instrumentalmusik; der Kasus heißt „Instrumentalis“",
    ),
    ("Ursachen der Französischen Revolution", "Steuersubvention"): (
        "archiv",
        "Weiterleitung",
        "„Steuerprivileg“ leitet zur heutigen Steuersubvention",
    ),
    ("Barockliteratur", "Friedrich von Spee"): (
        "archiv",
        "gleichnamiger Artikel",
        "ein Landrat (1882–1959); der Dichter heißt im Archiv „Friedrich Spee“",
    ),
    ("Künstliche Intelligenz im Unterricht", "Neuronales Netz"): (
        "archiv",
        "gleichnamiger Artikel",
        "das biologische Netz; das gemeinte heißt „Künstliches neuronales Netz“",
    ),
    ("Strom (Fach: Geografie)", "Stromtal"): (
        "archiv",
        "gleichnamiger Artikel",
        "ein ehemaliges Naturschutzgebiet; den gemeinten Begriff hat das Archiv nicht",
    ),
    ("Französische Revolution", "Nationalversammlung (Frankreich)"): (
        "archiv",
        "Klammerzusatz trifft eine andere Zeit",
        "das heutige Unterhaus; die Nationalversammlung von 1789 hat keinen eigenen Artikel",
    ),
    ("Intervall (Fach: Musik)", "Intervall (Mathematik)"): (
        "ki",
        "Begriff eines anderen Fachs",
        "N nennt das Intervall der Mathematik",
    ),
    ("Intervall (Fach: Musik)", "Intervallschachtelung"): (
        "ki",
        "Begriff eines anderen Fachs",
        "N nennt ein Beweisprinzip der Analysis",
    ),
    ("Satz des Pythagoras", "Pythagoreisches Komma"): (
        "ki",
        "Begriff eines anderen Fachs",
        "N nennt ein Intervall der Musiktheorie",
    ),
    ("Spannung (Fach: Physik)", "Mechanische Spannung"): (
        "ki",
        "andere Lesart des Themas",
        "N liest Spannung als mechanische Spannung (Gold: elektrische)",
    ),
    ("Spannung (Fach: Physik)", "Oberflächenspannung"): (
        "ki",
        "andere Lesart des Themas",
        "N liest Spannung als Oberflächenspannung (Gold: elektrische)",
    ),
    ("Strom", "Meeresströmung"): ("ki", "andere Lesart des Themas", "N liest Strom auch als Strömung"),
    ("Stamm (Fach: Biologie)", "Baum"): (
        "ki",
        "andere Lesart des Themas",
        "N liest Stamm botanisch; „Stamm (Botanik)“ leitet in den Artikel Baum",
    ),
    ("Stamm (Fach: Biologie)", "Sprossachse"): ("ki", "andere Lesart des Themas", "N liest Stamm botanisch"),
    ("Strom (Fach: Geografie)", "Gezeitenströmung"): (
        "ki",
        "andere Lesart des Themas",
        "N liest Strom als Strömung; „Gezeitenstrom“ leitet weiter",
    ),
    ("Strom", "Strom (Gewässerart)"): (
        "variante",
        "Klammerzusatz aus N's Antwort",
        "nur in klammer: „Strom“ wird zum Fluss, das Thema meint Elektrizität",
    ),
}


def heard(n: dict) -> str:
    """The topic as N heard it, as the sheets show it (mc_n_bedeutung_boegen.heard)."""
    text = f"{n['thema']} – {n['kontext']}" if n.get("kontext") else n["thema"]
    return f"{text} (Fach: {', '.join(n['faecher'])})" if n.get("faecher") else text


def kappa(pairs: list[tuple[str, str]]) -> float:
    """Cohen's kappa of two graders over the same items."""
    total = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / total
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[c] * second[c] for c in set(first) | set(second)) / total**2
    return round((observed - expected) / (1 - expected), 3) if expected < 1 else 1.0


def judgements(key: dict, folder: Path) -> tuple[dict, dict]:
    """Per (topic, title) both graders' labels and notes; the agreement on the four labels and on another meaning."""
    both: dict[tuple[str, str], dict] = {}
    for ident, item in key.items():
        both[(item["thema"], item["titel"])] = {"id": ident, "A": None, "B": None, "notizen": {}}
    for grader in ("A", "B"):
        for path in sorted((folder / f"urteile_{grader}").glob(f"bogen_*_{grader}.json")):
            answer = json.loads(path.read_text("utf-8"))
            for ident, label in answer.get("urteile", {}).items():
                item = key.get(ident)
                if item is None:
                    continue
                entry = both[(item["thema"], item["titel"])]
                entry[grader] = str(label).strip().lower()
                note = answer.get("notizen", {}).get(ident)
                if note:
                    entry["notizen"][grader] = note
    graded = [(e["A"], e["B"]) for e in both.values() if e["A"] in LABELS and e["B"] in LABELS]
    binary = [(str(a == "andere_bedeutung"), str(b == "andere_bedeutung")) for a, b in graded]
    agreement = {
        "artikel": len(both),
        "beide_benotet": len(graded),
        "fehlend": [e["id"] for e in both.values() if e["A"] not in LABELS or e["B"] not in LABELS],
        "gleich": sum(1 for a, b in graded if a == b),
        "kappa": kappa(graded) if graded else None,
        "andere_bedeutung_gleich": sum(1 for a, b in binary if a == b),
        "andere_bedeutung_kappa": kappa(binary) if binary else None,
        "je_urteil": {grader: dict(Counter(e[grader] for e in both.values())) for grader in ("A", "B")},
    }
    return both, agreement


def label_of(entry: dict | None) -> str:
    """The judgement both graders gave, else ``uneinig``; ``ohne`` for a title no sheet holds."""
    if entry is None:
        return "ohne"
    return entry["A"] if entry["A"] == entry["B"] else "uneinig"


def other_meaning(entry: dict | None) -> tuple[bool, bool]:
    """Another meaning by both graders (the lower count) and by at least one (the upper)."""
    if entry is None:
        return False, False
    votes = [entry["A"] == "andere_bedeutung", entry["B"] == "andere_bedeutung"]
    return all(votes), any(votes)


def load_rows(names: str) -> list[dict]:
    rows = []
    for name in names.split(","):
        rows += [row for row in json.loads(Path(name).read_text("utf-8"))["zeilen"] if "fehler" not in row]
    return rows


def resolution_counts(asked: list[dict], traces: dict) -> dict:
    """How the archive answers the named parts today: the title itself, a redirect, a redirect into a section, a
    spelling variant; a missing title (with a qualifier among them) or a disambiguation drops out."""
    ways = Counter()
    missing = Counter()
    overview = Counter()
    for row in asked:
        n = row["n"][0]
        for label in n["genannt"]:
            trace = traces[label]
            ways["genannt"] += 1
            if trace["ergebnis"] is None:
                spelling = trace.get("schreibvariante") or {}
                if trace["begriffsklaerung"] or spelling.get("begriffsklaerung"):
                    ways["begriffsklaerung"] += 1
                else:
                    ways["fehlt"] += 1
                    if label.rstrip().endswith(")"):
                        ways["fehlt_mit_klammerzusatz"] += 1
                        missing[label] += 1
            elif trace["weiterleitung"]:
                ways["weiterleitung"] += 1
            elif trace["abschnitt"]:
                ways["abschnitt"] += 1
            elif trace["artikel"] is None or trace["begriffsklaerung"]:
                ways["schreibvariante"] += 1
            else:
                ways["titel"] += 1
        if not n["uebersicht"]:
            overview["keine"] += 1
        elif n["uebersicht_titel"] is None:
            overview["fehlt"] += 1
        elif n["uebersicht_titel"] == n["uebersicht"]:
            overview["titel"] += 1
        elif n["uebersicht"].rstrip().endswith(")") and n["uebersicht"].startswith(n["uebersicht_titel"] + " ("):
            overview["ohne_klammerzusatz"] += 1
        else:
            overview["weiterleitung_oder_schreibweise"] += 1
    return {"teile": dict(ways), "uebersicht": dict(overview), "fehlend_mit_klammerzusatz": missing.most_common(25)}


def spread(asked: list[dict]) -> dict:
    """How much the articles N names change from run to run of the same request."""
    by_request = defaultdict(list)
    for row in asked:
        by_request[row["anfrage"]].append(row)
    per_run, distinct, in_all, jaccard, printed = [], [], [], [], []
    same_overview = same_main = 0
    for rows in by_request.values():
        found = [set(row["n"][0]["gefunden"]) for row in rows]
        union = set().union(*found)
        per_run.append(statistics.mean(len(s) for s in found))
        distinct.append(len(union))
        in_all.append(len(set.intersection(*found)) / len(union) if union else 1.0)
        jaccard += [len(a & b) / len(a | b) if a | b else 1.0 for a, b in itertools.combinations(found, 2)]
        sources = [{p["quelle"] for p in row["gedruckt"]} for row in rows]
        printed += [len(a & b) / len(a | b) if a | b else 1.0 for a, b in itertools.combinations(sources, 2)]
        same_overview += len({row["n"][0]["uebersicht_titel"] for row in rows}) == 1
        same_main += len({row["hauptartikel"] for row in rows}) == 1
    return {
        "anfragen": len(by_request),
        "artikel_je_lauf_median": round(statistics.median(per_run), 1),
        "verschiedene_in_5_laeufen_median": statistics.median(distinct),
        "anteil_in_allen_laeufen_median": round(statistics.median(in_all), 2),
        "jaccard_zweier_laeufe_median": round(statistics.median(jaccard), 2),
        "jaccard_gedruckter_quellen_median": round(statistics.median(printed), 2),
        "gleiche_uebersicht_in_allen_laeufen": same_overview,
        "gleicher_hauptartikel_in_allen_laeufen": same_main,
    }


def frequency(asked: list[dict], both: dict) -> tuple[dict, dict]:
    """heute: the named articles per kind of request by judgement, the runs and requests with another meaning, the
    printed paragraphs by the judgement of their article; and the hits of another meaning."""
    instances = defaultdict(Counter)
    runs = defaultdict(Counter)
    requests = defaultdict(lambda: defaultdict(set))
    printed = defaultdict(Counter)
    hits: dict[tuple[str, str], dict] = {}
    for row in asked:
        group, n = KINDS[row["art"]], row["n"][0]
        topic = heard(n)
        runs[group]["laeufe"] += 1
        requests[group][row["anfrage"]]  # noqa: B018 - every request counts, with or without a hit
        lower_run = upper_run = False
        for index, title in enumerate(n["gefunden"]):
            entry = both.get((topic, title))
            instances[group][label_of(entry)] += 1
            instances[group]["genannt"] += 1
            lower, upper = other_meaning(entry)
            lower_run, upper_run = lower_run or lower, upper_run or upper
            if not upper:
                continue
            hit = hits.setdefault(
                (topic, title),
                {"laeufe": 0, "anfragen": set(), "uebersicht": False, "ersetzt_haupt": False, "gedruckt": 0},
            )
            hit["laeufe"] += 1
            hit["anfragen"].add(row["anfrage"])
            if index == 0 and n.get("uebersicht_titel") == title:
                hit["uebersicht"] = True
                hit["ersetzt_haupt"] |= bool(n.get("ersetzt_haupt"))
            requests[group][row["anfrage"]].add("unten" if lower else "oben")
        runs[group]["andere_bedeutung_unten"] += lower_run
        runs[group]["andere_bedeutung_oben"] += upper_run
        named = {source["titel"] for source in row["korpus"] if source["herkunft"] == "named"}
        lower_printed = False
        for paragraph in row["gedruckt"]:
            printed[group]["alle"] += 1
            if paragraph["herkunft"] != "named" or paragraph["quelle"] not in named:
                continue
            entry = both.get((topic, paragraph["quelle"]))
            printed[group][label_of(entry)] += 1
            printed[group]["genannt"] += 1
            if other_meaning(entry)[1]:
                hits[(topic, paragraph["quelle"])]["gedruckt"] += 1
            lower_printed |= other_meaning(entry)[0]
        runs[group]["gedruckt_andere_bedeutung_unten"] += lower_printed
    table = {
        group: {
            "anfragen": len(requests[group]),
            "laeufe": runs[group]["laeufe"],
            "genannte_artikel": dict(instances[group]),
            "laeufe_mit_andere_bedeutung": [
                runs[group]["andere_bedeutung_unten"],
                runs[group]["andere_bedeutung_oben"],
            ],
            "laeufe_gedruckt_andere_bedeutung": runs[group]["gedruckt_andere_bedeutung_unten"],
            "anfragen_mit_andere_bedeutung": [
                sum(1 for marks in requests[group].values() if "unten" in marks),
                sum(1 for marks in requests[group].values() if marks),
            ],
            "gedruckte_absaetze": dict(printed[group]),
        }
        for group in GROUPS
        if runs[group]["laeufe"]
    }
    return table, hits


def variant_effects(varied: list[dict], both: dict) -> list[dict]:
    """Per variant, against heute in the same runs: the named articles in the corpus by judgement, those it took out
    and put in, the printed paragraphs by judgement of their article, the filled blocks and the questions asked live."""
    by_run = defaultdict(dict)
    for row in varied:
        by_run[(row["nr"], row["lauf"])][row["variante"]] = row
    effects = []
    for variant in VARIANTS:
        counted, out, came = Counter(), Counter(), Counter()
        for per in by_run.values():
            today, row = per.get("heute"), per.get(variant)
            if today is None or row is None or not today["n"]:
                continue
            topic = heard(today["n"][0])
            named_today = [s["titel"] for s in today["korpus"] if s["herkunft"] == "named"]
            named_now = [s["titel"] for s in row["korpus"] if s["herkunft"] == "named"]
            counted["laeufe"] += 1
            counted["korpus_anders"] += named_now != named_today
            counted["ohne_genannten_teil"] += not named_now
            for title in named_now:
                counted["korpus_genannt"] += 1
                counted[f"korpus_{label_of(both.get((topic, title)))}"] += 1
            for title in sorted(set(named_today) - set(named_now)):
                out[(label_of(both.get((topic, title))), topic, title)] += 1
            for title in sorted(set(named_now) - set(named_today)):
                came[(label_of(both.get((topic, title))), topic, title)] += 1
            lower_run = False
            for paragraph in row["gedruckt"]:
                counted["gedruckt"] += 1
                if paragraph["herkunft"] == "named":
                    entry = both.get((topic, paragraph["quelle"]))
                    counted[f"gedruckt_{label_of(entry)}"] += 1
                    lower_run |= other_meaning(entry)[0]
            counted["laeufe_gedruckt_andere_bedeutung"] += lower_run
            filled = row.get("bausteine_gefuellt")
            counted["bausteine_gefuellt"] += filled if filled is not None else today.get("bausteine_gefuellt", 0)
            counted["llm_live"] += row.get("llm_live", 0)
        effects.append(
            {
                "variante": variant,
                **counted,
                "weg": dict(sorted(Counter(label for label, _, _ in out.elements()).items())),
                "neu": dict(sorted(Counter(label for label, _, _ in came.elements()).items())),
                "weg_andere_bedeutung": sorted(
                    [t, ti, c] for (lab, t, ti), c in out.items() if lab == "andere_bedeutung"
                ),
                "weg_passt": sorted(
                    ([t, ti, c] for (lab, t, ti), c in out.items() if lab == "passt"), key=lambda x: (-x[2], x[0], x[1])
                ),
                "neu_nicht_passend": sorted(
                    [lab, t, ti, c] for (lab, t, ti), c in came.items() if lab not in ("passt", "randthema")
                ),
            }
        )
    return effects


def dump(result: dict) -> str:
    """The result as JSON, the judgements one pair per line (indented, they took two thirds of the file)."""
    body = json.dumps({k: v for k, v in result.items() if k != "urteile"}, ensure_ascii=False, indent=1)
    rows = ",\n  ".join(json.dumps(row, ensure_ascii=False) for row in result["urteile"])
    return body[: body.rindex("}")].rstrip() + ',\n "urteile": [\n  ' + rows + "\n ]\n}\n"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    out = Path(args[0])
    asked = load_rows(options["fragen"])
    titled = json.loads(Path(options["titel"]).read_text("utf-8"))
    varied = load_rows(options["varianten"])
    key = json.loads(Path(options["schluessel"]).read_text("utf-8"))
    both, agreement = judgements(key, Path(options["urteile"]))
    traces, beginnings = titled["spuren"], titled["anfaenge"]
    tokens = [row["tokens"]["total"] for row in asked if row.get("tokens")]
    table, hits = frequency(asked, both)
    named = {(item["thema"], item["titel"]): item["genannt"] for item in key.values()}
    listed = []
    for (topic, title), hit in sorted(hits.items(), key=lambda kv: (-kv[1]["laeufe"], kv[0])):
        entry = both[(topic, title)]
        where, kind, note = CAUSES.get((topic, title), ("?", "?", ""))
        listed.append(
            {
                "thema": topic,
                "titel": title,
                "genannt": named[(topic, title)],
                "urteile": [entry["A"], entry["B"]],
                "laeufe": hit["laeufe"],
                "anfragen": sorted(hit["anfragen"]),
                "uebersicht": hit["uebersicht"],
                "ersetzt_haupt": hit["ersetzt_haupt"],
                "gedruckte_absaetze": hit["gedruckt"],
                "ursache": {"wo": where, "art": kind, "beschreibung": note},
                "anfang": (beginnings.get(title) or {}).get("text", "")[:120],
            }
        )
    result = {
        "ablauf": {
            "anfragen": len({row["anfrage"] for row in asked}),
            "gehoerte_themen": len({heard(row["n"][0]) for row in asked}),
            "laeufe": len(asked),
            "tokens_summe": sum(tokens),
            "tokens_je_lauf_median": statistics.median(tokens),
            "llm_aufrufe": sum(row["tokens"].get("calls", 0) for row in asked if row.get("tokens")),
            "wiederholt_wie_fragen": sum(1 for row in varied if row["variante"] == "heute" and row.get("wie_fragen")),
        },
        "uebereinstimmung": agreement,
        "aufloesung": resolution_counts(asked, traces),
        "streuung": spread(asked),
        "haeufigkeit": table,
        "treffer_andere_bedeutung": listed,
        "varianten": variant_effects(varied, both),
        "urteile": [
            [topic, title, entry["A"], entry["B"], entry["notizen"].get("A", ""), entry["notizen"].get("B", "")]
            for (topic, title), entry in sorted(both.items())
        ],
    }
    out.write_text(dump(result), "utf-8")

    print("Übereinstimmung:", json.dumps(agreement, ensure_ascii=False))
    print(
        "Auflösung:",
        json.dumps(result["aufloesung"]["teile"], ensure_ascii=False),
        json.dumps(result["aufloesung"]["uebersicht"], ensure_ascii=False),
    )
    print("Streuung:", json.dumps(result["streuung"], ensure_ascii=False))
    print("\nHeute, je Art der Anfrage:")
    for group, values in table.items():
        print(f"  {group}: {json.dumps(values, ensure_ascii=False)}")
    print(f"\nTreffer einer anderen Bedeutung (mindestens ein Gutachter): {len(listed)}")
    for hit in listed:
        print(
            f"  {hit['thema']} -> {hit['titel']} {hit['urteile']} Läufe {hit['laeufe']} gedruckt "
            f"{hit['gedruckte_absaetze']} | {hit['ursache']['wo']}: {hit['ursache']['art']}"
        )
    print("\nVarianten:")
    for row in result["varianten"]:
        short = {k: v for k, v in row.items() if not isinstance(v, list)}
        print(f"  {json.dumps(short, ensure_ascii=False)}")
        print(f"     weg andere Bedeutung: {row['weg_andere_bedeutung']}")
        print(f"     neu nicht passend: {row['neu_nicht_passend']}")


if __name__ == "__main__":
    main()
