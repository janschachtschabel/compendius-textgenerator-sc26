"""Step 3 (project venv): one yardstick for all methods — the gold standard.

Classification: every chunk a method assigns is compared with its gold label (macro/micro F1 of the project's eval).
Selection: the chunks a method would actually print (top-k per slot): share that is correct, covered slots,
slots with at least one correct chunk. Predictions for "akteure" are ignored: that block is generated, not matched.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

from app.matching.eval import aggregate, evaluate

export = json.load(open(sys.argv[1], encoding="utf-8"))


def selection_stats(selection: dict[str, list], gold: dict[str, str | None], slot_keys: list[str], k: int | None):
    chosen = judged = correct = 0
    covered = correct_slots = 0
    for slot in slot_keys:
        items = selection.get(slot, [])
        items = items[:k] if k else items
        if not items:
            continue
        covered += 1
        hit = False
        for chunk_id, _score in items:
            chosen += 1
            if chunk_id not in gold:
                continue
            judged += 1
            if gold[chunk_id] == slot:
                correct += 1
                hit = True
        correct_slots += hit
    return chosen, judged, correct, covered, correct_slots


rows: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(list))
for topic in export["topics"]:
    name = topic["topic"]
    gold: dict[str, str | None] = topic["gold"]
    slot_keys = [s["slot"] for s in topic["slots"] if not s.get("generator")]
    for pool in ("gold", "full"):
        methods: dict[str, dict] = {}
        for label, run in topic["mine"][pool].items():
            methods[f"MEIN {label}"] = {"classified": run["classified"], "selection": run["selection"], "ms": run["ms"]}
        for method, data in methods.items():
            row = rows[(pool, method)]
            row["eval"].append(evaluate(name, gold, data["classified"], slot_keys, matcher=method))
            row["ms"].append(data["ms"])
            row["topics"].append(name)
            for tag, k, sel in (("sel", None, data["selection"]), ("sel2", 2, data["selection"])):
                row[tag].append(selection_stats(sel, gold, slot_keys, k))

for pool in ("gold", "full"):
    print(f"\n=== Kandidatenpool: {pool} ===")
    print(f"{'Verfahren':34s} {'Themen':>6s} {'macroF1':>8s} {'microF1':>8s} {'zugeordnet':>10s} {'falsch':>7s} | "
          f"{'Auswahl':>7s} {'beurteilt':>9s} {'richtig%':>8s} {'Slots':>6s} {'Slots ok':>8s} | {'@2 richtig%':>11s} {'Slots ok@2':>10s} | {'ms':>5s}")
    for (p, method), row in sorted(rows.items(), key=lambda kv: (kv[0][0], -aggregate(kv[1]["eval"]).macro_f1)):
        if p != pool:
            continue
        total = aggregate(row["eval"])
        n = len(row["topics"])
        chosen, judged, correct, covered, ok = (sum(x[i] for x in row["sel"]) for i in range(5))
        c2, j2, r2, cov2, ok2 = (sum(x[i] for x in row["sel2"]) for i in range(5))
        print(f"{method:34s} {n:6d} {total.macro_f1:8.2f} {total.micro_f1:8.2f} {total.assigned:10d} {total.misassigned:7d} | "
              f"{chosen:7d} {judged:9d} {100 * correct / max(judged, 1):8.1f} {covered / n:6.1f} {ok / n:8.1f} | "
              f"{100 * r2 / max(j2, 1):11.1f} {ok2 / n:10.1f} | {sum(row['ms']) / n:5.0f}")
