"""Telegram channel handler: routing rules, replies, registration, and commands.

# ------------------------------------------------------------------------- #
# BOT SETUP IN GROUPS (Part I)                                               #
# ------------------------------------------------------------------------- #
# REQUIRED: Set bot privacy mode to DISABLED via BotFather
# Steps: Open @BotFather → /mybots → select bot → Bot Settings
#        → Group Privacy → Turn off
# Why: By default, bots in groups only receive messages that start with /
#      Disabling privacy mode allows bot to receive ALL messages in the group
#      so it can detect @mentions anywhere in the message text.
#
# ALTERNATIVE: Add bot as GROUP ADMIN
# If privacy mode cannot be disabled, adding bot as admin also allows
# it to read all messages in the group.
# ------------------------------------------------------------------------- #
"""

import logging
import re

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.agents import (
    ContentCreatorAgent,
    FasilitatorHubAgent,
    ImpactAnalyzerAgent,
    MissionBriefingAgent,
    ProgressTrackerAgent,
    RouterAgent,
    VolunteerSupportAgent,
)
from backend.config import settings
from backend.database.supabase_client import db
from backend.utils.image_handler import ImageHandler
from backend.utils.query_utils import get_active_mission as _get_active_mission_shared

logger = logging.getLogger(__name__)

GROUP_CHAT_TYPES = ("group", "supergroup")
GROUP_COMMANDS = ("/start", "/help", "/status", "/laporan")
TELEGRAM_MAX_LEN = 4096

NOT_REGISTERED_GROUP_MSG = (
    "Halo! Kamu belum terdaftar. Silakan DM bot ini untuk registrasi."
)
WELCOME_ASK_NAME = (
    "Selamat datang di Generasi Bebas Plastik! 🌱\n"
    "Kamu belum terdaftar. Boleh saya tahu nama lengkap kamu?"
)
HELP_MESSAGE = (
    "<b>Macca Bot — apa yang bisa saya bantu?</b>\n\n"
    "• Kirim laporan: <code>laporan [berat] kg [lokasi]</code>\n"
    "• /status — progress misi kamu saat ini\n"
    "• /laporan — format laporan\n"
    "• /help — pesan ini\n\n"
    "Di grup: mention saya (@bot) atau reply pesan saya.\n"
    "Di DM: langsung ketik saja, saya selalu mendengarkan."
)

# In-memory registration state, keyed by telegram_id (Part F)
pending_registrations: dict[int, dict] = {}

_router: RouterAgent | None = None
_image_handler: ImageHandler | None = None


def init_agents() -> RouterAgent:
    """Initialise the agent registry and router exactly once."""
    global _router, _image_handler
    if _router is None:
        _router = RouterAgent(
            {
                "mission_briefing": MissionBriefingAgent(),
                "progress_tracker": ProgressTrackerAgent(),
                "volunteer_support": VolunteerSupportAgent(),
                "content_creator": ContentCreatorAgent(),
                "impact_analyzer": ImpactAnalyzerAgent(),
                "fasilitator_hub": FasilitatorHubAgent(),
            }
        )
        _image_handler = ImageHandler()
        logger.info("All agents initialised")
    return _router


# ------------------------------------------------------------------------- #
# Part A — message routing logic (DM vs group)                               #
# ------------------------------------------------------------------------- #

def determine_should_process(update: Update, bot_username: str) -> bool:
    """Decide whether the bot should process this update.

    Private chats are always processed. Group messages are only processed
    when the bot is @mentioned, the message replies to the bot, the message
    starts with a known command, or the sender is the fasilitator — so the
    bot never responds to general group chatter.
    """
    message = update.message or update.edited_message
    if not message or not message.chat:
        return False

    chat_type = message.chat.type

    if chat_type == "private":
        return True

    if chat_type not in GROUP_CHAT_TYPES:
        return False

    text = message.text or message.caption or ""

    # a. Bot is @mentioned anywhere in the text
    if f"@{bot_username}".lower() in text.lower():
        return True

    # b. Direct reply to a message sent by the bot
    reply = message.reply_to_message
    if reply and reply.from_user and reply.from_user.is_bot:
        return True

    # c. Message starts with a known command (handles "/laporan@botname" too)
    first_token = text.split()[0] if text.split() else ""
    if first_token.split("@")[0].lower() in GROUP_COMMANDS:
        return True

    # d. Sender is the fasilitator
    if message.from_user and message.from_user.id == settings.fasilitator_telegram_id:
        return True

    return False


