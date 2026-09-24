"""laya-multilingual on the decisions of article choice and hit check (M16), on the CPU, against the gold.

Runs outside the project: in the venv of the test app (torch 2.14 CPU, transformers 5.17) with the laya package
(0.3.20, PyPI) on PYTHONPATH and the model convaiinnovations/laya-multilingual from Hugging Face. Reads what
mc_laya_export.py wrote and poses each decision as the service poses it to the LLM:

- article choice: one choice question over the candidates of an unsure resolution (title and opening);
- hit check: per full-text hit a yes/no question (noul) and a three-way choice (belongs, related, does not fit),
  with the topic and the opening of its main article as the state.

Writes the decisions and times without any article text. Usage: python mc_laya.py <export.json> <out.json>
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import laya

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

export = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out_path = Path(sys.argv[2])
MAX_OPTIONS = 20  # the model card: keep choice questions under about 20 options

started = time.perf_counter()
agent = laya.load("convaiinnovations/laya-multilingual", device="cpu")
load_s = time.perf_counter() - started
agent.predict("Aufwärmen.", {"x": {"type": "noul", "instructions": "Ist das ein Test?"}})


def choose(entry: dict, limit: int | None) -> tuple[str, float, float]:
    candidates = entry["kandidaten"][:limit] if limit else entry["kandidaten"]
    subject = entry["fach"] or "keine Angabe"
    question = {
        "artikel": {
            "type": "choice",
            "instructions": f"Welcher Wikipedia-Artikel ist der Hauptartikel zum Schulthema „{entry['thema']}“ "
            f"im Fach {subject}?",
            "criteria": {c["titel"]: c["anfang"] for c in candidates},
        }
    }
    state = {"thema": entry["thema"], "fach": subject, "anfrage": entry["anfrage"]}
    started = time.perf_counter()
    answer = agent.predict(state, question)["answers"]["artikel"]
    return answer["choice"], float(answer.get("confidence", 0.0)), time.perf_counter() - started


article_rows = []
for entry in export["artikelwahl"]:
    full, full_conf, full_s = choose(entry, None)
    capped, capped_conf, capped_s = choose(entry, MAX_OPTIONS)
    article_rows.append(
        {
            "anfrage": entry["anfrage"],
            "kandidaten": len(entry["kandidaten"]),
            "akzeptiert": entry["akzeptiert"],
            "regeln": entry["regeln"],
            "regeln_richtig": entry["regeln"] in entry["akzeptiert"],
            "laya": full,
            "laya_richtig": full in entry["akzeptiert"],
            "laya_sicherheit": round(full_conf, 4),
            "laya_s": round(full_s, 3),
            "laya_20": capped,
            "laya_20_richtig": capped in entry["akzeptiert"],
            "gold_unter_20": any(c["titel"] in entry["akzeptiert"] for c in entry["kandidaten"][:MAX_OPTIONS]),
        }
    )

HIT_QUESTIONS = {
    "passt": {
        "type": "noul",
        "instructions": "Gehört der Kandidat-Artikel zum Thema? Ja, wenn er das Thema oder einen Teil davon behandelt "
        "oder eng damit zusammenhängt; nein, wenn er ein anderes Gebiet behandelt und mit dem Thema nur ein Wort "
        "teilt.",
    },
    "note": {
        "type": "choice",
        "instructions": "Wie gut passt der Kandidat-Artikel zum Thema?",
        "criteria": {
            "gehört zum Thema": "behandelt das Thema selbst oder einen Teil davon",
            "verwandt": "hängt mit dem Thema zusammen, behandelt aber etwas anderes",
            "passt nicht": "hat mit dem Thema nichts zu tun und teilt höchstens ein Wort",
        },
    },
}


def hit_state(hit: dict) -> dict:
    return {
        "thema": hit["thema"],
        "hauptartikel": f"{hit['hauptartikel']}: {hit['hauptartikel_anfang'] or ''}",
        "kandidat": f"{hit['titel']}: {hit['anfang'] or ''}",
    }


hit_rows = []
for hit in export["treffer"]:
    started = time.perf_counter()
    answers = agent.predict(hit_state(hit), HIT_QUESTIONS)["answers"]
    hit_rows.append(
        {
            "thema": hit["thema"],
            "titel": hit["titel"],
            "gold": hit["note"],
            "ja": round(float(answers["passt"]["noul"]), 4),
            "note": answers["note"]["choice"],
            "s": round(time.perf_counter() - started, 3),
        }
    )
started = time.perf_counter()
agent.predict_batch([hit_state(hit) for hit in export["treffer"]], HIT_QUESTIONS, batch_size=16)
batch_s = time.perf_counter() - started

out = {
    "modell": "convaiinnovations/laya-multilingual",
    "paket": laya.__version__ if hasattr(laya, "__version__") else "0.3.20",
    "geraet": "cpu",
    "laden_s": round(load_s, 1),
    "artikelwahl": article_rows,
    "treffer": hit_rows,
    "treffer_stapel_s": round(batch_s, 2),
}
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"geladen in {load_s:.1f} s")
right = sum(r["regeln_richtig"] for r in article_rows)
capped_right = sum(r["laya_20_richtig"] for r in article_rows)
print(f"Artikelwahl, {len(article_rows)} unsichere Anfragen: Regeln {right}, "
      f"laya {sum(r['laya_richtig'] for r in article_rows)}, "
      f"laya mit höchstens {MAX_OPTIONS} Kandidaten {capped_right} "
      f"(Gold unter den ersten {MAX_OPTIONS}: {sum(r['gold_unter_20'] for r in article_rows)}); "
      f"Zeit je Entscheidung Median {statistics.median(r['laya_s'] for r in article_rows):.2f} s")
for threshold in (0.5,):
    dropped = [r for r in hit_rows if r["ja"] < threshold]
    print(f"Treffer, ja/nein unter {threshold}: verworfen gehört {sum(r['gold'] == 2 for r in dropped)} von "
          f"{sum(r['gold'] == 2 for r in hit_rows)}, verwandt {sum(r['gold'] == 1 for r in dropped)} von "
          f"{sum(r['gold'] == 1 for r in hit_rows)}, passt nicht {sum(r['gold'] == 0 for r in dropped)} von "
          f"{sum(r['gold'] == 0 for r in hit_rows)}")
dropped = [r for r in hit_rows if r["note"] == "passt nicht"]
print(f"Treffer, Dreiwahl 'passt nicht': gehört {sum(r['gold'] == 2 for r in dropped)}, verwandt "
      f"{sum(r['gold'] == 1 for r in dropped)}, passt nicht {sum(r['gold'] == 0 for r in dropped)}; "
      f"Zeit je Treffer Median {statistics.median(r['s'] for r in hit_rows):.2f} s, alle 47 im Stapel {batch_s:.1f} s")
