# Macca

Volunteer coordination platform for plastic-collection missions, powered by
Claude and reachable via WhatsApp Cloud API + Telegram.

The codebase follows a **Clean Architecture** layering inspired by Hexagonal /
Onion / Ports & Adapters. Domain rules sit at the center; everything that
talks to the network (Supabase, Anthropic, Meta, Telegram) lives on the
outside ring and depends inward. New channels or LLM providers slot in by
adding an adapter — no business-logic change required.

---

## Project structure

```
Macca/
├── backend/
│   ├── domain/                          # Innermost ring: entities, value
│   │   ├── entities/                    # objects, domain errors. Pure
│   │   │   ├── volunteer.py             # stdlib. No framework imports.
│   │   │   ├── mission.py
│   │   │   ├── report.py
│   │   │   └── score.py
│   │   ├── value_objects/
│   │   │   ├── phone.py                 # Phone (E.164-ish, parse + invariants)
│   │   │   ├── kg.py                    # Kg (0 < value ≤ 999, enforced)
│   │   │   └── persona.py               # Persona / Channel enums
│   │   └── errors.py
│   │
│   ├── application/                     # Middle ring: use cases + ports.
│   │   ├── ports/                       # Protocols the use cases need.
│   │   │   ├── volunteer_repository.py        # entity (command side)
│   │   │   ├── volunteer_query_repository.py   # dict read-model (query side)
│   │   │   ├── mission_repository.py
│   │   │   ├── report_repository.py
│   │   │   ├── score_repository.py
│   │   │   ├── chat_history_repository.py
│   │   │   ├── fasilitator_context_repository.py
│   │   │   ├── llm_client.py
│   │   │   ├── outbound_sender.py
│   │   │   ├── photo_verifier.py
│   │   │   └── clock.py
│   │   └── use_cases/
│   │       ├── submit_report.py         # Migrated (Pass G)
│   │       ├── brief_mission.py         # Migrated
│   │       └── _prompts.py
│   │
│   ├── infrastructure/                  # Outermost ring: adapters.
│   │   ├── persistence/                 # Supabase-backed repositories.
│   │   │   ├── supabase_volunteer_repo.py
│   │   │   ├── supabase_mission_repo.py
│   │   │   ├── supabase_report_repo.py
│   │   │   └── supabase_chat_history_repo.py
│   │   ├── llm/anthropic_client.py      # Claude SDK adapter.
│   │   ├── vision/photo_verifier_adapter.py
│   │   ├── system/utc_clock.py
│   │   └── composition_root.py          # Wires concrete adapters → use cases.
│   │
│   ├── agents/                          # Thin presentation layer over use
│   │   ├── router_agent.py              # cases. Decorator-based intent
│   │   ├── mission_briefing.py          # registry (Pass E). Each specialist
│   │   ├── progress_tracker.py          # declares its intent + examples
│   │   ├── volunteer_support.py         # next to the class.
│   │   ├── content_creator.py
│   │   ├── impact_analyzer.py
│   │   ├── fasilitator_hub/             # Package: agent.py + mixins
│   │   │                                #   (commands / consult / relay / queries)
│   │   ├── intent_registry.py
│   │   ├── prompts/                     # Per-agent system prompts.
│   │   └── services/                    # Cross-cutting agent services:
│   │       ├── pending_state.py         #   multi-turn in-memory store
│   │       └── notifications.py         #   WA-primary, TG-fallback alerts
│   │
│   ├── channels/                        # Inbound + outbound channel handlers.
│   │   ├── base_handler.py              # InboundReceiver + OutboundSender
│   │   ├── telegram_handler.py          #   ABCs (Pass D ISP split).
│   │   ├── telegram_channel_handler.py  # OutboundSender-only TG wrapper.
│   │   ├── whatsapp_handler.py          # Full WA Cloud API handler.
│   │   └── __init__.py                  # Channel factory.
│   │
│   ├── utils/                           # Shared infrastructure helpers.
│   │   ├── http_dispatcher.py           # One httpx wrapper (Pass B).
│   │   ├── phone_utils.py               # normalize_phone (Pass A).
│   │   ├── date_utils.py                # parse / format helpers (Pass A).
│   │   ├── query_utils.py               # shared Supabase queries (Pass A).
│   │   ├── ranking_calculator.py        # Score + leaderboard logic.
│   │   ├── impact_calculator.py         # kg → bottles / CO₂ / water.
│   │   ├── image_handler.py             # Cloudinary uploads.
│   │   ├── photo_verifier.py            # Claude vision verifier.
│   │   └── scheduler.py                 # APScheduler wrapper.
│   │
│   ├── database/                        # Supabase client singleton.
│   ├── tests/                           # phase1–3 smoke tests.
│   ├── main.py                          # FastAPI app + webhooks + scheduler.
│   └── config.py                        # Singleton Settings.
│
├── dashboard/                           # Streamlit fasilitator dashboard
│                                        #   (volunteers, missions, reports,
│                                        #   messages, ranking, content, persona).
├── .env.example
└── .gitignore
```

