"""Phase 6 tests: Fasilitator Hub commands + Scheduler wiring.

Run from the project root::

    python backend/test_phase6.py

Uses real Claude calls (Haiku + Sonnet) and writes to the real Supabase
project named in ``.env``. ``notify_volunteer`` and ``alert_fasilitator``
are monkey-patched so nothing is actually sent to Telegram / WhatsApp,
and the in-memory recorders are inspected by the assertions.

Test fixture:
    Fasilitator phone forced to FAS_PHONE.
    Five test volunteers (Rizki / Sari reported today; Hendra / Budi /
    Andi have not). Mission deadline 2 days from now. Quota 10 kg.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.agents.services.notifications as notif
import backend.utils.scheduler as scheduler_mod
from backend.config import settings
from backend.database.supabase_client import db
from backend.main import app  # noqa: F401 — boots Settings

# --------------------------------------------------------------------------- #
# Fixture constants                                                            #
# --------------------------------------------------------------------------- #

PASS = "✅ PASS"
FAIL = "❌ FAIL"

FAS_PHONE = "628999000600"
FAS_TG = 999000600

VOLUNTEERS = (
    {"name": "Rizki",  "area": "Cikini",       "phone": "628999000601", "tg": 999000601, "reported_today": True,  "kg": 5},
    {"name": "Sari",   "area": "Menteng",      "phone": "628999000602", "tg": 999000602, "reported_today": True,  "kg": 3},
    {"name": "Hendra", "area": "Senen",        "phone": "628999000603", "tg": 999000603, "reported_today": False, "kg": 0},
    {"name": "Budi",   "area": "Tebet",        "phone": "628999000604", "tg": 999000604, "reported_today": False, "kg": 0},
    {"name": "Andi",   "area": "Pasar Minggu", "phone": "628999000605", "tg": 999000605, "reported_today": False, "kg": 0},
)
QUOTA_KG = 10
DEADLINE_DAYS = 2


# --------------------------------------------------------------------------- #
# Mocks                                                                        #
# --------------------------------------------------------------------------- #

notify_log: list[tuple[dict, str]] = []
alert_log: list[str] = []


async def _mock_notify_volunteer(volunteer: dict, text: str) -> None:
    notify_log.append((volunteer, text))


async def _mock_alert_fasilitator(text: str) -> None:
    alert_log.append(text)


notif.notify_volunteer = _mock_notify_volunteer
notif.alert_fasilitator = _mock_alert_fasilitator
# Force fasilitator identity to a known phone for tests
settings.fasilitator_phone = FAS_PHONE
settings.fasilitator_telegram_id = FAS_TG


def reset_logs() -> None:
    notify_log.clear()
    alert_log.clear()


# --------------------------------------------------------------------------- #
# Setup / teardown                                                             #
# --------------------------------------------------------------------------- #


def setup() -> tuple[list[dict], dict, str, dict]:
    """Insert / refresh 5 volunteers, 1 mission, today's reports.

    Returns: (volunteers_list, mission_row, deadline_iso, flagged_report).
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_iso = today_start.isoformat()
    deadline_iso = (now + timedelta(days=DEADLINE_DAYS)).isoformat()

    # Volunteers — upsert by telegram_id
    inserted: list[dict] = []
    for spec in VOLUNTEERS:
        existing = (
            db.table("volunteers")
            .select("*")
            .eq("telegram_id", spec["tg"])
            .limit(1)
            .execute()
            .data
        )
        profile = {
            "name": spec["name"],
            "area": spec["area"],
            "phone": spec["phone"],
            "quota_kg": QUOTA_KG,
            "is_active": True,
        }
        if existing:
            row = (
                db.table("volunteers")
                .update(profile)
                .eq("telegram_id", spec["tg"])
                .execute()
                .data[0]
            )
        else:
            row = (
                db.table("volunteers")
                .insert({**profile, "telegram_id": spec["tg"]})
                .execute()
                .data[0]
            )
        inserted.append({**row, "_reported_today": spec["reported_today"], "_kg": spec["kg"]})

    mission = (
        db.table("missions")
        .insert(
            {
                "title": "Phase 6 Test Mission",
                "description": "Created by test_phase6.py",
                "deadline": deadline_iso,
                "status": "active",
            }
        )
        .execute()
        .data[0]
    )
    for v in inserted:
        db.table("volunteer_missions").insert(
            {
                "volunteer_id": v["id"],
                "mission_id": mission["id"],
                "quota_kg": QUOTA_KG,
                "assigned_area": v.get("area") or "-",
            }
        ).execute()

    # Clean any stale reports for these volunteers
    for v in inserted:
        db.table("reports").delete().eq("volunteer_id", v["id"]).execute()

    # Insert today's reports for Rizki + Sari
    for v in inserted:
        if not v["_reported_today"]:
            continue
        db.table("reports").insert(
            {
                "volunteer_id": v["id"],
                "mission_id": mission["id"],
                "kg_collected": v["_kg"],
                "location": v.get("area"),
                "source": "whatsapp",
                "is_test": True,
                "reported_at": today_iso,
            }
        ).execute()

    # Flagged report for A8 (Rizki, kg=99)
    rizki = inserted[0]
    flagged = (
        db.table("reports")
        .insert(
            {
                "volunteer_id": rizki["id"],
                "mission_id": mission["id"],
                "kg_collected": 99,
                "location": "Cikini",
                "source": "whatsapp",
                "is_test": True,
                "is_flagged": True,
                "flag_reason": "kg_suspicious_high",
                "reported_at": today_iso,
            }
        )
        .execute()
        .data[0]
    )

    # Wipe chat history for clean state
    for v in inserted:
        db.table("chat_history").delete().eq("telegram_id", v["telegram_id"]).execute()
    db.table("chat_history").delete().eq("telegram_id", FAS_TG).execute()

    return inserted, mission, deadline_iso, flagged


