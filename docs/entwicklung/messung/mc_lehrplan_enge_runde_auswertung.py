"""Auswertung M64 (03.10.2026): Teil 2 mit weiteren Suchwörtern (mc_lehrplan_enge_runde.py), gepoolt mit M57 und M58.

  python mc_lehrplan_enge_runde_auswertung.py stichprobe <m64_out>... --bogen=<ordner>
      zieht je Thema, Profil und Variante bis zu sechs einzeln gezeigte und zwei gebündelte Elemente (Saat 64), lässt
      weg, was M57 und M58 schon benotet haben, und schreibt die übrigen als Bögen zu je 150 (eingabe_<n>.json) samt
      Schlüssel; benotet wird blind auf der Skala von M22, zum Thema wie angefragt
  python mc_lehrplan_enge_runde_auswertung.py bauen <m57_out> <m58_out> <m64_out>... --noten=<ordner> <ziel.json>
      alle Pools von M57, M58 und M64 mit ihrer Ziehungschance, die Noten von Gutachter 1 (M57/M58 aus den
      Ergebnisdateien, M64 aus noten_<n>_g1.json im Ordner) und je Paar die Varianten, die es einzeln zeigen
  python mc_lehrplan_enge_runde_auswertung.py auswerten <ziel.json>
      passend / unpassend je Variante und Art (Hajek-Schätzer je Thema, Themen-Bootstrap mit 2.000 Ziehungen, Saat
      6458), Themen mit passendem Element, und je Variante der Unterschied zu „heute“ desselben Profils; eine
      Variante gilt, wo sie lief, und ist „heute“, wo sie nichts änderte (kein Schulwort, das Thema ist der Titel)

Gezeigt heißt nach D80: mit LLM-Prüfung nur Note 2 einzeln, ohne sie alles außer Überschriften-Treffern. Die Varianten
von M64 heißen <profil>/m64:<variante>; die von M57 und M58 wie in mc_lehrplan_gepoolt.py.
"""

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent / "ergebnisse"
KINDS = ("einfach", "gruppe", "aspekt")
M64 = ("heute", "schulform", "begriffe", "thema")
SHOWN, BUNDLED = 6, 2


def _runs(path, key=None):
    data = json.loads(Path(path).read_text(encoding="utf-8").split("JSON-START\n", 1)[1])
    return data[key] if key else data


def _shown_d80(entry):
    note = entry.get("note")
    return note == 2 if note is not None else entry.get("matched_in") != "parent"


def _bundled_m57(entry):  # how M57 and M58 drew: before D80
    return entry.get("matched_in") == "parent" and entry.get("note") != 2


def m64_pools(paths):
    """(topic, kind, variant, shown, bundled, entries) per run and variant of M64."""
    pools = []
    for path in paths:
        for row in _runs(path):
            if row.get("error"):
                continue
            for name in M64:
                # the variant "schulform" was written over the field of the same name (the school form, a string)
                part = row.get(name)
                if not isinstance(part, dict):
                    continue
                entries = part["entries"]
                shown = {e["iri"] for e in entries if _shown_d80(e)}
                bundled = {e["iri"] for e in entries if not _shown_d80(e)}
                pools.append((row["topic"], row["kind"], f"{row['preset']}/m64:{name}", shown, bundled, entries))
    return pools


def graded_before():
    grades = {}
    for name, key in (("m57_lehrplan_profile.json", "stichprobe"), ("m58_lehrplan_suchbegriffe.json", "b_stichprobe")):
        for row in json.loads((HERE / name).read_text(encoding="utf-8"))[key]:
            if row.get("note") is not None:
                grades[(row["thema"], row["iri"])] = row["note"]
    return grades


