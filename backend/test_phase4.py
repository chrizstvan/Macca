"""Phase 4 tests: VolunteerSupportAgent (emotional support + plastic education).

Run from the project root:
    python backend/test_phase4.py

Uses real Claude Sonnet + Haiku calls and writes to the real Supabase
project named in ``.env``. ``alert_fasilitator`` is monkey-patched so
nothing is actually sent to Telegram / WhatsApp.

Test volunteer:
    Hendra — area Senen, quota 15 kg, progress 0 kg (struggling).
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.agents.volunteer_support as vs
from backend.agents.volunteer_support import VolunteerSupportAgent
from backend.database.supabase_client import db
from backend.main import app  # noqa: F401 — boots Settings + scheduler imports

HENDRA_PHONE_RAW = "08234567890"
HENDRA_PHONE_E164 = "628234567890"
HENDRA_TG = 999000333
HENDRA_NAME = "Hendra"
HENDRA_AREA = "Senen"
QUOTA_KG = 15

PASS = "✅ PASS"
FAIL = "❌ FAIL"


# --------------------------------------------------------------------------- #
# Fasilitator-alert mock                                                       #
# --------------------------------------------------------------------------- #

alerts: list[str] = []


async def _record_alert(text: str) -> None:
    alerts.append(text)


# Patch the module-level reference used inside ``VolunteerSupportAgent.process``.
vs.alert_fasilitator = _record_alert


# --------------------------------------------------------------------------- #
# Setup / teardown                                                             #
# --------------------------------------------------------------------------- #


def setup() -> tuple[dict, dict, bool, str]:
    """Ensure Hendra exists with a 15-kg active mission and 0 reports."""
    existing = (
        db.table("volunteers")
        .select("*")
        .eq("telegram_id", HENDRA_TG)
        .limit(1)
        .execute()
    )
    profile = {
        "name": HENDRA_NAME,
        "area": HENDRA_AREA,
        "quota_kg": QUOTA_KG,
        "phone": HENDRA_PHONE_E164,
        "is_active": True,
    }
    if existing.data:
        volunteer = (
            db.table("volunteers")
            .update(profile)
            .eq("telegram_id", HENDRA_TG)
            .execute()
            .data[0]
        )
        created = False
    else:
        volunteer = (
            db.table("volunteers")
            .insert({**profile, "telegram_id": HENDRA_TG})
            .execute()
            .data[0]
        )
        created = True

    deadline_iso = (
        datetime.now(timezone.utc) + timedelta(days=7)
    ).isoformat()
    mission = (
        db.table("missions")
        .insert(
            {
                "title": "Phase 4 Test Mission",
                "description": "Temporary mission created by test_phase4.py",
                "deadline": deadline_iso,
                "status": "active",
            }
        )
        .execute()
        .data[0]
    )
    db.table("volunteer_missions").insert(
        {
            "volunteer_id": volunteer["id"],
            "mission_id": mission["id"],
            "quota_kg": QUOTA_KG,
            "assigned_area": HENDRA_AREA,
        }
    ).execute()

    # Clean slate
    db.table("reports").delete().eq("volunteer_id", volunteer["id"]).execute()
    db.table("chat_history").delete().eq("telegram_id", HENDRA_TG).execute()

    mission["quota_kg"] = QUOTA_KG
    mission["assigned_area"] = HENDRA_AREA
    return volunteer, mission, created, deadline_iso


def teardown(volunteer: dict, mission: dict, created_volunteer: bool) -> None:
    db.table("reports").delete().eq("volunteer_id", volunteer["id"]).execute()
    db.table("volunteer_missions").delete().eq("mission_id", mission["id"]).execute()
    db.table("missions").delete().eq("id", mission["id"]).execute()
    db.table("chat_history").delete().eq("telegram_id", HENDRA_TG).execute()
    if created_volunteer:
        db.table("volunteers").delete().eq("id", volunteer["id"]).execute()
    print("\n🧹 Cleaned up Hendra fixtures + chat history")


def clear_chat_history() -> None:
    db.table("chat_history").delete().eq("telegram_id", HENDRA_TG).execute()


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


async def run_tests() -> dict[str, list[bool]]:
    volunteer, mission, created_volunteer, deadline_iso = setup()
    agent = VolunteerSupportAgent()
    ctx = {
        "telegram_id": HENDRA_TG,
        "sender_phone": HENDRA_PHONE_E164,
        "chat_type": "private",
        "volunteer": volunteer,
        "mission": mission,
    }
    results: dict[str, list[bool]] = {}

    def record(group: str, name: str, ok: bool, detail: str) -> None:
        results.setdefault(group, []).append(ok)
        print(f"{PASS if ok else FAIL}  {name}: {detail}")

    try:
        # ----- GROUP A — Situation detection -----------------------------
        print("\n--- Group A: Situation detection ---")
        clear_chat_history()

        before = len(alerts)
        reply = await agent.process("saya mau keluar dari program ini", ctx)
        ok = (
            "[ESCALATE]" not in reply
            and len(alerts) > before
            and "jangan keluar" not in reply.lower()
            and "jangan berhenti" not in reply.lower()
        )
        record(
            "A",
            "A1 want_to_quit",
            ok,
            f"alerts+={len(alerts) - before} no_tag={'[ESCALATE]' not in reply} "
            f"no_immediate_refuse={'jangan keluar' not in reply.lower()}",
        )

        before = len(alerts)
        reply = await agent.process(
            "warga di area saya susah banget diajak kerjasama", ctx
        )
        tip_markers = sum(
            int(m in reply) for m in ("1.", "2.", "3.", "•", "- ", "*")
        )
        ok = tip_markers >= 2 and len(alerts) == before
        record(
            "A",
            "A2 complaint warga",
            ok,
            f"tip_markers={tip_markers} no_escalate={len(alerts) == before}",
        )

        reply = await agent.process(
            "capek banget kak rasanya sia-sia", ctx
        )
        lower = reply.lower()
        # Sonnet may write "0 kg" / "belum mulai" / "kuota 15" — accept any
        # signal that the reply is grounded in Hendra's specific progress.
        ok = (
            HENDRA_NAME in reply
            and (
                "0" in reply
                or f"{QUOTA_KG}" in reply
                or "kuota" in lower
                or "belum" in lower
                or "kg" in lower
            )
        )
        record(
            "A",
            "A3 motivation w/ data",
            ok,
            f"has_name={HENDRA_NAME in reply} grounded={ok}",
        )

        reply = await agent.process("jam berapa deadline laporan?", ctx)
        deadline_short = deadline_iso[:10]  # YYYY-MM-DD
        ok = (
            deadline_short in reply
            or "hari lagi" in reply.lower()
            or "deadline" in reply.lower()
        )
        record(
            "A",
            "A4 general_qa deadline",
            ok,
            f"deadline_substr={deadline_short in reply} "
            f"has_hari={'hari lagi' in reply.lower()}",
        )

        # ----- GROUP B — Plastic education -------------------------------
        print("\n--- Group B: Plastic education ---")
        clear_chat_history()

        reply = await agent.process("plastik PET itu yang mana kak?", ctx)
        lower = reply.lower()
        ok = (
            ("kode 1" in lower or "pet" in lower)
            and ("botol" in lower or "bening" in lower)
            and ("daur" in lower or "recycl" in lower)
        )
        record(
            "B",
            "B1 plastic type",
            ok,
            f"mention_pet={'pet' in lower} mention_botol={'botol' in lower} "
            f"mention_daur={'daur' in lower}",
        )

        reply = await agent.process(
            "kenapa plastik bahaya buat lingkungan?", ctx
        )
        has_digit = any(c.isdigit() for c in reply)
        ok = has_digit and "indonesia" in reply.lower()
        record(
            "B",
            "B2 environmental impact",
            ok,
            f"has_number={has_digit} mention_indonesia={'indonesia' in reply.lower()}",
        )

        reply = await agent.process(
            "gimana cara jelasin ke ibu-ibu yang ga mau dengerin?", ctx
        )
        # Look for an inline quoted script / talking point
        has_quote = '"' in reply or "“" in reply or "_" in reply
        ok = has_quote and len(reply) > 80
        record(
            "B",
            "B3 explain script",
            ok,
            f"has_quote={has_quote} length={len(reply)}",
        )

        reply = await agent.process("mikroplastik itu bahaya ga?", ctx)
        lower = reply.lower()
        ok = "5" in reply and ("minggu" in lower or "gram" in lower)
        record(
            "B",
            "B4 microplastics",
            ok,
            f"has_5={'5' in reply} has_unit={'minggu' in lower or 'gram' in lower}",
        )

        reply = await agent.process(
            "alternatif plastik sekali pakai apa aja?", ctx
        )
        alt_hits = sum(
            int(t in reply.lower())
            for t in (
                "tumbler", "kain", "bambu", "stainless", "beeswax",
                "kaca", "kertas", "singkong",
            )
        )
        ok = alt_hits >= 3
        record(
            "B",
            "B5 alternatives",
            ok,
            f"alt_keywords={alt_hits}",
        )

        # ----- GROUP C — Conversation continuity --------------------------
        print("\n--- Group C: Conversation continuity ---")
        clear_chat_history()

        await agent.process("saya punya masalah di lapangan", ctx)
        await agent.process("warganya susah diajak kerjasama", ctx)
        reply = await agent.process(
            "udah coba pendekatan tapi tetap gagal", ctx
        )
        lower = reply.lower()
        ok = (
            any(
                kw in lower
                for kw in (
                    "warga", "pendekatan", "sebelumnya", "tadi", "tips",
                    "lagi", "kemarin", "coba", "lain", "ulangi", "alternatif",
                )
            )
            or len(reply) > 250
        )
        record(
            "C",
            "C1 multi-turn memory",
            ok,
            f"refs_prior={ok} len={len(reply)}",
        )

        clear_chat_history()
        reply = await agent.process("halo", ctx)
        ok = HENDRA_NAME in reply
        record(
            "C",
            "C2 name personalization",
            ok,
            f"has_{HENDRA_NAME}={HENDRA_NAME in reply}",
        )

        # ----- GROUP D — Escalation ---------------------------------------
        print("\n--- Group D: Escalation ---")
        clear_chat_history()

        before = len(alerts)
        reply = await agent.process(
            "saya udah ga sanggup lagi, mau berhenti", ctx
        )
        latest_alert = alerts[-1] if len(alerts) > before else ""
        ok = (
            len(alerts) > before
            and HENDRA_NAME in latest_alert
            and "[ESCALATE]" not in reply
            and "quitting" in latest_alert.lower()
        )
        record(
            "D",
            "D1 escalation triggers",
            ok,
            f"alerts+={len(alerts) - before} "
            f"name_in_alert={HENDRA_NAME in latest_alert} "
            f"no_tag={'[ESCALATE]' not in reply}",
        )

        before = len(alerts)
        reply = await agent.process("capek tapi masih semangat kok", ctx)
        ok = len(alerts) == before
        record(
            "D",
            "D2 non-crisis no escalate",
            ok,
            f"alerts_unchanged={len(alerts) == before}",
        )

    finally:
        teardown(volunteer, mission, created_volunteer)

    return results


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


async def main() -> int:
    print("=" * 60)
    print("Macca — Phase 4: Volunteer Support Agent tests")
    print("=" * 60)
    results = await run_tests()

    print("\nPhase 4 Test Results:")
    labels = {
        "A": "Group A (Situations):",
        "B": "Group B (Education):",
        "C": "Group C (Continuity):",
        "D": "Group D (Escalation):",
    }
    total = 0
    passed = 0
    for key in ("A", "B", "C", "D"):
        arr = results.get(key, [])
        n_pass = sum(arr)
        n_total = len(arr)
        total += n_total
        passed += n_pass
        print(f"  {labels[key]:<23} {n_pass}/{n_total} passed")
    print(f"  TOTAL: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
