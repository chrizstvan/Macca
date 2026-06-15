"""Macca FastAPI application: Telegram webhook entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update

from backend.agents import progress_tracker as progress_tracker_module
from backend.agents.progress_tracker import ProgressTrackerAgent, cleanup_expired_pending
from backend.infrastructure.composition_root import (
    build_send_weekly_plastic_fact,
    build_send_weekly_quiz,
)
from backend.utils.ranking_calculator import RankingCalculator
from backend.channels.telegram_handler import create_application, init_agents
from backend.channels.whatsapp_handler import WhatsAppHandler
from backend.config import settings
from backend.database.supabase_client import db, test_connection
from backend.utils.scheduler import SchedulerManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

application = create_application()
bot_state = {"username": ""}
scheduler = SchedulerManager()
form_tracker = ProgressTrackerAgent()
whatsapp_handler = WhatsAppHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize all agent instances
    router = init_agents()
    whatsapp_handler.router = router

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

    # 5. Periodic jobs (cron times are system-local; deploy host runs WIB).
    scheduler.add_interval_job(
        cleanup_expired_pending, minutes=5, job_id="cleanup_pending_reports"
    )
    scheduler.add_cron_job(
        RankingCalculator().update_all_rankings,
        "0 23 * * *",
        job_id="daily_ranking_refresh",
    )

    async def _weekly_plastic_fact_job() -> None:
        await build_send_weekly_plastic_fact().execute()

    async def _weekly_quiz_job() -> None:
        await build_send_weekly_quiz().execute()

    # Mon 07:30 WIB — plastic-education broadcast
    scheduler.add_cron_job(
        _weekly_plastic_fact_job,
        "30 7 * * 1",
        job_id="weekly_plastic_fact",
    )
    # Wed 12:00 WIB — quiz broadcast (creates active_quiz row w/ 24h TTL)
    scheduler.add_cron_job(
        _weekly_quiz_job,
        "0 12 * * 3",
        job_id="weekly_plastic_quiz",
    )
    # Default cron jobs (daily_reminder 18:00, morning_briefing 07:00,
    # daily_content 20:00, weekly_report Mon 08:00) — see SchedulerManager.
    scheduler.start(default_jobs=True)

    # 6. Announce
    logger.info("Bot @%s is live. Webhook set to %s", bot_state["username"], webhook_url)

    yield

    scheduler.shutdown(wait=False)
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


@app.post("/webhook/google-form")
async def google_form_webhook(request: Request) -> dict:
    """Receive a Google Form submission (relayed by Apps Script) and record the report."""
    payload = await request.json()
    phone = str(payload.get("phone") or "").strip()

    result = db.table("volunteers").select("*").eq("phone", phone).limit(1).execute()
    volunteer = result.data[0] if result.data else None
    if volunteer is None:
        await progress_tracker_module._alert_fasilitator(
            f"⚠️ Google Form dari nomor tidak dikenal: {phone} — laporan tidak disimpan."
        )
        return {"status": "unknown_volunteer"}

    # Accept both the simple relay keys and the original form field names
    form_data = dict(payload)
    if payload.get("kg") is not None:
        form_data.setdefault("Kg", payload["kg"])
    if payload.get("location"):
        form_data.setdefault("Lokasi", payload["location"])

    context = {
        "source": "google_form",
        "form_data": form_data,
        "volunteer": volunteer,
        "telegram_id": volunteer.get("telegram_id"),
    }
    confirmation = await form_tracker.process("", context)
    return {"status": "ok", "confirmation": confirmation}


@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request) -> Response:
    """Meta webhook verification handshake.

    Meta sends ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    We echo back the challenge as plain text iff the token matches.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("WhatsApp webhook verified")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("WhatsApp verify rejected: mode=%r token_match=%s", mode, token == settings.whatsapp_verify_token)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> dict:
    """Receive a WhatsApp Cloud API event and dispatch any inbound message.

    We ack 200 immediately, then dispatch in the background. Meta's webhook
    contract expects a response in under ~20 s — slow Sonnet calls
    (impact_analyzer, content_creator, fasilitator_hub) blow past that and
    cause Meta to retry, which used to result in the same report being
    generated 2-3 times.
    """
    import asyncio as _asyncio

    payload = await request.json()

    async def _dispatch() -> None:
        try:
            await whatsapp_handler.handle_incoming(payload)
        except Exception as exc:
            logger.exception("WhatsApp handle_incoming failed: %s", exc)

    _asyncio.create_task(_dispatch())
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
