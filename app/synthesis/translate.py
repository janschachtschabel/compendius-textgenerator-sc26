"""Translation for the legacy utility endpoint (PLAN.md 8.1): only with an LLM, and never a faked answer.

The old service answered "[en translation of]: <original>" when the model failed, so a caller could not tell a
translation from a failure. Here the caller gets the translation or a status code.
"""

from __future__ import annotations

from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt

CHARS_PER_TOKEN = 3  # German text; the answer may be longer than the source, so the limit is generous
MIN_OUTPUT_TOKENS = 200


class LlmTranslator:
    def __init__(self, client: BApiClient) -> None:
        self.client = client

    def translate(
        self, text: str, target_lang: str, *, budget: RequestBudget, deadline: Deadline | None = None
    ) -> str | LlmSkipped:
        """The translation, or why there is none; an empty answer counts as a failure, not as an empty translation."""
        messages = get_prompt("translate").render(text=text, target_lang=target_lang)
        max_output = max(MIN_OUTPUT_TOKENS, len(text) // CHARS_PER_TOKEN + MIN_OUTPUT_TOKENS)
        answer = budgeted_chat(
            self.client, messages, max_output_tokens=max_output, budget=budget, what="translate", deadline=deadline
        )
        if isinstance(answer, LlmSkipped):
            return answer
        translation = answer.text.strip()
        if not translation:
            return LlmSkipped.after(f"leere Antwort des Modells (finish_reason={answer.finish_reason})", answer)
        return translation
