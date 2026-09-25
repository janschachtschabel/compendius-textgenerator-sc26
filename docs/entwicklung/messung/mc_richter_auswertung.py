"""Evaluate the blind judges of M28 (readable version) and M29 (QA pairs) against their keys.

Usage: python docs/entwicklung/messung/mc_richter_auswertung.py qa <key.json> <judge1.json> <judge2.json> <out.json>
       python docs/entwicklung/messung/mc_richter_auswertung.py text <key.json> <judge1.json> <judge2.json> <out.json>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def qa(key: dict[str, str], judges: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for method in sorted(set(key.values())):
        ids = [pair_id for pair_id, owner in key.items() if owner == method]
        per_judge = []
        for judge in judges:
            free = sum(1 for pair_id in ids if judge[pair_id]["mangelfrei"])
            defects = Counter(judge[pair_id]["mangel"] for pair_id in ids if not judge[pair_id]["mangelfrei"])
            per_judge.append({"mangelfrei": free, "von": len(ids), "maengel": dict(defects)})
        both = sum(1 for pair_id in ids if all(judge[pair_id]["mangelfrei"] for judge in judges))
        result[method] = {"gutachter": per_judge, "beide_mangelfrei": both, "paare": len(ids)}
    agree = sum(1 for pair_id in key if len({judge[pair_id]["mangelfrei"] for judge in judges}) == 1)
    result["uebereinstimmung_mangelfrei"] = f"{agree} von {len(key)}"
    return result


def text(key: dict[str, str], judges: list[dict[str, Any]]) -> dict[str, Any]:
    scores: dict[str, dict[str, list[float]]] = {}
    preferences: Counter[str] = Counter()
    errors: dict[str, list[int]] = {}
    for judge in judges:
        for topic, rating in judge["themen"].items():
            for label in ("A", "B"):
                profile = key[f"{topic}__{label}"]
                sheet = rating[label]
                for field in ("lesbarkeit", "zusammenhang", "passend_zum_thema", "fuellsaetze"):
                    scores.setdefault(profile, {}).setdefault(field, []).append(float(sheet[field]))
                errors.setdefault(profile, []).append(len(sheet.get("fachfehler") or []))
            choice = rating["vorzug"]
            preferences[key[f"{topic}__{choice}"] if choice in ("A", "B") else "gleich"] += 1
    knowledge = Counter()
    for judge in judges:
        for sentences in judge["modellwissen"].values():
            for sentence in sentences:
                knowledge[(sentence["korrekt"], sentence["nutzen"])] += 1
    return {
        "mittel": {
            profile: {field: round(statistics.mean(values), 2) for field, values in fields.items()}
            for profile, fields in scores.items()
        },
        "fachfehler_summe": {profile: sum(values) for profile, values in errors.items()},
        "vorzug": dict(preferences),
        "modellwissen": {f"{correct}/{use}": count for (correct, use), count in sorted(knowledge.items())},
    }


if __name__ == "__main__":
    kind, key_path, *judge_paths, out = sys.argv[1:]
    key = load(key_path)
    judges = [load(path) for path in judge_paths]
    evaluated = qa(key, judges) if kind == "qa" else text(key, judges)
    Path(out).write_text(json.dumps(evaluated, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(evaluated, ensure_ascii=False, indent=1))
