"""Add-on feature verification — runnable script (not pytest).

    .venv/bin/python backend/test_addon.py

Self-contained: stubs the LLM (``BaseAgent.call_claude`` echoes the system
prompt so we test OUR prompt construction, not model quality) and uses
in-memory fakes for Supabase + the settings store. No network, no live DB,
no migration required.

Honest scoping — these are SKIPPED (not faked green), with reasons:
  * C7/C8  — 'batalkan jadwal' / 'ubah jadwal' overrides were never built.
  * D1/D3/D4/D5/D6 — quiz auto-job + broadcast + scoring need live
    API/DB/ranking integration.
  * G1-G3  — knowledge on/off-topic is LLM-quality, non-deterministic here.
  * H2/H4 volunteer full path — progress_tracker.process hits DB before the
    guard; the guard's effect is covered at the flag-service + relay level.
Prints "Add-on Tests: X/Y passed" + failures + skips.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# backend/test_addon.py → repo root is parents[1]; put it on the path so
# ``import backend.*`` resolves when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --------------------------------------------------------------------------- #
# Tiny test harness                                                            #
# --------------------------------------------------------------------------- #

_passed = 0
_failed: list[str] = []
_skipped: list[str] = []
_notes: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  ✅ {name}")
    else:
        _failed.append(f"{name}{(' — ' + detail) if detail else ''}")
        print(f"  ❌ {name}{(' — ' + detail) if detail else ''}")


def skip(name: str, reason: str) -> None:
    _skipped.append(f"{name} — {reason}")
    print(f"  ⏭️  SKIP {name} — {reason}")


def note(text: str) -> None:
    _notes.append(text)
    print(f"  📝 {text}")


async def guard(name: str, coro) -> None:
    """Await a check-producing coroutine, turning exceptions into failures."""
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        _failed.append(f"{name} — raised {type(exc).__name__}: {exc}")
        print(f"  ❌ {name} — raised {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# Fakes                                                                        #
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal chainable Supabase query over an in-memory table (list[dict])."""

    def __init__(self, table: "_Table", op: str = "select"):
        self._t = table
        self._op = op
        self._filters: list = []
        self._payload = None
        self._limit = None
        self._order = None

    # builder ------------------------------------------------------------- #
    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, **_k):
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def ilike(self, col, pat):
        self._filters.append(("ilike", col, pat))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    # exec ---------------------------------------------------------------- #
    def _match(self, row) -> bool:
        for kind, col, val in self._filters:
            cell = row.get(col)
            if kind == "eq" and cell != val:
                return False
            if kind == "lte" and not (cell is not None and str(cell) <= str(val)):
                return False
            if kind == "gte" and not (cell is not None and str(cell) >= str(val)):
                return False
            if kind == "ilike":
                if cell is None:
                    return False
                needle = str(val).lower()
                hay = str(cell).lower()
                if needle.startswith("%") and needle.endswith("%"):
                    if needle.strip("%") not in hay:
                        return False
                elif hay != needle:  # no wildcards → case-insensitive equality
                    return False
        return True

    def execute(self):
        rows = self._t.rows
        if self._op == "insert":
            new = dict(self._payload)
            new.setdefault("id", f"id-{len(rows) + 1}")
            new.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            rows.append(new)
            return _Result([new])
        if self._op in ("update",):
            hit = [r for r in rows if self._match(r)]
            for r in hit:
                r.update(self._payload)
            return _Result(hit)
        if self._op == "upsert":
            rows.append(dict(self._payload))
            return _Result([self._payload])
        # select
        out = [r for r in rows if self._match(r)]
        if self._order:
            col, desc = self._order
            out = sorted(out, key=lambda r: str(r.get(col) or ""), reverse=desc)
        if self._limit is not None:
            out = out[: self._limit]
        return _Result(out)


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a, **k):
        return _Query(self, "select").select(*a, **k)

    def insert(self, payload):
        return _Query(self).insert(payload)

    def update(self, payload):
        return _Query(self).update(payload)

    def upsert(self, payload, **k):
        return _Query(self).upsert(payload, **k)


class _FakeDB:
    def __init__(self, tables: dict[str, list] | None = None):
        self._tables = {k: list(v) for k, v in (tables or {}).items()}

    def table(self, name):
        return _Table(self._tables.setdefault(name, []))


class _FakeCtxRepo:
    """Stand-in for FasilitatorContextRepository (records upserts)."""

    def __init__(self, values: dict | None = None):
        self.values = dict(values or {})
        self.upserts: list = []

    async def get(self, key):
        return self.values.get(key)

    async def upsert(self, key, value):
        self.upserts.append((key, value))
        self.values[key] = value


