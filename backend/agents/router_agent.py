"""Router agent: classifies every incoming message and delegates to a specialist agent.

Adds two cross-cutting features on top of plain routing:

* **Test mode** — the fasilitator can run ``/test_as <name>`` to temporarily
  impersonate a volunteer. Subsequent messages from the fasilitator are
  routed as if they came from that volunteer. ``/test_off`` clears it,
  ``/test_status`` reports the current binding.
* **Dual-persona routing** — every dispatch sets ``context["persona"]`` to
  either ``"fasilitator"`` or ``"volunteer"`` so downstream agents can
  return wider or narrower data accordingly.
"""

import logging

from backend.config import settings
from backend.database.supabase_client import db
from backend.utils.query_utils import find_volunteers_by_name

from .base_agent import BaseAgent

# Importing the specialist agent modules has the side effect of populating
# the intent registry via the ``@register_intent`` decorators on each class.
# Order doesn't matter as long as every specialist module is imported before
# the router builds its dispatch table.
from . import (  # noqa: F401  (imports for registry side-effect)
    content_creator,
    impact_analyzer,
    mission_briefing,
    progress_tracker,
    volunteer_support,
)
from .fasilitator_hub import FasilitatorHubAgent
from .intent_registry import (
    build_classification_prompt,
    get_intent_names,
    instantiate_agents,
)
from .progress_tracker import RANK_KEYWORDS, has_pending_report_for_context
from .volunteer_support import is_allowed_topic

logger = logging.getLogger(__name__)

DEFAULT_INTENT = "volunteer_support"


def __getattr__(name: str):
    """Back-compat shims for symbols that used to be module-level constants."""
    if name == "VALID_INTENTS":
        return get_intent_names()
    if name == "CLASSIFICATION_PROMPT":
        return build_classification_prompt()
    raise AttributeError(f"module 'router_agent' has no attribute {name!r}")

# ---------------------------------------------------------------------- #
# Test mode — module-level so it survives across messages within a       #
# single process. Keyed by sender_phone (WhatsApp) or str(telegram_id).  #
# Value: volunteer_id (UUID string) that the fasilitator is impersonating.
# ---------------------------------------------------------------------- #
test_mode_state: dict[str, str] = {}


def _sender_key(context: dict) -> str:
    """Resolve a unified key from either channel's sender identifier."""
    return context.get("sender_phone") or str(context.get("telegram_id") or "")


