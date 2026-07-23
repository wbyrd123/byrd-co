# Byrd & CO — Preview → Production Release Checklist

**Preview URL:** `https://google-ads-auto-2.preview.emergentagent.com`
**Production URL:** `https://byrd-co.com`
**Admin login:** `wayne@byrd-co.com` / `byrdco2026`
**Test client login:** `sample@example.com` / `sample123`

Run this checklist on **preview first**. When every box is checked, contact Emergent Support to redeploy preview → production. This bundle covers Ada rename, Proforma, CRM tag updates, Lender Marketplace, Postmark unlock, manual portal invites, password reset, "New Construction" property type, and multi-sponsor architecture with per-sponsor fee agreements.

---

## 1. Ada (Both Portals — Single Persona Rename)

- [ ] `/admin/assistant` — ask "What's your name?" → she says **Ada**
- [ ] Client portal (`/portal`) — Ada chat still labeled Ada with same personality
- [ ] Ada answers questions about scenario docs (context-aware per turn)
- [ ] Ada refuses to make loan qualification claims (guardrail)

## 2. Proforma Generator

- [ ] Log in as `sample@example.com` → open Ada → ask "Build me a proforma"
- [ ] Ada asks for property + income + expenses → generates 5-page PDF
- [ ] "Approve & Upload" attaches PDF to the correct scenario doc line
- [ ] PDF renders sections: Property Summary → Rent Roll → OpEx → NOI → 5-Year Projection

## 3. CRM Tag Updates

- [ ] `/admin/assistant` — say "Add a tag called 'borrower' to Jane Doe in the CRM"
- [ ] Green **"CRM Updated"** card appears in chat
- [ ] Refresh `/admin/contacts` → Jane Doe now has `borrower` tag
- [ ] Try tagging a non-existent contact — Ada should NOT confabulate success

## 4. Lender Marketplace

- [ ] Public **`/lenders/apply`** — form submits, "Application received" success page
- [ ] `/admin/lenders` — new "Marketplace applications" card appears
- [ ] **Approve** button → activation email fires (check `contact@testfrost.example` in Postmark logs if you're testing with a real address)
- [ ] Activation link → set password → lands in `/lender/portal`
- [ ] Lender portal: 3 tabs render (**Credit Box → Active Invites → Term Sheets**)
- [ ] Edit credit box → refresh → changes persist
- [ ] On admin scenario Lenders tab: green **"Marketplace Matches"** card appears with matched approved lenders + one-click Invite
- [ ] Lender sees the invite → **Submit Term Sheet** with full 17 fields
- [ ] Admin scenario → new **Term Sheets tab** shows submission side-by-side
- [ ] Click **Counter with note** → modal opens → confirm → status changes to "countered"
- [ ] Borrower opens their portal → sees the term sheet + broker note on that scenario

## 5. Postmark (Live — no longer sandbox)

- [ ] Send a test email from `/admin` Email Status widget → arrives in inbox
- [ ] Fee agreement email lands in a real inbox (no bounces)
- [ ] Ada 3-day nudge fires for borrowers with pending docs

## 6. Client Portal — Manual Invite Flow

- [ ] `/admin/clients` → **+ Add Client** with a fake email
- [ ] Verify: NO email is sent immediately (only the copy-link + "Send Portal Invite" buttons appear)
- [ ] Go to `/admin/clients/{id}` → click **"Send Portal Invite"** button → confirmation toast
- [ ] Client receives the email at that point (not before)
- [ ] Try "Copy Link" as an alternative — pastes silently

## 7. Password Reset

- [ ] `/portal/login` → **"Forgot password?"** link visible
- [ ] Click → `/portal/forgot-password` → enter any email → confirmation screen
- [ ] For `sample@example.com`: grab the reset token from your inbox (or DB during test) → click `/portal/reset-password/:token`
- [ ] Set new password → auto-logged in → routed to correct portal (client/lender/admin)
- [ ] Try the same token again — should show "Link already used" (410)
- [ ] Login with old password fails; new password works

## 8. "New Construction" Property Type

- [ ] `/lenders/apply` — "New Construction" appears in Property Types chips
- [ ] Lender portal Credit Box tab — same chip appears
- [ ] `/admin/lenders` add-lender form — "New Construction" appears
- [ ] New scenario Package tab — "New Construction" in Property Type dropdown

## 9. Multi-Sponsor (Biggest change)

- [ ] Create a new scenario → Package tab shows "Sponsors (0)" with **+ Add Sponsor** button
- [ ] Add 3 sponsors: Alice (40% Managing), Bob (30% Guarantor), Carol (30% Passive)
- [ ] Verify Alice's card shows "Managing" chip; Bob shows "Guarantor"; Carol shows "Passive"
- [ ] **Ownership % ≥20** — auto-checks "Signs the note" box (guarantor flag)
- [ ] Change ownership to 15% — you can uncheck the guarantor box manually
- [ ] **Client link dropdown** on each sponsor — pick from existing clients
- [ ] Try assigning "Managing" to Bob — Alice auto-demotes to Guarantor
- [ ] Remove a sponsor with the Remove button
- [ ] Documents tab: **"Viewing docs for" filter** dropdown works (All / Shared / per-sponsor)
- [ ] Each doc row shows a sponsor chip AND an inline sponsor dropdown to move it
- [ ] Add a new doc via the AddDocForm — sponsor dropdown pre-selects the current filter
- [ ] Log in as `sample@example.com` (linked as Alice) → confirm you see ALL 17 docs on the 3-sponsor deal (9 Alice-scoped + 8 shared)
- [ ] Move a doc's scope to Bob via the inline selector — refresh client portal → doc DISAPPEARS from Alice's view (verified strict filtering)

## 10. Fee Agreement per Sponsor

- [ ] On a multi-sponsor scenario → Documents tab → Broker Fee card
- [ ] **"Send to Sponsor" dropdown** appears (only lists sponsors with client links)
- [ ] Select Alice → Send → sponsor-specific fee agreement is created
- [ ] Fee Agreements list at bottom of card shows each sponsor's row separately
- [ ] Try sending to Bob (no client link) — button/dropdown correctly excludes him
- [ ] Sample client (Alice) sees the fee agreement in her portal → **Sign in Portal** button works
- [ ] Also test **Send by Email** flow → click Postmark link → sign publicly

## 11. Lender View — Sponsors Card

- [ ] Share a scenario with a lender via one-time token OR marketplace invite
- [ ] Open the shared `/lender/scenario/{token}` page
- [ ] Verify new **Sponsors card** shows all sponsors with:
  - Name + Managing/Guarantor/Passive chip
  - Entity, Ownership %, FICO, Liquidity, Net Worth
  - No `client_user_id` leaked

## 12. Admin Guide

- [ ] `/admin/guide` → **Clients** section: manual invite flow explained (Step 2)
- [ ] **Scenarios** section: new Step 2.5 for multi-sponsor
- [ ] **Documents** step 3: per-sponsor scoping explained
- [ ] **Fee Agreement** step 1: sponsor dropdown mentioned
- [ ] **Lender Marketplace** section: full 6-step walkthrough
- [ ] **Getting Started**: password reset mention

---

## When everything checks out

Reach out to **Emergent Support** to redeploy preview → `byrd-co.com`. Everything listed above will ship together in one deploy.

## If anything fails on this checklist

Reproduce the exact step, capture a screenshot if visual, and hand it to the agent — fixes happen on preview, and this checklist gets re-run before deployment.
