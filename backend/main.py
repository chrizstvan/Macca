"""Macca FastAPI application: Telegram webhook entry point."""

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Header, HTTPException, Request, Response
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
    allow_origins=settings.cors_allow_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.post("/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Receive a Telegram Update JSON payload and dispatch it to the bot handlers."""
    _verify_webhook_secret(
        secret=settings.telegram_webhook_secret,
        provided=x_telegram_bot_api_secret_token,
        label="Telegram",
    )
    payload = await request.json()
    update = Update.de_json(payload, application.bot)
    if update:
        await application.process_update(update)
    return {"ok": True}


@app.post("/webhook/google-form")
async def google_form_webhook(
    request: Request,
    x_form_secret: str | None = Header(default=None),
) -> dict:
    """Receive a Google Form submission (relayed by Apps Script) and record the report."""
    _verify_webhook_secret(
        secret=settings.google_form_secret,
        provided=x_form_secret,
        label="Google Form",
    )
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
async def whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    """Receive a WhatsApp Cloud API event and dispatch any inbound message.

    We verify Meta's ``X-Hub-Signature-256`` HMAC over the raw body, then ack
    200 immediately and dispatch in the background. Meta's webhook contract
    expects a response in under ~20 s — slow Sonnet calls (impact_analyzer,
    content_creator, fasilitator_hub) blow past that and cause Meta to retry,
    which used to result in the same report being generated 2-3 times.
    """
    import asyncio as _asyncio

    raw = await request.body()
    secret = settings.whatsapp_app_secret
    if secret:
        expected = "sha256=" + hmac.new(
            secret.encode(), raw, hashlib.sha256
        ).hexdigest()
        if not x_hub_signature_256 or not hmac.compare_digest(
            x_hub_signature_256, expected
        ):
            logger.warning("WhatsApp webhook signature rejected")
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
    elif _is_production():
        logger.error(
            "WHATSAPP_APP_SECRET not configured in production — webhook unverified"
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

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


# --------------------------------------------------------------------------- #
# Admin endpoints — driven by the Streamlit dashboard. Thin wrappers over     #
# existing services / use cases; no business logic lives here.                 #
# --------------------------------------------------------------------------- #


def _is_production() -> bool:
    return settings.environment == "production"


def _require_admin(authorization: str | None) -> None:
    """Validate the admin bearer token (constant-time).

    Fail-closed in production: a missing ``ADMIN_TOKEN`` there refuses the
    request rather than serving it openly. In development an empty token
    leaves the endpoint open for localhost convenience.
    """
    expected = getattr(settings, "admin_token", "") or ""
    if not expected:
        if _is_production():
            raise HTTPException(
                status_code=503, detail="Admin endpoints disabled: ADMIN_TOKEN not set"
            )
        return  # dev only
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    provided = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid admin token")


def _verify_webhook_secret(
    *, secret: str, provided: str | None, label: str
) -> None:
    """Enforce a webhook shared secret with a constant-time compare.

    When ``secret`` is set, a missing/mismatched value raises 403. When it is
    unset we allow the request (dev), but in production log an error so the
    gap is visible — webhook secrets must be configured for prod.
    """
    if not secret:
        if _is_production():
            logger.error(
                "%s webhook secret not configured in production — request unverified",
                label,
            )
        return
    if not provided or not hmac.compare_digest(provided, secret):
        logger.warning("%s webhook signature/secret rejected", label)
        raise HTTPException(status_code=403, detail="Invalid webhook signature")


@app.post("/admin/reminders/send")
async def admin_reminders_send(
    payload: dict = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
) -> dict:
    """Trigger reminders. Body: ``{volunteer_ids: [...], only_non_reporters: bool}``."""
    _require_admin(authorization)

    from datetime import datetime, timezone
    from backend.agents.fasilitator_hub import REMIND_TEMPLATES
    from backend.agents.services.notifications import notify_volunteer

    volunteer_ids: list[str] = list(payload.get("volunteer_ids") or [])
    only_non_reporters = bool(payload.get("only_non_reporters"))

    query = db.table("volunteers").select(
        "id, name, area, quota_kg, phone, telegram_id"
    ).eq("is_active", True)
    if volunteer_ids:
        query = query.in_("id", volunteer_ids)
    rows = query.execute().data or []

    if only_non_reporters and rows:
        today = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        reported_ids = {
            r["volunteer_id"]
            for r in (
                db.table("reports")
                .select("volunteer_id")
                .gte("reported_at", today)
                .execute()
                .data
                or []
            )
        }
        rows = [v for v in rows if v["id"] not in reported_ids]

    template = REMIND_TEMPLATES["progress"]
    dispatched = 0
    for v in rows:
        reported_total = sum(
            float(r.get("kg_collected") or 0)
            for r in (
                db.table("reports")
                .select("kg_collected")
                .eq("volunteer_id", v["id"])
                .execute()
                .data
                or []
            )
        )
        text = template.format(
            name=v.get("name") or "Volunteer",
            arg="",
            area=v.get("area") or "-",
            quota_kg=float(v.get("quota_kg") or 0),
            reported_kg=reported_total,
        )
        try:
            await notify_volunteer(v, text)
            dispatched += 1
        except Exception as exc:
            logger.warning("admin reminder to %s failed: %s", v.get("name"), exc)
    return {"dispatched": dispatched, "selected": len(rows)}


@app.post("/admin/broadcast")
async def admin_broadcast(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
) -> dict:
    """Body: ``{message: str, channel: 'whatsapp'|'telegram'|'both'|None}``."""
    _require_admin(authorization)

    from backend.agents.services.notifications import notify_volunteer

    message = (payload.get("message") or "").strip()
    if len(message) < 5:
        raise HTTPException(status_code=400, detail="Message too short (min 5 chars)")
    requested_channel = payload.get("channel")
    if requested_channel and requested_channel not in {"whatsapp", "telegram", "both"}:
        raise HTTPException(status_code=400, detail="Invalid channel")

    # Temporary override of active_channel for the broadcast duration.
    original = settings.active_channel
    if requested_channel:
        settings.active_channel = requested_channel
    try:
        rows = (
            db.table("volunteers")
            .select("id, name, phone, telegram_id")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        dispatched = 0
        for v in rows:
            try:
                await notify_volunteer(v, message)
                dispatched += 1
            except Exception as exc:
                logger.warning("broadcast to %s failed: %s", v.get("name"), exc)
        return {"dispatched": dispatched, "recipients": len(rows)}
    finally:
        settings.active_channel = original


@app.post("/admin/rankings/recalculate")
async def admin_rankings_recalculate(
    authorization: str | None = Header(default=None),
) -> dict:
    """Trigger ``RankingCalculator.update_all_rankings()``."""
    _require_admin(authorization)

    try:
        await RankingCalculator().update_all_rankings()
    except Exception as exc:
        logger.exception("ranking recalc failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"recalc failed: {exc}") from exc
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Content / quiz / impact generators (dashboard tab 6)                          #
# --------------------------------------------------------------------------- #


def _anthropic_client():
    """Lazy AsyncAnthropic factory — saves one import on every cold path."""
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


@app.post("/admin/content/generate")
async def admin_generate_content(
    payload: dict = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
) -> dict:
    """Body: ``{topic, tone, audience}`` → returns ``{content}`` (Indonesian)."""
    _require_admin(authorization)

    topic = (payload.get("topic") or "Fakta plastik mingguan").strip()
    tone = (payload.get("tone") or "Semangat").strip()
    audience = (payload.get("audience") or "Semua volunteer").strip()

    system = (
        "Kamu adalah penulis konten edukasi lingkungan untuk program "
        "pengumpulan plastik di Indonesia. Bahasa Indonesia santai, "
        "ramah, konkret. 60-120 kata, siap di-broadcast ke WhatsApp."
    )
    user = (
        f"Buat konten singkat untuk volunteer dengan:\n"
        f"- Topik: {topic}\n"
        f"- Tone: {tone}\n"
        f"- Audience: {audience}\n\n"
        "Sertakan 1 ajakan tindakan konkret di akhir."
    )
    try:
        client = _anthropic_client()
        response = await client.messages.create(
            model=settings.claude_complex_model,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return {"content": response.content[0].text}
    except Exception as exc:
        logger.exception("generate_content failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"generate failed: {exc}") from exc


@app.post("/admin/quiz/generate")
async def admin_generate_quiz(
    payload: dict = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
) -> dict:
    """Body: ``{difficulty, num_options}`` → ``{question, options, answer, explanation}``."""
    _require_admin(authorization)

    import json as _json
    import re as _re

    difficulty = (payload.get("difficulty") or "Sedang").strip()
    num_options = int(payload.get("num_options") or 4)
    num_options = max(2, min(num_options, 6))

    letters = ["A", "B", "C", "D", "E", "F"][:num_options]
    system = (
        "Kamu adalah penulis quiz trivia plastik & lingkungan untuk volunteer "
        "Indonesia. Bahasa Indonesia santai. Jawaban harus akurat secara faktual."
    )
    user = (
        f"Buat 1 quiz trivia tingkat {difficulty} dengan {num_options} pilihan "
        f"jawaban berlabel {', '.join(letters)}. Balas HANYA JSON valid dengan "
        "kunci: question (string), options (list of strings, masing-masing "
        "dimulai dengan label + ') '), answer (single huruf), explanation "
        "(string, maks 25 kata)."
    )
    try:
        client = _anthropic_client()
        response = await client.messages.create(
            model=settings.claude_complex_model,
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = response.content[0].text
    except Exception as exc:
        logger.exception("generate_quiz failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"generate failed: {exc}") from exc

    match = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if not match:
        raise HTTPException(status_code=500, detail="Model did not return JSON")
    try:
        data = _json.loads(match.group(0))
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"JSON parse failed: {exc}") from exc

    return {
        "question": data.get("question", ""),
        "options": list(data.get("options") or []),
        "answer": (data.get("answer") or "").strip().upper()[:1],
        "explanation": data.get("explanation", ""),
    }


@app.post("/admin/messages/schedule")
async def admin_messages_schedule(
    payload: dict = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
) -> dict:
    """Send (or store) a content / quiz message to a recipient filter.

    Body shape:
        ``{content?: str, quiz?: {...}, recipient_filter: str, scheduled_at?: ISO8601}``

    Without ``scheduled_at`` we broadcast immediately. With a future
    timestamp we stash the row in ``scheduled_messages`` for the scheduler
    to consume; if the table doesn't exist the request returns a 501.
    """
    _require_admin(authorization)

    from datetime import datetime, timedelta, timezone
    from backend.agents.services.notifications import notify_volunteer

    content = (payload.get("content") or "").strip()
    quiz = payload.get("quiz")
    recipient_filter = (payload.get("recipient_filter") or "all").lower()
    scheduled_at = payload.get("scheduled_at")

    if not content and not quiz:
        raise HTTPException(status_code=400, detail="content or quiz required")

    if scheduled_at:
        try:
            db.table("scheduled_messages").insert(
                {
                    "content": content or None,
                    "quiz": quiz,
                    "recipient_filter": recipient_filter,
                    "scheduled_at": scheduled_at,
                    "status": "pending",
                }
            ).execute()
        except Exception as exc:
            logger.warning("scheduled_messages insert failed: %s", exc)
            raise HTTPException(
                status_code=501,
                detail=(
                    "Scheduled delivery requires a ``scheduled_messages`` "
                    f"table. Underlying error: {exc}"
                ),
            ) from exc
        return {"status": "scheduled", "scheduled_at": scheduled_at}

    query = db.table("volunteers").select("id, name, phone, telegram_id").eq(
        "is_active", True
    )
    if recipient_filter in {"yang belum lapor", "non_reporters"}:
        today = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        reported_ids = {
            r["volunteer_id"]
            for r in (
                db.table("reports")
                .select("volunteer_id")
                .gte("reported_at", today)
                .execute()
                .data
                or []
            )
        }
        rows = [
            v for v in (query.execute().data or []) if v["id"] not in reported_ids
        ]
    else:
        rows = query.execute().data or []

    if quiz:
        from backend.application.use_cases._plastic_content import (
            QUIZ_TTL_HOURS,
            format_quiz_message,
        )
        try:
            db.table("active_quizzes").insert(
                {
                    "question": quiz.get("question"),
                    "options": list(quiz.get("options") or []),
                    "answer": (quiz.get("answer") or "").upper(),
                    "explanation": quiz.get("explanation", ""),
                    "expires_at": (
                        datetime.now(timezone.utc)
                        + timedelta(hours=QUIZ_TTL_HOURS)
                    ).isoformat(),
                }
            ).execute()
        except Exception as exc:
            logger.warning("active_quizzes insert failed: %s", exc)
        text = format_quiz_message(quiz)
    else:
        text = content

    dispatched = 0
    for v in rows:
        try:
            await notify_volunteer(v, text)
            dispatched += 1
        except Exception as exc:
            logger.warning("schedule_message send to %s failed: %s", v.get("name"), exc)
    return {"dispatched": dispatched, "recipients": len(rows)}


@app.post("/admin/persona/preview")
async def admin_persona_preview(
    payload: dict = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
) -> dict:
    """Render a one-shot sample reply using the supplied persona settings.

    Body: ``{test_name: str, settings: {agent_name, agent_role, tone,
    use_emoji, address_style, greeting_template, max_sentences,
    personality_notes}}``.
    """
    _require_admin(authorization)

    test_name = (payload.get("test_name") or "Volunteer").strip()
    s = payload.get("settings") or {}

    agent_name = s.get("agent_name") or "Asisten GBP"
    agent_role = s.get("agent_role") or "asisten program Generasi Bebas Plastik"
    tone = s.get("tone") or "Kasual"
    use_emoji = bool(s.get("use_emoji"))
    address_style = (s.get("address_style") or "kamu").lower()
    greeting_template = s.get("greeting_template") or "Halo {nama}!"
    max_sentences = int(s.get("max_sentences") or 4)
    personality_notes = s.get("personality_notes") or ""

    address_rule = {
        "name": f"Sapa volunteer dengan nama saja ('{test_name}').",
        "kak_name": f"Sapa volunteer dengan 'Kak {test_name}'.",
        "kamu": "Gunakan kata ganti 'kamu'.",
        "anda": "Gunakan kata ganti 'Anda'.",
    }.get(address_style, "Gunakan kata ganti 'kamu'.")

    emoji_rule = (
        "Gunakan emoji secukupnya (1-3 per pesan)."
        if use_emoji
        else "Jangan gunakan emoji sama sekali."
    )

    system = (
        f"Kamu adalah {agent_name}, {agent_role}. "
        f"Tone: {tone}. {address_rule} {emoji_rule} "
        f"Batas maksimum {max_sentences} kalimat per respons. "
        f"{personality_notes}"
    ).strip()

    user = (
        f"(Sample) Volunteer bernama {test_name} baru saja bilang: "
        f"\"halo, gimana cara lapor laporan hari ini ya?\""
    )

    try:
        client = _anthropic_client()
        response = await client.messages.create(
            model=settings.claude_default_model,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return {"response": response.content[0].text, "greeting": greeting_template.format(nama=test_name, area="-")}
    except Exception as exc:
        logger.exception("persona preview failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"preview failed: {exc}") from exc


@app.post("/admin/impact/generate")
async def admin_generate_impact(
    payload: dict = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
) -> dict:
    """Compute impact metrics + Sonnet narrative. Body: ``{target_kg?: number}``."""
    _require_admin(authorization)

    reports = (
        db.table("reports").select("kg_collected").execute().data or []
    )
    total_kg = round(sum(float(r.get("kg_collected") or 0) for r in reports), 2)

    BOTTLE_KG = 0.025  # ~25g per PET bottle
    CO2_PER_KG = 2.5   # kg CO2 avoided per kg plastic recycled
    bottles = int(total_kg / BOTTLE_KG) if total_kg else 0
    co2_kg = round(total_kg * CO2_PER_KG, 1)

    target_kg = payload.get("target_kg")
    target_line = (
        f"Target visualisasi: {target_kg} kg "
        f"({(total_kg / float(target_kg) * 100):.1f}% tercapai)."
        if target_kg
        else "Tidak ada target khusus — gambarkan dampak nyata sejauh ini."
    )

    try:
        client = _anthropic_client()
        response = await client.messages.create(
            model=settings.claude_complex_model,
            max_tokens=700,
            system=(
                "Kamu menulis narasi dampak program lingkungan dalam Bahasa "
                "Indonesia. 80-150 kata, hangat tapi faktual."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Total plastik terkumpul: {total_kg} kg.\n"
                        f"Setara dengan {bottles:,} botol diselamatkan dan "
                        f"{co2_kg} kg CO2 dicegah.\n"
                        f"{target_line}\n\n"
                        "Tulis narasi dampak untuk dibagikan ke stakeholder."
                    ),
                }
            ],
        )
        narrative = response.content[0].text
    except Exception as exc:
        logger.warning("impact narrative failed, using fallback: %s", exc)
        narrative = (
            f"Sampai hari ini, program telah mengumpulkan {total_kg} kg plastik — "
            f"setara dengan {bottles:,} botol PET yang tidak berakhir di TPA atau "
            f"laut, dan {co2_kg} kg emisi CO2 yang berhasil dicegah."
        )

    return {
        "total_kg": total_kg,
        "bottles": bottles,
        "co2_kg": co2_kg,
        "narrative": narrative,
    }


@app.post("/admin/missions/{mission_id}/brief")
async def admin_mission_brief(
    mission_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    """Trigger ``SendMissionEducationBrief`` for ``mission_id``."""
    _require_admin(authorization)

    from uuid import UUID

    from backend.infrastructure.composition_root import (
        build_send_mission_education_brief,
    )

    try:
        target = UUID(str(mission_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {exc}") from exc

    result = await build_send_mission_education_brief().execute(mission_id=target)
    dispatched = getattr(result, "recipients_dispatched", None) or getattr(
        result, "dispatched", 0
    )
    return {"dispatched": dispatched}


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