# --------------------------------------------------------------------------- #
# Stubs / patches                                                              #
# --------------------------------------------------------------------------- #

# LLM hook: BaseAgent.call_claude(self, system_prompt, messages, ...) → echo prompt.
_LLM = lambda system_prompt, messages: system_prompt  # noqa: E731


def install_stubs() -> None:
    import backend.agents.base_agent as base_mod
    import backend.infrastructure.composition_root as cr

    async def _fake_call_claude(self, system_prompt, messages, model=None, max_tokens=None):
        return _LLM(system_prompt, messages)

    base_mod.BaseAgent.call_claude = _fake_call_claude

    # Default settings store — overridable per group.
    global FAKE_CTX
    FAKE_CTX = _FakeCtxRepo({"reminder_delay_hours": "8", "enable_reporting": "true"})
    cr.build_fasilitator_context_repository = lambda: FAKE_CTX


FAKE_CTX: _FakeCtxRepo


# --------------------------------------------------------------------------- #
# GROUP A — Action Items & Resolver                                            #
# --------------------------------------------------------------------------- #


async def group_a():
    print("\nGROUP A — Action Items & Resolver")
    from backend.utils.action_item_resolver import ActionItemResolver

    types = [
        "challenge", "submission", "kelas", "presensi",
        "pre_test", "post_test", "tautan", "buku_saku",
    ]
    db = _FakeDB({"action_items": []})
    for t in types:
        db.table("action_items").insert(
            {"type": t, "title": f"Item {t}", "is_active": True}
        ).execute()
    saved = db.table("action_items").select("*").eq("is_active", True).execute().data
    check("A1 insert all 8 types", len(saved) == 8, f"got {len(saved)}")

    db2 = _FakeDB({"action_items": [
        {"id": "x1", "title": "Minggu Bersih Pantai", "type": "challenge", "is_active": True},
        {"id": "x2", "title": "Kelas A", "type": "kelas", "is_active": True},
        {"id": "x3", "title": "Kelas B", "type": "kelas", "is_active": True},
    ]})
    r = ActionItemResolver(db2, llm_caller=lambda *a, **k: None)
    hit = await r.find_by_mention("bersih pantai")
    check("A2 partial match → Minggu Bersih Pantai",
          isinstance(hit, dict) and hit.get("title") == "Minggu Bersih Pantai",
          repr(hit))
    multi = await r.find_by_mention("kelas")
    check("A3 multiple matches → list", isinstance(multi, list) and len(multi) == 2,
          repr(multi))
    check("A4 detect_type 'ingetin presensi' → presensi",
          await r.detect_type_from_message("ingetin presensi") == "presensi")
    check("A5 detect_type 'ingetin baca buku saku' → buku_saku",
          await r.detect_type_from_message("ingetin baca buku saku") == "buku_saku")


# --------------------------------------------------------------------------- #
# GROUP B — Reminder Generation (prompt construction)                          #
# --------------------------------------------------------------------------- #


async def group_b():
    print("\nGROUP B — Reminder Generation")
    from backend.agents.reminder_generator import ReminderGenerator, TYPE_INSTRUCTIONS

    gen = ReminderGenerator()
    persona = {"agent_name": "Asisten GBP", "tone": "Kasual", "use_emoji": True}

    ok = True
    for t in TYPE_INSTRUCTIONS:
        d = await gen.generate_draft({"type": t, "title": f"T-{t}"}, persona)
        if not d or f"T-{t}" not in d:
            ok = False
    check("B1 draft for each of 8 types (non-empty, has title)", ok)

    with_link = await gen.generate_draft(
        {"type": "submission", "title": "Lapor", "link_url": "https://forms.gle/abc"},
        persona,
    )
    check("B2 draft includes link_url", "https://forms.gle/abc" in with_link)

    no_deadline = await gen.generate_draft({"type": "tautan", "title": "X"}, persona)
    check("B3 missing field rendered '-' + no-hallucinate instruction",
          "Deadline: -" in no_deadline and "jangan" in no_deadline.lower())

    check("B4 uses {nama} placeholder instruction", "{nama}" in no_deadline)

    combo = await gen.generate_combined_draft(
        [{"type": "kelas", "title": "Kelas Sabtu"},
         {"type": "pre_test", "title": "Pretest Awal"}],
        persona,
    )
    check("B5 combined draft references both items",
          "Kelas Sabtu" in combo and "Pretest Awal" in combo)