def stichprobe(paths, folder):
    rng = random.Random(64)
    known = graded_before()
    elements, drawn = {}, set()
    for topic, _, _, shown, bundled, entries in m64_pools(paths):
        for entry in entries:
            elements.setdefault((topic, entry["iri"]), entry)
        for pool, k in ((sorted(shown), SHOWN), (sorted(bundled), BUNDLED)):
            drawn.update((topic, iri) for iri in rng.sample(pool, min(k, len(pool))))
    new = sorted(pair for pair in drawn if pair not in known)
    rng.shuffle(new)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = {}
    for number in range(0, len(new), 150):
        sheet = []
        for nr, pair in enumerate(new[number : number + 150], start=1):
            entry = elements[pair]
            sheet.append({"nr": nr, "thema": pair[0], "fach": entry.get("schulfaecher") or [],
                          "lehrplan": entry.get("lehrplan"), "bereich": entry.get("bereich"), "element": entry.get("label")})
            key[f"{number // 150 + 1}:{nr}"] = {"thema": pair[0], "iri": pair[1]}
        (folder / f"eingabe_{number // 150 + 1}.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=1), "utf-8")
    (folder / "schluessel.json").write_text(json.dumps(key, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(drawn)} gezogen, {len(drawn) - len(new)} schon benotet, {len(new)} neu in {(len(new) + 149) // 150} Bögen")


def bauen(m57_out, m58_out, paths, folder, target):
    pools = []  # (topic, kind, variant, shown, bundled)
    for r in _runs(m57_out):
        if "error" not in r:
            e = r["entries"]
            pools.append((r["topic"], r["kind"], f"{r['preset']}/m57", {x["iri"] for x in e if not _bundled_m57(x)},
                          {x["iri"] for x in e if _bundled_m57(x)}))
    for r in _runs(m58_out, "b"):
        for variant in ("titel_und_begriffe", "mit_fach"):
            if not r.get("error") and variant in r:
                e = r[variant]["entries"]
                pools.append((r["topic"], r["kind"], f"{r['preset']}/m58:{variant}",
                              {x["iri"] for x in e if not _bundled_m57(x)}, {x["iri"] for x in e if _bundled_m57(x)}))
    pools += [pool[:5] for pool in m64_pools(paths)]
    miss = defaultdict(lambda: 1.0)
    for topic, _, _, shown, bundled in pools:
        for pool, k in ((shown, SHOWN), (bundled, BUNDLED)):
            for iri in pool:
                miss[(topic, iri)] *= 1 - min(1.0, k / len(pool))
    grades = graded_before()
    key = json.loads((Path(folder) / "schluessel.json").read_text(encoding="utf-8"))
    for sheet in sorted(Path(folder).glob("noten_*_g1.json")):
        number = sheet.name.split("_")[1]
        for nr, note in json.loads(sheet.read_text(encoding="utf-8")).items():
            pair = key[f"{number}:{nr}"]
            grades[(pair["thema"], pair["iri"])] = int(note)
    variants = sorted({v for _, _, v, _, _ in pools if "/m64:" in v})
    shows = defaultdict(set)
    for topic, _, variant, shown, _ in pools:
        if variant in variants:
            for iri in shown:
                if (topic, iri) in grades:
                    shows[(topic, iri)].add(variants.index(variant))
    out = {
        "note": "M64 gepoolt (03.10.2026): je benotetem Paar die Note von Gutachter 1, die Chance, gezogen zu werden "
        "(pi, über alle Pools von M57, M58 und M64), und die Varianten von M64, die es einzeln zeigen.",
        "varianten": variants,
        "art": {topic: kind for topic, kind, *_ in pools},
        "gezeigt": {v: {t: len(s) for t, _, var, s, _ in pools if var == v} for v in variants},
        "paare": [{"thema": t, "iri": i, "note": g, "pi": round(1 - miss[(t, i)], 6), "einzeln_in": sorted(shows[(t, i)])}
                  for (t, i), g in sorted(grades.items()) if (t, i) in miss],
    }
    Path(target).write_text(json.dumps(out, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"{len(out['paare'])} Paare, {len(variants)} Varianten, {len(out['art'])} Themen")


def auswerten(source):
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    names, kind_of, shown = data["varianten"], data["art"], data["gezeigt"]
    per = defaultdict(lambda: defaultdict(list))
    for pair in data["paare"]:
        for index in pair["einzeln_in"]:
            per[names[index]][pair["thema"]].append((pair["note"], 1 / pair["pi"]))

    def ran(variant, topic):
        """The variant where it ran; where it did not (no school form, the topic is the title) it is "heute"."""
        return variant if topic in shown[variant] else variant.split("/")[0] + "/m64:heute"

    def estimate(variant, topics):
        weight = fit = unfit = 0.0
        for topic in topics:
            used = ran(variant, topic)
            rows = per[used].get(topic) if shown[used].get(topic) else None
            if rows:
                total = sum(w for _, w in rows)
                w = min(SHOWN, shown[used][topic])
                weight += w
                fit += w * sum(x for g, x in rows if g == 2) / total
                unfit += w * sum(x for g, x in rows if g == 0) / total
        return (fit / weight, unfit / weight) if weight else (0.0, 0.0)

    rng = random.Random(6458)
    for kind in KINDS:
        topics = sorted(t for t, k in kind_of.items() if k == kind)
        draws = [[rng.choice(topics) for _ in topics] for _ in range(2000)]
        print(f"-- {kind} ({len(topics)} Themen): passend / unpassend, Themen mit passendem Element, Elemente (Median), "
              "Themen, bei denen die Variante lief")
        for variant in names:
            fit, unfit = estimate(variant, topics)
            seen = sum(1 for t in topics if any(g == 2 for g, _ in per[ran(variant, t)].get(t, [])))
            sizes = sorted(shown[ran(variant, t)].get(t, 0) for t in topics)
            runs = sum(1 for t in topics if t in shown[variant])
            print(f"   {variant:30} {fit:4.0%} / {unfit:4.0%}  {seen:2}  {sizes[len(sizes) // 2]:4}  {runs:2}")
        for variant in names:
            base = variant.split("/")[0] + "/m64:heute"
            if variant == base:
                continue
            diffs = sorted(estimate(variant, d)[0] - estimate(base, d)[0] for d in draws)
            unfit = sorted(estimate(variant, d)[1] - estimate(base, d)[1] for d in draws)
            print(f"   {variant} - heute: passend {estimate(variant, topics)[0] - estimate(base, topics)[0]:+.0%} "
                  f"[{diffs[50]:+.0%}, {diffs[1949]:+.0%}], unpassend "
                  f"{estimate(variant, topics)[1] - estimate(base, topics)[1]:+.0%} [{unfit[50]:+.0%}, {unfit[1949]:+.0%}]")


if __name__ == "__main__":
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[2:] if a.startswith("--"))
    if sys.argv[1] == "stichprobe":
        stichprobe(args, options["bogen"])
    elif sys.argv[1] == "bauen":
        bauen(args[0], args[1], args[2:-1], options["noten"], args[-1])
    else:
        auswerten(args[0])
