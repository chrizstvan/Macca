"""Router agent that classifies incoming messages and delegates to the correct agent."""

from typing import Any

from .base_agent import BaseAgent


INTENT_MAP = {
    "mission_briefing": "mission",
    "progress_tracker": "progress",
    "volunteer_support": "support",
    "content_creator": "content",
    "impact_analyzer": "impact",
    "fasilitator_hub": "fasilitator",
}


class RouterAgent(BaseAgent):
    """Determines which specialist agent should handle a given user message.

    Sends the message to Claude with a routing system prompt and parses the
    returned intent label to select the next agent in the pipeline.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are a routing assistant for a volunteer coordination platform called Macca. "
            "Classify the user's intent into exactly one of these labels and reply with only "
            "that label, no punctuation:\n"
            "mission_briefing, progress_tracker, volunteer_support, "
            "content_creator, impact_analyzer, fasilitator_hub"
        )

    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Classify message intent and return the target agent name."""
        raw = self._call_claude(message).strip().lower()
        intent = raw if raw in INTENT_MAP else "volunteer_support"
        return {"intent": intent, "original_message": message, "context": context or {}}
