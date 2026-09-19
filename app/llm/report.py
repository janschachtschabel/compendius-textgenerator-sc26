"""Audit block, token counts and frontmatter block of the LLM layer for one compendium (PLAN.md 7)."""

from __future__ import annotations

from typing import Any

from app.llm.gateway import LlmGateway
from app.llm.prompts import get_prompt
from app.matching.router import RoutingResult
from app.synthesis.writer import LlmReport


def build_llm_report(
    gateway: LlmGateway | None,
    generation_requested: str,
    generation_used: str,
    note: str | None,
    report: LlmReport | None,
    routing: RoutingResult | None,
) -> tuple[dict[str, Any] | None, dict[str, int] | None, dict[str, Any] | None]:
    """Audit block, token counts and frontmatter block of the LLM layer; all ``None`` for plain rule-based runs."""
    if generation_requested == "rule-based" and report is None:
        return None, None, None
    calls = (report.calls if report else 0) + (routing.calls if routing else 0)
    tokens: dict[str, int] | None = None
    if calls:
        tokens = {
            "prompt": (report.prompt_tokens if report else 0) + (routing.prompt_tokens if routing else 0),
            "completion": (report.completion_tokens if report else 0) + (routing.completion_tokens if routing else 0),
            "total": (report.total_tokens if report else 0) + (routing.total_tokens if routing else 0),
            "calls": calls,
        }
    if note is None and generation_used == "rule-based":
        note = "kein Baustein per LLM geschrieben; Regelmodus verwendet"
    generation: dict[str, Any] = {
        "requested": generation_requested,
        "used": generation_used,
        "sections": list(report.sections) if report else [],
        "fallbacks": dict(report.fallbacks) if report else {},
        "dropped_sentences": report.dropped_sentences if report else 0,
        "unsupported_sentences": report.unsupported_sentences if report else 0,
        "marked_sentences": report.marked_sentences if report else 0,
    }
    audit: dict[str, Any] = {
        "note": note,
        "generation": generation,
        "router": (
            {
                "considered": routing.considered,
                "routed": routing.routed,
                "moved": routing.moved,
                "calls": routing.calls,
                "skipped": routing.skipped,
            }
            if routing is not None
            else None
        ),
    }
    prompts = set(report.prompts) if report else set()
    if routing is not None and routing.calls:
        prompts.add(get_prompt("slot_router").tag)
    front: dict[str, Any] = {}
    if gateway is not None:
        front["provider"] = gateway.client.provider
        front["model"] = report.model if report and report.model else gateway.client.model
    front["prompts"] = sorted(prompts)
    front["generation"] = {"sections": generation["sections"], "fallbacks": generation["fallbacks"]}
    if note:
        front["note"] = note
    if routing is not None:
        front["router"] = {"considered": routing.considered, "routed": routing.routed, "moved": routing.moved}
    return audit, tokens, front
