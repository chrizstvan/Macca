# Macca

Volunteer coordination platform powered by Claude AI and Telegram.

## Structure

```
Macca/
├── backend/
│   ├── agents/          # Claude-powered specialist agents
│   ├── channels/        # Telegram bot handler
│   ├── database/        # Supabase models and client
│   ├── utils/           # Image upload, impact scoring, scheduler
│   ├── main.py          # FastAPI app + webhook endpoint
│   └── config.py        # Environment-based configuration
├── dashboard/           # (coming soon)
├── .env.example
└── .gitignore
```

## Setup

```bash
cp .env.example .env
# Fill in all values in .env

pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

## Environment Variables

See `.env.example` for the full list. All variables are required.

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `TELEGRAM_BOT_TOKEN` | BotFather token |
| `WEBHOOK_URL` | Public HTTPS URL for the Telegram webhook |
| `FASILITATOR_TELEGRAM_ID` | Chat ID that receives escalation alerts |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon or service-role key |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret |

## Agents

| Agent | Responsibility |
|---|---|
| `RouterAgent` | Classifies intent and dispatches to the right agent |
| `MissionBriefingAgent` | Generates volunteer mission briefings |
| `ProgressTrackerAgent` | Analyses progress updates and flags blockers |
| `VolunteerSupportAgent` | Answers volunteer FAQs and queries |
| `ContentCreatorAgent` | Writes social posts, reports, and campaign copy |
| `ImpactAnalyzerAgent` | Quantifies and narrates mission outcomes |
| `FasilitatorHubAgent` | Operational summaries and tools for fasilitators |