def teardown(volunteers: list[dict], mission: dict) -> None:
    for v in volunteers:
        db.table("reports").delete().eq("volunteer_id", v["id"]).execute()
        db.table("chat_history").delete().eq("telegram_id", v["telegram_id"]).execute()
    db.table("volunteer_missions").delete().eq("mission_id", mission["id"]).execute()
    db.table("missions").delete().eq("id", mission["id"]).execute()
    db.table("chat_history").delete().eq("telegram_id", FAS_TG).execute()
    for v in volunteers:
        db.table("volunteers").delete().eq("id", v["id"]).execute()
    print("\n🧹 Cleaned up Phase 6 fixtures")


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def fas_ctx() -> dict:
    return {
        "telegram_id": FAS_TG,
        "sender_phone": FAS_PHONE,
        "chat_type": "private",
        "is_fasilitator": True,
    }


def volunteer_ctx(volunteer: dict) -> dict:
    return {
        "telegram_id": volunteer["telegram_id"],
        "sender_phone": volunteer.get("phone"),
        "chat_type": "private",
        "volunteer": volunteer,
    }


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


async def run_tests() -> dict[str, list[bool]]:
    from backend.agents.fasilitator_hub import FasilitatorHubAgent
    from backend.agents.router_agent import RouterAgent

    volunteers, mission, deadline_iso, flagged = setup()
    rizki = next(v for v in volunteers if v["name"] == "Rizki")
    hendra = next(v for v in volunteers if v["name"] == "Hendra")

    fas = FasilitatorHubAgent()
    router = RouterAgent()

    results: dict[str, list[bool]] = {}

    def record(group: str, name: str, ok: bool, detail: str) -> None:
        results.setdefault(group, []).append(ok)
        print(f"{PASS if ok else FAIL}  {name}: {detail}")

    try:
        # ============================================================== #
        # GROUP A — command recognition                                   #
        # ============================================================== #
        print("\n--- Group A: Command recognition ---")

        # ----- A1: send_reminder, only non-reporters --------------------
        reset_logs()
        msg = "kirim reminder ke yang belum lapor"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        recipients = [v.get("name") for v, _ in notify_log]
        ok = (
            intent == "send_reminder"
            and len(notify_log) == 3
            and {"Hendra", "Budi", "Andi"} == set(recipients)
            and "Rizki" not in recipients
            and "Sari" not in recipients
            and "3 volunteer" in reply.lower().replace("  ", " ")
        )
        record(
            "A", "A1 send_reminder filters non-reporters", ok,
            f"intent={intent} sent={len(notify_log)} to={recipients}",
        )

        # ----- A2: get_status -------------------------------------------
        reset_logs()
        msg = "status program hari ini"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        lower = reply.lower()
        ok = (
            intent == "get_status"
            and ("8 kg" in lower or "8kg" in lower)
            and "2/5" in reply
            and all(name in reply for name in ("Hendra", "Budi", "Andi"))
        )
        record(
            "A", "A2 get_status metrics", ok,
            f"intent={intent} has_2/5={'2/5' in reply} "
            f"non_reporters_listed={all(n in reply for n in ('Hendra','Budi','Andi'))}",
        )

        # ----- A3: broadcast --------------------------------------------
        reset_logs()
        msg = "broadcast ke semua volunteer: besok ada evaluasi jam 10 pagi"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        ok = (
            intent == "broadcast"
            and len(notify_log) == 5
            and all("evaluasi" in text.lower() for _, text in notify_log)
            and "5 volunteer" in reply.lower()
        )
        record(
            "A", "A3 broadcast to all 5", ok,
            f"intent={intent} sent={len(notify_log)} confirm_5={'5 volunteer' in reply.lower()}",
        )

        # ----- A4: query volunteer (Rizki tugas) ------------------------
        reset_logs()
        msg = "apa tugas rizki?"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        ok = (
            intent in ("query_other_volunteer", "get_volunteer_detail")
            and "Rizki" in reply
            and "Cikini" in reply
            and (f"{QUOTA_KG:g} kg" in reply or f"{QUOTA_KG} kg" in reply)
        )
        record(
            "A", "A4 query volunteer Rizki", ok,
            f"intent={intent} has_area={'Cikini' in reply} has_quota={f'{QUOTA_KG} kg' in reply}",
        )

        # ----- A5: cross-volunteer query "Rizki sudah lapor?" -----------
        reset_logs()
        msg = "rizki sudah lapor belum?"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        # Rizki has reported 5 kg + 99 kg flagged today → progress > 0
        ok = (
            intent in ("query_other_volunteer", "get_volunteer_detail", "get_status")
            and "Rizki" in reply
            and ("Cikini" in reply or "kg" in reply.lower())
        )
        record(
            "A", "A5 cross-volunteer status", ok,
            f"intent={intent} has_Rizki={'Rizki' in reply}",
        )

        # ----- A6: analytics — area performance -------------------------
        reset_logs()
        msg = "area mana yang paling bagus performanya?"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        lower = reply.lower()
        ok = (
            intent == "get_analytics"
            and ("cikini" in lower or "menteng" in lower or "area" in lower)
            and any(c.isdigit() for c in reply)
        )
        record(
            "A", "A6 analytics by area", ok,
            f"intent={intent} mentions_area={'cikini' in lower or 'menteng' in lower} "
            f"has_digit={any(c.isdigit() for c in reply)}",
        )

        # ----- A7: generate content (IG caption) ------------------------
        reset_logs()
        msg = "buatkan caption instagram dari data hari ini"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        lower = reply.lower()
        ok = (
            intent == "generate_content"
            and len(reply) > 80
            and ("kg" in lower or "plastik" in lower or "#" in reply)
        )
        record(
            "A", "A7 generate IG content", ok,
            f"intent={intent} length={len(reply)} has_kg={'kg' in lower} has_hash={'#' in reply}",
        )

        # ----- A8: flag review ------------------------------------------
        reset_logs()
        msg = "ada laporan yang perlu dicek?"
        intent = await fas._classify_command(msg)
        reply = await fas.process(msg, fas_ctx())
        ok = (
            intent == "flag_review"
            and "Rizki" in reply
            and "99" in reply
            and ("suspicious" in reply.lower() or "flag" in reply.lower() or "kg_" in reply.lower())
        )
        record(
            "A", "A8 flag review shows flagged report", ok,
            f"intent={intent} has_Rizki={'Rizki' in reply} has_99={'99' in reply}",
        )

        # ============================================================== #
        # GROUP B — access control                                        #
        # ============================================================== #
        print("\n--- Group B: Access control ---")

        # ----- B1: volunteer cannot reach Hub ---------------------------
        reset_logs()
        ctx_v = volunteer_ctx(hendra)
        await router.route("apa progress saya?", ctx_v)
        ok = router.last_agent != "fasilitator_hub"
        record(
            "B", "B1 non-fasilitator NOT routed to hub", ok,
            f"last_agent={router.last_agent}",
        )

        # ----- B2: fasilitator always to Hub ----------------------------
        reset_logs()
        ctx_f = fas_ctx()
        await router.route("halo", ctx_f)
        ok_b2 = router.last_agent == "fasilitator_hub"
        record(
            "B", "B2 fasilitator always to hub", ok_b2,
            f"last_agent={router.last_agent}",
        )

        # ============================================================== #
        # GROUP C — scheduler jobs                                        #
        # ============================================================== #
        print("\n--- Group C: Scheduler jobs ---")

        # ----- C1: morning briefing format ------------------------------
        reset_logs()
        briefing = await fas.get_morning_briefing()
        lower = briefing.lower()
        ok = (
            ("kg" in lower)
            and (f"/{len(VOLUNTEERS)}" in briefing)  # "/5"
            and ("belum lapor" in lower)
            and ("hari lagi" in lower)
            and len(alert_log) == 1
        )
        record(
            "C", "C1 morning briefing format", ok,
            f"has_kg={'kg' in lower} has_/5={'/5' in briefing} "
            f"has_belum_lapor={'belum lapor' in lower} has_deadline={'hari lagi' in lower}",
        )

        # ----- C2: daily reminder triggers for 3 non-reporters ----------
        reset_logs()
        await scheduler_mod._daily_reminder_job()
        recipients = {v.get("name") for v, _ in notify_log}
        msgs_have_name = all(
            v.get("name") in text for v, text in notify_log
        )
        msgs_have_deadline_hint = all(
            ("hari" in text.lower() or "deadline" in text.lower())
            for _, text in notify_log
        )
        ok = (
            len(notify_log) == 3
            and {"Hendra", "Budi", "Andi"} == recipients
            and msgs_have_name
            and msgs_have_deadline_hint
        )
        record(
            "C", "C2 daily_reminder targets non-reporters", ok,
            f"sent={len(notify_log)} to={recipients} personalized={msgs_have_name} "
            f"has_deadline={msgs_have_deadline_hint}",
        )

        # ----- C3: scheduler registration --------------------------------
        manager = scheduler_mod.SchedulerManager()
        manager.register_default_jobs()
        jobs = {j.id: j for j in manager._scheduler.get_jobs()}
        expected_ids = {"daily_reminder", "morning_briefing", "daily_content", "weekly_report"}
        ok = expected_ids.issubset(set(jobs.keys()))
        print(f"   Registered jobs:")
        for jid in sorted(jobs):
            print(f"     • {jid:<18} trigger={jobs[jid].trigger}")
        record(
            "C", "C3 scheduler registers 4 default jobs", ok,
            f"jobs={sorted(jobs.keys())}",
        )

    finally:
        teardown(volunteers, mission)

    return results


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


async def main() -> int:
    print("=" * 60)
    print("Macca — Phase 6: Fasilitator Hub + Scheduler tests")
    print("=" * 60)
    results = await run_tests()

    print("\nPhase 6 Test Results:")
    labels = {
        "A": "Group A (Commands):  ",
        "B": "Group B (Access):    ",
        "C": "Group C (Scheduler): ",
    }
    total = 0
    passed = 0
    for key in ("A", "B", "C"):
        arr = results.get(key, [])
        n_pass = sum(arr)
        n_total = len(arr)
        total += n_total
        passed += n_pass
        print(f"  {labels[key]} {n_pass}/{n_total} passed")
    print(f"  TOTAL: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
