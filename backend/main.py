"""Macca FastAPI application: Telegram webhook entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update

from backend.channels.telegram_handler import create_application, init_agents
from backend.config import settings
from backend.database.supabase_client import db, test_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

application = create_application()
bot_state = {"username": ""}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize all agent instances
    init_agents()

    # 2. Verify Supabase connection
    if not await test_connection():
        logger.warning("Supabase connection check failed — continuing anyway")

    # 3-4. Start the bot, set the webhook, and cache the bot username
    await application.initialize()
    await application.start()

    webhook_url = f"{settings.webhook_url.rstrip('/')}/webhook"
    await application.bot.set_webhook(
        url=webhook_url,
        allowed_updates=["message", "edited_message"],
    )
    me = await application.bot.get_me()
    bot_state["username"] = me.username or ""

    # 5. Announce
    logger.info("Bot @%s is live. Webhook set to %s", bot_state["username"], webhook_url)

    yield

    await application.stop()
    await application.shutdown()
    logger.info("Macca backend stopped")


app = FastAPI(title="Macca", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    """Receive a Telegram Update JSON payload and dispatch it to the bot handlers."""
    payload = await request.json()
    update = Update.de_json(payload, application.bot)
    if update:
        await application.process_update(update)
    return {"ok": True}


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "agents": "all_running",
        "bot_username": bot_state["username"],
    }


@app.get("/dashboard/stats")
async def dashboard_stats() -> dict:
    """Aggregate stats for the dashboard."""
    volunteers = db.table("volunteers").select("id", count="exact").execute()
    active_missions = (
        db.table("missions").select("id", count="exact").eq("status", "active").execute()
    )
    reports = db.table("reports").select("kg_collected, is_flagged, verified").execute()
    rows = reports.data or []

    return {
        "total_volunteers": volunteers.count or 0,
        "active_missions": active_missions.count or 0,
        "total_reports": len(rows),
        "total_kg_collected": round(sum(float(r["kg_collected"]) for r in rows), 2),
        "flagged_reports": sum(1 for r in rows if r.get("is_flagged")),
        "verified_reports": sum(1 for r in rows if r.get("verified")),
    }