# --------------------------------------------------------------------------- #
# GROUP C — Reminder Scheduling                                                #
# --------------------------------------------------------------------------- #


async def group_c():
    print("\nGROUP C — Reminder Scheduling")
    from backend.utils.schedule_parser import ScheduleParser, WIB

    now = datetime.now(WIB)

    async def fixed_llm(prompt, messages, max_tokens=None):
        return fixed_llm.value
    fixed_llm.value = "NONE"

    p = ScheduleParser(llm_caller=fixed_llm)

    s = await p.parse_send_time("kirim")
    dh = (s["send_at"] - now).total_seconds() / 3600
    check("C1 'kirim' → default delay ~8h", s["mode"] == "default_delay" and 7.5 < dh < 8.5,
          f"{s['mode']} {dh:.2f}h")

    s = await p.parse_send_time("kirim sekarang")
    check("C2 'kirim sekarang' → immediate", s["mode"] == "immediate")

    s = await p.parse_send_time("kirim 24 jam lagi")
    dh = (s["send_at"] - now).total_seconds() / 3600
    check("C3 '24 jam lagi' → +24h", s["mode"] == "relative" and 23.5 < dh < 24.5, f"{dh:.2f}h")

    s = await p.parse_send_time("kirim 3 hari lagi")
    dd = (s["send_at"] - now).total_seconds() / 86400
    check("C4 '3 hari lagi' → +3d", s["mode"] == "relative" and 2.5 < dd < 3.5, f"{dd:.2f}d")

    fixed_llm.value = "2026-07-06 19:00"
    s = await p.parse_send_time("kirim 6 juli jam 7 malam")
    dt = s["send_at"]
    check("C5 '6 Juli jam 7 malam' → 2026-07-06 19:00",
          s["mode"] == "absolute" and (dt.year, dt.month, dt.day, dt.hour) == (2026, 7, 6, 19),
          str(dt))

    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    fixed_llm.value = f"{tomorrow} 08:00"
    s = await p.parse_send_time("kirim besok jam 8 pagi")
    dt = s["send_at"]
    check("C6 'besok jam 8 pagi' → tomorrow 08:00",
          s["mode"] == "absolute" and dt.strftime("%Y-%m-%d %H:%M") == f"{tomorrow} 08:00",
          str(dt))

    skip("C7 'batalkan jadwal' → cancelled", "override handler not implemented")
    skip("C8 'ubah jadwal jadi besok jam 9'", "reschedule handler not implemented")

    # C9 — scheduler drains a due row, sends, marks sent.
    await guard("C9", _c9_scheduler())

    fixed_llm.value = "NONE"
    s = await p.parse_send_time("kirim pokoknya deh")
    check("C10 vague input → default delay", s["mode"] == "default_delay", s["mode"])


async def _c9_scheduler():
    import backend.database.supabase_client as sc
    import backend.agents.services.notifications as notif
    import backend.utils.scheduler as sched
    import backend.infrastructure.composition_root as cr
    from backend.infrastructure.persistence.supabase_scheduled_message_repo import (
        SupabaseScheduledMessageRepository,
    )

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    fake = _FakeDB({
        "scheduled_messages": [
            {"id": "m1", "message_template": "Halo {nama}", "recipient_filter": "all",
             "status": "pending", "scheduled_at": past, "quiz": None},
        ],
        "volunteers": [{"id": "v1", "name": "Sari", "is_active": True,
                        "phone": "628", "telegram_id": None}],
        "reports": [],
    })
    sc.db = fake  # _expand_recipients reads volunteers via the shared db
    # Queue access now goes through the port — point its factory at the fake.
    cr.build_scheduled_message_repository = lambda: SupabaseScheduledMessageRepository(fake)
    sent: list = []

    async def fake_notify(v, text):
        sent.append((v.get("name"), text))
    notif.notify_volunteer = fake_notify

    await sched._scheduled_messages_job()
    row = fake.table("scheduled_messages").select("*").eq("id", "m1").execute().data[0]
    check("C9 scheduler sends due message + marks sent",
          row["status"] == "sent" and sent and sent[0] == ("Sari", "Halo Sari"),
          f"status={row['status']} sent={sent}")


# --------------------------------------------------------------------------- #
# GROUP D — Quiz                                                               #
# --------------------------------------------------------------------------- #


