"""Phase 3 tests: ProgressTrackerAgent end-to-end (chat parsing, flagging,
duplicates, inquiries, Google Form, impact numbers).

Run from the project root:
    python backend/tests/test_phase3.py

Requires a filled .env. Makes real Claude Haiku calls and writes to the real
Supabase database (everything it creates is cleaned up at the end).
Fasilitator alerts are mocked — nothing is sent to Telegram.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

import backend.agents.progress_tracker as pt
from backend.agents.progress_tracker import ProgressTrackerAgent, pending_reports
from backend.database.supabase_client import db
from backend.main import app
from backend.utils.photo_verifier import PhotoVerifier

RIZKI_PHONE = "08123456789"
RIZKI_TELEGRAM_ID = 999000222  # distinctive test id
UNKNOWN_PHONE = "09999999999"
FAKE_PHOTO_URL = "https://res.cloudinary.com/test/phase3-photo.jpg"
QUOTA_KG = 25.0

PASS, FAIL = "✅ PASS", "❌ FAIL"

# Mock fasilitator alerts (validate_and_save and the form webhook both resolve
# this at call time from the module, so patching here covers everything)
alerts: list[str] = []


async def _record_alert(text: str) -> None:
    alerts.append(text)


pt._alert_fasilitator = _record_alert


# Photo verification was added after these tests were written. The test
# suite intentionally exercises text-only reports, so stub the verifier to
# always pass — that keeps the test focused on parsing/validation/flagging
# logic without hitting the real Claude vision API.
async def _photo_pass(self, photo_url, reported_kg, volunteer_area,
                      is_fasilitator_relay, require_photo=True):
    return {"verdict": "pass", "should_flag": False, "flag_reason": None}


PhotoVerifier.verify_or_skip = _photo_pass


# --------------------------------------------------------------------------- #
# Setup / teardown
# --------------------------------------------------------------------------- #

def today_start_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


def setup() -> tuple[dict, dict, bool]:
    """Ensure Rizki (phone 08123456789, area Menteng) + an active 25kg mission."""
    existing = db.table("volunteers").select("*").eq("phone", RIZKI_PHONE).limit(1).execute()
    created_volunteer = not existing.data
    profile = {
        "name": "Rizki",
        "phone": RIZKI_PHONE,
        "area": "Menteng",
        "quota_kg": QUOTA_KG,
    }
    if created_volunteer:
        volunteer = (
            db.table("volunteers")
            .insert({**profile, "telegram_id": RIZKI_TELEGRAM_ID})
            .execute()
            .data[0]
        )
    else:
        volunteer = (
            db.table("volunteers")
            .update(profile)
            .eq("id", existing.data[0]["id"])
            .execute()
            .data[0]
        )

    mission = (
        db.table("missions")
        .insert(
            {
                "title": "Phase 3 Test Mission",
                "description": "Temporary mission created by test_phase3.py",
                "deadline": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
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
            "assigned_area": "Menteng",
        }
    ).execute()

    mission["quota_kg"] = QUOTA_KG
    mission["assigned_area"] = "Menteng"
    return volunteer, mission, created_volunteer


def teardown(volunteer: dict, mission: dict, created_volunteer: bool) -> None:
    clear_reports(volunteer["id"])
    db.table("volunteer_missions").delete().eq("mission_id", mission["id"]).execute()
    db.table("missions").delete().eq("id", mission["id"]).execute()
    db.table("chat_history").delete().eq("telegram_id", volunteer["telegram_id"]).execute()
    if created_volunteer:
        db.table("volunteers").delete().eq("id", volunteer["id"]).execute()
    pending_reports.clear()
    print("\n🧹 Cleaned up test reports, mission, and chat history")


def clear_reports(volunteer_id: str) -> None:
    (
        db.table("reports")
        .delete()
        .eq("volunteer_id", volunteer_id)
        .gte("reported_at", today_start_iso())
        .execute()
    )


def latest_report(volunteer_id: str) -> dict | None:
    rows = (
        db.table("reports")
        .select("*")
        .eq("volunteer_id", volunteer_id)
        .order("reported_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def reports_today(volunteer_id: str) -> list[dict]:
    return (
        db.table("reports")
        .select("*")
        .eq("volunteer_id", volunteer_id)
        .gte("reported_at", today_start_iso())
        .execute()
        .data
        or []
    )


# --------------------------------------------------------------------------- #
# Test groups
# --------------------------------------------------------------------------- #

async def run_tests() -> dict[str, list[bool]]:
    volunteer, mission, created_volunteer = setup()
    agent = ProgressTrackerAgent()
    ctx = {
        "telegram_id": volunteer["telegram_id"],
        "chat_type": "private",
        "volunteer": volunteer,
        "mission": mission,
    }
    results: dict[str, list[bool]] = {}

    def record(group: str, name: str, ok: bool, detail: str) -> None:
        results.setdefault(group, []).append(ok)
        print(f"{PASS if ok else FAIL}  {name}: {detail}")

    try:
        # ----- GROUP A — chat report parsing --------------------------------
        print("\n--- Group A: Chat report parsing ---")
        clear_reports(volunteer["id"])

        await agent.process("laporan 18 kg menteng", ctx)
        r = latest_report(volunteer["id"]) or {}
        ok = (
            float(r.get("kg_collected", 0)) == 18
            and "menteng" in str(r.get("location", "")).lower()
            and r.get("source") == "telegram"
            and not r.get("is_flagged")
        )
        record("A", "A1 standard format", ok,
               f"kg={r.get('kg_collected')} location={r.get('location')!r} "
               f"source={r.get('source')} flagged={r.get('is_flagged')}")

        await agent.process("udah nih 12 kilo di gondangdia kak", ctx)
        r = latest_report(volunteer["id"]) or {}
        ok = float(r.get("kg_collected", 0)) == 12 and "gondangdia" in str(r.get("location", "")).lower()
        record("A", "A2 casual format", ok,
               f"kg={r.get('kg_collected')} location={r.get('location')!r}")

        await agent.process("laporan 7.5 kg cikini", ctx)
        r = latest_report(volunteer["id"]) or {}
        ok = float(r.get("kg_collected", 0)) == 7.5 and "cikini" in str(r.get("location", "")).lower()
        record("A", "A3 decimal weight", ok,
               f"kg={r.get('kg_collected')} location={r.get('location')!r}")

        # A4 — photo without details (clear first so A5's 18kg isn't a duplicate of A1)
        clear_reports(volunteer["id"])
        reply = await agent.process("laporan foto", {**ctx, "photo_url": FAKE_PHOTO_URL})
        pending = pending_reports.get(volunteer["telegram_id"])
        ok = "?" in reply and pending is not None and pending["data"].get("photo_url") == FAKE_PHOTO_URL
        record("A", "A4 photo without text", ok,
               f"asked={'?' in reply} pending_step={pending['step'] if pending else None}")

        reply = await agent.process("18 kg menteng", ctx)
        r = latest_report(volunteer["id"]) or {}
        ok = float(r.get("kg_collected", 0)) == 18 and r.get("photo_url") == FAKE_PHOTO_URL
        record("A", "A5 complete pending report", ok,
               f"kg={r.get('kg_collected')} photo_url={r.get('photo_url')!r}")

        # ----- GROUP B — flagging -------------------------------------------
        print("\n--- Group B: Flagging ---")
        clear_reports(volunteer["id"])

        n_alerts = len(alerts)
        await agent.process("laporan 60 kg menteng", ctx)
        r = latest_report(volunteer["id"]) or {}
        reason = str(r.get("flag_reason") or "")
        ok = (
            r.get("is_flagged") is True
            and ("melebihi" in reason or "kuota" in reason.lower())
            and len(alerts) == n_alerts + 1
        )
        record("B", "B1 weight > 2x quota", ok,
               f"flagged={r.get('is_flagged')} reason={reason!r} alert_sent={len(alerts) == n_alerts + 1}")

        await agent.process("laporan 10 kg kemayoran", ctx)
        r = latest_report(volunteer["id"]) or {}
        reason = str(r.get("flag_reason") or "")
        ok = r.get("is_flagged") is True and "area" in reason.lower() and float(r.get("kg_collected", 0)) == 10
        record("B", "B2 wrong area (still saved)", ok,
               f"flagged={r.get('is_flagged')} reason={reason!r} saved_kg={r.get('kg_collected')}")

        n_alerts = len(alerts)
        await agent.process("laporan 15 kg menteng", ctx)
        r = latest_report(volunteer["id"]) or {}
        ok = r.get("is_flagged") is False and len(alerts) == n_alerts
        record("B", "B3 normal report (no flag)", ok,
               f"flagged={r.get('is_flagged')} new_alerts={len(alerts) - n_alerts}")

        # ----- GROUP C — duplicate detection --------------------------------
        print("\n--- Group C: Duplicate detection ---")
        clear_reports(volunteer["id"])

        reply = await agent.process("laporan 10 kg menteng", ctx)
        ok = len(reports_today(volunteer["id"])) == 1 and "Tambahan" not in reply
        record("C", "C1 first report of the day", ok,
               f"reports_today={len(reports_today(volunteer['id']))}")

        reply = await agent.process("laporan 10.5 kg menteng", ctx)
        pending = pending_reports.get(volunteer["telegram_id"])
        ok = (
            "tambahan" in reply.lower()
            and pending is not None
            and pending["step"] == "waiting_confirmation"
            and len(reports_today(volunteer["id"])) == 1
        )
        record("C", "C2 similar report asks A/B", ok,
               f"pending_step={pending['step'] if pending else None} "
               f"reports_today={len(reports_today(volunteer['id']))}")

        await agent.process("tambahan", ctx)
        count = len(reports_today(volunteer["id"]))
        record("C", "C3 confirm as additional", count == 2, f"reports_today={count}")

        # ----- GROUP D — progress inquiry -----------------------------------
        print("\n--- Group D: Progress inquiry ---")
        clear_reports(volunteer["id"])
        pending_reports.clear()

        await agent.process("laporan 10 kg menteng", ctx)
        reply = await agent.process("sudah berapa kg saya?", ctx)
        db_total = sum(float(r["kg_collected"]) for r in reports_today(volunteer["id"]))
        ok = f"{db_total:g}" in reply and f"{QUOTA_KG:g}" in reply
        record("D", "D1 inquiry matches DB sum", ok,
               f"db_total={db_total:g} quota_in_reply={f'{QUOTA_KG:g}' in reply}")

        # Fresh slate so the 3-tier duplicate clarifier (Pass-C) doesn't
        # turn the second report into a confirmation prompt instead of a
        # save — D1's 10 kg row would otherwise trigger ambiguous match.
        clear_reports(volunteer["id"])
        pending_reports.clear()
        await agent.process("laporan 18 kg menteng", ctx)
        reply = await agent.process("progress saya gimana?", ctx)
        ok = "18" in reply and "72%" in reply  # 18/25 = 72%
        record("D", "D2 total + percentage", ok,
               f"has_18={'18' in reply} has_72pct={'72%' in reply}")

        # ----- GROUP E — Google Form source ----------------------------------
        print("\n--- Group E: Google Form ---")
        clear_reports(volunteer["id"])

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/webhook/google-form",
                json={
                    "phone": RIZKI_PHONE,
                    "kg": "20",
                    "location": "Menteng",
                    "form_type": "laporan_plastik",
                },
            )
            body = resp.json()
            r = latest_report(volunteer["id"]) or {}
            ok = (
                body.get("status") == "ok"
                and "✅" in body.get("confirmation", "")
                and r.get("source") == "google_form"
                and float(r.get("kg_collected", 0)) == 20
            )
            record("E", "E1 valid form submission", ok,
                   f"status={body.get('status')} source={r.get('source')} kg={r.get('kg_collected')}")

            n_alerts = len(alerts)
            n_reports = len(reports_today(volunteer["id"]))
            resp = await client.post(
                "/webhook/google-form",
                json={"phone": UNKNOWN_PHONE, "kg": "5", "location": "Menteng"},
            )
            body = resp.json()
            ok = (
                body.get("status") == "unknown_volunteer"
                and len(alerts) == n_alerts + 1
                and len(reports_today(volunteer["id"])) == n_reports
            )
            record("E", "E2 unknown phone", ok,
                   f"status={body.get('status')} alert_sent={len(alerts) == n_alerts + 1}")

        # ----- GROUP F — impact calculation ----------------------------------
        print("\n--- Group F: Impact calculation ---")
        clear_reports(volunteer["id"])
        pending_reports.clear()

        reply = await agent.process("laporan 18 kg menteng", ctx)
        ok = "1,278" in reply and "54.0" in reply  # 18*71 bottles, 18*3 kg CO2
        record("F", "F1 impact numbers in confirmation", ok,
               f"has_1278_bottles={'1,278' in reply} has_54_co2={'54.0' in reply}")

    finally:
        teardown(volunteer, mission, created_volunteer)

    return results


async def main() -> int:
    print("=" * 60)
    print("Macca — Phase 3: Progress Tracker tests")
    print("=" * 60)

    results = await run_tests()

    labels = {
        "A": "Group A (Parsing):    ",
        "B": "Group B (Flagging):   ",
        "C": "Group C (Duplicates): ",
        "D": "Group D (Inquiry):    ",
        "E": "Group E (Form):       ",
        "F": "Group F (Impact):     ",
    }
    print("\nPhase 3 Test Results:")
    total_pass = total = 0
    for group, label in labels.items():
        outcomes = results.get(group, [])
        passed = sum(outcomes)
        total_pass += passed
        total += len(outcomes)
        print(f"  {label} {passed}/{len(outcomes)} passed")
    print(f"  TOTAL: {total_pass}/{total} passed")
    return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
