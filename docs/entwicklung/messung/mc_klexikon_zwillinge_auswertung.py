"""Evaluation of mc_klexikon_zwillinge.py: the label sheet of the printed Klexikon paragraphs, and the tables.

Usage:
    python mc_klexikon_zwillinge_auswertung.py bogen <sheet.json> <pool.json>...
        one entry per distinct (main article, Klexikon page, printed text), without profile or variant (blind)
    python mc_klexikon_zwillinge_auswertung.py tabelle <labels.json> <name>=<run.json>,<pool.json> ...
        the labels map an entry id to passt | teilweise | daneben
    python mc_klexikon_zwillinge_auswertung.py kurzform <run.json> <pool.json> <out.json> <out_pool.json>
        a run without the variant kurzform gets its rows: the twin kurzform takes (looked up in the archive as
        the service does) and the row of the same request whose twin step took the same page; under the same LLM
        answers the rest of the corpus follows from that decision alone
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

VARIANTS = ["heute", "titel", "anfang", "teilwort", "kurzform"]
DEFINITION = "1 · Themendefinition"
DATA = Path("C:/Users/jan/staging/Windsurf/kompendium-test/data")


def key(main: str, page: str, text: str) -> str:
    return hashlib.sha1(f"{main}\n{page}\n{text}".encode()).hexdigest()[:10]


def sheet(out: Path, pools: list[Path]) -> None:
    entries: dict[str, dict] = {}
    for path in pools:
        for item in json.loads(path.read_text("utf-8")):
            for printed in item["gedruckt"]:
                if printed["projekt"] != "klexikon":
                    continue
                ident = key(item["hauptartikel"], printed["quelle"], printed["text"])
                entries.setdefault(ident, {
                    "id": ident,
                    "thema": item["hauptartikel"],
                    "klexikon_seite": printed["quelle"],
                    "text": printed["text"],
                })
    from app.sources.zim.archive import ZimArchive

    wiki = ZimArchive(DATA / "wikipedia_de_all_nopic_2026-01.zim")
    for entry in entries.values():  # which meaning the topic has: the first sentences of its main article
        article = wiki.read(entry["thema"])
        parsed = wiki.parse(article) if article is not None else None
        lead = next((p.text for s in parsed.sections for p in s.paragraphs), "") if parsed else ""
        entry["hauptartikel_anfang"] = lead[:300]
    ordered = sorted(entries.values(), key=lambda e: (e["thema"], e["klexikon_seite"], e["text"]))
    out.write_text(json.dumps(ordered, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(ordered)} Einträge, {len({e['thema'] for e in ordered})} Themen")


def way(row: dict) -> str:
    """How the twin in the corpus came in; a twin without a paragraph (Klexikon "Computervirus") is none."""
    taken = [x for x in row["zwilling_weg"] if x["genommen"] and x["gefunden"] == row["zwilling"]]
    if row["zwilling"] is None or not taken:
        return "keiner"
    first = taken[0]
    if first["index"] == 0:
        return "Titel (Weiterleitung)" if first["weiterleitung"] else "Titel"
    return "Alias"


def table(labels_path: Path, runs: list[str]) -> None:
    labels = json.loads(labels_path.read_text("utf-8"))
    for spec in runs:
        name, paths = spec.split("=", 1)
        run_path, pool_path = paths.split(",")
        rows = json.loads(Path(run_path).read_text("utf-8"))["zeilen"]
        pools = {(p["anfrage"], p["variante"]): p for p in json.loads(Path(pool_path).read_text("utf-8"))}
        errors = [r for r in rows if "fehler" in r]
        print(f"\n### {name}: {len(rows)} Zeilen, {len(errors)} Fehler")
        for scope, keep in (("alle Anfragen", lambda r: True), ("normale", lambda r: r["art"] == "normal")):
            count = len({r["anfrage"] for r in rows if keep(r)})
            print(f"\n{scope} ({count})")
            print("| Variante | mit Zwilling | über Titel | Titel-Weiterl. | über Alias | Klexikon gedruckt | davon "
                  "Themendef. | passt | teilweise | daneben | ohne Urteil | daneben in Themendef. | gefüllte Bausteine | "
                  "davon nur daneben | gedruckt gesamt | LLM live |")
            print("|" + "---|" * 16)
            for variant in VARIANTS:
                chosen = [r for r in rows if r["variante"] == variant and "fehler" not in r and keep(r)]
                ways = Counter(way(r) for r in chosen)
                verdicts: Counter = Counter()
                definition = off_definition = only_off = 0
                for r in chosen:
                    blocks: dict[str, list[str]] = defaultdict(list)
                    for printed in pools[(r["anfrage"], variant)]["gedruckt"]:
                        if printed["projekt"] != "klexikon":
                            blocks[printed["baustein"]].append("wikipedia")
                            continue
                        verdict = labels.get(key(r["hauptartikel"], printed["quelle"], printed["text"]), "?")
                        blocks[printed["baustein"]].append(verdict)
                        definition += printed["baustein"] == DEFINITION
                        off_definition += printed["baustein"] == DEFINITION and verdict == "daneben"
                        verdicts[verdict] += 1
                    only_off += sum(1 for found in blocks.values() if set(found) == {"daneben"})
                print(f"| {variant} | {sum(1 for r in chosen if r['zwilling'])} | {ways['Titel']} | "
                      f"{ways['Titel (Weiterleitung)']} | {ways['Alias']} | {sum(r['gedruckt_klexikon'] for r in chosen)}"
                      f" | {definition} | {verdicts['passt']} | {verdicts['teilweise']} | {verdicts['daneben']} | "
                      f"{verdicts['?']} | {off_definition} | {sum(r['bausteine_gefuellt'] for r in chosen)} | {only_off} | "
                      f"{sum(r['gedruckt'] for r in chosen)} | {sum(r.get('llm_live', 0) for r in chosen)} |")
        changed = defaultdict(list)
        base = {r["anfrage"]: r for r in rows if r["variante"] == "heute" and "fehler" not in r}
        for r in rows:
            if r["variante"] == "heute" or "fehler" in r or r["anfrage"] not in base:
                continue
            b = base[r["anfrage"]]
            if r["zwilling"] != b["zwilling"] or r["hauptartikel"] != b["hauptartikel"]:
                added = sorted(set(r["artikel"]) - set(b["artikel"]))
                changed[r["variante"]].append(
                    f"{r['anfrage']} ({b['hauptartikel']}): {b['zwilling']} -> {r['zwilling']}; neu {added}; "
                    f"Bausteine {b['bausteine_gefuellt']} -> {r['bausteine_gefuellt']}, gedruckt {b['gedruckt']} -> "
                    f"{r['gedruckt']}"
                )
        for variant in VARIANTS[1:]:
            print(f"\n{variant}: {len(changed[variant])} Anfragen anders als heute")
            for line in changed[variant]:
                print("  -", line)


def taken_page(row: dict) -> str | None:
    return next((x["gefunden"] for x in row["zwilling_weg"] if x["genommen"]), None)


def short_form(run_path: Path, pool_path: Path, out: Path, out_pool: Path) -> None:
    import re

    from app.knowledge.topic import TopicMention, title_words
    from app.sources.zim.archive import ZimArchive

    klex = ZimArchive(DATA / "klexikon_de_all_maxi_2026-08.zim")
    word = re.compile("[a-zäöüß]+")

    def left_out(alias: str, title: str) -> list[str] | None:  # as in mc_klexikon_zwillinge.py
        words = word.findall(alias.lower())
        if not words or not all(TopicMention.of(w).found_in(title) for w in words):
            return None
        return [w for w in title_words(title) if not TopicMention.of(w).found_in(alias)]

    run = json.loads(run_path.read_text("utf-8"))
    pool = json.loads(pool_path.read_text("utf-8"))
    rows = run["zeilen"]
    pools = {(p["anfrage"], p["variante"]): p for p in pool}
    added_rows, added_pool = [], []
    for base in [r for r in rows if r["variante"] == "heute" and "fehler" not in r]:
        title = base["hauptartikel"]
        decision = None
        for index, candidate in enumerate([title, *base["aliasse"][:2]]):
            found = klex.read(candidate)
            if found is None or klex.parse(found).is_disambiguation:
                continue
            if index > 0:
                missing = left_out(candidate, title)
                if missing:  # a shortened form of the title: never
                    continue
            decision = found.title
            break
        same = [r for r in rows if r["anfrage"] == base["anfrage"] and r["variante"] != "kurzform"
                and "fehler" not in r and taken_page(r) == decision]
        if not same:
            raise SystemExit(f"keine Zeile mit Zwilling {decision} für {base['anfrage']}")
        source = same[0]
        added_rows.append({  # the same answers, as a run would replay them
            **source, "variante": "kurzform", "aus_variante": source["variante"], "llm_live": 0,
            "llm_wiederholt": source.get("llm_live", 0) + source.get("llm_wiederholt", 0),
        })
        added_pool.append({**pools[(source["anfrage"], source["variante"])], "variante": "kurzform"})
    run["zeilen"] = [r for r in rows if r["variante"] != "kurzform"] + added_rows
    out.write_text(json.dumps(run, ensure_ascii=False, indent=1), "utf-8")
    out_pool.write_text(json.dumps([p for p in pool if p["variante"] != "kurzform"] + added_pool,
                                   ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(added_rows)} Zeilen kurzform, aus", Counter(r["aus_variante"] for r in added_rows))


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "bogen":
        sheet(Path(sys.argv[2]), [Path(p) for p in sys.argv[3:]])
    elif command == "tabelle":
        table(Path(sys.argv[2]), sys.argv[3:])
    elif command == "kurzform":
        short_form(*(Path(p) for p in sys.argv[2:6]))
    else:
        raise SystemExit(__doc__)
