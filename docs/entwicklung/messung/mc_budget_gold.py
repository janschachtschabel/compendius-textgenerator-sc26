"""M86: the paragraphs the blocks print at larger block budgets, against the assignment gold - right or wrong ones?

The ten gold topics of eval/gold (the directory bound to /gold) in the service's flow: the corpus of llm-free, as
labelled, and 30,000 characters; the whole corpus competes for the places, as in a compendium. Every topic is prepared
once and assigned once per matcher (hybrid_light, llm); the assignment's last cut to the block budgets is caught and
made again with the paragraphs and characters of every block times 1, 2, 4 and 10, as mc_kompendium_profil.py
--budgets does (``--budgets=`` for other factors; 1000 sets no limit in practice). Printed precision and recall over
the labelled paragraphs, as M44 counts them (app/matching/eval); a printed paragraph without a label counts in
neither. A wrong one is either in another block than its label's or labelled for none at all (``nicht_hinein``).

From release 2.19.0 the service widens the budgets itself (BLOCK_BUDGET_FACTOR, default 10, D102); to measure the
factors as M86 did, start the container with -e BLOCK_BUDGET_FACTOR=1.

In the one-off container with OpenAI direct (M86), the budgets of a request raised so that none of them steps in:
  cat mc_openai_direkt.py mc_budget_gold.py | docker compose run --rm --no-deps -T -v <repo>/eval/gold:/gold \\
      -v <ordner>:/out -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid \\
      -e OPENAI_API_KEY -e LLM_MAX_TOKENS_PER_REQUEST=2000000 api python - /out/<lauf>.json [--matchers=a,b]
      [--budgets=1,2,4,10]
"""

import json
import os
import sys
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching import llm_assignment, policy  # noqa: E402
from app.matching.eval import aggregate, align, evaluate, predictions_from_assignment  # noqa: E402
from app.matching.gold import load_gold  # noqa: E402

TARGET_LENGTH = 30_000
FACTORS = (1, 2, 4, 10)
MATCHERS = ("hybrid_light", "llm")
shipped_cut = policy.cut_to_budgets
caught: dict[str, tuple] = {}


def catching_cut(template, candidates):  # the signature of policy.cut_to_budgets
    """The cut as shipped; its template and candidates stay for the factors (the last call is the assignment's)."""
    caught["last"] = (template, candidates)
    return shipped_cut(template, candidates)


policy.cut_to_budgets = llm_assignment.cut_to_budgets = catching_cut


def scaled(template, factor: int):  # a Template in, a Template out
    """The block budgets times ``factor``: paragraphs and characters, as mc_kompendium_profil.py --budgets."""
    slots = [
        slot
        if slot.is_generated
        else slot.model_copy(
            update={
                "budget": slot.budget.model_copy(
                    update={
                        "max_chunks": slot.budget.max_chunks * factor,
                        "target_chars": slot.budget.target_chars * factor,
                    }
                )
            }
        )
        for slot in template.slots
    ]
    return template.model_copy(update={"slots": slots})


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    matchers = options["matchers"].split(",") if "matchers" in options else list(MATCHERS)
    factors = [int(f) for f in options["budgets"].split(",")] if "budgets" in options else list(FACTORS)
    if "install" in globals():  # piped in after mc_openai_direkt.py: every call goes to OpenAI direct
        install()  # noqa: F821
    service = cli_service(None)
    topics = []
    for path in sorted(Path("/gold").glob("*.jsonl")):
        gold = load_gold(path)
        request = GenerateRequest(topic=gold.topic, template_id=gold.template_id, parts=["world"], preset="llm-free")
        prepared = service.prepare(request)
        topics.append((gold, prepared, align(gold, prepared.chunks)))
    out: dict[str, dict] = {}
    for matcher in matchers:
        cuts, tokens, fallback = [], 0, 0
        for gold, prepared, alignment in topics:
            matched = service.match(prepared, matcher, TARGET_LENGTH)
            if matched.llm is not None:
                tokens += matched.llm.total_tokens
                fallback += matched.llm.fallback
            cuts.append((gold, prepared, alignment, caught["last"]))
        for factor in factors:
            results, printed = [], 0
            for gold, prepared, alignment, (template, candidates) in cuts:
                kept, _notes, _dropped = shipped_cut(scaled(template, factor), candidates)
                printed += sum(len(items) for items in kept.values())
                slot_keys = [slot.slot for slot in prepared.template.content_slots()]
                predictions = predictions_from_assignment(kept, prepared.template)
                title = prepared.resolution.title or gold.topic
                results.append(evaluate(title, alignment.gold_by_chunk, predictions, slot_keys, matcher=matcher))
            whole = aggregate(results)
            tp, fp, fn = (sum(getattr(m, key) for m in whole.slots) for key in ("tp", "fp", "fn"))
            not_in = sum(count for key, count in whole.confusion.items() if key.startswith("none>"))
            out[f"{matcher}@{factor}"] = {
                "gedruckt": printed,
                "gelabelt": whole.labeled,
                "richtig": tp,
                "falsch_zugeordnet": fp,
                "nicht_hinein": not_in,  # labelled for no block, printed all the same
                "ohne_label": printed - tp - fp,
                "verpasst": fn,
                "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                "macro_f1": round(whole.macro_f1, 3),
                "micro_f1": round(whole.micro_f1, 3),
                "veraltet": whole.stale_labels,
                "tokens_zuordnung": tokens,
                "rueckfaelle_zuordnung": fallback,
            }
            print(f"{matcher}@{factor}", out[f"{matcher}@{factor}"], file=sys.stderr, flush=True)
    Path(args[0]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
