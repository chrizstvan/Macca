"""Router agent that classifies message intent and delegates to a specialist agent."""

import logging

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

ROUTING_PROMPT = (
    "You are a routing assistant for Macca, a volunteer coordination platform for waste "
    "collection missions. Volunteers report collections (e.g. 'laporan 18 kg menteng'), "
    "ask questions, and check status. Classify the user's message into exactly one of "
    "these labels and reply with only that label, nothing else:\n"
    "mission_briefing - questions about mission details, objectives, deadlines, assignments\n"
    "progress_tracker - collection reports (laporan), status checks, progress updates\n"
    "volunteer_support - general questions, help requests, onboarding, logistics\n"
    "content_creator - requests to draft posts, stories, or campaign content\n"
    "impact_analyzer - requests for impact data, totals, or analysis\n"
    "fasilitator_hub - fasilitator operations: team summaries, escalations, broadcasts"
)


class RouterAgent(BaseAgent):
    """Classifies intent with a cheap Claude call, then delegates to the matching agent."""

    def __init__(self, agents: dict[str, BaseAgent]) -> None:
        super().__init__(
            name="router",
            description="Classifies message intent and dispatches to specialist agents",
        )
        self._agents = agents
        self.last_agent: str = "router"

    async def route(self, message: str, context: dict) -> str:
        """Public entry point used by the channel handler."""
        return await self.process(message, context)

    async def process(self, message: str, context: dict) -> str:
        """Classify the message and return the delegated agent's reply."""
        label = await self.call_claude(
            ROUTING_PROMPT,
            [{"role": "user", "content": message}],
            max_tokens=20,
        )
        intent = label.strip().lower()
        agent = self._agents.get(intent)
        if agent is None:
            logger.warning("Unknown intent %r, falling back to volunteer_support", intent)
            agent = self._agents["volunteer_support"]

        self.last_agent = agent.name
        logger.info("Routing message to %s", agent.name)
        return await agent.process(message, context)
