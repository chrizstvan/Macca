"""Content creator agent that generates social media posts, reports, and campaign material."""

from typing import Any

from .base_agent import BaseAgent


CONTENT_TYPES = ("social_post", "impact_report", "volunteer_story", "campaign_update", "newsletter")


class ContentCreatorAgent(BaseAgent):
    """Generates campaign and communication content for Macca missions.

    Accepts a content brief via message and an optional content_type in context.
    Returns polished, platform-appropriate copy ready for review or publishing.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Content Creator for Macca, a volunteer coordination platform. "
            "Write compelling, authentic content that highlights volunteer impact and mission outcomes. "
            "Adapt tone and length to the content type requested: "
            "social posts should be punchy and shareable, "
            "impact reports should be data-focused and professional, "
            "volunteer stories should be personal and inspiring. "
            "Avoid jargon. Always include a clear call-to-action where appropriate."
        )

    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate content based on the provided brief."""
        ctx = context or {}
        content_type = ctx.get("content_type", "social_post")
        if content_type not in CONTENT_TYPES:
            content_type = "social_post"

        extra = (
            f"Content type: {content_type}. "
            f"Mission: {ctx.get('mission_name', 'general')}. "
            f"Target platform: {ctx.get('platform', 'Telegram/social media')}."
        )

        content = self._call_claude(message, extra_system=extra)
        return {
            "agent": "content_creator",
            "content": content,
            "content_type": content_type,
            "mission_id": ctx.get("mission_id"),
        }
