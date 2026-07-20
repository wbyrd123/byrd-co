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
- **Personal Assistant (per-admin private Claude bot)** — Wayne and Caleb each get a private chat + task tracker at `/admin/assistant`. Claude addresses them by name, knows today's date, auto-extracts tasks with due dates from conversation, greets with overdue/due-today counts, drafts outbound emails (sent from `wayne@byrd-co.com` / `caleb@byrd-co.com` with review-before-send), suggests adding new names as clients, and marks tasks done when the broker says so — 2026-02
- **Teammate handoffs in the assistant** — say *"Tell Caleb here's Rod's number, call him and interview him for the Ohio loan"* and Claude routes it to Caleb's private assistant as a task with a "→ FROM WAYNE" badge, Wayne's exact note attached, and a due date. Wayne's own reminder task ("Ask Caleb…") auto-completes since it's now handed off. Caleb's greeting auto-mentions handoff count on next login — 2026-02
- **Bidirectional reply on handoff tasks** — Caleb (or any recipient) can click **Reply** on a handoff task, type a status update, and optionally mark the original task done. Reply lands in the original sender's task list as a new task with "→ FROM CALEB" badge and the reply text as the note, keeping full attribution and enabling threaded back-and-forth without leaving the assistant — 2026-02
- **@mention shortcut in the assistant chat** — type `@` to open an autocomplete popover of teammates, filter by first name, hit Tab/Enter or click to insert. Messages that begin with `@Firstname` are auto-routed as handoffs (no need to spell out "Tell Caleb…"). Arrow keys navigate the list, Escape dismisses — 2026-02
- **Email Delivery status widget + Send Test button on the admin Overview** — shows Postmark configuration (from address), 30-day sent/failed counts, last success/failure timestamps, last error text, and a health chip (Healthy / Recent Failures / Not Configured). Includes an inline **Send Test** action (prefilled with `waynebyrd11@gmail.com`, editable) that fires a canary email through Postmark synchronously and shows the exact raw error inline if it fails — includes friendly detection of the common "pending approval" and "sender signature" errors — 2026-02
- **Assistant email send fix** — POST /admin/assistant/email/send now sends via the verified `POSTMARK_FROM` Sender Signature with the admin's real email in Reply-To, returns HTTP 400 (not 502) so Cloudflare passes the JSON error through, and surfaces failures as a persistent inline red "Not sent" banner on the draft card. Every send (test + assistant) is logged in `db.assistant_emails` with status + error for the status widget — 2026-02

## Backlog
- P0: Redeploy production to activate Postmark env vars
- P1: Automatic reminder emails when client docs missing X days
- P2: Postmark inbound routing → route replies back into Personal Assistant
- P2: Tighten DMARC to p=quarantine after 2-4 weeks
- P3: Real Marketplace (lender self-onboarding + term-sheet capture)

### Personal Assistant × CRM (marketing awareness) — SHIPPED 2026-02
- Assistant turn context now injects a compact CRM snapshot: total contacts, tag counts, unsubscribed count, days_since_last_marketing, last marketing subject, and up to 15 stale contacts (never contacted OR contacted 60+ days ago, valid email, not unsubscribed).
- System prompt updated: Claude answers rolodex queries ("who haven't I contacted in 60 days?"), and when 30+ days have passed since the last marketing send, mentions it once and offers to draft a marketing email.
- New `marketing_suggestion` fenced block: Claude drafts marketing emails with `{{first_name}}` + `{{admin_first_name}}` merge tags and a `target_tags` filter. Marketing drafts are separated from `email_draft` (which is transactional 1:1 only).
- **Automatic 30-day cadence:** `GET /admin/assistant/marketing-status` returns `needs_suggestion` = true when 30+ days have passed (or never sent), unless a dismissal happened in the last 7 days (quiet window).
- Assistant page renders a **Marketing Nudge** banner + a **Marketing Suggestion Card** with subject, target audience, body preview, rationale, and three actions: **Regenerate**, **Dismiss** (starts 7-day quiet window), **Open in CRM** (accepts + hands off to Contacts).
- **Open in CRM** flow: navigates to `/admin/contacts?compose=1` with the draft cached in sessionStorage; the CRM auto-opens the ComposeDialog with subject/body pre-filled, target contacts pre-selected by tag (or everyone-with-email when `target_tags=[]`), and a "Draft from your Assistant" banner shown at the top.
- New endpoints: `GET /admin/assistant/marketing-status`, `POST /admin/assistant/marketing-suggestion/generate`, `POST /admin/assistant/marketing-suggestion/{id}/dismiss`, `POST /admin/assistant/marketing-suggestion/{id}/accept`.
- New Mongo collection: `marketing_suggestions` (pending/accepted/dismissed/superseded states).