---

## Architectural rules

* `domain/` imports only from the Python stdlib. No Supabase, no httpx, no
  anthropic, no FastAPI, no telegram.
* `application/` imports from `domain/` only. Use cases depend on **ports**
  (`typing.Protocol`), never concrete adapters.
* `infrastructure/` imports from `domain/`, `application/`, and vendor SDKs.
  Adapter classes implement the application ports structurally.
* `agents/` and `channels/` are the **presentation layer**: they translate
  webhook payloads ↔ use-case / repository calls ↔ user-facing text. They make
  **no `db.table(...)` calls at all** — every read/write goes through a
  repository port obtained from `composition_root.build_xxx()`.
* The composition root (`infrastructure/composition_root.py`) is the only
  module that knows concrete adapter classes. FastAPI routes / agents call
  `build_*()` helpers to obtain a wired-up use case.

```
┌──────────────────────────────────────────────┐
│ infrastructure  (Supabase, anthropic, httpx) │
│  ┌────────────────────────────────────────┐  │
│  │ application  (use cases + ports)       │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │ domain  (entities + invariants)  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
   Dependencies always point inward only.
```

---

## Refactor passes

Migration from a "fat agent" codebase to clean architecture happened in 7
passes. Each was shipped independently; older passes don't depend on newer
ones being merged.

| Pass | Theme | Win |
|---|---|---|
| **A** | DRY utilities | `phone_utils`, `date_utils`, `query_utils` replace 4 duplicated helpers. |
| **B** | HTTP wrapper | One `http_dispatcher` replaces 6 inline httpx blocks across channels + alerts. |
| **C** | Split progress_tracker | Pending state, notifications, repository extracted to `agents/services/`. |
| **D** | ISP on channels | `InboundReceiver` vs `OutboundSender` split. `TelegramHandler` no longer pretends to receive. |
| **E** | Intent registry | Decorator-based; specialist agents declare their intent + examples next to the class. Router prompt regenerated from registry. |
| **F** | Domain layer | Entities (`Volunteer`, `Mission`, `Report`, `Score`) + value objects (`Phone`, `Kg`, `Persona`) + ports as Protocols. |
| **G** | Use cases + adapters | `SubmitReport` and `BriefMission` use cases wired through `composition_root`. WhatsApp inbound + Google form + mission-briefing all run through them. |

---

## Migrated use cases

| Use case | What it does | Outcome ADT |
|---|---|---|
| `SubmitReport` | Validates kg + location, classifies duplicates, runs photo verification, persists report, updates mission totals. | `Saved` / `NeedsPhoto` / `PhotoRejected` / `DuplicateClarificationNeeded` |
| `BriefMission` | Loads volunteer profile + active mission + progress kg, enforces daily 2-query cap (via `Volunteer.consume_mission_query`), generates Claude reply, persists chat history. | `Brief(text, is_last_free_query)` / `QuotaCapped` / `NotRegistered` |

These two encapsulate the heavier business logic (validation, duplicate
classification, photo verification, quota enforcement). Every **other** agent
path — progress/rank inquiries, fasilitator status/strategy/relay, analytics,
content — now reads and writes exclusively through **repository ports**
(`VolunteerQueryRepository`, `ReportRepository`, `MissionRepository`,
`ChatHistoryRepository`, `FasilitatorContextRepository`) via
`composition_root.build_xxx()`. No agent or channel touches `db.table(...)`
directly.

---

## Setup

