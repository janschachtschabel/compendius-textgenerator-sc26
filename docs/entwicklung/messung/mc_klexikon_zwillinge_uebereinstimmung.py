"""Agreement of two label files over the same sheet: counts, confusion, Cohen's kappa, the disagreements (M85).

Usage: python mc_klexikon_zwillinge_uebereinstimmung.py <bogen.json> <urteil.json> <urteil_zweitgutachter.json>
"""

import json
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sheet = {e["id"]: e for e in json.loads(Path(sys.argv[1]).read_text("utf-8"))}
first = json.loads(Path(sys.argv[2]).read_text("utf-8"))
second = json.loads(Path(sys.argv[3]).read_text("utf-8"))
assert set(first) == set(second) == set(sheet), "ids differ"
classes = ["passt", "teilweise", "daneben"]
pairs = Counter((first[i], second[i]) for i in sheet)
n = len(sheet)
observed = sum(pairs[(c, c)] for c in classes) / n
expected = sum(
    (sum(pairs[(c, x)] for x in classes) / n) * (sum(pairs[(x, c)] for x in classes) / n) for c in classes
)
print("Gutachter 1:", Counter(first.values()), "| Gutachter 2:", Counter(second.values()))
print("Übereinstimmung", f"{observed:.3f}", "kappa", f"{(observed - expected) / (1 - expected):.3f}")
for a in classes:
    print(f"  G1 {a:<9}", {b: pairs[(a, b)] for b in classes})
# binary: daneben or not, the measure the report counts
bin_obs = sum(1 for i in sheet if (first[i] == "daneben") == (second[i] == "daneben")) / n
print("daneben ja/nein gleich:", f"{bin_obs:.3f}")
for i in sorted(sheet, key=lambda i: sheet[i]["thema"]):
    if first[i] != second[i]:
        print(f"  {i} {sheet[i]['thema']} / {sheet[i]['klexikon_seite']}: G1 {first[i]}, G2 {second[i]} | "
              f"{sheet[i]['text'][:110]}")
