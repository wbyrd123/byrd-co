# Byrd & CO — Product Requirements Document

## Original Problem Statement
"Commercial Real Estate Broker website for Byrd & CO. Lending on multifamily, hotels, office, condo projects, single-family units, condo units incl. leaseholds, 1–4 unit properties, portfolio loans. Offering refinances, purchases, cash-outs, new construction. Principals Caleb Byrd and Wayne Byrd. Need public site, login for Google Ads portal (internal), client portal where potential clients create login and upload docs via a shareable invite link. Testimonials section."

## Product
Byrd & CO — a marketing website + client document portal + broker admin console + AdsCopilot internal tool.

## Personas
- **Public visitor** — reads the marketing site, requests a quote.
- **Client** — receives an invite link from a broker, sets a password, uploads documents against a broker-tailored checklist.
- **Broker (Wayne / Caleb)** — invites clients, curates their doc checklist per deal, reviews uploads (Pending → Uploaded → Reviewed / Rejected), reads quote inbox, runs AdsCopilot for marketing.

## Architecture
- Backend: FastAPI + MongoDB (Motor). JWT auth (bcrypt). Base64 file storage in Mongo, 15MB cap.
- Frontend: React 19 + Tailwind + Shadcn/UI, Recharts (AdsCopilot only), Sonner toasts.
- Design: Editorial finance — Playfair Display headlines, Inter body, IBM Plex Mono for data. Palette: ivory #FBF8F1, gold #C89434, charcoal #1A1A1A.
- AdsCopilot preserved at `/adscopilot/*` with its Swiss Brutalist styling scoped via `.adscopilot-scope`.

## Implemented (2026-02)
- **Public site**: Hero, four Programs (Purchase, Refinance, Cash-Out, New Construction), eight Property Types (Multifamily, Hotels, Office, Condo Projects, SFR, Condo Units, 1–4 Unit, Portfolio), Process, Principals (Wayne + Caleb with phone/email), Testimonials (4 seeded), Quote form, Footer.
- **Auth**: JWT login. Startup seeds Wayne + Caleb as admins.
- **Client invites**: Broker creates invite → shareable link `/portal/invite/<token>`. Client sets password, becomes role=client.
- **Client portal** (`/portal`): grouped doc checklist by category, upload/replace with progress, status chips, file view/download, broker notes visible.
- **Admin console** (`/admin`): overview stats, client roster, per-client detail with status dropdowns, notes, add/remove doc lines, copy invite link, quote inbox with reply/call actions, sidebar link into AdsCopilot and out to Google Ads.
- **Files API** with per-user access control.

## Test Credentials
- `wayne@byrd-co.com` / `byrdco2026` (admin)
- `caleb@byrd-co.com` / `byrdco2026` (admin)
- `sample@example.com` / `sample123` (client, checklist pre-populated)

## Backlog
- **P1** Email delivery on quote form (Resend integration) — currently DB-only inbox.
- **P1** Email delivery on invite creation (send link to client instead of manual copy).
- **P1** Object storage (S3) — replace base64-in-Mongo for larger docs.
- **P2** Password reset flow.
- **P2** Editable testimonials in admin.
- **P2** Doc templates (save a checklist as a template per loan type; auto-apply).
- **P2** Client-facing status timeline / activity feed.
- **P2** Public rate limiting + captcha on quote form.
- **P3** Multi-broker teams beyond Wayne/Caleb.
- **P3** Migrate FastAPI `on_event` to lifespan handlers.

## Notes / Mocked
- Testimonials are static seeded data.
- Google Ads is a link out; AdsCopilot campaigns simulated.
- Quote emails to wayne@ / caleb@ are NOT dispatched until Resend is wired.
