"""Election system end-to-end tests.

Run from the project root::

    .venv/bin/python backend/test_election.py

Writes to the real Supabase project in ``.env`` and cleans up after itself.
``notify_volunteer`` is monkey-patched so no WhatsApp/Telegram is actually sent;
a counter records blast fan-out. Uses a throwaway team so it never touches
real volunteers.

Requires election migrations 0008–0013 applied.
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.agents.services.notifications as notif  # noqa: E402
from backend.database.supabase_client import db  # noqa: E402
from backend.main import app  # noqa: F401,E402 — boots Settings

from backend.agents import election_handler as EH  # noqa: E402
from backend.infrastructure.composition_root import (  # noqa: E402
    build_election_repository,
)

PASS = "✅ PASS"
FAIL = "❌ FAIL"

TEAM = f"TEST_ELECT_{uuid.uuid4().hex[:6]}"
OTHER_TEAM = f"TEST_ELECT_{uuid.uuid4().hex[:6]}"

# blast recorder
_blasts: list[tuple] = []


async def _fake_notify(volunteer: dict, text: str) -> None:
    _blasts.append((volunteer.get("id"), text))


results: dict[str, list[bool]] = {}


def check(group: str, name: str, cond: bool, detail: str = "") -> None:
    results.setdefault(group, []).append(bool(cond))
    print(f"{PASS if cond else FAIL}  {name}" + (f"  — {detail}" if detail else ""))


def _mk_volunteer(name: str, phone: str, team: str) -> dict:
    row = (
        db.table("volunteers")
        .insert(
            {
                "name": name,
                "phone": phone,
                "team": team,
                "area": "Test",
                "is_active": True,
            }
        )
        .execute()
        .data[0]
    )
    return row


async def run() -> None:
    notif.notify_volunteer = _fake_notify  # patch fan-out

    repo = build_election_repository()

    # 5 members in TEAM, 1 in OTHER_TEAM (isolation)
    members = [
        _mk_volunteer(f"Vol{i}", f"628900{uuid.uuid4().hex[:7]}", TEAM)
        for i in range(5)
    ]
    other = _mk_volunteer("Outsider", f"628900{uuid.uuid4().hex[:7]}", OTHER_TEAM)

    # ---------------- GROUP A — setup & approval gate ----------------
    _blasts.clear()
    reply = await EH.start_election_request(TEAM, {})
    check("A", "A1 start = approval request, NO blast",
          ("PENCALONAN" in reply and "Anggota: 5" in reply and not _blasts),
          f"blasts={len(_blasts)}")

    _blasts.clear()
    reply = await EH.open_nomination(TEAM)
    election = await repo.get_active(TEAM)
    check("A", "A2 open_nomination = created + blast",
          (election and election["status"] == "nomination_open" and len(_blasts) == 5),
          f"status={election and election['status']} blasts={len(_blasts)}")
    check("A", "A3 no auto-advance (stays nomination_open)",
          election["status"] == "nomination_open")

    # ---------------- GROUP B — nomination ----------------
    check("B", "B1 parse 'Budi (08123456789)'",
          EH.parse_nomination("Budi (08123456789)") == ("Budi", "08123456789"))
    check("B", "B2 parse 'Budi Santoso (628123456789)'",
          EH.parse_nomination("Budi Santoso (628123456789)") == ("Budi Santoso", "628123456789"))

    r = await EH.try_handle_nomination(members[0], "Sari (08111111111)")
    nom = await repo.get_nomination(election_id=election["id"], nominator_id=str(members[0]["id"]))
    check("B", "B3 nominate → recorded + thank-you",
          (r and "tercatat" in r and nom is not None))

    r2 = await EH.try_handle_nomination(members[0], "Andi (08222222222)")
    check("B", "B4 nominate AGAIN → rejected (locked)",
          (r2 and "sudah mencalonkan" in r2.lower()))

    r3 = await EH.try_handle_nomination(members[1], "nama tanpa nomor")
    nom1 = await repo.get_nomination(election_id=election["id"], nominator_id=str(members[1]["id"]))
    check("B", "B5 bad format → error, not counted",
          (r3 and "format" in r3.lower() and nom1 is None))

    r4 = await EH.try_handle_nomination(other, "Sari (08111111111)")
    check("B", "B6 no active election for team → None (normal routing)",
          r4 is None)

    # B7 race — direct duplicate insert must raise (UNIQUE)
    raced = False
    try:
        await repo.add_nomination(
            election_id=election["id"], nominator_id=str(members[0]["id"]),
            candidate_name="X", candidate_phone="628000", candidate_volunteer_id=None,
        )
    except Exception:
        raced = True
    check("B", "B7 race → UNIQUE blocks 2nd", raced)

    # Seed a clear tally: candidate A=3, B=2, C=1 (+ pos-3 tie later handled separately)
    await EH.try_handle_nomination(members[1], "Kandidat A (08333333333)")
    await EH.try_handle_nomination(members[2], "Kandidat A (08333333333)")
    await EH.try_handle_nomination(members[3], "Kandidat B (08444444444)")
    # members[0] already nominated Sari, members[4] nominates A → A=3, Sari=1, B=1
    await EH.try_handle_nomination(members[4], "Kandidat A (08333333333)")

    # ---------------- GROUP C — nomination tally ----------------
    _blasts.clear()
    reply = await EH.close_nomination(TEAM)
    election = await repo.get_latest(TEAM)
    finalists = await repo.get_finalists(election_id=election["id"])
    check("C", "C1 close → rekap to fasilitator, status closed",
          ("REKAP" in reply and election["status"] == "nomination_closed"))
    check("C", "C2 top-3 saved as finalists",
          (len(finalists) == 3 and finalists[0]["candidate_phone"] == "628333333333"),
          f"top={finalists[0]['candidate_name']} n={finalists[0]['nomination_count']}")
    check("C", "C4 close does NOT blast volunteers", not _blasts, f"blasts={len(_blasts)}")

    # ---------------- GROUP D — voting ----------------
    _blasts.clear()
    reply = await EH.open_voting(TEAM)
    election = await repo.get_active(TEAM)
    check("D", "D1 open_voting → top-3 blasted, status voting_open",
          (election and election["status"] == "voting_open" and len(_blasts) == 5))

    r = await EH.try_handle_vote(members[0], "1")
    vote0 = await repo.get_vote(election_id=election["id"], voter_id=str(members[0]["id"]))
    check("D", "D2 vote '1' → recorded slot-1 + thank-you",
          (r and "tercatat" in r and vote0 is not None
           and vote0["candidate_phone"] == finalists[0]["candidate_phone"]))

    r = await EH.try_handle_vote(members[1], finalists[1]["candidate_name"])
    vote1 = await repo.get_vote(election_id=election["id"], voter_id=str(members[1]["id"]))
    check("D", "D3 vote by name → matched",
          (r and "tercatat" in r and vote1["candidate_name"] == finalists[1]["candidate_name"]))

    r = await EH.try_handle_vote(members[0], "2")
    check("D", "D4 vote AGAIN → rejected (locked)", (r and "sudah vote" in r.lower()))

    # D5 vote self — members[2] votes slot 1 (allowed regardless of identity)
    r = await EH.try_handle_vote(members[2], "1")
    check("D", "D5 vote allowed (incl. self)", (r and "tercatat" in r))

    # D6 race — direct duplicate vote raises
    raced = False
    try:
        await repo.add_vote(
            election_id=election["id"], voter_id=str(members[0]["id"]),
            candidate_phone="628000", candidate_name="X",
        )
    except Exception:
        raced = True
    check("D", "D6 race → UNIQUE blocks 2nd vote", raced)

    # more votes for a clear winner: members 0,2 → slot1; member1 → slot2; 3,4 → slot1
    await EH.try_handle_vote(members[3], "1")
    await EH.try_handle_vote(members[4], "2")
    # tally now: slot1(A) = members 0,2,3 = 3 ; slot2 = members 1,4 = 2

    # ---------------- GROUP E — final result ----------------
    reply = await EH.close_voting(TEAM)
    election = await repo.get_latest(TEAM)
    check("E", "E1 close_voting → ketua=1st, wakil=2nd reported",
          ("KETUA:" in reply and "WAKIL" in reply and election["status"] == "voting_closed"))

    reply = await EH.finalize_election(TEAM)
    election = await repo.get_latest(TEAM)
    check("E", "E3 finalize → completed + ketua/wakil saved",
          (election["status"] == "completed" and election.get("ketua_name")
           and election.get("wakil_name")),
          f"ketua={election.get('ketua_name')} wakil={election.get('wakil_name')}")

    # E4 per-team isolation — OTHER_TEAM election votes never counted in TEAM
    other_el = await repo.create(team=OTHER_TEAM, status="voting_open")
    await repo.add_vote(election_id=other_el["id"], voter_id=str(other["id"]),
                        candidate_phone="628999", candidate_name="Ghost")
    team_votes = await repo.list_votes(election_id=election["id"])
    ghost_leaked = any(v["candidate_name"] == "Ghost" for v in team_votes)
    check("E", "E4 per-team isolation (no cross-team votes)", not ghost_leaked)

    # ---------------- GROUP F — dashboard mirror (endpoint) ----------------
    # F1: the admin endpoint dispatches to the SAME election_handler functions.
    from backend.main import admin_election_action  # noqa
    import inspect
    src = inspect.getsource(admin_election_action)
    f1 = all(fn in src for fn in [
        "open_nomination", "close_nomination", "open_voting",
        "close_voting", "finalize_election", "announce_result",
    ])
    check("F", "F1 endpoint calls same handler funcs", f1)
    # F3: cancel from a non-completed state → get_active excludes it
    db.table("elections").update({"status": "cancelled"}).eq("id", other_el["id"]).execute()
    still_active = await repo.get_active(OTHER_TEAM)
    check("F", "F3 cancel → excluded from active", still_active is None)

    # ---------------- C3 — tie at position 3 (dedicated) ----------------
    TIE_T = f"TEST_ELECT_{uuid.uuid4().hex[:6]}"
    tie_el = await repo.create(team=TIE_T, status="nomination_open")
    seed = [("A", "628a"), ("A", "628a"), ("B", "628b"), ("C", "628c"), ("D", "628d")]
    for (nm, ph), m in zip(seed, members):
        await repo.add_nomination(
            election_id=tie_el["id"], nominator_id=str(m["id"]),
            candidate_name=nm, candidate_phone=ph, candidate_volunteer_id=None,
        )
    reply = await EH.close_nomination(TIE_T)  # A=2, B/C/D tie at 1 (pos 3 tie)
    check("C", "C3 tie at position 3 → flagged", "seri di posisi 3" in reply.lower())

    # ---------------- E2 — tie at top (dedicated) ----------------
    TIE_T2 = f"TEST_ELECT_{uuid.uuid4().hex[:6]}"
    tie_el2 = await repo.create(team=TIE_T2, status="voting_open")
    vseed = [("X", "628x"), ("X", "628x"), ("Y", "628y"), ("Y", "628y")]
    for (nm, ph), m in zip(vseed, members):
        await repo.add_vote(election_id=tie_el2["id"], voter_id=str(m["id"]),
                            candidate_phone=ph, candidate_name=nm)
    reply = await EH.close_voting(TIE_T2)  # X=2, Y=2 tie top
    check("E", "E2 tie at top → flagged", "seri di posisi teratas" in reply.lower())

    print("\n(Note: D2a–d & F2 are Streamlit UI — verified manually. Vote rows "
          "store voter_id + candidate; dashboard progress query reads voter_id "
          "only, so who-voted-for-whom is not shown.)")

    # cleanup
    ids = [m["id"] for m in members] + [other["id"]]
    for el in {election["id"], other_el["id"], tie_el["id"], tie_el2["id"]}:
        db.table("election_votes").delete().eq("election_id", el).execute()
        db.table("election_finalists").delete().eq("election_id", el).execute()
        db.table("election_nominations").delete().eq("election_id", el).execute()
    db.table("elections").delete().in_(
        "team", [TEAM, OTHER_TEAM, TIE_T, TIE_T2]
    ).execute()
    db.table("volunteers").delete().in_("id", ids).execute()
    print("🧹 cleaned up fixtures")


async def main() -> int:
    print("=" * 60)
    print("Macca — Election system tests")
    print("=" * 60)
    try:
        await run()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\nFATAL: {exc}")
        return 1

    print("\nElection Test Results:")
    total = passed = 0
    for key in sorted(results):
        arr = results[key]
        total += len(arr)
        passed += sum(arr)
        print(f"  Group {key}: {sum(arr)}/{len(arr)} passed")
    print(f"  TOTAL: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
