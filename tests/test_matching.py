from app.domain.models import Chunk, ScoredChunk, Source, SourceRole
from app.matching.fusion import fuse_rankings, smooth_sections
from app.matching.lexical import BM25Matcher, CharTfidfMatcher
from app.matching.policy import assign, exclusion_terms
from app.matching.registry import get_matcher, list_strategies
from app.templates.manager import TemplateManager


def _chunk(cid: str, heading: str, text: str, **kwargs: object) -> Chunk:
    return Chunk(
        chunk_id=cid,
        source_id="wikipedia:Test",
        heading=heading,
        heading_path=[heading] if heading != "Einleitung" else [],
        heading_level=2 if heading != "Einleitung" else 0,
        text=text,
        **kwargs,  # type: ignore[arg-type]
    )


CHUNKS = [
    _chunk(
        "c0",
        "Einleitung",
        "Die Optik ist ein Gebiet der Physik und beschäftigt sich mit der Ausbreitung von Licht.",
        is_lead=True,
    ),
    _chunk(
        "c1",
        "Geschichte",
        "Im 17. Jahrhundert entdeckte Snellius das Brechungsgesetz; die Entwicklung der Fernrohre begann.",
        lexicon_slot="entwicklung_ausblick",
    ),
    _chunk(
        "c2",
        "Anwendungen",
        "Brillen, Mikroskope und Kameras sind praktische Anwendungen optischer Geräte im Einsatz.",
        lexicon_slot="praxis",
    ),
    _chunk(
        "c3",
        "Berufe",
        "Augenoptiker und Feinoptiker fertigen Brillen; der Arbeitsmarkt der Branche wächst.",
        lexicon_slot="beruf_wirtschaft",
    ),
    _chunk(
        "c4",
        "Sonstiger Absatz",
        "Gesetze und Normen wie DIN-Vorschriften regeln die Sicherheit von Laserklassen und Grenzwerte.",
    ),
    _chunk(
        "c5",
        "Noch ein Absatz",
        "Der Unterricht in der Schule behandelt Linsen; Lehrpläne und Didaktik der Optik sind Thema der Bildung.",
    ),
]
SOURCES = {
    "wikipedia:Test": Source(
        source_id="wikipedia:Test",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title="Test",
        url="u",
        is_primary=True,
    )
}


def test_rankers_return_normalised_scores() -> None:
    template = TemplateManager().get("sc26")
    for matcher in (BM25Matcher(), CharTfidfMatcher()):
        results = matcher.score(template.slots, CHUNKS)
        assert set(results) == {s.id for s in template.slots}
        for scored in results.values():
            assert all(0 <= sc.score <= 1 for sc in scored)
        assert results["sc26_12"] == [] and results["sc26_13"] == []


def test_rrf_fuses_rankings() -> None:
    template = TemplateManager().get("sc26")
    fused = fuse_rankings(
        [BM25Matcher().score(template.slots, CHUNKS), CharTfidfMatcher().score(template.slots, CHUNKS)]
    )
    best = max(sc.score for scored in fused.values() for sc in scored)
    assert best == 1.0
    assert any(sc.matcher == "fused" for scored in fused.values() for sc in scored)


def test_policy_assigns_each_chunk_once_and_respects_lexicon() -> None:
    template = TemplateManager().get("sc26")
    fused = get_matcher("hybrid_light").score(template.slots, CHUNKS)
    result = assign(template, CHUNKS, fused, SOURCES)
    assigned_ids = [sc.chunk.chunk_id for scored in result.assigned.values() for sc in scored]
    assert len(assigned_ids) == len(set(assigned_ids)), "a chunk must land in at most one slot"
    by_slot = {slot.slot: [sc.chunk.chunk_id for sc in result.assigned[slot.id]] for slot in template.slots}
    assert by_slot["themendefinition"][0] == "c0"
    assert "c1" in by_slot["entwicklung_ausblick"]
    assert "c2" in by_slot["praxis"]
    assert "c3" in by_slot["beruf_wirtschaft"]
    assert "c4" in by_slot["regularien"]
    assert "c5" in by_slot["bildung"]