### P1 · Contacts CRM with Personal Assistant integration — SHIPPED 2026-02
**Delivered:**
- Contacts CRUD (name, email, phone, contact_type multi-select, tags, notes, last_contact_at/channel)
- CSV import (name, email, phone, contact_type, tags, notes headers accepted, comma/pipe multi-values)
- Shared team address book (both Wayne + Caleb see all contacts)
- Email templates admin (4 seeded: New Product Announcement, Rate Update, Quarterly Check-In, Referral Thank-You)
- Bulk marketing send with `{{first_name}}` + `{{admin_first_name}}` personalization, unsubscribe footer, and per-recipient rendering (each gets their own email, not a CC blast)
- Global unsubscribe suppression list with public `/unsubscribe?t=` page
- Marketing sends respect suppression; transactional/assistant sends bypass it (loan correspondence is CAN-SPAM exempt)
- Every send logged in `db.assistant_emails` with `tag=marketing` for the Email Delivery status widget

**Still to do (next session — small enhancement):**
- Wire Personal Assistant to the contacts collection: teach Claude to answer questions like "who haven't I talked to in 60 days?" and to propose bulk sends via a new structured block. Add contacts (name+email only) + template names to the assistant turn context.
**Goal:** A lightweight CRM for Wayne/Caleb to manage relationships (referral sources, past sponsors, prospects) — separate from the tighter "Clients" area which is for active borrowers with document portals.

**Data model** (per admin, private):
- `name` (required)
- `email`
- `phone`
- `contact_type` (multi-select: email · phone · text) — how they prefer to be reached
- `last_contact_at` (date + auto-updated when assistant sends outreach)
- `last_contact_channel` (email / phone / text) — matches what was actually used
- `notes` (freeform)
- `tags` (chips, e.g. "referral source", "past client", "warm lead")
- `owner_admin_id` — Wayne or Caleb

**UI:**
- New sidebar item: **"Contacts"** with icon `Contact` from lucide
- Roster table: name, email, phone, tags, last contact (colored: green <30d, gold 30-90d, red 90d+), preferred channel icons
- Add/Edit dialog with the fields above
- **Bulk selection** with a "Send Marketing Email" button that opens a compose flow

**Assistant integration:**
- Assistant's system prompt gains access to the current admin's contacts (name + email only, not phone/notes to keep tokens tight)
- New assistant capabilities:
  - "Draft a marketing email to my referral sources about the new SBA construction product" → Claude drafts one email + suggests recipients tagged "referral source"
  - "Who haven't I talked to in 60 days?" → Claude answers from `last_contact_at`
  - "Send Rod a follow-up about the docs" → routes through the existing email flow, but marks contact.last_contact_at + contact.last_contact_channel="email"
- Bulk send: assistant proposes one templated email, admin approves once, sends to N recipients with proper `To:` personalization (each gets their own email, not a CC blast). Rate-limited to Postmark's plan cap.

**Notes for build:**
- Reuses the existing Postmark send infra (currently for assistant emails) — needs `bulk_send` variant that iterates + writes to `assistant_emails` log per recipient
- Contact roster is private per admin (like Personal Assistant chat), so Wayne's Rolodex ≠ Caleb's
- Should we let contacts be **imported from a CSV**? Common for onboarding an existing rolodex. Recommend yes as a Phase-1 optional feature.

**Open questions to answer when we start:**
1. Import from CSV on day one, or add later?
2. Private per admin, or a shared team address book with visibility per record?
3. Auto-suppress list — if a client marks unsubscribe, should other admins also be blocked from emailing them?
4. Do you want basic template library ("New product announcement", "Rate update", "Quarterly check-in") or freeform only for MVP?
