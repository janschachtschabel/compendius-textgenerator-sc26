"""What the LLM may do in a request: the switches that need one, its budget, the article choice and the
curriculum check (D35, D53, D58, D59), and what the audit says about the article choice.

A mixin of CompendiumService (app/service.py): it reads the service's ``llm``, ``settings`` and ``subjects``, so a
caller that swaps the gateway on the service swaps it here too.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.compendium.errors import LlmNotConfiguredError
from app.compendium.gateway import LlmGateway
from app.compendium.prepared import PreparedTopic
from app.domain.requests import BEST_QUALITY_PRESETS, LLM_ARTICLE_CHOICES, GenerateRequest, Preset, default_preset
from app.knowledge.article_choice import ArticleChoiceJob, ChoiceAudit, choice_used
from app.knowledge.curriculum_check import CurriculumCheckJob, CurriculumCheckReport, check_curriculum
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.matching.registry import LLM_MATCHER
from app.settings import Settings
from app.sources.lehrplan.matcher import CurriculumMatch
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.zim.registry import CHOSEN_BY_LLM


class LlmPolicy:
    llm: LlmGateway | None
    settings: Settings
    subjects: SubjectCatalog

    @property
    def default_preset(self) -> Preset:
        """The profile of a request that names none: PRESET_DEFAULT with an LLM, llm-free without one (D68)."""
        return default_preset(self.settings.preset_default, self.llm is not None)

    def refuse_without_llm(self, needed: Sequence[str], profile: str, defaulted: bool) -> None:
        """Refuse what needs an LLM when none is configured (D53); one that is only unavailable for now falls back.

        ``needed`` names the switches as name=value, ``profile`` the one in effect, ``defaulted`` whether the request
        named none. Then it runs llm-free whatever PRESET_DEFAULT says (D68), and only its own switches can need the
        LLM. The message names the setting that keeps the LLM away, as app.main.build_llm checks them.
        """
        if self.llm is not None or not needed:
            return
        if not self.settings.llm_enabled:
            missing = "LLM_ENABLED ist nicht aktiv"
        elif not self.settings.b_api_key:
            missing = "B_API_KEY ist leer"
        else:
            missing = "keine b-api-Adresse bekannt (B_API_BASE_URL, das Startlog nennt den Grund)"
        if defaulted:
            origin, advice = "Anfrage ohne Profil: ohne LLM gilt llm-free, D68", "Die Schalter auf rule-based setzen"
        else:
            origin, advice = f"Profil {profile}", "Profil llm-free wählen, die Schalter auf rule-based setzen"
        raise LlmNotConfiguredError(
            f"{missing}, aber {', '.join(needed)} braucht ein LLM ({origin}). {advice} oder LLM_ENABLED und "
            "B_API_KEY setzen"
        )

    def curriculum_check(
        self,
        topic: str,
        subjects: Sequence[str],
        budget: RequestBudget | None,
        deadline: Deadline | None,
        reports: list[CurriculumCheckReport],
    ) -> tuple[Callable[[list[CurriculumMatch]], list[CurriculumMatch]] | None, str | None]:
        """curriculum_check=llm (D58) as part 2 and the curriculum search call it, or ``None`` and why the rules decide
        instead.

        ``subjects`` are the ones the elements were narrowed to, as the request named them. The check appends what it
        did to ``reports``; it spends from the request's budget and time like the other LLM steps.
        """
        if self.llm is None:  # refused before any work (llm_switches); here only for a caller that skipped that
            return None, "LLM nicht konfiguriert (LLM_ENABLED, B_API_KEY); Regelmodus verwendet"
        unavailable = self.llm_unavailable()
        if unavailable is not None:
            return None, unavailable
        job = CurriculumCheckJob(
            client=self.llm.client,
            budget=budget if budget is not None else self.llm.open_budget(),
            topic=topic,
            subjects=self.subjects.labels_of(subjects),
            concurrency=self.llm.options.concurrency,
            deadline=deadline,
        )

        def check(matches: list[CurriculumMatch]) -> list[CurriculumMatch]:
            kept, report = check_curriculum(job, matches)
            reports.append(report)
            return kept

        return check, None

    def article_choice_job(
        self, requested: str | None, deadline: Deadline | None, budget: RequestBudget | None = None
    ) -> tuple[str, str | None, ArticleChoiceJob | None]:
        """The article choice in effect, why the LLM cannot make it, and the job when it can (D35, D53).

        ``requested`` is the switch of the request or of its profile. A server without an LLM has refused ``llm``
        before (refuse_without_llm), so a note here means the b-api is not available for now. ``budget`` is the one
        a caller shares over more than the compendium (/qa).
        """
        wanted = requested or "rule-based"
        if wanted not in LLM_ARTICLE_CHOICES:
            return wanted, None, None
        note = self.llm_unavailable()
        if note is not None or self.llm is None:
            return wanted, note, None
        opened = budget if budget is not None else self.llm.open_budget()
        return wanted, None, ArticleChoiceJob(self.llm.client, opened, deadline, thorough=wanted == "llm-thorough")

    def open_budget(self, profile: str) -> RequestBudget | None:
        """The token budget of one request in ``profile``; ``None`` without a configured LLM.

        The best-quality profiles spend from LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY: their LLM also checks the
        curriculum elements of part 2, and next to matcher llm the 60,000 tokens of the others covered only about
        400 of them (D59, M32).
        """
        if self.llm is None:
            return None
        large = profile in BEST_QUALITY_PRESETS
        return self.llm.open_budget(self.settings.llm_max_tokens_per_request_best_quality if large else None)

    def llm_unavailable(self) -> str | None:
        """Why an LLM switch cannot be used now (D3, D10), or ``None``: it needs a configured, available LLM."""
        if self.llm is None:
            return "LLM nicht konfiguriert (LLM_ENABLED, B_API_KEY); Regelmodus verwendet"
        if not self.llm.available:
            return f"LLM nicht verfügbar ({self.llm.unavailable_reason}); Regelmodus verwendet"
        return None


def choice_audit(prepared: PreparedTopic, requested: str) -> ChoiceAudit:
    """What the article choice of a prepared topic asked and decided (D35, D47), for the audit of a compendium and
    the answers of /knowledge and the curriculum search."""
    resolution, hit_check, node_report = prepared.resolution, prepared.hit_check, prepared.node_article
    articles = prepared.articles
    named_by_llm = node_report is not None and node_report.way == "llm"
    return ChoiceAudit(
        requested=requested,
        used=choice_used(resolution.method == CHOSEN_BY_LLM or named_by_llm, hit_check, articles),
        report=prepared.article_choice,
        chosen=resolution.title if resolution.method == CHOSEN_BY_LLM else None,
        # the model is asked for an unsure article (a chosen one stays unsure), for side articles and, with a topic,
        # for its articles (D63)
        needed=(
            not resolution.confident or prepared.side_articles > 0 or node_report is not None or articles is not None
        ),
        hit_check=hit_check,
        node=node_report,
        articles=articles,
    )


def llm_switches(request: GenerateRequest, *, corpus: bool) -> list[str]:
    """The switches of a request that need an LLM, as name=value (D53). ``corpus``: whether an article is chosen at
    all; the switches of part 1 count only when part 1 is asked for, curriculum_check only with part 2 (D58).
    enrichment needs none of its own: it only acts through generation."""
    choice = request.article_choice
    needed = [f"article_choice={choice}"] if corpus and choice in LLM_ARTICLE_CHOICES else []
    if "curricula" in request.parts and request.curriculum_check == "llm":
        needed.append("curriculum_check=llm")
    if "world" in request.parts:
        if request.matcher == LLM_MATCHER:
            needed.append("matcher=llm")
        if request.extraction == "llm":
            needed.append("extraction=llm")
        if request.generation not in (None, "rule-based"):
            needed.append(f"generation={request.generation}")
    return needed
