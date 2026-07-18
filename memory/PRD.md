# Byrd & CO — Product Requirements Document

## Original Problem Statement
"Commercial Real Estate Broker website for Byrd & CO. Add a lender-shopping platform for personal broker use — scenario builder, lender directory, shareable packages, gated document sharing."

## Product
Marketing site + client document portal + broker admin console + **Deal Engine** (Phase 1 + light Phase 2) + Google Ads Portal (internal marketing tool).

## Personas
- Public visitor → quote form
- Client → invited via link, uploads docs
- Broker (Wayne, Caleb) → invites clients, builds loan scenarios, curates a private lender directory, shops deals via watermarked shareable links, sees audit trail of lender engagement
- Lender (external, no login) → soft-gated view of a scenario package; can request full data room

## Architecture
- Backend: FastAPI + MongoDB (Motor). JWT auth (bcrypt). Base64 file storage (15MB cap). PDF via reportlab.
- Frontend: React 19 + Tailwind + Shadcn/UI. Byrd editorial theme (Playfair Display + gold + charcoal). AdsCopilot scoped Swiss-Brutalist theme preserved.

## Implemented (2026-02)
### Prior iterations
- Public site (hero, programs, properties, principals, testimonials, quote form)
- Auth + client invite + client portal + broker admin console
- Google Ads Portal (internal — formerly AdsCopilot) at `/adscopilot`

### Iteration 3 — Deal Engine
- **Scenario Builder** (`/admin/scenarios`): sponsor, property, loan request, financials, construction, sources & uses, business plan/notes; optional link to a client; status pipeline (draft → shopping → term_sheet → closed / lost).
- **Sizing engine** (pure functions, unit-tested): LTV, LTC, DSCR, Debt Yield, Cash-on-Cash, monthly P&I, annual DS, S&U balance check.
- **Lender Directory** (`/admin/lenders`): private CRM per broker — name, type, contacts, credit box (min/max loan, LTV/LTC/DSCR/DY thresholds), property types, geography, rate range, term, recourse preference, decision speed, fees, notes, status.
- **Match Engine**: scores each lender vs a scenario (fits vs misses); one-click "Share" per match.
- **Scenario Shares**: per-lender token; auto-transitions scenario status; audit log of every action (gate, view_scenario, view_doc, request_docs, download_pdf).
- **Hybrid doc sharing**: attach each client doc as `included` (rides with link) or `on_request` (broker grants per lender).
- **Public lender view** (`/lender/scenario/:token`): soft gate (name + email + institution), 12h session JWT, watermarked overlay ("Institution — Name"), metric grid, S&U, docs (Available Now vs On Request), "Request Full Data Room" button, downloadable watermarked PDF.
- **PDF generation** (reportlab): brand cover, executive summary numbers, property/sponsor/loan detail, S&U, business plan/notes, diagonal watermark on every page + footer stamp with recipient name.

## Test Credentials
See `/app/memory/test_credentials.md`.

## Prioritized Backlog
- **P1** Resend integration → email quote requests + invite links + "you have a new lender view" notifications to broker.
- **P1** Split server.py into modules (auth, byrd_portal, byrd_deal, adscopilot, pricing) — flagged by testing agent, mechanical refactor.
- **P2** Object storage (S3) — replace base64-in-Mongo for large docs.
- **P2** Editable testimonials in admin.
- **P2** Save doc-checklist and scenario templates per loan type.
- **P2** Password reset flow.
- **P2** Unit tests for sizing formulas (test_sizing.py — pin the math).
- **P2** Rate limiting + captcha on `/api/public/quote`.
- **P3** Real Google Ads API (developer token + OAuth) — replace simulated campaigns.
- **P3** Lender-side "quote back" — capture proposed terms inside the link, side-by-side comparison for the broker.
- **P3** Deal-level activity timeline (broker view: "Frost Bank viewed PFS 3× this week").

## Notes / Mocked
- Testimonials: seeded static data.
- Quote form emails: not dispatched (needs Resend key).
- Google Ads campaigns: simulated in Mongo.
- Lender view session JWT is 12h; revoking a share invalidates the token immediately at the share-lookup layer.