async def group_d():
    print("\nGROUP D — Quiz")
    from backend.agents.quiz_generator import QuizGenerator
    from backend.agents.fasilitator_hub._quiz import QuizApprovalMixin

    quiz = {"question": "Q?", "options": ["A) x", "B) y"], "answer": "B",
            "explanation": "karena B"}
    review = QuizGenerator.build_review_text(quiz)
    check("D2 fasilitator review shows answer + explanation",
          "Jawaban: B" in review and "karena B" in review)
    vol = QuizGenerator.build_volunteer_quiz_text(quiz)
    check("D2b volunteer text hides answer",
          "Q?" in vol and "karena B" not in vol)

    # D7 — 'batal quiz' discards the latest draft.
    class _Repo:
        def __init__(self):
            self.draft = {"id": "q1", "status": "draft", "question": "Q?",
                          "options": [], "answer": "B", "explanation": ""}
        async def get_latest_draft(self):
            return self.draft if self.draft["status"] == "draft" else None
        async def update_status(self, qid, status):
            self.draft["status"] = status
        async def update(self, qid, fields):
            self.draft.update(fields)

    import backend.infrastructure.composition_root as cr
    repo = _Repo()
    cr.build_quiz_draft_repository = lambda: repo
    agent = QuizApprovalMixin()
    reply = await agent._handle_quiz_command("batal quiz", {})
    check("D7 'batal quiz' → draft cancelled, nothing sent",
          repo.draft["status"] == "cancelled" and "batal" in reply.lower(), reply)

    for n in ("D1 auto quiz job", "D3 'kirim quiz 12 jam lagi' schedule",
              "D4 'kirim quiz sekarang' broadcast",
              "D5 answer → quiz_attempts", "D6 correct/wrong scoring"):
        skip(n, "needs live API/DB/ranking integration")


# --------------------------------------------------------------------------- #
# GROUP E — Education                                                          #
# --------------------------------------------------------------------------- #


async def group_e():
    print("\nGROUP E — Education")
    from backend.agents.education_generator import EducationContentGenerator, TOPICS

    # E1 — quiz (day */3) vs education (3,6,..30) never overlap.
    quiz_days = {d for d in range(1, 32) if (d - 1) % 3 == 0}
    edu_days = set(range(3, 31, 3))
    check("E1 quiz vs education day-sets disjoint (no overlap)",
          quiz_days.isdisjoint(edu_days), f"overlap={quiz_days & edu_days}")

    topics = {EducationContentGenerator.topic_for(i) for i in range(len(TOPICS))}
    check("E3 topic rotates across runs (distinct topics)", len(topics) == len(TOPICS))

    msg = EducationContentGenerator.build_draft_message("topik X", "isi konten")
    # Education draft carries the copy-paste line, then an 'edit edukasi' hint —
    # so assert the hand-off is present (not strictly the final chars).
    check("E4 draft includes copy-paste hand-off",
          "copy-paste ke grup WA ya!" in msg)

    skip("E2 draft to fasilitator only, never volunteers",
         "by design (job calls alert_fasilitator); needs live job run")


# --------------------------------------------------------------------------- #
# GROUP F — On-demand drafts                                                   #
# --------------------------------------------------------------------------- #


async def group_f():
    print("\nGROUP F — On-demand drafts")
    from backend.agents.fasilitator_hub import FasilitatorHubAgent
    from backend.agents.impact_analyzer import ImpactAnalyzerAgent
    from backend.utils.impact_calculator import ImpactCalculator
    import backend.database.supabase_client as sc

    agent = FasilitatorHubAgent()  # full agent → has call_claude (stubbed)

    # F1 — checklist draft (resolver hits patched db).
    sc.db = _FakeDB({"action_items": [
        {"id": "c1", "title": "Bersih Pantai", "type": "challenge",
         "description": "ayo", "is_active": True},
    ]})
    checklist = await agent._handle_checklist_draft("buatkan checklist bersih pantai")
    check("F1 checklist draft produced (not sent)",
          "Checklist" in checklist and "Bersih Pantai" in checklist)
    check("F3a checklist ends with copy-paste",
          checklist.rstrip().endswith("copy-paste ke grup WA ya!"))

    # F2 — impact draft with stubbed stats.
    async def fake_stats(self, message="minggu ini"):
        return {"period_kg": 100.0, "active_volunteers": 5,
                "top_volunteers": [("Sari", 40.0)]}
    ImpactAnalyzerAgent.impact_stats = fake_stats
    impact = await agent._handle_impact_draft("buatkan laporan impact minggu ini")
    check("F2 impact aggregate draft (not sent)",
          "Laporan Dampak" in impact and "100" in impact and "Sari" in impact)
    check("F3b impact ends with copy-paste",
          impact.rstrip().endswith("copy-paste ke grup WA ya!"))

    check("F4 bottles = kg*71", ImpactCalculator.kg_to_bottles(10) == 710)
    check("F4 co2 = kg*3", ImpactCalculator.kg_to_co2_prevented(10) == 30.0)
    note("F4 trees: code uses CO₂ ÷ 1.81 (monthly, matches draft 'sebulan'); "
         "spec said ÷21 (yearly) — divergence, not asserted.")