```bash
cp .env.example .env
# Fill in all required values in .env

python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Run the database migrations in your Supabase SQL editor
# (see backend/database/ for the schema scripts).

# Start the API + scheduler
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000

# For WhatsApp, expose the webhook publicly
ngrok http --domain=<your-reserved-domain> 8000
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Claude API key |
| `TELEGRAM_BOT_TOKEN` | yes | BotFather token |
| `WEBHOOK_URL` | yes | Public HTTPS URL the bot is reachable at |
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_KEY` | yes | Supabase service-role key |
| `CLOUDINARY_CLOUD_NAME` | yes | For volunteer photo uploads |
| `CLOUDINARY_API_KEY` | yes | |
| `CLOUDINARY_API_SECRET` | yes | |
| `WHATSAPP_PHONE_NUMBER_ID` | for WA | Meta Cloud API phone number ID |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | for WA | Meta WABA ID |
| `WHATSAPP_ACCESS_TOKEN` | for WA | Bearer token (24h temp or 60d System User) |
| `WHATSAPP_VERIFY_TOKEN` | for WA | Shared secret for webhook handshake |
| `FASILITATOR_PHONE` | for WA | Fasilitator's WhatsApp number (628…) |
| `FASILITATOR_TELEGRAM_ID` | for TG | Fasilitator's Telegram chat ID |
| `ACTIVE_CHANNEL` | optional | `telegram` \| `whatsapp` \| `both` (default `telegram`) |
| `TEST_MODE_ENABLED` | optional | Allow `/test_as` impersonation (default `true`) |

---

## Agents (presentation layer)

| Agent | Role |
|---|---|
| `RouterAgent` | Classifies intent (Claude Haiku) and dispatches. Rank/leaderboard + off-topic + pending-state shortcuts bypass the classifier. |
| `MissionBriefingAgent` | Volunteer-persona path delegates to `BriefMission` use case. Fasilitator-persona path remains in the agent (list-all-missions view). |
| `ProgressTrackerAgent` | Chat reports + Google Form submissions delegate to `SubmitReport`. Progress inquiries + rank inquiries + pending-state clarifications stay in the agent. |
| `VolunteerSupportAgent` | Topic guardrail + general support replies. |
| `ContentCreatorAgent` | Drafts social posts / announcements (Sonnet). |
| `ImpactAnalyzerAgent` | Quantifies program impact (Sonnet). |
| `FasilitatorHubAgent` | Strategy consultation, psychological guidance, Q&A relay (`/qa`), direct send (`/send`), project context store, leaderboard injection. |

---

## Channels

| Class | Implements | Inbound | Outbound |
|---|---|---|---|
| `WhatsAppHandler` | `BaseChannelHandler` (both ABCs) | yes | yes |
| `TelegramHandler` | `OutboundSender` only | (PTB owns it at `/webhook`) | yes |
| `MultiChannelHandler` | `OutboundSender` only | not applicable | fan-out |

`get_active_handler()` reads `ACTIVE_CHANNEL` and returns the right
`OutboundSender`. Tests can pass fakes to use cases without touching the
factory.

---

## Background jobs

| Job | Schedule | What |
|---|---|---|
| `cleanup_expired_pending` | every 5 min | Drops expired in-memory pending-report states. |
| `RankingCalculator.update_all_rankings` | `0 23 * * *` | Recomputes scores and assigns ranks for every volunteer. |

---

## Tests

```bash
.venv/bin/python backend/tests/test_phase1.py   # Supabase + Telegram + /health
.venv/bin/python backend/tests/test_phase3.py   # Progress tracker end-to-end (16 cases)
```

Phase 3 stubs `PhotoVerifier.verify_or_skip` to `verdict='pass'` so the
text-only test cases don't hit Claude vision.

---

## Why Clean Architecture here?

* **Vendor swap freedom.** Replacing Supabase with Postgres-native or
  swapping Anthropic for another LLM provider = one new adapter, one line
  in `composition_root`. Use cases never change.
* **Domain rules are unit-testable.** `Kg(-1)` raises `InvalidKg`,
  `Report.classify_against` returns `DuplicateVerdict` — both in
  microseconds, no fixtures.
* **Channel-agnostic.** Both WhatsApp and Telegram drive the same use
  cases. Adding LINE / SMS = new channel handler implementing
  `BaseChannelHandler`. No use-case change.
* **Reasoning by layer.** Looking at `backend/domain/` tells you the
  business rules without grepping for `db.table(...)` calls.

The data flow is the same for every path:

```
WhatsApp/Telegram webhook
    → channel handler (parses payload)
    → router agent (classifies intent)
    → specialist agent (presentation)
    → use case (heavy business logic)  ─┐
      or repository port (reads/writes) ─┤→ ports (interfaces)
    → infrastructure adapters            ┘
    → Supabase / Anthropic / Meta
```

The presentation layer is `db.table`-free: agents either invoke a use case or
call a repository port, never the Supabase client directly. (LLM calls still
use `BaseAgent.call_claude` on some paths and the `AnthropicLLMClient` adapter
on others — that's an orthogonal, in-progress consolidation.)