def test_budget_caps_chunks_per_slot() -> None:
    template = TemplateManager().get("sc26")
    many = [
        _chunk(
            f"p{i}", "Anwendungen", f"Anwendung Nummer {i} in Geräten und Verfahren der Praxis.", lexicon_slot="praxis"
        )
        for i in range(10)
    ]
    fused = get_matcher("hybrid_light").score(template.slots, many)
    result = assign(template, many, fused, SOURCES)
    praxis = template.slot_by_key("praxis")
    assert praxis is not None
    assert len(result.assigned[praxis.id]) <= praxis.budget.max_chunks
    assert result.unassigned >= 10 - praxis.budget.max_chunks


def test_exclusion_terms_ignore_slot_references() -> None:
    template = TemplateManager().get("sc26")
    slot = template.slot_by_key("themendefinition")
    assert slot is not None
    terms = exclusion_terms(slot)
    assert "baustein" not in terms
    assert "gesellschaft" in terms


def test_strategy_registry() -> None:
    ids = {s["id"] for s in list_strategies()}
    assert {"hybrid_light", "bm25", "char_tfidf", "lexicon_only"} <= ids
    assert get_matcher("lexicon_only").score(TemplateManager().get("sc26").slots, CHUNKS)["sc26_1"] == []


def test_classification_survives_the_budget_cut() -> None:
    template = TemplateManager().get("sc26")
    tight = template.model_copy(
        update={
            "slots": [
                s.model_copy(update={"budget": s.budget.model_copy(update={"max_chunks": 1})})
                if s.slot == "praxis"
                else s
                for s in template.slots
            ]
        }
    )
    chunks = [
        _chunk("p1", "Anwendungen", "Brillen und Kameras sind Anwendungen.", lexicon_slot="praxis"),
        _chunk("p2", "Verwendung", "Mikroskope werden in Labors verwendet.", lexicon_slot="praxis"),
    ]
    result = assign(tight, chunks, {}, SOURCES)
    praxis_id = next(s.id for s in template.slots if s.slot == "praxis")
    assert len(result.assigned[praxis_id]) == 1
    assert result.classified == {"p1": praxis_id, "p2": praxis_id}
    assert result.unassigned == 1


def _ids() -> dict[str, str]:
    return {s.slot: s.id for s in TemplateManager().get("sc26").slots}


def _secondary(title: str, origin: str) -> dict[str, Source]:
    primary = Source(
        source_id="wikipedia:Optik",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title="Optik",
        url="u",
        is_primary=True,
    )
    other = Source(
        source_id=f"wikipedia:{title}",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title=title,
        url="u",
        is_primary=False,
        origin=origin,
    )
    return {primary.source_id: primary, other.source_id: other}


def test_sc26_declares_fachinhalte_as_default_slot() -> None:
    assert TemplateManager().get("sc26").default_slot == "fachinhalte"


def test_weak_topical_chunk_falls_back_to_the_default_slot() -> None:
    template, ids = TemplateManager().get("sc26"), _ids()
    chunk = _chunk(
        "w1", "Irgendein Abschnitt", "Ein Absatz des Hauptartikels ohne klare Signalwörter für einen Baustein."
    )
    weak = {ids["regularien"]: [ScoredChunk(chunk=chunk, score=0.3, matcher="fused")]}
    result = assign(template, [chunk], weak, SOURCES)
    assert result.classified == {"w1": ids["fachinhalte"]}


def test_confident_match_beats_the_default_slot() -> None:
    template, ids = TemplateManager().get("sc26"), _ids()
    chunk = _chunk("s1", "Irgendein Abschnitt", "Brillen, Kameras und Mikroskope sind Anwendungen im Einsatz.")
    strong = {ids["praxis"]: [ScoredChunk(chunk=chunk, score=0.8, matcher="fused")]}
    assert assign(template, [chunk], strong, SOURCES).classified == {"s1": ids["praxis"]}


