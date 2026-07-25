# Byrd & CO — Product Requirements

## Backlog
- P0: Redeploy production (`byrd-co.com`) to ship Ada/Proforma/CRM-tags/Marketplace/Postmark-unlock/PortalPolish/MultiSponsor/MultiFileUploads/BulkUpload/LenderTerms live.
- P1: Automatic reminder emails when client docs missing X days
- P2: Postmark inbound routing → route replies back into Personal Assistant
- P2: Tighten DMARC to p=quarantine after 2-4 weeks
- P2: Rate-limit `/public/lender/apply` and `/public/password-reset/request` (basic per-IP throttle)
- P2: Automated weekly Postmark lender-activity summary emails
- P2: Postmark notification to borrower when broker uploads a doc on their behalf
- P3: Refactor `server.py` (~7,700 lines) into modular routes


### Financials Tab + Executive Loan Summary — SHIPPED 2026-02
Phase 1 + Phase 2 built in one push per user request. Owner-occupied support included.

**Backend:**
- `PropertyInfo.occupancy_type` field: `owner_occupied` | `non_owner_occupied` | null.
- New schema: `scenario.financials.periods[]` (per-column tax return / P&L / pro forma), `selected_period_id`, `uw_assumptions` (rate/amort/term — broker-forced, independent from borrower target).
- `compute_scenario_metrics` prefers the selected period for NOI/DSCR/DebtYield; legacy `financials.gross_income` block is fallback.
- Endpoints: GET/POST/PATCH/DELETE `/admin/scenarios/{sid}/financials/periods{/{pid}}`, POST `/select`, PATCH `/assumptions`, POST `/parse-doc` (Ada reads tax return/P&L PDF via Claude Sonnet 4.5 + pypdf, strips depreciation/interest add-backs, returns structured proposal).
- Executive Summary section: PDF via ReportLab with map (OSM static, free), Census demographics (U.S. Census ACS 5-year, free), sponsor snapshot, up to 4 photos (`db.summary_photos` collection), broker narrative, occupancy chip, pro-forma badge. Endpoints: GET/PATCH `/summary`, POST/DELETE/GET `/summary/photos{/{pid}}`, POST `/summary/generate`, POST `/summary/save-to-portal` (pins doc with `order=-1000`, `lender_visibility=included`, replaces prior file on regen).

**Frontend:**
- `AdminFinancialsTab.jsx` (new): multi-column period grid, UW rate inputs, add-period chooser (manual OR Ada upload+parse), inline editing, delete confirm, executive summary section with narrative textarea, photo grid (drag+drop-ready), toggle controls, Preview PDF & Save to Portal buttons.
- `AdminScenarioDetail.jsx`: new "Financials" tab in the nav, Occupancy Type dropdown added to Package tab (`data-testid=pr-occupancy-type`).

**Test results:** 19/19 backend endpoints pass. Frontend E2E verified (financials tab renders, UW inputs persist, add/select/delete periods, preview PDF opens, save-to-portal pins doc). See `/app/test_reports/iteration_11.json`.

**Deferred hardening (non-blocking):** replace label-based summary doc lookup with a `system_key` field; fix pre-existing `<span>-inside-<option>` warning from visual editor instrumentation; refactor `server.py` (~9k lines).


### Lender View Reframe — Facts vs Preferences — SHIPPED 2026-02
Removed rate-dependent metrics from the lender review screen so lenders aren't shown a "target rate" that biases their pricing.
- **Zone 1 (top metrics strip):** 7 objective tiles — Loan Requested, Purchase, Value, LTV, LTC, NOI, Debt Yield. Debt Yield is rate-independent (NOI ÷ loan) so it's the safe deal-quality metric.
- **Zone 2 (below):** "Borrower's Preferred Structure" card — Loan Type, Amount, Amortization, Term, Recourse. Subheading clarifies these are preferences, not commitments.
- **Removed from lender view:** Requested Rate, Monthly P&I, DSCR (all rate-dependent), Annual DS. These stay in admin/internal screens and PDFs.
- **File:** `LenderView.jsx` only. Server-side PDF (`render_scenario_pdf`) is unchanged — it's shared between admin's internal working copy and the lender's downloadable PDF; future work if desired.


