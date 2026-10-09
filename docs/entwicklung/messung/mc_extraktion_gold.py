"""M89: the AI's choice of sentences (extraction=llm) against the assignment gold - does it print better paragraphs?

The ten gold topics of eval/gold (the directory bound to /gold) in the service's flow, as mc_budget_gold.py: the corpus
of llm-free, as labelled, and 30,000 characters. Every topic is prepared once; per run (matcher and block budget
factor) the service assigns and cuts as it ships (service.match with budget_factor, D102), and the choice of sentences
of extraction=llm works on that cut (service.extract). Printed paragraphs against the labels, as M44 and M86 count
them: without the choice the paragraphs the cut keeps, with it the paragraphs whose sentences the text prints, each
in the block where it prints the most (predictions_from_selection). A printed paragraph without a label counts in
neither precision nor recall.

In the one-off container with OpenAI direct, the budget of a request raised so that it does not step in:
  cat mc_openai_direkt.py mc_extraktion_gold.py | docker compose run --rm --no-deps -T -v <repo>/eval/gold:/gold \\
      -v <ordner>:/out -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid \\
      -e OPENAI_API_KEY -e LLM_MAX_TOKENS_PER_REQUEST=2000000 api python - /out/<lauf>.json
      [--runs=hybrid_light@1,hybrid_light@10,llm@10]
"""

import json
import os
import sys
import time
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching.eval import (  # noqa: E402
    aggregate,
    align,
    evaluate,
    predictions_from_assignment,
    predictions_from_selection,
)
from app.matching.gold import load_gold  # noqa: E402

TARGET_LENGTH = 30_000
RUNS = ("hybrid_light@1", "hybrid_light@10", "llm@10")


def counted(results: list, printed: int) -> dict:
    """Precision, recall and F1 of the printed paragraphs, as mc_budget_gold.py counts them."""
    whole = aggregate(results)
    tp, fp, fn = (sum(getattr(m, key) for m in whole.slots) for key in ("tp", "fp", "fn"))
    not_in = sum(count for key, count in whole.confusion.items() if key.startswith("none>"))
    return {
        "gedruckt": printed,
        "richtig": tp,
        "falsch_zugeordnet": fp,
        "nicht_hinein": not_in,  # labelled for no block, printed all the same
        "ohne_label": printed - tp - fp,
        "verpasst": fn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "f1": round(2 * tp / (2 * tp + fp + fn), 3) if tp else 0.0,
        "macro_f1": round(whole.macro_f1, 3),
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    runs = options["runs"].split(",") if "runs" in options else list(RUNS)
    if "install" in globals():  # piped in after mc_openai_direkt.py: every call goes to OpenAI direct
        install()  # noqa: F821
    service = cli_service(None)
    if service.llm is None:
        raise SystemExit("LLM_ENABLED did not reach the settings")
    topics = []
    for path in sorted(Path("/gold").glob("*.jsonl")):
        gold = load_gold(path)
        request = GenerateRequest(topic=gold.topic, template_id=gold.template_id, parts=["world"], preset="llm-free")
        prepared = service.prepare(request)
        topics.append((gold, prepared, align(gold, prepared.chunks)))
    out: dict[str, dict] = {}
    for run in runs:
        matcher, factor = run.split("@")
        without, chosen, printed = [], [], {"ohne": 0, "mit": 0}
        cost = {"tokens_zuordnung": 0, "tokens_auswahl": 0, "aufrufe_auswahl": 0, "sekunden_auswahl": 0.0}
        choice = {"angeboten": 0, "saetze": 0, "gekuerzt": 0, "leer": 0, "rueckfaelle": 0}
        per_topic = []
        for gold, prepared, alignment in topics:
            matched = service.match(prepared, matcher, TARGET_LENGTH, budget_factor=float(factor))
            if matched.llm is not None:
                cost["tokens_zuordnung"] += matched.llm.total_tokens
            slot_keys = [slot.slot for slot in prepared.template.content_slots()]
            title = prepared.resolution.title or gold.topic
            plain = predictions_from_assignment(matched.assignment.assigned, prepared.template)
            started = time.monotonic()
            extracted = service.extract(prepared, matched, TARGET_LENGTH)
            if extracted is None:
                raise SystemExit("no LLM for the choice of sentences")
            cost["sekunden_auswahl"] += time.monotonic() - started
            selected = predictions_from_selection(extracted.assigned, prepared.template)
            report = extracted.report
            cost["tokens_auswahl"] += report.total_tokens
            cost["aufrufe_auswahl"] += report.calls
            choice["angeboten"] += report.offered
            choice["saetze"] += report.sentences
            choice["gekuerzt"] += report.cut
            choice["leer"] += len(report.emptied)
            choice["rueckfaelle"] += len(report.fallbacks)
            printed["ohne"] += len(plain)
            printed["mit"] += len(selected)
            without.append(evaluate(title, alignment.gold_by_chunk, plain, slot_keys, matcher=run))
            chosen.append(evaluate(title, alignment.gold_by_chunk, selected, slot_keys, matcher=f"{run}+ex"))
            per_topic.append(
                {
                    "thema": gold.topic,
                    "ohne": len(plain),
                    "mit": len(selected),
                    "tokens_auswahl": report.total_tokens,
                    "rueckfaelle": dict(report.fallbacks),
                    "leer": list(report.emptied),
                }
            )
        cost["sekunden_auswahl"] = round(cost["sekunden_auswahl"], 1)
        out[run] = {
            "ohne_auswahl": counted(without, printed["ohne"]),
            "mit_auswahl": counted(chosen, printed["mit"]),
            **cost,
            **choice,
            "themen": per_topic,
        }
        print(run, json.dumps({k: out[run][k] for k in ("ohne_auswahl", "mit_auswahl")}), file=sys.stderr, flush=True)
        Path(args[0]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