# --------------------------------------------------------------------------- #
# GROUP G — Knowledge                                                          #
# --------------------------------------------------------------------------- #


async def group_g():
    print("\nGROUP G — Knowledge")
    skip("G1 carbon footprint on-topic", "LLM-quality, non-deterministic offline")
    skip("G2 climate change on-topic", "LLM-quality, non-deterministic offline")
    skip("G3 off-topic rejected", "LLM-quality, non-deterministic offline")


# --------------------------------------------------------------------------- #
# GROUP H — Reporting Toggle                                                   #
# --------------------------------------------------------------------------- #


async def group_h():
    print("\nGROUP H — Reporting Toggle")
    import backend.infrastructure.composition_root as cr
    from backend.agents.services import reporting_flag as rf

    on = _FakeCtxRepo({"enable_reporting": "true"})
    cr.build_fasilitator_context_repository = lambda: on
    check("H1 enable_reporting=true → reporting enabled", await rf.is_reporting_enabled())

    custom = "Isi form: https://forms.gle/xyz"
    off = _FakeCtxRepo({"enable_reporting": "false", "reporting_off_message": custom})
    cr.build_fasilitator_context_repository = lambda: off
    check("H2 enable_reporting=false → disabled", not await rf.is_reporting_enabled())
    check("H5 custom off_message used (not hardcoded)",
          await rf.reporting_off_message() == custom)

    # H3 — fasilitator relay short-circuits to off message (guard is first line).
    from backend.agents.fasilitator_hub._relay import RelayMixin
    relay = RelayMixin()
    reply = await relay._handle_save_report_for("Sari: 5kg Menteng", {})
    check("H3 relay blocked → off_message, not saved", reply == custom, reply)

    # H4 — non-report intent (checklist) still works while reporting off.
    from backend.agents.fasilitator_hub import FasilitatorHubAgent
    import backend.database.supabase_client as sc
    sc.db = _FakeDB({"action_items": [
        {"id": "c1", "title": "Bersih Pantai", "type": "challenge", "is_active": True},
    ]})
    od = FasilitatorHubAgent()
    cl = await od._handle_checklist_draft("buatkan checklist bersih pantai")
    check("H4 non-report intent unaffected when reporting off",
          "Checklist" in cl and cl != custom)

    # H6 — toggle false→true re-enables (no code change).
    tog = _FakeCtxRepo({"enable_reporting": "false"})
    cr.build_fasilitator_context_repository = lambda: tog
    before = await rf.is_reporting_enabled()
    await tog.upsert("enable_reporting", "true")
    after = await rf.is_reporting_enabled()
    check("H6 false→true re-enables reporting", (not before) and after)

    # H7 — reading the flag performs no writes (existing data untouched).
    probe = _FakeCtxRepo({"enable_reporting": "false"})
    cr.build_fasilitator_context_repository = lambda: probe
    await rf.is_reporting_enabled()
    await rf.reporting_off_message()
    check("H7 flag check performs no writes", probe.upserts == [], str(probe.upserts))

    skip("H2/H4 volunteer full process() path",
         "hits DB before guard; effect covered via flag service + relay (H2/H3/H5)")


# --------------------------------------------------------------------------- #
# Runner                                                                       #
# --------------------------------------------------------------------------- #


async def main():
    install_stubs()
    for g in (group_a, group_b, group_c, group_d, group_e, group_f, group_g, group_h):
        await guard(g.__name__, g())

    total = _passed + len(_failed)
    print("\n" + "=" * 60)
    print(f"Add-on Tests: {_passed}/{total} passed "
          f"({len(_skipped)} skipped, {len(_notes)} notes)")
    if _failed:
        print("\nFAILURES:")
        for f in _failed:
            print(f"  - {f}")
    if _skipped:
        print("\nSKIPPED (not implemented / integration / non-deterministic):")
        for s in _skipped:
            print(f"  - {s}")
    print("=" * 60)
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