### Admin Delete Term Sheet — SHIPPED 2026-02
Broker can now delete individual quote submissions from the admin scenario's Term Sheets tab.
- **Backend**: `DELETE /admin/term-sheets/{tid}` — hard-deletes the term_sheet doc + any attached `term_sheet_files` blob. Removes it from both admin and borrower views. Lender is NOT notified.
- **Frontend**: Trash icon (top-right of each term sheet card in `AdminScenarioDetail.jsx > TermSheetsTab`) opens a confirmation modal with the lender name and a "cannot be undone" warning. `data-testid=ts-delete-{id}` / `ts-delete-confirm`.

### Lender Confidentiality Acknowledgement + Bulk Upload — SHIPPED 2026-02
**Lender terms (LIGHTWEIGHT — v2 iteration):** Full Non-Circumvention Agreement pulled from the lender registration flow to avoid triggering bank legal reviews during DB-building phase. Replaced with a per-package Confidentiality Acknowledgement at the lender-view gate.
- **Backend**: `LenderApplyBody.terms_accepted` is now Optional and no longer enforced. `LENDER_TERMS_*` constants updated to a 4-point confidentiality acknowledgement (no non-circumvention clause, no signature — just borrower confidentiality + purpose limitation + Byrd introduction courtesy). `LenderGate` requires `acknowledged:true` on every session. Backend enforces via 400 "Please acknowledge the confidentiality notice…". Audit trail on `share_views`: `acknowledged_version`, `acknowledged_at`, `acknowledged_ip`, `acknowledged_user_agent`.
- **Frontend**: `LendersApplyPage.jsx` — terms section fully removed; form goes straight to Submit. `LenderView.jsx` gate — new Confidentiality panel below the 3 identity fields with scrollable text + acknowledgement checkbox; "View Package" disabled until checked.
- **Rationale**: broker's borrower relationship is already protected via the borrower's signed Fee Agreement (which includes non-circumvention). The lender-side heavy agreement was creating a "escalate-to-legal" bottleneck during DB seed phase. Keep it light for now; can bring back a stronger version later once relationships are established.

**Bulk Upload Zone (admin scenario Documents tab):** Broker can drag-and-drop many files at once; each auto-matches to the right doc line by filename regex; auto-created new lines on-the-fly; every file uploaded uses the admin upload-on-behalf endpoint (tagged uploaded_by='broker').
- **Component**: `/app/frontend/src/byrd/BulkUploadZone.jsx`. Dashed-orange drop zone, browse-files button, per-file dropdown (target doc line / create new / skip), auto-match confidence indicator, per-row status (pending/uploading/done/error), progress counters ("N auto-matched • N uploaded • N pending"), Clear All, per-row remove.
- **Auto-match rules**: normalizes filename separators (`_`, `-`, `.`) → spaces, then regex-matches against PFS, tax returns (with year → picks Year 1/2/3), bank statements, gov ID, resume/bio, entity docs (LLC/EIN/operating agreement/W-9), rent roll, T-12, PSA/purchase contract, insurance, appraisal, survey, photos. Tax-return year-to-slot inference uses current year math.
- **Verified**: dragged 3 files (`PFS_2024.txt`, `Tax_Return_2023.txt`, `Drivers_License.txt`) → all 3 auto-matched to correct lines → uploaded → status flipped to "Uploaded" → BROKER badge shown on each file row. End-to-end tested via browser automation.

