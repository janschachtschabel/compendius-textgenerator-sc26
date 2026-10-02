"""Part 1 of a compendium: match the chunks to the blocks, let the LLM choose sentences and write blocks as the
switches ask (D33, D34), keep the blocks of an earlier text (PLAN.md 4.6).

A mixin of CompendiumService (app/service.py) on top of LlmPolicy: it reads the service's ``llm``, ``settings`` and
``writer``.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from app.compendium.llm_policy import LlmPolicy
from app.compendium.prepared import Matched, PreparedTopic, Requested, Stopwatch, WorldPart
from app.compose.kept_sources import attribute
from app.compose.regeneration import PreservedSection, UnplacedSectionsError, parse_document, to_keep
from app.domain.models import ScoredChunk
from app.domain.requests import GenerateRequest
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.matching.fusion import smooth_sections
from app.matching.llm_assignment import MATCHER as LLM_ASSIGNED
from app.matching.llm_assignment import AssignmentJob, assign_with_llm
from app.matching.policy import AssignmentResult, assign
from app.matching.registry import LLM_MATCHER, LOCAL_MATCHER, get_matcher
from app.synthesis.extraction import Extracted, ExtractionJob, ExtractionReport, extract_with_llm
from app.synthesis.writer import LlmJob, SectionWriter
from app.templates.schema import Template, TemplateSlot


class WorldBuilding(LlmPolicy):
    writer: SectionWriter

    def match(
        self,
        prepared: PreparedTopic,
        matcher_name: str | None,
        target_length: int,
        *,
        budget: RequestBudget | None = None,
        deadline: Deadline | None = None,
    ) -> Matched:
        """Score and assign the prepared chunks with one matching strategy.

        ``llm`` runs the default strategy and lets the model decide on top (D34); ``budget`` and ``deadline`` bound
        its calls, and a budget of its own is opened when none is given (evaluation).
        """
        name = matcher_name or LOCAL_MATCHER
        if name == LLM_MATCHER:
            return self._match_with_llm(prepared, target_length, budget, deadline)
        started = time.perf_counter()
        matcher = get_matcher(name, self.settings.model2vec_path)
        fused = matcher.score(prepared.template.slots, prepared.chunks)
        fused = smooth_sections(fused, prepared.chunks, self.settings.policy_section_smoothing)
        assignment = self._assign(prepared, fused, target_length)
        duration_ms = int((time.perf_counter() - started) * 1000)
        return Matched(matcher=name, assignment=assignment, duration_ms=duration_ms)

    def _match_with_llm(
        self, prepared: PreparedTopic, target_length: int, budget: RequestBudget | None, deadline: Deadline | None
    ) -> Matched:
        """matcher=llm: the local strategy decides first; without a usable LLM its result is the answer."""
        started = time.perf_counter()
        base = self.match(prepared, LOCAL_MATCHER, target_length)
        if self.llm is None or self.llm_unavailable() is not None:
            return base
        job = AssignmentJob(
            client=self.llm.client,
            budget=budget if budget is not None else self.llm.open_budget(),
            topic=prepared.prompt_topic,
            concurrency=self.llm.options.concurrency,
            deadline=deadline,
        )
        template = scale_budgets(prepared.template, target_length)
        assignment, report = assign_with_llm(template, prepared.chunks, prepared.sources_by_id, base.assignment, job)
        duration_ms = int((time.perf_counter() - started) * 1000)
        matcher = LLM_MATCHER if report.answered else base.matcher
        return Matched(matcher=matcher, assignment=assignment, duration_ms=duration_ms, llm=report)

    def _assign(
        self,
        prepared: PreparedTopic,
        scores: dict[str, list[ScoredChunk]],
        target_length: int,
    ) -> AssignmentResult:
        return assign(
            scale_budgets(prepared.template, target_length),
            prepared.chunks,
            scores,
            prepared.sources_by_id,
            confident_score=self.settings.policy_confident_score,
        )

    def _facets_visible(self, request: GenerateRequest) -> bool:
        return self.settings.facets_visible if request.facets_visible is None else request.facets_visible

    def _world_part(
        self,
        prepared: PreparedTopic,
        request: GenerateRequest,
        requested: Requested,
        deadline: Deadline,
        timings: dict[str, int],
        shared_budget: RequestBudget | None = None,
    ) -> WorldPart:
        """Part 1: match the chunks (with matcher=llm the model assigns them, D34), let the LLM choose sentences and
        write blocks as the switches ask (D33).

        ``requested`` holds the extraction, the generation and the enrichment switch; without a usable LLM
        the first two run rule-based and nothing is enriched. ``shared_budget`` is the request's budget when the
        article choice opened it already or the caller brought one (/qa).
        """
        extraction_wanted, generation_wanted = requested.extraction, requested.generation
        enrichment_wanted = requested.enrichment
        matcher_wanted = request.matcher or LOCAL_MATCHER
        wants_llm = (
            extraction_wanted != "rule-based" or generation_wanted != "rule-based" or matcher_wanted == LLM_MATCHER
        )
        llm_note = self.llm_unavailable() if wants_llm else None
        extraction, generation = ("rule-based", "rule-based") if llm_note else (extraction_wanted, generation_wanted)
        enrichment = "sources-only" if generation == "rule-based" else enrichment_wanted
        llm = self.llm if wants_llm and llm_note is None else None
        # one budget for all LLM work of the request
        budget = (shared_budget or llm.open_budget()) if llm is not None else None
        matched = self.match(prepared, request.matcher, request.target_length, budget=budget, deadline=deadline)
        timings["match"] = matched.duration_ms
        lap = Stopwatch(timings).lap

        # The scaled budgets carry ``target_length`` into the LLM prompts (target characters, output limit).
        template = scale_budgets(prepared.template, request.target_length)
        # D69, D72: a text the LLM writes is about the topic as asked, its qualifiers included, or the model's wording
        # of a text in its place - not about the article it resolved to (prepare); full mode fills every block
        full = enrichment == "model-knowledge-full"
        topic = prepared.prompt_topic
        assigned: Mapping[str, Sequence[ScoredChunk]] = matched.assignment.assigned
        selected: set[str] = set()
        extracted: ExtractionReport | None = None
        if extraction == "llm" and budget is not None:
            result = self.extract(prepared, matched, request.target_length, budget=budget, deadline=deadline)
            if result is not None:
                assigned, selected, extracted = result.assigned, result.selected, result.report
            lap("extract")

        sources, primary = prepared.sources, prepared.primary
        llm_job: LlmJob | None = None
        if generation != "rule-based" and llm is not None and budget is not None:
            llm_job = LlmJob(
                synthesizer=llm.synthesizer,
                budget=budget,
                slots=llm.generation_slots(generation, (slot.id for slot in template.content_slots())),
                topic=topic,
                concurrency=llm.options.concurrency,
                deadline=deadline,
                enrich=enrichment in ("model-knowledge", "model-knowledge-full"),
                full=full,
                article=prepared.title,
                check=requested.model_knowledge_check == "llm",
            )
        preserved = self._preserved(request, template)
        attribution = attribute(preserved, request.existing_markdown or "", sources)
        ai_assigned = {  # blocks holding paragraphs the model assigned: marked as chosen by an AI
            slot_id
            for slot_id, items in matched.assignment.assigned.items()
            if any(item.matcher == LLM_ASSIGNED for item in items)
        }
        written = self.writer.write(
            template,
            assigned,
            sources,
            prepared.sources_by_id,
            self._facets_visible(request),
            primary,
            prepared.lexicon,
            llm=llm_job,
            selected=selected,
            ai_assigned=ai_assigned,
            preserved=attribution.kept,
            carried=attribution.carried,
            lookup=prepared.registry.lookup if prepared.registry is not None else None,
        )
        lap("synthesize")
        return WorldPart(
            matcher=matched.matcher,
            matcher_requested=matcher_wanted,
            extraction=extraction,
            generation=generation,
            enrichment=enrichment,
            llm_note=llm_note,
            topic=topic if llm_job is not None else "",
            chunks_assigned=sum(len(v) for v in assigned.values()),
            extracted=extracted,
            written=written,
            matching=matched.llm,
            carried=attribution.carried,
            unattributed=attribution.unattributed,
            regenerated=(
                [slot.id for slot in template.content_slots() if slot.id not in preserved]
                if request.existing_markdown
                else []
            ),
        )

    def extract(
        self,
        prepared: PreparedTopic,
        matched: Matched,
        target_length: int,
        *,
        budget: RequestBudget | None = None,
        deadline: Deadline | None = None,
    ) -> Extracted | None:
        """extraction=llm on matched chunks (D33): the LLM's choice per block; ``None`` without a configured LLM.

        The caller checks ``llm_unavailable`` first; a budget of its own is opened when none is given (evaluation).
        """
        if self.llm is None:
            return None
        job = ExtractionJob(
            selector=self.llm.selector,
            budget=budget if budget is not None else self.llm.open_budget(),
            topic=prepared.prompt_topic,
            candidates=self.llm.options.extraction_candidates,
            concurrency=self.llm.options.concurrency,
            deadline=deadline,
        )
        template = scale_budgets(prepared.template, target_length)  # the prompts name the target length
        return extract_with_llm(template, matched.assignment, prepared.chunks, prepared.sources_by_id, job)

    def _preserved(self, request: GenerateRequest, template: Template) -> dict[str, PreservedSection]:
        """Blocks of an earlier compendium that stay word for word (PLAN.md 4.6); generated blocks never do."""
        if not request.existing_markdown:
            return {}
        keep = to_keep(parse_document(request.existing_markdown), request.regenerate_sections)
        ids = [slot.id for slot in template.slots]
        unplaced = [f"{slot_id} ({section.status.value})" for slot_id, section in keep.items() if slot_id not in ids]
        if unplaced:  # another template dropped them without a word (audit 2026-09-29, T5)
            raise UnplacedSectionsError(unplaced, template.id, ids)
        content = {slot.id for slot in template.content_slots()}
        return {slot_id: section for slot_id, section in keep.items() if slot_id in content}


def scale_budgets(template: Template, target_length: int) -> Template:
    """Distribute the requested total length over the content slots by weight."""
    content = template.content_slots()
    total_weight = sum(s.budget.weight for s in content) or 1.0
    scaled: list[TemplateSlot] = []
    for slot in template.slots:
        if slot.is_generated:
            scaled.append(slot)
            continue
        share = int(target_length * slot.budget.weight / total_weight)
        budget = slot.budget.model_copy(update={"target_chars": max(300, share)})
        scaled.append(slot.model_copy(update={"budget": budget}))
    return template.model_copy(update={"slots": scaled})