def test_default_slot_only_for_topical_sources() -> None:
    template, ids = TemplateManager().get("sc26"), _ids()
    sources = _secondary("Nebenthema", "search")
    chunk = Chunk(
        chunk_id="x1",
        source_id="wikipedia:Nebenthema",
        heading="Abschnitt",
        heading_path=["Abschnitt"],
        heading_level=2,
        text="Ein Absatz aus einem nachgeladenen Artikel, dessen Titel das Thema nicht nennt.",
    )
    weak = {ids["regularien"]: [ScoredChunk(chunk=chunk, score=0.3, matcher="fused")]}
    result = assign(template, [chunk], weak, sources)
    assert result.classified == {}
    assert result.unassigned == 1


def test_sub_article_lead_with_topic_stem_goes_to_systematik() -> None:
    template, ids = TemplateManager().get("sc26"), _ids()
    sources = _secondary("Wellenoptik", "linked")
    lead = Chunk(
        chunk_id="l0",
        source_id="wikipedia:Wellenoptik",
        heading="Einleitung",
        heading_level=0,
        position=0,
        text="Die Wellenoptik ist der Teilbereich der Optik, der Licht als elektromagnetische Welle behandelt.",
    )
    assert assign(template, [lead], {}, sources).classified == {"l0": ids["systematik"]}


def test_chunks_under_generated_slot_headings_are_not_classified() -> None:
    template = TemplateManager().get("sc26")
    chunk = _chunk("a1", "Bekannte Vertreter", "Bekannte Vertreter waren A, B, C, D und E.", lexicon_slot="akteure")
    result = assign(template, [chunk], {}, SOURCES)
    assert result.classified == {}
    assert result.unassigned == 1


def test_confidence_threshold_is_a_parameter() -> None:
    template, ids = TemplateManager().get("sc26"), _ids()
    chunk = _chunk("t1", "Irgendein Abschnitt", "Brillen, Kameras und Mikroskope sind Anwendungen im Einsatz.")
    hit = {ids["praxis"]: [ScoredChunk(chunk=chunk, score=0.6, matcher="fused")]}  # source boost keeps it < 0.9
    assert assign(template, [chunk], hit, SOURCES, confident_score=0.9).classified == {"t1": ids["fachinhalte"]}
    assert assign(template, [chunk], hit, SOURCES, confident_score=0.5).classified == {"t1": ids["praxis"]}


def test_default_slot_skips_person_and_work_articles() -> None:
    from app.domain.models import ArticleSection, Paragraph

    template, ids = TemplateManager().get("sc26"), _ids()
    primary = Source(
        source_id="wikipedia:Sinfonie",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title="Sinfonie",
        url="u",
        is_primary=True,
    )
    work = Source(
        source_id="wikipedia:Manfred-Sinfonie",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title="Manfred-Sinfonie",
        url="u",
        is_primary=False,
        origin="linked",
        sections=[
            ArticleSection(
                heading="",
                path=[],
                level=0,
                paragraphs=[Paragraph(text="Die Manfred-Sinfonie ist eine Sinfonie in vier Bildern.")],
            )
        ],
    )
    sources = {primary.source_id: primary, work.source_id: work}
    chunk = Chunk(
        chunk_id="w1",
        source_id=work.source_id,
        heading="Inhalt",
        heading_path=["Inhalt"],
        heading_level=2,
        position=3,
        text="Der dritte Satz ist eine Pastorale, in der das friedliche Leben der Bergbewohner geschildert wird.",
    )
    weak = {ids["regularien"]: [ScoredChunk(chunk=chunk, score=0.3, matcher="fused")]}
    assert assign(template, [chunk], weak, sources).classified == {}