### Multi-File Uploads Per Doc Line — SHIPPED 2026-02
Every doc line item now accepts many files (e.g., 3 years of tax returns, multi-page entity docs). Applies uniformly to borrower portal, admin scenario page, and lender view.
- **Schema**: `client_docs.files: [{file_id, filename, content_type, size, uploaded_at, uploaded_by}]`. Legacy `file_id` still tracks the "latest" file for backward compat. Reads use `_ensure_doc_files_meta` which auto-synthesizes a 1-item array from legacy rows.
- **Endpoints added/changed**: `POST /client/docs/{doc_id}/upload` now appends (was: replace). New `DELETE /client/docs/{doc_id}/files/{file_id}` (borrower) and `POST/DELETE /admin/scenarios/{sid}/docs/{doc_id}/upload|files/{fid}` (broker upload-on-behalf + surgical file delete). New `GET /lender-view/{token}/doc/{doc_id}/zip` bundles every file on one line. `/lender-view/{token}/doc/{doc_id}` accepts `?file_id=` to fetch a specific attachment; all-docs zip and admin `docs.zip` now iterate every file (not just latest).
- **Auth helper**: `_resolve_client_doc_for_user` lets linked sponsors upload/delete on their own doc lines even when the doc row's legacy `client_id` field differs. Ada's finalize-into-doc-line path (`_ada_apply_upload`) now uses the same helper for symmetry and preserves prior files.
- **Frontend**: ClientPortal.jsx renders `files[]` with per-file delete + "Add file" button. AdminScenarioDetail.jsx renders per-file list with "+ Add another file", per-row delete icon, and BROKER/ADA badges on uploaded_by. LenderView.jsx shows a "N files" chip; multi-file lines get "Download all" (zip); single-file lines keep "View".
- **Cascade**: doc deletion, scenario deletion, and client deletion all now clear every underlying `client_files` row (both legacy `file_id` and every entry in `files[]`).
- **Verified by testing agent (iteration 10): 16/16 pytest cases** covering borrower multi-upload as linked sponsor, admin upload-on-behalf, single-file delete, status transitions (`pending↔uploaded`), scenario docs.zip across lines, lender view file_count/files/file_id/per-doc zip/all-docs zip, legacy backward-compat empty-row handling, and cascade delete.

