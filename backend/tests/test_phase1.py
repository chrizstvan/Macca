"""Phase 1 smoke tests: database, Telegram bot, and API health.

Run from the project root:
    python backend/tests/test_phase1.py

Requires a filled .env and (for the health check) the API running locally,
e.g.: uvicorn backend.main:app
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

from backend.config import settings
from backend.database.supabase_client import db

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
TABLES = ("volunteers", "missions", "volunteer_missions", "reports", "chat_history", "notifications")
TEST_TELEGRAM_ID = 999000111  # distinctive fake id, cleaned up after the test

PASS = "✅"
FAIL = "❌"


def test_supabase_tables() -> bool:
    """1. Verify the Supabase connection and that all 6 tables exist."""
    print("\n--- Test 1: Supabase connection & tables ---")
    all_ok = True
    for table in TABLES:
        try:
            db.table(table).select("id").limit(1).execute()
            print(f"{PASS} table '{table}' exists and is queryable")
        except Exception as exc:
            print(f"{FAIL} table '{table}': {exc}")
            all_ok = False
    return all_ok


def test_volunteer_insert_retrieve() -> bool:
    """2. Insert a test volunteer, retrieve it, then clean up."""
    print("\n--- Test 2: volunteer insert & retrieve ---")
    try:
        # Clean up any leftover from a previous failed run
        db.table("volunteers").delete().eq("telegram_id", TEST_TELEGRAM_ID).execute()

        inserted = (
            db.table("volunteers")
            .insert(
                {
                    "telegram_id": TEST_TELEGRAM_ID,
                    "name": "Test Volunteer",
                    "area": "Test Area",
                    "quota_kg": 10,
                }
            )
            .execute()
        )
        if not inserted.data:
            print(f"{FAIL} insert returned no data")
            return False
        print(f"{PASS} inserted test volunteer (id={inserted.data[0]['id']})")

        fetched = (
            db.table("volunteers")
            .select("*")
            .eq("telegram_id", TEST_TELEGRAM_ID)
            .execute()
        )
        if not fetched.data or fetched.data[0]["name"] != "Test Volunteer":
            print(f"{FAIL} retrieved record does not match inserted data")
            return False
        print(f"{PASS} retrieved test volunteer by telegram_id")

        db.table("volunteers").delete().eq("telegram_id", TEST_TELEGRAM_ID).execute()
        print(f"{PASS} cleaned up test volunteer")
        return True
    except Exception as exc:
        print(f"{FAIL} volunteer insert/retrieve: {exc}")
        return False


async def test_telegram_bot() -> bool:
    """3. Verify the bot token and send a test message via the Telegram API."""
    print("\n--- Test 3: Telegram bot ---")
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base}/getMe")
            data = resp.json()
            if not data.get("ok"):
                print(f"{FAIL} getMe failed: {data}")
                return False
            print(f"{PASS} bot token valid: @{data['result']['username']}")

            resp = await client.post(
                f"{base}/sendMessage",
                json={
                    "chat_id": settings.fasilitator_telegram_id,
                    "text": "🧪 Macca Phase 1 test — bot can send messages.",
                },
            )
            data = resp.json()
            if not data.get("ok"):
                print(f"{FAIL} sendMessage to fasilitator failed: {data}")
                return False
            print(f"{PASS} test message sent to fasilitator ({settings.fasilitator_telegram_id})")
            return True
    except Exception as exc:
        print(f"{FAIL} Telegram bot test: {exc}")
        return False


async def test_health_endpoint() -> bool:
    """4. Verify GET /health returns 200."""
    print("\n--- Test 4: /health endpoint ---")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{API_BASE_URL}/health")
        if resp.status_code == 200:
            print(f"{PASS} /health returned 200: {resp.json()}")
            return True
        print(f"{FAIL} /health returned {resp.status_code}")
        return False
    except Exception as exc:
        print(f"{FAIL} /health unreachable at {API_BASE_URL} ({exc}) — is uvicorn running?")
        return False


async def main() -> int:
    print("=" * 50)
    print("Macca — Phase 1 smoke tests")
    print("=" * 50)

    results = {
        "Supabase tables": test_supabase_tables(),
        "Volunteer insert/retrieve": test_volunteer_insert_retrieve(),
        "Telegram bot": await test_telegram_bot(),
        "/health endpoint": await test_health_endpoint(),
    }

    print("\n" + "=" * 50)
    print("Summary")
    print("=" * 50)
    for name, ok in results.items():
        print(f"{PASS if ok else FAIL} {name}")

    failed = sum(1 for ok in results.values() if not ok)
    print(f"\n{len(results) - failed}/{len(results)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
