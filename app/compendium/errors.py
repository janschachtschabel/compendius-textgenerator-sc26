"""The refusals of the compendium service and their messages; app.api.domain_errors answers each."""

from __future__ import annotations

from typing import Any

from app.domain.models import Resolution
from app.knowledge.node_article import NodeArticleReport, node_block
from app.knowledge.resolution import CHOSEN_BY_LLM


class PartsUnavailableError(RuntimeError):
    """None of the requested parts can be generated with the configuration of this server."""


class RepositoryUnavailableError(RuntimeError):
    """No repository to read a node or a collection from: none is configured and the request names none."""


class LlmNotConfiguredError(RuntimeError):
    """A profile or a switch needs an LLM, and this server has none configured (LLM_ENABLED, B_API_KEY; D53)."""


NO_REPOSITORY = "Kein Repository konfiguriert (EDU_SHARING_BASE_URL)"


NOT_FOUND = "Thema in den Archiven nicht gefunden"
NO_SUBJECT_TOPIC = "Das LLM sieht in diesem Material kein fachliches Thema; topic angeben"
NO_MATERIAL_ARTICLE = (
    "Zu diesem Material fanden die Regeln keinen Artikel: weder sein Titel noch die Begriffe aus Titel und "
    "Beschreibung führen zu einem; topic angeben, oder article_choice llm lässt das LLM das Thema bestimmen"
)
NO_ARTICLE_AFTER_LLM = "Zu diesem Material fanden weder das LLM noch die Regeln einen Artikel; topic angeben"
NO_FITTING_MEANING = (
    "Kein Artikel passt nach dem LLM zum Thema: ein Fach (subject) oder ein genaueres Thema angeben; "
    "resolution.alternatives nennt die verworfenen Artikel"
)


class TopicNotFoundError(LookupError):
    """No article for the request; ``node`` says how the article of a material was sought (D47).

    ``from_material``: the material alone was to name the article (no topic came along), so the message says why that
    failed and what to send instead.
    """

    def __init__(
        self, resolution: Resolution, node: NodeArticleReport | None = None, *, from_material: bool = False
    ) -> None:
        super().__init__(f"topic not found: {resolution.normalized}")
        self.resolution = resolution
        self.node = node
        self.from_material = from_material

    def detail(self) -> dict[str, Any]:
        """The body of the 404, alike for every endpoint: why, the resolution and, for a material, its search."""
        body: dict[str, Any] = {"message": NOT_FOUND, "resolution": self.resolution.model_dump()}
        if self.resolution.method == CHOSEN_BY_LLM:  # the LLM found that no candidate of the rules fits (A01)
            body["message"] = NO_FITTING_MEANING
        if self.node is not None:
            body["node_article"] = node_block(self.node)
            if self.from_material and self.node.named == "":
                body["message"] = NO_SUBJECT_TOPIC
            elif self.from_material:
                body["message"] = NO_ARTICLE_AFTER_LLM if self.node.calls else NO_MATERIAL_ARTICLE
        return body