# ------------------------------------------------------------------------- #
# Part B — clean message text                                                #
# ------------------------------------------------------------------------- #

def extract_clean_message(text: str, bot_username: str) -> str:
    """Strip the bot @mention from message text and normalise whitespace.

    "@botname laporan 18 kg menteng" -> "laporan 18 kg menteng"
    """
    cleaned = re.sub(re.escape(f"@{bot_username}"), " ", text, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


# ------------------------------------------------------------------------- #
# Part C — reply behaviour (DM vs group)                                     #
# ------------------------------------------------------------------------- #

async def send_response(
    update: Update, context: ContextTypes.DEFAULT_TYPE, response: str
) -> None:
    """Send a reply, threading it in groups and chunking long messages.

    DMs get a plain message; in groups the bot always replies to the
    triggering message so members can see the context. Responses longer
    than Telegram's 4096-char limit are split into multiple messages.
    HTML parse mode: <b>bold</b>, <i>italic</i>, <code>code</code>.
    """
    if not response:
        return

    chat = update.effective_chat
    message = update.message or update.edited_message
    is_group = chat.type in GROUP_CHAT_TYPES

    chunks = [
        response[i : i + TELEGRAM_MAX_LEN]
        for i in range(0, len(response), TELEGRAM_MAX_LEN)
    ]
    for chunk in chunks:
        kwargs: dict = {
            "chat_id": chat.id,
            "text": chunk,
            "parse_mode": ParseMode.HTML,
        }
        if is_group and message:
            kwargs["reply_to_message_id"] = message.message_id
        await context.bot.send_message(**kwargs)


# ------------------------------------------------------------------------- #
# Part D — context building (DM vs group)                                    #
# ------------------------------------------------------------------------- #

def build_context(update: Update) -> dict:
    """Build the agent context dict from an update.

    Always uses update.effective_user.id (the sender) for volunteer lookups
    — never the group chat id.
    """
    message = update.message or update.edited_message
    is_group = update.effective_chat.type in GROUP_CHAT_TYPES

    ctx = {
        "telegram_id": update.effective_user.id,
        "username": update.effective_user.username,
        "chat_type": "group" if is_group else "private",
        "chat_id": update.effective_chat.id,
        "message_id": message.message_id if message else None,
        "photo_url": None,
    }
    if is_group:
        ctx["group_title"] = update.effective_chat.title
    return ctx


# ------------------------------------------------------------------------- #
# Part H — fasilitator alerts                                                #
# ------------------------------------------------------------------------- #

async def send_fasilitator_alert(bot, alert_message: str) -> None:
    """DM '🚨 ALERT: ...' to the fasilitator (e.g. for anomalous/flagged reports)."""
    try:
        await bot.send_message(
            chat_id=settings.fasilitator_telegram_id,
            text=f"🚨 ALERT: {alert_message}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error("Failed to send fasilitator alert: %s", exc)


# ------------------------------------------------------------------------- #
# Database helpers                                                           #
# ------------------------------------------------------------------------- #

def _get_volunteer(telegram_id: int) -> dict | None:
    result = (
        db.table("volunteers").select("*").eq("telegram_id", telegram_id).limit(1).execute()
    )
    return result.data[0] if result.data else None


_get_active_mission = _get_active_mission_shared


def _total_collected_kg(volunteer_id: str) -> float:
    result = (
        db.table("reports").select("kg_collected").eq("volunteer_id", volunteer_id).execute()
    )
    return sum(float(r["kg_collected"]) for r in result.data or [])


# ------------------------------------------------------------------------- #
# Part F — registration flow (DM only)                                       #
# ------------------------------------------------------------------------- #

async def _registration_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE, clean_text: str
) -> None:
    """Two-step DM registration: ask for the name, then create the volunteer."""
    telegram_id = update.effective_user.id
    pending = pending_registrations.get(telegram_id)

    if not pending or pending.get("step") != "waiting_name":
        pending_registrations[telegram_id] = {"step": "waiting_name"}
        await send_response(update, context, WELCOME_ASK_NAME)
        return

    name = clean_text.strip()
    pending_registrations[telegram_id] = {"step": "done", "name": name}

    # Schema requires a non-null area; the fasilitator assigns the real one later
    db.table("volunteers").insert(
        {"telegram_id": telegram_id, "name": name, "area": "pending_assignment"}
    ).execute()

    await send_response(
        update,
        context,
        f"Terima kasih {name}! Pendaftaran berhasil 🎉\n"
        f"Fasilitator akan segera mengassign area dan misimu.",
    )
    await send_fasilitator_alert(
        context.bot,
        f"👤 Volunteer baru: {name} (ID: {telegram_id}) — belum diassign area.",
    )


# ------------------------------------------------------------------------- #
# Part E — full message handler flow                                         #
# ------------------------------------------------------------------------- #

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main pipeline: gate → context → photo → volunteer → router → reply → history."""
    bot_username = context.bot.username

    if not determine_should_process(update, bot_username):
        return

    ctx = build_context(update)
    message = update.message or update.edited_message
    text = message.text or message.caption or ""
    clean_text = extract_clean_message(text, bot_username)

    if message.photo:
        # Largest size; download + compress (max 1MB) + Cloudinary upload all
        # happen inside upload_from_telegram
        ctx["photo_url"] = await _image_handler.upload_from_telegram(
            message.photo[-1].file_id, context.application
        )
        clean_text = (
            extract_clean_message(message.caption, bot_username)
            if message.caption
            else "laporan foto"
        )

    if not clean_text:
        return

    await _process_text(update, context, ctx, clean_text)


async def _process_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: dict, clean_text: str
) -> None:
    """Steps 6-15: typing indicator, volunteer lookup, routing, reply, history."""
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    volunteer = _get_volunteer(ctx["telegram_id"])
    if volunteer is None:
        if ctx["chat_type"] == "private":
            await _registration_step(update, context, clean_text)
        else:
            await send_response(update, context, NOT_REGISTERED_GROUP_MSG)
        return

    ctx["volunteer"] = volunteer
    ctx["mission"] = _get_active_mission(volunteer["id"])

    router = init_agents()
    # Chat history is persisted inside each agent's process()
    response = await router.route(clean_text, ctx)
    await send_response(update, context, response)


# ------------------------------------------------------------------------- #
# Part G — commands                                                          #
# ------------------------------------------------------------------------- #

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registration check for new users, welcome back for existing ones."""
    volunteer = _get_volunteer(update.effective_user.id)
    if volunteer:
        await send_response(
            update,
            context,
            f"Selamat datang kembali, <b>{volunteer['name']}</b>! 🌱\n"
            f"Ketik /status untuk lihat progress, atau /help untuk bantuan.",
        )
    elif update.effective_chat.type == "private":
        await _registration_step(update, context, "/start")
    else:
        await send_response(update, context, NOT_REGISTERED_GROUP_MSG)


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List bot capabilities; works in both DM and group."""
    await send_response(update, context, HELP_MESSAGE)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the volunteer's current mission progress from the database."""
    volunteer = _get_volunteer(update.effective_user.id)
    if volunteer is None:
        msg = (
            NOT_REGISTERED_GROUP_MSG
            if update.effective_chat.type in GROUP_CHAT_TYPES
            else WELCOME_ASK_NAME
        )
        await send_response(update, context, msg)
        return

    total = _total_collected_kg(volunteer["id"])
    quota = float(volunteer.get("quota_kg") or 0)
    mission = _get_active_mission(volunteer["id"])

    lines = [
        f"<b>Status {volunteer['name']}</b>",
        f"Area: {volunteer.get('area', '-')}",
        f"Terkumpul: <b>{total:g} kg</b> dari target {quota:g} kg",
    ]
    if mission:
        lines.append(f"Misi aktif: {mission.get('title')} (deadline {mission.get('deadline')})")
    else:
        lines.append("Belum ada misi aktif yang diassign.")

    await send_response(update, context, "\n".join(lines))


async def handle_laporan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Format hint — or process directly when the report is inline with the command."""
    args = " ".join(context.args or [])
    if args:
        # "/laporan 18 kg menteng" — treat as an actual report
        await _process_text(update, context, build_context(update), f"laporan {args}")
        return

    await send_response(
        update,
        context,
        "Kirim laporan dengan format: <code>laporan [berat] kg [lokasi]</code>\n"
        "Contoh: <code>laporan 18 kg menteng</code>\n"
        "Boleh juga lampirkan foto sebagai bukti! 📸",
    )


# ------------------------------------------------------------------------- #
# Application factory                                                        #
# ------------------------------------------------------------------------- #

def create_application() -> Application:
    """Build the python-telegram-bot Application with all handlers registered."""
    application = (
        Application.builder().token(settings.telegram_bot_token).updater(None).build()
    )
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(CommandHandler("laporan", handle_laporan))
    application.add_handler(
        MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_message)
    )
    return application