class RouterAgent(BaseAgent):
    """Classifies intent with a cheap Haiku call, then delegates to the matching agent."""

    def __init__(self, agents: dict[str, BaseAgent] | None = None) -> None:
        super().__init__(
            name="router",
            description="Classifies message intent and dispatches to specialist agents",
        )
        if agents is None:
            agents = instantiate_agents()
            # fasilitator_hub is intentionally absent from the registry: it is
            # reachable only via the is_fasilitator check in route(), never via
            # classification. Wire it in here so route() can still dispatch.
            agents.setdefault("fasilitator_hub", FasilitatorHubAgent())
        self._agents = agents
        # Snapshot the valid classifier outputs once at construction time.
        self._valid_intents: tuple[str, ...] = get_intent_names()
        self.last_agent: str = self.name

    # ------------------------------------------------------------------ #
    # Identity / intent helpers                                           #
    # ------------------------------------------------------------------ #

    def detect_fasilitator(self, context: dict) -> bool:
        """True if either channel identifier matches a configured fasilitator."""
        phone = (context.get("sender_phone") or "").strip()
        tg_id = context.get("telegram_id") or 0
        if phone and settings.fasilitator_phone and phone == settings.fasilitator_phone:
            return True
        if tg_id and settings.fasilitator_telegram_id and tg_id == settings.fasilitator_telegram_id:
            return True
        return False

    async def classify_intent(self, message: str, context: dict) -> str:
        """Pending-report short-circuit + Claude Haiku classification."""
        if has_pending_report_for_context(context):
            return "progress_tracker"

        # Rank/leaderboard inquiries go straight to progress_tracker — no
        # need to round-trip Claude for an unambiguous keyword match.
        lowered = message.lower()
        if any(kw in lowered for kw in RANK_KEYWORDS):
            return "progress_tracker"

        # Cheap off-topic gate: skip Claude classification entirely when the
        # message is clearly outside the program scope. volunteer_support will
        # short-circuit again with the canned OFF_TOPIC_RESPONSE.
        if is_allowed_topic(message) is False:
            logger.info("Off-topic message short-circuited to %s", DEFAULT_INTENT)
            return DEFAULT_INTENT

        label = await self.call_claude(
            build_classification_prompt(),
            [{"role": "user", "content": message}],
            max_tokens=20,
        )
        intent = label.strip().lower()
        if intent not in self._valid_intents:
            logger.warning("Invalid intent %r, defaulting to %s", intent, DEFAULT_INTENT)
            intent = DEFAULT_INTENT
        return intent

    def get_agent_for_intent(self, intent: str) -> BaseAgent:
        return self._agents[intent]

    # ------------------------------------------------------------------ #
    # Process (kept for callers that only want the intent label)         #
    # ------------------------------------------------------------------ #

    async def process(self, message: str, context: dict) -> str:
        """Classify the message and return the intent category string."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)

        if context["is_fasilitator"]:
            return "fasilitator_hub"
        return await self.classify_intent(message, context)

    # ------------------------------------------------------------------ #
    # Test mode commands                                                  #
    # ------------------------------------------------------------------ #

    async def handle_test_commands(
        self, message: str, sender_key: str
    ) -> str | None:
        """Handle ``/test_as``, ``/test_off``, ``/test_status``.

        Returns the user-facing reply text, or ``None`` if the message is not
        a recognised test command (caller continues with normal routing).
        ``settings.test_mode_enabled=False`` short-circuits all three so
        production deployments can disable impersonation without rebuilding.
        """
        if not settings.test_mode_enabled:
            return (
                "Test mode dimatikan di environment ini. "
                "Hubungi admin untuk mengaktifkan kembali."
            )

        cmd = message.strip()
        lowered = cmd.lower()

        if lowered.startswith("/test_off"):
            removed = test_mode_state.pop(sender_key, None)
            if removed:
                return "🧪 Test mode dinonaktifkan. Kembali ke mode fasilitator."
            return "Test mode memang belum aktif."

        if lowered.startswith("/test_status"):
            current = test_mode_state.get(sender_key)
            if not current:
                return "Test mode: *tidak aktif*. Gunakan `/test_as <nama>` untuk mulai."
            volunteer = self._get_volunteer_by_id(current)
            if volunteer is None:
                test_mode_state.pop(sender_key, None)
                return "Test mode bound ke volunteer yang tidak ditemukan — direset."
            return (
                "🧪 Test mode aktif:\n"
                f"Nama: {volunteer.get('name')} | Area: {volunteer.get('area')}\n"
                f"Kuota: {volunteer.get('quota_kg')} kg"
            )

        if lowered.startswith("/test_as"):
            name = cmd[len("/test_as"):].strip()
            if not name:
                return "Format: `/test_as <nama volunteer>`"
            matches = self._find_volunteers_by_name(name)
            if not matches:
                return f"❌ Volunteer '{name}' tidak ditemukan."
            if len(matches) > 1:
                names = ", ".join(v.get("name", "") for v in matches)
                return (
                    f"Ada {len(matches)} volunteer: {names}. "
                    "Sebutkan nama lengkap."
                )
            volunteer = matches[0]
            test_mode_state[sender_key] = volunteer["id"]
            return (
                "🧪 Test mode aktif — kamu bertindak sebagai:\n"
                f"Nama: {volunteer.get('name')} | Area: {volunteer.get('area')}\n"
                f"Kuota: {volunteer.get('quota_kg')} kg\n"
                "Ketik `/test_off` untuk kembali ke mode fasilitator."
            )

        return None

    # ------------------------------------------------------------------ #
    # Route — main dispatcher                                             #
    # ------------------------------------------------------------------ #

    async def route(self, message: str, context: dict) -> str:
        """Classify, delegate to the matching agent, and return its response."""
        context = self.build_context_flags(context)
        # detect_fasilitator overrides what build_context_flags may have set
        # because it also matches via sender_phone (the base helper only
        # checks the normalised phone, which is identical, but keep them
        # in sync explicitly to avoid drift if either changes later).
        context["is_fasilitator"] = self.detect_fasilitator(context)

        sender_key = _sender_key(context)

        # 1. Fasilitator-only commands FIRST
        if context["is_fasilitator"] and message.strip().lower().startswith("/test"):
            response = await self.handle_test_commands(message, sender_key)
            if response is not None:
                self.last_agent = "router_test_commands"
                return response

        # 2. Test mode active → impersonate the bound volunteer
        if context["is_fasilitator"] and sender_key in test_mode_state:
            volunteer = self._get_volunteer_by_id(test_mode_state[sender_key])
            if volunteer is None:
                # Stale binding — clear it and continue as fasilitator
                test_mode_state.pop(sender_key, None)
            else:
                context["volunteer"] = volunteer
                context["is_fasilitator"] = False
                context["is_test_mode"] = True
                # Persist so downstream build_context_flags calls don't reset it.
                context["test_volunteer_id"] = volunteer["id"]

        # 3. Fasilitator (not in test mode) → Fasilitator Hub
        if context["is_fasilitator"]:
            context["persona"] = "fasilitator"
            agent = self._agents["fasilitator_hub"]
            self.last_agent = agent.name
            logger.info("Routing message to %s (persona=fasilitator)", agent.name)
            return await agent.process(message, context)

        # 4. Volunteer (including test-mode impersonation) → classify intent
        context["persona"] = "volunteer"
        intent = await self.classify_intent(message, context)
        agent = self.get_agent_for_intent(intent)
        self.last_agent = agent.name
        logger.info(
            "Routing message to %s (persona=volunteer, test_mode=%s)",
            agent.name, context.get("is_test_mode", False),
        )
        return await agent.process(message, context)

    # ------------------------------------------------------------------ #
    # Supabase helpers                                                    #
    # ------------------------------------------------------------------ #

    _find_volunteers_by_name = staticmethod(find_volunteers_by_name)

    @staticmethod
    def _get_volunteer_by_id(volunteer_id: str) -> dict | None:
        result = (
            db.table("volunteers").select("*").eq("id", volunteer_id).limit(1).execute()
        )
        return result.data[0] if result.data else None
