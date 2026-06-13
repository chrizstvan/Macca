"""Router agent: classifies every incoming message and delegates to a specialist agent."""

import logging

from .base_agent import BaseAgent
from .content_creator import ContentCreatorAgent
from .fasilitator_hub import FasilitatorHubAgent
from .impact_analyzer import ImpactAnalyzerAgent
from .mission_briefing import MissionBriefingAgent
from .progress_tracker import ProgressTrackerAgent, has_pending_report
from .prompts.router import CLASSIFICATION_PROMPT
from .volunteer_support import VolunteerSupportAgent

logger = logging.getLogger(__name__)

DEFAULT_INTENT = "volunteer_support"

# fasilitator_hub is intentionally absent: it is reachable only via the
# telegram_id check in process(), never via classification.
VALID_INTENTS = (
    "mission_briefing",
    "progress_tracker",
    "volunteer_support",
    "content_creator",
    "impact_analyzer",
)


class RouterAgent(BaseAgent):
    """Classifies intent with a cheap Haiku call, then delegates to the matching agent."""

    def __init__(self, agents: dict[str, BaseAgent] | None = None) -> None:
        super().__init__(
            name="router",
            description="Classifies message intent and dispatches to specialist agents",
        )
        self._agents = agents or {
            "mission_briefing": MissionBriefingAgent(),
            "progress_tracker": ProgressTrackerAgent(),
            "volunteer_support": VolunteerSupportAgent(),
            "content_creator": ContentCreatorAgent(),
            "impact_analyzer": ImpactAnalyzerAgent(),
            "fasilitator_hub": FasilitatorHubAgent(),
        }
        self.last_agent: str = self.name

    async def process(self, message: str, context: dict) -> str:
        """Classify the message and return the intent category string."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)

        # 1. Fasilitator always goes to the fasilitator hub
        if context["is_fasilitator"]:
            return "fasilitator_hub"

        # 1b. A volunteer mid-report (pending kg/location/confirmation) skips
        #     classification — their reply belongs to the progress tracker
        if has_pending_report(context.get("telegram_id")):
            return "progress_tracker"

        # 2-3. Classify with Claude Haiku and normalise the label
        label = await self.call_claude(
            CLASSIFICATION_PROMPT,
            [{"role": "user", "content": message}],
            max_tokens=20,
        )
        intent = label.strip().lower()

        # 4. Unknown labels (including fasilitator_hub for non-fasilitators)
        #    fall back to volunteer_support
        if intent not in VALID_INTENTS:
            logger.warning("Invalid intent %r, defaulting to %s", intent, DEFAULT_INTENT)
            intent = DEFAULT_INTENT

        # 5. Return the category string
        return intent

    async def route(self, message: str, context: dict) -> str:
        """Classify, delegate to the matching agent, and return its response."""
        intent = await self.process(message, context)
        agent = self._agents[intent]
        self.last_agent = agent.name
        logger.info("Routing message to %s", agent.name)
        return await agent.process(message, context)
