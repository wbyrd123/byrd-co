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

## Backlog
- P0: Redeploy production to activate Postmark env vars
- P1: Automatic reminder emails when client docs missing X days
- P1: Dashboard "Email Status" indicator
- P2: Tighten DMARC to p=quarantine after 2-4 weeks
- P3: Real Marketplace (lender self-onboarding + term-sheet capture)
