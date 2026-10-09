"""M86: the paragraphs best-quality-generated gives its writer at the block budgets times 1, 2, 4 and 10 - does more
budget hand the writer worse evidence?

Every topic is prepared once as best-quality-generated prepares it (the thorough article choice and the articles the
LLM names, D63) and assigned once by the LLM; the assignment's last cut to the block budgets is caught and made again
for every factor, as mc_budget_gold.py does, so the factors share one corpus and one assignment and the evidence of a
smaller factor is part of every larger one's. One row per topic and factor holds the kept paragraphs per block, as the
writer reads them (1,500 characters at most), under "belege" - the form mc_budget_absaetze.py judges.

From release 2.19.0 the service widens the budgets itself (BLOCK_BUDGET_FACTOR, default 10, D102); to measure the
factors as M86 did, start the container with -e BLOCK_BUDGET_FACTOR=1.

In the one-off container with OpenAI direct (M86):
  cat mc_openai_direkt.py mc_budget_belege.py | docker compose run --rm --no-deps -T -v <ordner>:/out \\
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \\
      -e LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY=2000000 api python - /out/<lauf>.json <thema> [...]
"""

import json
import os
import sys
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.llm.deadline import Deadline  # noqa: E402
from app.matching import llm_assignment, policy  # noqa: E402
from app.synthesis.llm import MAX_EVIDENCE_CHARS  # noqa: E402

PROFILE = "best-quality-generated"
FACTORS = (1, 2, 4, 10)
TARGET_LENGTH = 30_000
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
    out_path, topics = Path(sys.argv[1]), sys.argv[2:]
    if "install" in globals():  # piped in after mc_openai_direkt.py: every call goes to OpenAI direct
        install()  # noqa: F821
    service = cli_service(None)
    rows = []
    for topic in topics:
        deadline = Deadline(service.settings.request_time_limit_s)
        request, profile = service._admit(GenerateRequest(topic=topic, preset=PROFILE, parts=["world"]), deadline)
        budget = service.open_budget(profile)
        _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
        prepared = service.prepare(request, deadline, choice)
        matched = service.match(prepared, "llm", TARGET_LENGTH, budget=budget, deadline=deadline)
        template, candidates = caught["last"]
        titles = {slot.id: slot.title for slot in template.slots}
        for factor in FACTORS:
            kept, _notes, _dropped = shipped_cut(scaled(template, factor), candidates)
            evidence = {
                titles[slot_id]: [" ".join(item.chunk.text.split())[:MAX_EVIDENCE_CHARS] for item in items]
                for slot_id, items in kept.items()
                if items
            }
            rows.append(
                {
                    "topic": topic,
                    "variant": f"{PROFILE}@{factor}",
                    "budget": factor,
                    "main": prepared.resolution.title,
                    "sources": [source.title for source in prepared.sources],
                    "tokens": budget.used,
                    "matcher": matched.matcher,
                    "belege": evidence,
                }
            )
            print(topic, factor, sum(len(texts) for texts in evidence.values()), "Belege", file=sys.stderr, flush=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