def test_material_chunks_are_evidence_for_the_slots_that_prefer_materials() -> None:
    """PLAN.md 6.3: paragraphs of reusable collection materials feed Bildung and Praxis even without a strong ranker hit."""
    from app.matching.policy import MATERIAL_SCORE
    from app.sources.wlo.knowledge import TEXT_HEADING

    template, ids = TemplateManager().get("sc26"), _ids()
    material = Source(
        source_id="wlo:mat1",
        project="wlo_material",
        role=SourceRole.MATERIAL,
        title="Stationsarbeit zur Optik",
        url="https://example.org/m",
        origin="material",
        license="CC0 1.0",
    )
    sources = {**SOURCES, material.source_id: material}
    chunk = Chunk(
        chunk_id="m1",
        source_id="wlo:mat1",
        heading=TEXT_HEADING,
        heading_path=[TEXT_HEADING],
        heading_level=2,
        text="Beschrifte das Augenmodell und konstruiere den Strahlengang durch die Linse.",
    )
    weak = {
        ids["praxis"]: [ScoredChunk(chunk=chunk, score=0.2, matcher="fused")],
        ids["fachinhalte"]: [ScoredChunk(chunk=chunk, score=0.3, matcher="fused")],
    }
    result = assign(template, [chunk], weak, sources)
    assert result.classified == {"m1": ids["praxis"]}
    assert result.assigned[ids["praxis"]][0].score >= MATERIAL_SCORE
    strict = assign(template, [chunk], weak, sources, confident_score=0.8)
    assert strict.classified == {"m1": ids["praxis"]}, "a material stays evidence whatever threshold is configured"
    assert strict.assigned[ids["praxis"]][0].score >= 0.8
    assert "Material der Wissens-Sammlung" in result.assigned[ids["praxis"]][0].reasons


def test_section_smoothing_lets_paragraphs_under_one_heading_support_each_other() -> None:
    """Paragraphs of one section mostly belong to one block; measured 2026-09-18: fewer wrong paragraphs printed."""
    a = _chunk("a", "Anwendungen", "Erster Absatz des Abschnitts.")
    b = _chunk("b", "Anwendungen", "Zweiter Absatz des Abschnitts.")
    silent = _chunk("d", "Anwendungen", "Dritter Absatz ohne eigenes Signal.")
    other = _chunk("c", "Geschichte", "Absatz unter einer anderen Überschrift.")
    lead = _chunk("l", "Einleitung", "Der Einleitungsabsatz.", is_lead=True)
    fused = {
        "x": [
            ScoredChunk(chunk=a, score=0.9, matcher="fused"),
            ScoredChunk(chunk=lead, score=0.7, matcher="fused"),
            ScoredChunk(chunk=other, score=0.5, matcher="fused"),
            ScoredChunk(chunk=b, score=0.3, matcher="fused"),
        ]
    }
    chunks = [lead, a, b, silent, other]
    smoothed = smooth_sections(fused, chunks, 0.5)
    scores = {sc.chunk.chunk_id: sc.score for sc in smoothed["x"]}
    assert scores == {"a": 0.65, "l": 0.7, "c": 0.5, "b": 0.35}, (
        "group mean 0.4 over three paragraphs, one of them silent"
    )
    assert [sc.chunk.chunk_id for sc in smoothed["x"]] == ["l", "a", "c", "b"], "sorted by the new scores"
    assert "d" not in scores, "a paragraph without an own signal is not pulled in"
    assert smooth_sections(fused, chunks, 0.0) is fused


def test_below_the_confidence_threshold_a_topical_paragraph_takes_the_default_block() -> None:
    """With the stricter threshold the band 0.45 to 0.65 is no evidence; extraction=llm may still choose it."""
    template = TemplateManager().get("sc26")
    ids = {s.slot: s.id for s in template.slots}
    chunk = _chunk("z1", "Sonstiger Absatz", "Brillen und Kameras nutzen Linsen; die Branche beschäftigt Fachkräfte.")
    fused = {
        ids["praxis"]: [ScoredChunk(chunk=chunk, score=0.55, matcher="fused")],
        ids["beruf_wirtschaft"]: [ScoredChunk(chunk=chunk, score=0.5, matcher="fused")],
    }
    result = assign(template, [chunk], fused, SOURCES, confident_score=0.65)
    assert result.classified == {"z1": ids["fachinhalte"]}, "by rule it stays in the default block"
    assert result.slot_scores[ids["praxis"]]["z1"] > 0, "a candidate of the block for extraction=llm"
