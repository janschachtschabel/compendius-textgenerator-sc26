"""The block budgets times BLOCK_BUDGET_FACTOR when the assignment is cut (D102, M86).

M86 measured the factor 1, 2, 4 and 10 on the paragraphs a block keeps and on the characters at which a block with
enough paragraphs stops: the precision of what is printed stayed, the recall grew until every assigned paragraph was
printed. Jan, 2026-10-09: the tenfold budget as the default, adjustable. The writer's target length stays the
request's: only the cut sees the larger budget.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.compendium.world import scale_budgets, widen_budgets
from app.domain.models import Chunk
from app.domain.requests import GenerateRequest
from app.main import create_app
from app.settings import Settings
from app.sources.zim.registry import ZimRegistry
from app.templates.manager import TemplateManager
from app.wiring import build_service
from tests.conftest import make_settings

SC26 = TemplateManager().get("sc26")


def test_the_factor_multiplies_what_a_block_keeps_and_where_it_stops() -> None:
    widened = widen_budgets(scale_budgets(SC26, 30_000), 10)
    for before, after in zip(scale_budgets(SC26, 30_000).slots, widened.slots, strict=True):
        if before.is_generated:
            assert after == before
            continue
        assert after.budget.max_chunks == before.budget.max_chunks * 10
        assert after.budget.target_chars == before.budget.target_chars * 10
        assert after.budget.min_chunks == before.budget.min_chunks


def test_factor_one_keeps_the_templates_budgets() -> None:
    template = scale_budgets(SC26, 30_000)
    assert widen_budgets(template, 1) == template


def test_a_fraction_of_a_paragraph_counts_as_a_whole_one() -> None:
    widened = widen_budgets(SC26, 1.5)
    themendefinition = widened.slot_by_key("themendefinition")
    assert themendefinition is not None
    assert themendefinition.budget.max_chunks == 5  # 3 times 1.5, rounded up


def test_the_default_is_the_tenfold_budget_and_one_is_the_least() -> None:
    assert Settings.model_fields["block_budget_factor"].default == 10
    with pytest.raises(ValueError, match="block_budget_factor"):
        Settings(_env_file=None, block_budget_factor=0.5)


def _praxis_paragraphs(source_id: str, count: int) -> list[Chunk]:
    """``count`` paragraphs whose heading the lexicon gives to Praxis: each one a confident hit for that block."""
    return [
        Chunk(
            chunk_id=f"praxis-{number}",
            source_id=source_id,
            heading="Anwendungen",
            heading_path=["Anwendungen"],
            heading_level=2,
            position=number,
            text=f"Anwendung Nummer {number} in Geräten und Verfahren der Praxis.",
            lexicon_slot="praxis",
        )
        for number in range(count)
    ]


@pytest.mark.parametrize(("factor", "kept"), [(1, 6), (10, 12)])
def test_a_block_keeps_as_many_paragraphs_as_its_budget_times_the_factor(
    sample_zims: dict[str, Path], tmp_path: Path, factor: int, kept: int
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path, block_budget_factor=factor)
    service = build_service(settings, ZimRegistry(settings.zim_path_list), TemplateManager())
    prepared = service.prepare(GenerateRequest(topic="Optik", parts=["world"]))
    praxis = prepared.template.slot_by_key("praxis")
    assert praxis is not None and praxis.budget.max_chunks == 6  # sc26 as shipped
    prepared = replace(prepared, chunks=_praxis_paragraphs(prepared.sources[0].source_id, 12))

    matched = service.match(prepared, "hybrid_light", 30_000)

    assert len(matched.assignment.assigned[praxis.id]) == kept
    assert prepared.template.slot_by_key("praxis") == praxis  # the template itself keeps its budget


def test_the_pairs_of_qa_ask_about_part_1_at_the_templates_budgets(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pairs read all of part 1 and reserve it by its bytes: at the tenfold budget part 1 is three to seven times
    longer (M86), and the pairs of the LLM would cost as much more or fall back to the rules. /qa keeps the
    templates' budgets (D102)."""
    client = TestClient(create_app(settings))
    service = client.app.state.service  # type: ignore[attr-defined]
    factors: list[float | None] = []
    real = service.match

    def match(*args: Any, **kwargs: Any) -> Any:
        factors.append(kwargs.get("budget_factor"))
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "match", match)
    assert client.post("/api/v2/qa", json={"topic": "Optik"}).status_code == 200
    assert factors == [1]
