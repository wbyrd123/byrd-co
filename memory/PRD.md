# AdsCopilot — Product Requirements Document

## Original Problem Statement
"Can you build a bot to manage and create Google ads?"

## Product
AdsCopilot — an AI copilot for advertisers running Google Ads. Combines a management dashboard with a streaming AI assistant powered by Claude Sonnet 4.5. Operates in **demo mode** (campaigns stored in Mongo; no real Google Ads API connection).

## User Personas
- **Solo marketer / founder** — needs to draft campaigns quickly without agency overhead.
- **In-house performance marketer** — wants a fast copy + keyword ideation sandbox.
- **Agency PM** — reviewing metrics across many client campaigns.

## Architecture
- Backend: FastAPI + MongoDB (Motor). JWT auth (bcrypt). Streaming SSE for chat.
- LLM: Claude Sonnet 4.5 via `emergentintegrations` + `EMERGENT_LLM_KEY`.
- Frontend: React 19 + Tailwind + Shadcn/UI (customized to Swiss Brutalist), Recharts, Sonner.
- Design archetype: Swiss Brutalist — light theme, 2px black borders, hard shadows, no rounding, IBM Plex Mono for data.

## Implemented (2026-02)
- JWT register / login / me
- Campaign CRUD (create, list, detail, patch status/budget, delete)
- Simulated performance metrics per campaign (deterministic seed based on campaign id)
- Analytics overview endpoint with 30-day series
- AI ad copy generator (headlines ≤30c / descriptions ≤90c, JSON schema)
- AI keyword research (match type, intent, volume, CPC, difficulty)
- Streaming chat copilot (SSE) with persistent history
- Frontend: Auth split screen, Sidebar shell + right-side Copilot panel, Overview, Campaigns table, Create Campaign 5-step wizard (with "AI Generate" copy button), Campaign Detail with charts, Ad Copy Studio, Keyword Lab, Analytics

## Prioritized Backlog
- **P1** Real Google Ads API integration (OAuth, developer token, live campaign push/pull)
- **P1** Bulk operations (pause/enable multiple campaigns, CSV export)
- **P2** Negative keyword suggestions endpoint
- **P2** Landing-page audit (LLM reads URL and scores relevance)
- **P2** A/B copy variants w/ tracked winners
- **P2** Budget pacing alerts (email/toast)
- **P2** Multi-account / workspaces
- **P3** Team collaboration (shared sessions)

## Test Credentials
See `/app/memory/test_credentials.md`.
