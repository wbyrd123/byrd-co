# Byrd & CO — Product Requirements

## Original problem statement
Commercial Real Estate Broker website + client portal + broker admin + Deal Engine + token-gated lender view, transactional emails.

## Personas
- Wayne / Caleb Byrd — brokers (admins)
- Sponsors / borrowers — clients
- Lenders — token-gated read-only viewers

## Core features (built)
- Public marketing site (Home)
- Client portal: docs checklist + uploads, status tracking
- Admin dashboard: clients, scenarios, lenders, quotes, guide
- Deal Engine / Scenario Builder w/ financial metrics + PDF
- Lender directory + match engine
- Token-gated Lender View with watermark, soft gate, audit trail, PDF download
- Google Ads Portal (staff internal tool)
- Postmark transactional emails
- **Per-share per-document visibility (Include / On Request / Hidden)** — 2026-02
- **ZIP bundle download** for admins and lenders (audit-logged for lenders) — 2026-02
- **AI Deal Engine assistant (Claude Sonnet 4.5)** — 3-mode chat (Interview / Parse / Analyst) available as a dedicated "AI Assist" tab and floating chat FAB; streams tokens, proposes structured scenario updates with one-click Apply, and recommends lenders from the directory — 2026-02
- **Data-model refactor: loan_type belongs to Scenario, not Client** — removed loan_type from Add Client form + client roster; each client page now shows a "Loan Scenarios" strip listing all their deals with per-scenario loan type/amount/status, plus a "New Scenario" quick-create — 2026-02
- **New Scenario dialog** — Top-level "+ New Scenario" now opens a dialog that lets you name it and optionally link a client + pick loan type in one shot — 2026-02
- **Testimonials CRUD admin page** — Add / edit / publish/draft / reorder / delete testimonials from `/admin/testimonials`; public homepage reads from DB, seeded with the original 4 quotes so nothing disappears — 2026-02

## Backlog
- P0: Redeploy production to activate Postmark env vars
- P1: Automatic reminder emails when client docs missing X days
- P1: Dashboard "Email Status" indicator
- P2: Tighten DMARC to p=quarantine after 2-4 weeks
- P3: Real Marketplace (lender self-onboarding + term-sheet capture)
