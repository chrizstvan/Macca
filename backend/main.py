"""Macca FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from backend.agents import (
    ContentCreatorAgent,
    FasilitatorHubAgent,
    ImpactAnalyzerAgent,
    MissionBriefingAgent,
    ProgressTrackerAgent,
    RouterAgent,
    VolunteerSupportAgent,
)
from backend.channels.telegram_handler import TelegramHandler
from backend.config import config
from backend.utils.scheduler import MaccaScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Agent registry                                                       #
# ------------------------------------------------------------------ #

_AGENTS: dict[str, Any] = {
    "mission_briefing": MissionBriefingAgent(),
    "progress_tracker": ProgressTrackerAgent(),
    "volunteer_support": VolunteerSupportAgent(),
    "content_creator": ContentCreatorAgent(),
    "impact_analyzer": ImpactAnalyzerAgent(),
    "fasilitator_hub": FasilitatorHubAgent(),
}

_router = RouterAgent()
_telegram = TelegramHandler()
_scheduler = MaccaScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _telegram.set_webhook()
    _scheduler.start()
    logger.info("Macca backend started")
    yield
    _scheduler.shutdown()
    logger.info("Macca backend stopped")


app = FastAPI(title="Macca", version="0.1.0", lifespan=lifespan)


# ------------------------------------------------------------------ #
# Routes                                                               #
# ------------------------------------------------------------------ #

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> JSONResponse:
    """Receive Telegram updates, route through the agent pipeline, and reply."""
    payload = await request.json()

    normalised = await _telegram.receive(payload)
    if not normalised or not normalised.get("message"):
        return JSONResponse(content={"ok": True})

    user_message = normalised["message"]
    chat_id = normalised["chat_id"]
    context = {
        "volunteer_id": normalised.get("user_id"),
        "username": normalised.get("username"),
    }

    # Route to the appropriate agent
    route = await _router.handle(user_message, context)
    intent: str = route["intent"]
    agent = _AGENTS.get(intent, _AGENTS["volunteer_support"])

    result = await agent.handle(user_message, context)

    # Extract the reply text (agents use different keys)
    reply = result.get("response") or result.get("briefing") or result.get("analysis") or result.get("content") or ""
    if not reply:
        reply = "I received your message and am processing it. A fasilitator will follow up shortly."

    await _telegram.send(chat_id, reply)

    # Forward escalations to the fasilitator
    if result.get("needs_escalation") or result.get("needs_human_followup"):
        escalation_msg = (
            f"*Escalation from @{normalised.get('username', 'unknown')}*\n"
            f"Message: {user_message}\n"
            f"Agent response: {reply}"
        )
        await _telegram.send(config.FASILITATOR_TELEGRAM_ID, escalation_msg)

    return JSONResponse(content={"ok": True, "intent": intent})


@app.post("/api/missions/{mission_id}/impact")
async def generate_impact_report(mission_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Trigger an impact analysis for a specific mission."""
    agent = _AGENTS["impact_analyzer"]
    result = await agent.handle(
        f"Generate an impact report for mission {mission_id}.",
        context={"mission_id": mission_id, "metrics": body.get("metrics", {})},
    )
    return result


@app.post("/api/content/create")
async def create_content(body: dict[str, Any]) -> dict[str, Any]:
    """Generate content given a brief and optional content type."""
    brief = body.get("brief", "")
    if not brief:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="'brief' is required")
    agent = _AGENTS["content_creator"]
    return await agent.handle(brief, context=body.get("context", {}))
