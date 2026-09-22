"""What the endpoint asks for outside the question templates, and what it says when the answer is no.

Everything here can refuse: the two small models may not be in the image, the spaCy model the parse needs
may be missing, the b-api may be switched off or over budget, and a level the caller names may have no
counterpart in the project's own vocabulary. The three stages answer with ``None`` and a reason the
endpoint puts in ``note`` - falling back to the templates is the promise of this endpoint, so a missing
model is not an error. ``levels_from`` refuses loudly with 422 instead, because a made-up level would
travel on the pairs into a service that does not know it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fastapi import HTTPException, Request

from app.api.v2.qa_schemas import LEVEL_PROPERTY, MAX_TEXT_CHARS, QaRequest
from app.knowledge.recognise import load_spacy
from app.llm.deadline import Deadline
from app.synthesis.facets import bildungsstufe_facet
from app.synthesis.qa import QaPair
from app.synthesis.qa_models import answer_candidates, load_qa_models, model_pairs
from app.synthesis.qa_parse import parse_based_pairs


def from_models(request: Request, text: str, payload: QaRequest) -> tuple[list[QaPair] | None, str]:
    """The pairs of the two small models, or ``None`` and the reason the templates have to do it."""
    settings = request.app.state.settings
    models = load_qa_models(settings.qg_model_path, settings.qa_model_path)
    if models is None:
        return None, "QA-Modelle nicht im Image (QG_MODEL_PATH/QA_MODEL_PATH); Regelmodus verwendet"
    nlp = load_spacy(settings.spacy_model)
    if nlp is None:
        return None, "spaCy-Modell fehlt; ohne seine Nominalphrasen gibt es keine Antwortkandidaten"
    # Both the model and the splitter have to see the same string, so the offsets line up
    prepared = " ".join(text[:MAX_TEXT_CHARS].split())
    candidates = answer_candidates(nlp(prepared), prepared)
    pairs = model_pairs(candidates, models, count=payload.count, max_answer_length=payload.max_answer_length)
    if not pairs:
        return None, "Die Modelle fanden keine beantwortbare Frage; Regelmodus verwendet"
    return pairs, ""


def from_llm(request: Request, text: str, payload: QaRequest) -> tuple[list[QaPair] | None, str]:
    """The model's pairs, or ``None`` and the reason the templates have to do it."""
    service = request.app.state.service
    llm = service.llm if service is not None else None
    if llm is None:
        return None, "LLM nicht konfiguriert (LLM_ENABLED/B_API_KEY); Regelmodus verwendet"
    unavailable = service.llm_unavailable()
    if unavailable:
        return None, f"LLM nicht verfügbar: {unavailable}; Regelmodus verwendet"
    pairs = llm.qa.pairs(
        text,
        count=payload.count,
        max_answer_length=payload.max_answer_length,
        budget=llm.open_budget(),
        level_property=LEVEL_PROPERTY if payload.levels else None,
        level_values=payload.levels,
        deadline=Deadline(service.settings.request_timeout_s),
    )
    if pairs is None:
        return None, "LLM lieferte keine verwertbaren Paare; Regelmodus verwendet"
    return pairs, ""


def from_parse(request: Request, text: str, payload: QaRequest) -> tuple[list[QaPair] | None, str]:
    """The pairs of the dependency parse, or ``None`` and the reason the templates have to do it."""
    nlp = load_spacy(request.app.state.settings.spacy_model)
    if nlp is None:
        return None, "spaCy-Modell fehlt; ohne seinen Parse gibt es keine Satzsubjekte"
    pairs = parse_based_pairs(
        text[:MAX_TEXT_CHARS], limit=payload.count, max_answer_length=payload.max_answer_length, nlp=nlp
    )
    if not pairs:
        return None, "Der Parse fand kein Satzsubjekt zum Umstellen; Regelmodus verwendet"
    return pairs, ""


def levels_from(request: Request, levels: Sequence[str]) -> list[str]:
    """Map what the caller sent onto the project's own level values, or refuse it by name.

    The Bildungsstufe vocabulary (OpenEduHub) names a level as prefLabel ("Sekundarstufe I"), altLabel
    ("Sekundarstufe 1") or concept URI (".../educationalContext/sekundarstufe_1"); ``bildungsstufe_facet``
    reads all three, and the project's own values map to themselves. Four levels of that vocabulary -
    Schule, Förderschule, Fernunterricht, Informelles Lernen - have no counterpart in config/facets.yaml.
    They are refused by name rather than bent onto a neighbour, because a made-up level would travel on
    the pairs into a service that does not know it.
    """
    service = request.app.state.service
    declaration = service.facets.facets.get(LEVEL_PROPERTY) if service is not None else None
    if declaration is None or not declaration.values:
        raise HTTPException(
            status_code=422,
            detail=f"Stufenvokabular {LEVEL_PROPERTY} ist nicht konfiguriert (config/facets.yaml)",
        )
    mapped: list[str] = []
    unknown: list[str] = []
    for level in levels:
        value = bildungsstufe_facet(level)
        if value is not None and value in declaration.values:
            mapped.append(value)
        else:
            unknown.append(level)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unbekannte Stufen: {', '.join(unknown)}. "
                f"Erlaubt sind {', '.join(declaration.values)} sowie ihre Bezeichnungen und URIs "
                f"aus dem Vokabular {LEVEL_PROPERTY}"
            ),
        )
    return list(dict.fromkeys(mapped))


# The stages that can refuse, by the ``method`` that asks for them. rule-based is not here: it is what
# the endpoint falls back to, so it has no reason to be dispatched.
Stage = Callable[[Request, str, QaRequest], tuple[list[QaPair] | None, str]]
STAGES: dict[str, Stage] = {"parse-based": from_parse, "models": from_models, "llm": from_llm}
