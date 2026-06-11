"""Phase 2 routing tests: verify the RouterAgent classifies volunteer messages correctly.

Run from the project root:
    python backend/tests/test_phase2.py

Requires a filled .env (makes real Claude Haiku calls — 10 short classifications).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.agents.router_agent import RouterAgent

# Non-fasilitator id so classification (not the fasilitator short-circuit) is exercised
TEST_TELEGRAM_ID = 999000111

TEST_CASES = [
    ("halo apa tugas saya?", "mission_briefing"),
    ("laporan 15 kg gondangdia", "progress_tracker"),
    ("saya mau keluar dari program", "volunteer_support"),
    ("gimana cara laporan?", "mission_briefing"),
    ("sudah berapa total yang terkumpul?", "impact_analyzer"),
    ("buatkan caption buat instagram", "content_creator"),
    ("capek nih", "volunteer_support"),
    ("target saya berapa kg?", "mission_briefing"),
    ("20 kilo plastik dari menteng", "progress_tracker"),
    ("plastik pet itu apa?", "mission_briefing"),
]

PASS = "✅ PASS"
FAIL = "❌ FAIL"


async def main() -> int:
    print("=" * 60)
    print("Macca — Phase 2 routing tests")
    print("=" * 60)

    router = RouterAgent()
    context = {"telegram_id": TEST_TELEGRAM_ID, "chat_type": "private"}

    passed = 0
    for message, expected in TEST_CASES:
        actual = await router.process(message, context)
        ok = actual == expected
        passed += ok
        print(f'{PASS if ok else FAIL}  "{message}" → expected {expected}, got {actual}')

    print("\n" + "=" * 60)
    print(f"{passed}/{len(TEST_CASES)} routing tests passed")
    return 0 if passed == len(TEST_CASES) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