### Multi-Sponsor Architecture — SHIPPED 2026-02
Deals now support multiple sponsors with role-based doc scoping. Anyone with ≥20% ownership is auto-flagged as a guarantor and gets their own document channel + fee agreement.
- **Data model**: `scen.sponsors[]` array (replaces single `scen.sponsor`; legacy shape auto-migrates on read via `_ensure_sponsors_array`). Each sponsor: `{id, name, entity, credit_score, liquidity, net_worth, ownership_pct, role: "managing"|"guarantor"|"passive", is_guarantor, client_user_id}`. Only one `managing` per scenario — enforced on create + patch (auto-demotes prior managing).
- **Doc scoping**: `client_docs.sponsor_id` — `null` = shared (property/business, all sponsors + lenders see); set = personal (only that sponsor's linked client sees). Auto-tagged at scenario creation: personal-category items → managing sponsor, everything else → shared.
- **Admin UX**: Package tab has a repeating Sponsors card with "+ Add Sponsor", per-card role/guarantor toggle + **Link to Client Account dropdown** (grants portal access). Documents tab has a "Viewing docs for" filter dropdown + inline sponsor selector on every doc row + "Shared" chip.
- **Client portal**: `/client/me` filters strictly by sponsor scope. If Alice is linked as one sponsor and Bob's docs are scoped to him, Alice cannot see Bob's docs (even when she's also the scenario's primary `client_id`). Every sponsor with a `client_user_id` gets their own personalized doc pile.
- **Fee agreement per-sponsor**: send endpoint accepts `sponsor_id`; a separate `Signed Fee Agreement` doc line is created per sponsor. Prior sent-to-same-sponsor agreements are superseded. Sponsors without a linked client account cannot be sent to (returns 400).
- **Lender view**: `pkg.sponsors[]` returns sanitized fields (name, entity, ownership%, role, is_guarantor, FICO, liquidity, net worth) — no `client_user_id` leak. LenderView.jsx renders each sponsor as a card with a Managing/Guarantor/Passive chip.
- **Admin Guide** updated: Scenarios card has new Step 2.5 (multi-sponsor), Step 3 rewritten (per-sponsor doc scoping + filter dropdown), Fee Agreement Step 1 rewritten (sponsor dropdown).
- **Verified by testing agent (iteration 9): 13/13 pytest cases + 18/18 prior regression tests = 31/31 total.**
- **No more auto-invite on client creation** — `POST /admin/invites` no longer sends the welcome email. Broker now triggers manually via new **Send Portal Invite** button on the client detail page (`/admin/clients/{id}`) or the Add Client dialog. Prevents the "client got a welcome email before broker could set up scenarios/fee agreement" bug. New endpoint: `POST /admin/users/{uid}/send-invite` (reuses unused token or generates a new one).
- **Password reset flow** — works for all 3 roles (admin/client/lender). New endpoints: `POST /public/password-reset/request` (uniform 200 response, no email disclosure), `GET /public/password-reset/{token}` (verify + masked email), `POST /public/password-reset/{token}` (set new password, invalidates other unused tokens). 60-min token expiry, one-time use. New pages `/portal/forgot-password` and `/portal/reset-password/:token`. "Forgot password?" link added to `/portal/login`. Postmark template `tmpl_password_reset` added.
- **"New Construction" property type** — added to shared `PROPERTY_TYPES` list (`dealData.js`) + Lender Marketplace apply page + lender portal credit box.
- **Guide updated** — Clients section rewritten with the manual-invite flow + Forgot Password mention.


## Original problem statement
Commercial Real Estate Broker website + client portal + broker admin + Deal Engine + token-gated lender view, transactional emails.

## Personas
- Wayne / Caleb Byrd — brokers (admins)
- Sponsors / borrowers — clients
### Portal polish + Password Reset — SHIPPED 2026-02

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

### Lender Marketplace — SHIPPED 2026-02 (extended with activity + notes 2026-03)
Complete self-registration + credit-box + term-sheet marketplace. New surfaces:
- **Public** `/lenders/apply` — public application form (institution, primary contact, credit box). Confirmation email via Postmark. Public footer link "Become a Lending Partner" wired.
- **Admin** — new "Marketplace applications" card at top of `/admin/lenders` with Approve/Reject buttons. Approve creates a `role='lender'` user + one-time activation link + Postmark email.
- **Lender** — `/lender/activate/:token` (password setup) → `/lender/portal` (3 tabs: My Credit Box · Active Invites · My Term Sheets). Full structured term-sheet form (17 fields including rate_type, floating index/spread, LTV/LTC, amort, term, IO, recourse, prepay, fees, expiration, contingencies).
- **Term sheet flow** — lender submits → admin sees on scenario's new **Term Sheets tab** side-by-side w/ Accept/Counter/Pass actions → borrower sees them in their portal under each scenario. Broker notes visible to both lender (via Postmark) AND borrower (in portal).
- **Auto-match invites** — Scenario Lenders tab shows a green "Marketplace Matches" card with self-registered approved lenders that fit; one-click Invite per lender or "Invite all N". Never auto-sends without broker confirmation.
- **Personal Assistant hook** — when a term sheet is submitted, Ada (admin PA) gets a task "Review term sheet from {lender} on {scenario}".
- **Role isolation verified**: lender ≠ admin ≠ client. `require_lender` dep guards `/lender/*` routes.
- **Data model additions**: `lenders.approval_status` (pending/approved/rejected), `lenders.self_registered`, `lenders.owner_user_id`; new collections `term_sheets`, `lender_activation_tokens`; `users.role='lender'`.
- **Bug fix (blocker for the Lenders tab)**: `AdminScenarioDetail.LendersTab` referenced an undefined `attached` var (leftover from docs refactor) — was crashing the whole tab to blank. Fixed.
- **Admin Guide** — new "Lender Marketplace" section with 6-step walkthrough.
- **Verified by testing agent (iteration 8): 25/25 backend pytest cases PASS + all critical frontend flows.**

### Personal Assistant is "Ada" + contact tag updates — SHIPPED 2026-02
- Assistant identifies as **Ada** — the SAME persona as the borrower concierge inside the client portal. One unified AI brand across broker and borrower portals; system prompt tells her not to explain the two-hat setup unless asked.
- **New `contact_updates` block** — Ada can now add tags (or replace tags, append/overwrite notes) on contacts already in the CRM. Handler `_apply_contact_updates` resolves by `id` > `email` > case-insensitive `name`. Additive `add_tags` preserves existing tags; `set_tags` replaces the whole set. Frontend renders a green "CRM Updated" card with the tags that were added.
- **`contacts_index` now includes `id` and current `tags`** so Ada can (a) reference contacts precisely, (b) skip re-adding tags a contact already has.
- **Anti-hallucination guardrail** — the system prompt now includes a hard rule: NEVER claim to have added/tagged/updated/sent anything unless the corresponding fenced block is emitted in the SAME reply. This was the root cause of "she said okay it's done and nothing happened" — the LLM used to write "Done!" without emitting the mutation block.
- Handles the mixed case ("add my existing clients Rod, Jose, Breona to the CRM as borrowers"): Ada pulls their name+email from the `clients` roster, emits `new_contacts` with `tags:['borrower']` for anyone not in CRM, and `contact_updates` (add_tags) for anyone already in it — in the same reply.
- New pytest coverage: 3 cases (identity, contact_updates tags persistence, non-hallucination for unknown contacts) in `test_assistant_new_contacts.py`, all passing alongside the 5 prior tests.

### Ada — Borrower AI Concierge — SHIPPED 2026-02 (updated with Proforma 2026-02)
- New AI assistant embedded at the top of every borrower's portal at `/portal`, powered by Claude Sonnet 4.5. Warm, first-name greeting, quickstart suggestion pills.
- **Ada sees the checklist per turn**: every message dispatch includes a JSON snapshot of all the borrower's scenarios AND for each one the complete `docs` array — label, category, required flag, status (pending/uploaded/approved/rejected), and any broker rejection notes. Manually added doc lines flow through the same `client_docs` collection so Ada recognizes them without any extra config.
- **SEVEN document generators** (as of 2026-02 proforma add): `pfs_sba413` (SBA Form 413), `pfs_byrd` (clean Byrd branded PFS), `resume` (full CRE resume), `sponsor_bio` (1-page), `business_plan` (narrative 2-4 pages), `lox` (Letter of Explanation), `rent_roll` (landscape spreadsheet-style PDF), **`proforma` (5-page underwriting workbook: Property Summary → Income Schedule + EGI → Operating Expenses + NOI → Debt Service + DSCR/Debt Yield + Cash-on-Cash + LTV → 5-Year Cash-Flow Projection with rent/expense growth and terminal-value at exit cap)**. Ada picks pfs_sba413 automatically for SBA loans, pfs_byrd otherwise, borrower can override. Proforma is SEPARATE from business plan — one is numbers, one is narrative; both can be produced for the same deal.
- **Structured blocks**: `generate_doc` (creates ephemeral draft PDF), `upload_confirm` (attaches approved draft to the correct scenario doc line), `broker_note` (posts a task into every admin's assistant queue with the borrower's question).
- **Guardrails hard-coded** in system prompt + verified by testing agent: no loan-term quotes, no qualification claims, no legal/tax/investment advice, no fee negotiation, no cross-borrower data leakage, can only add files to existing lines (broker owns the checklist), can't mark docs Reviewed, can't send email as the borrower.
- **Proactive 3-day silence nudge**: background loop scans daily; if a borrower has pending required docs and no Ada activity in 3+ days, sends a Postmark email inviting them back. Per-borrower 7-day quiet window after each nudge. Manual trigger available at `POST /admin/ada/run-nudges`.
- New collections: `borrower_ada_messages`, `borrower_ada_drafts`, `borrower_ada_nudges`. New endpoints: `GET/POST /client/ada/messages`, `POST /client/ada/chat`, `POST /client/ada/reset`, `POST /admin/ada/run-nudges`.
- Every generated PDF carries: "Prepared with Byrd & CO Ada Assistant · Borrower-attested; not independently verified" — hallucination shield.
- **Verified by testing agent** (iteration 7): 100% backend (8/8 pytest cases including guardrails), 100% frontend Ada flows. Proforma verified 2026-02 via 2 new pytest cases + end-to-end curl (Ada emitted `generate_doc` with `doc_type: proforma` → 8KB PDF rendered → download endpoint served correct bytes).

### Fee Agreement E-Signature — SHIPPED 2026-02 (+ portal signing + certificate v2)
- New **Broker fee & e-signature** card at the top of every scenario's Documents tab. Enter fee %, preview draft PDF (pre-fills borrower name/email/entity, property address+type, loan purpose, agreement date, broker), then send.
- **Send** creates a pinned system-managed "Signed Fee Agreement" doc line (order = -1000, hidden from lenders, protected from deletion + not user-uploadable) and a one-time signing token; emails the borrower a signing link via Postmark.
- **Two signing entry points**, both using the same token: (1) the emailed **Review & Sign** button, (2) a **Sign Now** button on the pinned line inside the borrower's own portal (the `pending_sign_token` is exposed to the borrower only for their own doc).
- Public signing page at `/fee-agreement/{token}` — no auth. Full PDF preview + summary sidebar + typed-name signature form with cursive-style live preview. Consent checkbox restates the fee %.
- On submit, backend renders the fully-executed PDF, appends a **Certificate of Completion** page (document title/date, fee %, borrower typed name/email/UTC timestamp/IP/User-Agent, broker signer/method, ESIGN Act + Texas UETA legal citation), stores it on the doc line as Reviewed, saves a **SHA-256 hash** of the executed PDF for tamper-evidence, and emails confirmations.
- Resend / Cancel available while pending. Signed state shows a "Download Signed" button on the admin card and a "Signed & Executed" panel to the borrower.
- New endpoints: `GET /admin/scenarios/{sid}/fee-agreement/preview.pdf`, `POST /admin/scenarios/{sid}/fee-agreement/send`, `GET /admin/scenarios/{sid}/fee-agreement`, `POST /admin/scenarios/{sid}/fee-agreement/cancel`, `GET /fee-agreement/{token}`, `GET /fee-agreement/{token}/preview.pdf`, `POST /fee-agreement/{token}/sign`.
- New Mongo collection: `fee_agreements`. New scenario field: `broker_fee_pct` (0-10). New doc-line flag: `system: true`. Audit fields on `fee_agreements`: `borrower_signed_ip`, `borrower_signed_user_agent`, `signed_pdf_sha256`.

### Personal Assistant × pipeline coach (stalled deals) — SHIPPED 2026-02
- New backend helper `_stalled_scenarios_for_admin(admin_id)` — flags scenarios in draft/shopping status where the latest activity (max of scenario.updated_at and any doc.updated_at) is 7+ days ago AND fewer than 30% of docs are uploaded.
- Injected into the assistant turn context (`stalled_scenarios`, capped at 8) — Claude can answer "which deals are stuck?" and, per the updated system prompt, will gently mention the top 1-2 the first time in a conversation and offer to draft a follow-up email.
- **Stalled deals banner** on `/admin/assistant` (below the marketing nudge) — subtle red-tinted card that lists each stuck deal with `{days_silent} · {uploaded}/{total} docs ({pct}%)`. Three per-row actions: **Draft follow-up** (prefills a fully-specified prompt into the assistant chat box), **Open** (deep-link to the scenario), **Snooze** (7-day per-admin silence via `scenario_snoozes` collection).
- New endpoints: `GET /admin/assistant/stalled-scenarios`, `POST /admin/assistant/stalled-scenarios/{id}/snooze`.
- Stalled list auto-refreshes after every assistant chat turn — if the broker completes an action inside chat, the banner updates instantly.

### Scenario-owned document folders + client delete — SHIPPED 2026-02
- **Structural change:** document checklists moved from client → scenario. Each loan (Purchase, Refi, Construction, Bridge, SBA) has its own folder now, so a client with two deals (e.g. hotel purchase + MF refi) sees two independent doc lists.
- **Preset checklists** picked at scenario creation: Purchase, Refinance, Construction, Bridge, SBA, or Blank. Broker can then add/remove lines per scenario.
- **Copy between scenarios**: when a doc (like Personal Tax Returns) is relevant for two deals for the same client, the broker can copy the line + the uploaded file from one scenario into another with a picker dialog. Each copy is independent (re-uploading in one doesn't touch the other).
- **Client portal reshape**: borrower now sees one collapsible section per scenario, each with its own progress bar, category grouping, and upload controls.
- **Delete client**: new "Delete client" button on the client detail page. Blocks with a 409 if any scenarios exist ("Delete or reassign them first"), otherwise clean-deletes user + invite + any orphan doc records.
- **Lender visibility** simplified: per-doc `lender_visibility` field (Hidden / On Request / Included) replaces the old `scenario.attached_docs` array. Per-share overrides continue to work by doc_id, no lender-facing breakage.
- **Migration**: one-time startup step wiped legacy client-level docs + files (fresh start per user's request) and cleared stale `attached_docs`/`doc_grants`/`doc_overrides` on all scenarios.
- New endpoints: `GET /admin/scenarios/doc-templates`, `POST/PATCH/DELETE /admin/scenarios/{sid}/docs[/{did}]`, `GET /admin/scenarios/{sid}/docs/copy-source`, `POST /admin/scenarios/{sid}/docs/copy`, `DELETE /admin/clients/{id}`.

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
