/* eslint-disable react/no-unescaped-entities */
import React, { useState } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen, Copy, ArrowRight, Users, FileText, Building2, Share2,
  Inbox, Sparkles, ShieldCheck, ChevronRight, Bot, Megaphone,
  Contact as ContactIcon, Clock, AtSign,
} from "lucide-react";
import { toast } from "sonner";

const Step = ({ n, title, children }) => (
  <div className="flex gap-4">
    <div className="w-9 h-9 shrink-0 rounded-full bg-[#C89434] text-[#1A1A1A] grid place-items-center font-serif font-bold">
      {n}
    </div>
    <div className="flex-1 min-w-0 pb-6 border-b border-[#E4DFD1] last:border-b-0 last:pb-0">
      <h4 className="font-serif text-lg font-semibold">{title}</h4>
      <div className="text-sm text-[#2A2A2A] mt-1 leading-relaxed space-y-1">{children}</div>
    </div>
  </div>
);

const Card = ({ icon: Icon, title, children, id }) => (
  <section id={id} className="byrd-card p-6 md:p-7 scroll-mt-24">
    <div className="flex items-center gap-3 mb-5">
      <div className="w-10 h-10 rounded-md bg-[#F3EEE0] text-[#C89434] grid place-items-center">
        <Icon size={18} />
      </div>
      <h3 className="font-serif text-2xl font-bold">{title}</h3>
    </div>
    <div className="space-y-6">{children}</div>
  </section>
);

const InlineCode = ({ children }) => (
  <code className="px-1.5 py-0.5 rounded bg-[#F3EEE0] border border-[#E4DFD1] font-mono text-[12px] text-[#1A1A1A]">
    {children}
  </code>
);

const CopyRow = ({ label, value, testId }) => {
  const copy = () => {
    navigator.clipboard.writeText(value);
    toast.success("Copied");
  };
  return (
    <div className="flex items-center gap-2 border border-[#E4DFD1] rounded-md p-2 bg-white">
      <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] px-2 shrink-0">{label}</div>
      <div className="font-mono text-sm text-[#1A1A1A] flex-1 truncate">{value}</div>
      <button onClick={copy} className="byrd-btn byrd-btn-outline h-8 px-2 text-xs" data-testid={testId}>
        <Copy size={12} /> Copy
      </button>
    </div>
  );
};

const SECTIONS = [
  { id: "start", label: "Getting Started" },
  { id: "assistant", label: "Personal Assistant" },
  { id: "contacts", label: "Contacts CRM" },
  { id: "clients", label: "Clients" },
  { id: "scenarios", label: "Scenarios & Docs" },
  { id: "lenders", label: "Lender Directory" },
  { id: "shopping", label: "Shopping a Deal" },
  { id: "quotes", label: "Quote Inbox" },
  { id: "faq", label: "Help & FAQ" },
];

export default function AdminGuide() {
  const [origin] = useState(() => typeof window !== "undefined" ? window.location.origin : "");
  const loginUrl = `${origin}/portal/login`;
  const adminUrl = `${origin}/admin`;

  return (
    <div className="space-y-8" data-testid="admin-guide">
      <div>
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Guide</div>
        <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Byrd &amp; CO Console — How To.</h1>
        <p className="text-[#6B6558] mt-3 max-w-2xl">
          A short manual for using the broker console day-to-day. Anything not covered here, ping us.
        </p>
      </div>

      {/* URLs / credentials up top */}
      <div className="byrd-card p-6 bg-[#1A1A1A] text-[#FBF8F1]">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-md bg-[#C89434] text-[#1A1A1A] grid place-items-center">
            <BookOpen size={18} />
          </div>
          <h3 className="font-serif text-2xl font-bold text-white">Quick Reference</h3>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <CopyRow label="Login URL" value={loginUrl} testId="copy-login-url" />
          <CopyRow label="Admin URL" value={adminUrl} testId="copy-admin-url" />
        </div>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <div className="p-3 rounded-md bg-[#2A2A2A] border border-[#3A3A3A]">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#E5B968]">Wayne Byrd</div>
            <div className="mt-1">wayne@byrd-co.com</div>
            <div className="text-[#C9C1AF] text-xs mt-1">Password: <span className="font-mono">byrdco2026</span> (change any time by asking us to add a reset flow)</div>
          </div>
          <div className="p-3 rounded-md bg-[#2A2A2A] border border-[#3A3A3A]">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#E5B968]">Caleb Byrd</div>
            <div className="mt-1">caleb@byrd-co.com</div>
            <div className="text-[#C9C1AF] text-xs mt-1">Password: <span className="font-mono">byrdco2026</span></div>
          </div>
        </div>
        <p className="mt-4 text-[11px] text-[#C9C1AF]">
          Both of you use the same login page. The console knows you're an admin and drops you at <InlineCode>/admin</InlineCode>.
          Clients use the same URL — they get routed to their own portal automatically.
        </p>
      </div>

      {/* Section index */}
      <nav className="byrd-card p-4 grid grid-cols-2 md:grid-cols-3 gap-2" data-testid="guide-toc">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className="text-sm px-3 py-2 rounded-md hover:bg-[#F3EEE0] flex items-center justify-between">
            {s.label} <ChevronRight size={14} className="text-[#6B6558]" />
          </a>
        ))}
      </nav>

      <Card id="start" icon={ShieldCheck} title="Getting Started">
        <Step n="1" title="Bookmark two links">
          <p><InlineCode>{loginUrl}</InlineCode> — where you and clients sign in.</p>
          <p><InlineCode>{adminUrl}</InlineCode> — direct-jump to the console after signing in.</p>
        </Step>
        <Step n="2" title="Sign in">
          <p>Use your email and the shared password. If either of you wants a personal password, ask us to add a reset flow — quick change.</p>
        </Step>
        <Step n="3" title="Meet the sidebar">
          <p><b>Overview</b> — stats, roster shortcuts, recent quotes, and your email-status card (sandbox vs live).</p>
          <p><b>Personal Assistant</b> — your private AI chat: task capture, email drafting, teammate handoffs, marketing nudges, stalled-deal alerts.</p>
          <p><b>Clients</b> — invite borrowers, see all their scenarios at a glance, delete stragglers.</p>
          <p><b>Contacts</b> — the shared rolodex (referral sources, past sponsors, lenders you haven't onboarded yet). CSV import + bulk marketing sends live here.</p>
          <p><b>Scenarios</b> — each loan lives here. Own document folder, own metrics, own lender package.</p>
          <p><b>Lenders</b> — your private lender directory with credit boxes and match scoring.</p>
          <p><b>Quote Inbox</b> — public "Request a Quote" submissions land here.</p>
          <p><b>Testimonials</b> — CRUD for the marketing site testimonials.</p>
        </Step>
      </Card>

      <Card id="assistant" icon={Bot} title="Personal Assistant">
        <p className="text-sm text-[#6B6558] -mt-2 mb-4">
          Your private assistant lives at <InlineCode>/admin/assistant</InlineCode>. Wayne and Caleb each have their own —
          you can't read each other's chats, but you <em>can</em> hand tasks and notes across.
          It knows about your clients, your scenarios, your open tasks, and your rolodex.
        </p>

        <Step n="1" title="Just tell it what's going on.">
          <p>Talk to it like you'd talk to a smart junior at your firm. Examples:</p>
          <p>&mdash; "Remind me to call Rod on Tuesday at 3pm."</p>
          <p>&mdash; "Email Sarah at Wells &mdash; ask her if she can look at a $4.5M hotel refi in Miami."</p>
          <p>&mdash; "Mark the follow-up with the SBA lender done."</p>
          <p>It pulls out the actionable pieces &mdash; new tasks appear in the right rail with the right due date, and email drafts show up as a card with a Send button.</p>
        </Step>

        <Step n="2" title="Hand off to your teammate.">
          <div className="flex items-start gap-2 my-2">
            <AtSign size={16} className="text-[#C89434] mt-0.5" />
            <div className="text-sm">
              <p>Two ways to route work to Wayne or Caleb:</p>
              <p><b>Natural language:</b> "Tell Caleb to call Rod at 555-123-4567 &mdash; interview him for the Ohio mixed-use loan."</p>
              <p><b>@-mention shortcut:</b> Start your message with <InlineCode>@caleb</InlineCode> (or <InlineCode>@wayne</InlineCode>). Autocomplete pops as you type.</p>
            </div>
          </div>
          <p>The handoff shows up in your teammate's assistant as an inbound task with a <b>Reply</b> button. Their reply becomes an update card back in your assistant. Every exchange is threaded &mdash; you always see who said what.</p>
        </Step>

        <Step n="3" title="Draft transactional emails.">
          <p>Say "email Rod that his rent roll cleared and we're moving forward" &mdash; a full draft appears with subject and body. You edit it, then hit <b>Send</b> and it goes out via Postmark. Nothing is sent behind your back.</p>
          <p>Transactional sends carry <b>no unsubscribe link</b> &mdash; only marketing sends do. That's enforced by which endpoint the assistant hits.</p>
        </Step>

        <Step n="4" title="Marketing nudge (auto every 30 days).">
          <div className="flex items-start gap-2 my-2">
            <Megaphone size={16} className="text-[#C89434] mt-0.5" />
            <div className="text-sm">
              <p>If it's been 30+ days since your last marketing send (or you've never sent one), a gold banner appears at the top of the chat: <em>"You haven't sent a marketing email yet."</em></p>
              <p>Click <b>Draft one</b> &rarr; the assistant writes a subject + body + rationale + target-tag suggestion, tuned to the current month and your CRM state. You get three buttons on the draft:</p>
              <p><b>Open in CRM</b> &rarr; hands the draft off to the Contacts page with the recipients pre-selected by tag (or everyone with a valid email) and the compose dialog pre-filled.</p>
              <p><b>Regenerate</b> &rarr; ask for a different angle.</p>
              <p><b>Dismiss</b> &rarr; snoozes the banner for a week.</p>
              <p>Marketing sends automatically add an unsubscribe footer with a unique per-recipient token. When a borrower unsubscribes, the CRM excludes them from every future marketing send but they can still receive transactional emails.</p>
            </div>
          </div>
        </Step>

        <Step n="5" title="Stalled-deal alerts (pipeline coach).">
          <div className="flex items-start gap-2 my-2">
            <Clock size={16} className="text-[#8A1F1A] mt-0.5" />
            <div className="text-sm">
              <p>A subtle red-tinted banner surfaces every scenario in <b>draft</b> or <b>shopping</b> status that has:</p>
              <p>&mdash; No activity in 7+ days (scenario or docs)</p>
              <p>&mdash; AND fewer than 30% of the checklist uploaded</p>
              <p>Each row shows <InlineCode>Xd silent · Y/Z docs (P%)</InlineCode> plus three actions:</p>
              <p><b>Draft follow-up</b> &rarr; prefills the chat with a warm one-paragraph nudge to that specific borrower. Review, edit, send.</p>
              <p><b>Open</b> &rarr; deep-links to the scenario detail page.</p>
              <p><b>Snooze</b> &rarr; silences that one deal for 7 days (per admin &mdash; your snooze doesn't affect Caleb's view).</p>
              <p>The assistant is also aware of stalled deals in normal conversation &mdash; the first time in a chat, it'll mention the top 1&ndash;2 gently.</p>
            </div>
          </div>
        </Step>

        <Step n="6" title="Ask CRM questions in plain English.">
          <p>The assistant has a live snapshot of the rolodex on every turn. Try:</p>
          <p>&mdash; "Who haven't I contacted in 60 days?"</p>
          <p>&mdash; "How many referral sources do we have?"</p>
          <p>&mdash; "Is Sarah at Wells in the CRM?"</p>
          <p>It answers from the snapshot &mdash; up to 15 stale contacts (no touch in 60+ days) are always available.</p>
        </Step>
      </Card>

      <Card id="contacts" icon={ContactIcon} title="Contacts CRM">
        <p className="text-sm text-[#6B6558] -mt-2 mb-4">
          The shared rolodex &mdash; referral sources, past sponsors, prospective clients, lender contacts you haven't formalized yet.
          Both of you see and edit the same list.
        </p>
        <Step n="1" title="Add contacts">
          <p>Sidebar &rarr; <b>Contacts</b> &rarr; <b>New Contact</b>. Name, email, phone, tags (<InlineCode>referral</InlineCode>, <InlineCode>past sponsor</InlineCode>, whatever you like), and a Notes field.</p>
        </Step>
        <Step n="2" title="Bulk import (CSV)">
          <p>Click <b>Import CSV</b>. Format: <InlineCode>name, email, phone, tags, notes</InlineCode>. Tags can be comma-separated inside a semicolon-delimited cell (or just <InlineCode>tag1|tag2</InlineCode>). Import is idempotent-ish &mdash; existing emails update in place.</p>
        </Step>
        <Step n="3" title="Send a marketing email">
          <p>Filter/search to pick who you want, tick their checkboxes, click <b>Compose</b>.</p>
          <p><b>Templates</b> &mdash; save common blasts (quarterly rate note, holiday note, referral-source thank-you) once and reuse.</p>
          <p><b>Merge tags</b> &mdash; use <InlineCode>{"{{first_name}}"}</InlineCode> and <InlineCode>{"{{admin_first_name}}"}</InlineCode> in body/subject &mdash; the CRM personalizes each send.</p>
          <p><b>Unsubscribe footer</b> is added automatically. Anyone who unsubscribes drops off future marketing sends via a per-recipient token URL.</p>
        </Step>
        <Step n="4" title="Marketing vs. Transactional">
          <p>Only the CRM's <b>Compose</b> path adds the unsubscribe link. Emails your assistant drafts one-to-one (client updates, invite links, quote replies) are <b>transactional</b> &mdash; no unsubscribe footer.</p>
        </Step>
      </Card>

      <Card id="clients" icon={Users} title="Clients">
        <Step n="1" title="Add a client">
          <p>Sidebar &rarr; <b>Clients</b> &rarr; <b>Add Client</b>. Fill in name + email (optionally company / phone). Click <b>Add Client</b>.</p>
          <p>They get an invite link (auto-emailed via Postmark; also copyable from their client page). They click, set a password, and land in their portal.</p>
        </Step>
        <Step n="2" title="Client page = scenarios + delete">
          <p>Docs no longer live on the client page &mdash; they live on each <b>scenario</b>. So the client detail page is now clean: a list of that client's deals with progress bars, plus a <b>Delete client</b> button.</p>
          <p><b>Delete is blocked</b> if the client has any scenarios. Remove or reassign the scenarios first, then the delete button unlocks. That's the guardrail against wiping real data by mistake.</p>
        </Step>
        <Step n="3" title="What the client sees">
          <p>Their portal groups their upload checklist <b>by scenario</b>. If Rod has two deals with you (hotel purchase in Miami + MF refi in Sugar Land), he sees two collapsible sections &mdash; each with its own progress bar and its own document list. Way clearer than one flat pile.</p>
        </Step>
      </Card>

      <Card id="scenarios" icon={FileText} title="Scenarios &amp; Documents">
        <Step n="1" title="Create a scenario &mdash; pick a checklist template.">
          <p>From the Scenarios list <em>or</em> from a client's page, click <b>New Scenario</b>. Give it a name (<i>"Hotel Purchase &mdash; Miami"</i> or <i>"12-Unit MF Refi &mdash; Sugar Land"</i>).</p>
          <p>Now pick a <b>document checklist template</b>:</p>
          <p><b>Purchase &mdash; Standard</b> (personal + business core + purchase contract + T-12 + rent roll if any)</p>
          <p><b>Refinance &mdash; Standard</b> (personal + business + current rent roll + T-12 + payoff quote)</p>
          <p><b>Construction &mdash; Standard</b> (personal + business + budget + plans + GC docs + land contract)</p>
          <p><b>Bridge / Value-Add</b> (personal + business + business plan + T-12 + capex plan)</p>
          <p><b>SBA 7(a) / 504</b> (personal + business + 3-yr financials + SBA forms)</p>
          <p><b>Blank</b> &mdash; start empty, add each line manually.</p>
          <p>The template seeds the checklist. Rename, add, or delete lines any time.</p>
        </Step>
        <Step n="2" title="Package tab &mdash; the numbers.">
          <p>Field-by-field: sponsor, property, loan request, financials, construction, sources &amp; uses, notes. Everything auto-saves.</p>
          <p>Numbers drive the sizing bar at the top: <b>LTV, LTC, DSCR, Debt Yield, NOI, monthly P&amp;I</b>. DSCR turns green if &ge;1.25, red if &lt;1.0.</p>
        </Step>
        <Step n="3" title="Documents tab &mdash; per-scenario folder.">
          <p>Every scenario has its own document folder. Add / edit / delete lines directly. Set each line to <b>Pending / Uploaded / Reviewed / Rejected</b>. Client sees whatever notes you write.</p>
          <p>Each line has a <b>lender visibility</b> toggle: <b>Hidden</b> (lender never learns it exists), <b>Req.</b> (visible in the list but locked; lender must ask, you grant per lender), or <b>Included</b> (auto-rides with any lender link).</p>
          <p>Rule of thumb: property docs (rent roll, T-12, photos, PSA) &rarr; Included. Personal docs (PFS, tax returns, bank statements) &rarr; Req.</p>
        </Step>
        <Step n="4" title="Copy documents between a client's scenarios.">
          <p>If a client has two deals with you and some docs overlap (Personal Tax Returns is the same PDF for a hotel purchase and an MF refi), use <b>Copy from Another Scenario</b> in the Documents tab.</p>
          <p>Pick the source scenario, tick the doc lines you want, click Copy. The line <b>and the uploaded file</b> both copy over &mdash; each scenario keeps its own independent audit trail (re-uploading in one doesn't touch the other).</p>
        </Step>
        <Step n="5" title="Download the whole folder.">
          <p>Top-right of any scenario &rarr; <b>Download ZIP</b>. Every uploaded doc, filename-prefixed with the checklist label.</p>
        </Step>
        <Step n="6" title="Generate the PDF.">
          <p><b>PDF</b> button, top-right. Branded Byrd &amp; CO loan package with all the numbers and sponsor/property/loan detail.</p>
        </Step>
      </Card>

      <Card id="lenders" icon={Building2} title="Lender Directory">
        <Step n="1" title="Add a lender">
          <p>Sidebar &rarr; <b>Lenders</b> &rarr; <b>Add Lender</b>. Fill in name, type (bank / credit union / private / agency / bridge / hard money), then their <b>credit box</b>: loan size range, max LTV / LTC, min DSCR / DY, property types, geography, typical rate, term, recourse preference, decision speed.</p>
          <p>Add one or more contacts (name, title, phone, email). Notes field is for the human stuff &mdash; "prefers stabilized deals," "hates hotels in Q4."</p>
        </Step>
        <Step n="2" title="Set status">
          <p><b>Active</b> &mdash; regular placements. <b>Passive</b> &mdash; occasional. <b>Dormant</b> &mdash; inactive but kept for reference.</p>
        </Step>
        <Step n="3" title="Edit and prune over time">
          <p>Every card has Edit/Delete on the right. Keep the directory small and honest &mdash; the match engine is only as good as the credit boxes you enter.</p>
        </Step>
      </Card>

      <Card id="shopping" icon={Share2} title="Shopping a Deal to Lenders">
        <Step n="1" title="Run Match">
          <p>Inside a scenario &rarr; <b>Lenders</b> tab &rarr; <b>Run Match</b>. Every lender in your directory is scored against this deal &mdash; you'll see reasons why they fit or miss (LTV, DSCR, size, property type, geography).</p>
        </Step>
        <Step n="2" title="Share with the ones that fit">
          <p>Click <b>Share</b> next to a match. A per-lender link is generated and copied to your clipboard. Paste it into an email to your lender contact.</p>
          <p>You can also share with someone not in the directory &mdash; use the "any lender" option below the match list.</p>
        </Step>
        <Step n="3" title="The lender opens the link">
          <p>They see a soft gate &mdash; name, work email, institution &mdash; before viewing. This gives you a paper trail.</p>
          <p>The whole package is <b>watermarked</b> with their name across every screen and PDF. Deters forwarding.</p>
          <p>They see all "Included" docs immediately. On-Request docs are visible in the list but locked.</p>
        </Step>
        <Step n="4" title="Per-lender doc visibility overrides">
          <p>If a serious lender clicks <b>Request Full Data Room</b>, the share card in the Lenders tab flips to show a Requested date. Open <b>Manage Visibility</b> on that share and flip individual docs to <b>Included</b> just for that lender &mdash; other lenders keep the default view.</p>
        </Step>
        <Step n="5" title="Audit trail">
          <p>Every action (opened package, viewed a doc, downloaded PDF, requested docs) is logged per share. Great signal for who's actually serious.</p>
        </Step>
      </Card>

      <Card id="quotes" icon={Inbox} title="Quote Inbox">
        <p className="text-sm">
          The "Request a Quote" form on your website drops submissions into <b>/admin/quotes</b>. Click a row to read.
          Both Wayne and Caleb get an alert email when one arrives (via Postmark).
        </p>
      </Card>

      <Card id="faq" icon={BookOpen} title="Help &amp; FAQ">
        <div className="space-y-4 text-sm">
          <div>
            <div className="font-semibold">A client with two loans should see two different doc lists &mdash; how does that work?</div>
            <div className="text-[#6B6558] mt-1">Each scenario has its own document folder. Create Scenario A ("Hotel Purchase") with the Purchase template and Scenario B ("MF Refi") with the Refinance template &mdash; each seeds different docs, and the borrower's portal shows them as two separate collapsible sections.</div>
          </div>
          <div>
            <div className="font-semibold">A doc applies to both scenarios (Personal Tax Returns). Do I have to upload it twice?</div>
            <div className="text-[#6B6558] mt-1">No &mdash; in the Documents tab of the second scenario, click <b>Copy from Another Scenario</b>, pick the line, and both the doc metadata and the uploaded file copy over. Each scenario then owns its own copy independently.</div>
          </div>
          <div>
            <div className="font-semibold">I have ghost clients with no active deal &mdash; how do I clean them up?</div>
            <div className="text-[#6B6558] mt-1">Open the client, click <b>Delete client</b> at the top-right. If they have zero scenarios it deletes cleanly. If they have scenarios, the button is disabled with a note to delete/reassign those first.</div>
          </div>
          <div>
            <div className="font-semibold">Marketing emails aren't reaching people at gmail / non-Byrd addresses.</div>
            <div className="text-[#6B6558] mt-1">Postmark is still in sandbox/trial mode &mdash; it only sends to verified domains. Ask Postmark to approve your account from the Postmark dashboard, then those blasts will land normally. The dashboard email-status widget shows the current state.</div>
          </div>
          <div>
            <div className="font-semibold">How do I stop the assistant from nagging me about the same stalled deal?</div>
            <div className="text-[#6B6558] mt-1">Click <b>Snooze</b> on the row in the Stalled Deals banner &mdash; that deal disappears from your banner for 7 days. It's per-admin, so Caleb's view is independent.</div>
          </div>
          <div>
            <div className="font-semibold">A client can't upload a file.</div>
            <div className="text-[#6B6558] mt-1">Cap is 15 MB per file. If they need bigger, ask us to swap in S3.</div>
          </div>
          <div>
            <div className="font-semibold">I revoked a lender's share by accident.</div>
            <div className="text-[#6B6558] mt-1">Just create a new share for that same lender &mdash; new token, they'll gate again with the same details.</div>
          </div>
          <div>
            <div className="font-semibold">I updated something in the console but I don't see it on byrd-co.com.</div>
            <div className="text-[#6B6558] mt-1">The console you're using now is the <b>preview</b> environment. Changes go live on <InlineCode>byrd-co.com</InlineCode> only after a redeploy. Ping us to push and we'll ship it.</div>
          </div>
          <div className="border-t border-[#E4DFD1] pt-4">
            <div className="font-semibold">Support</div>
            <div className="text-[#6B6558] mt-1">
              For product questions, features, or bug reports &mdash; reply in the message thread you use to build this
              with your Emergent agent. Turnaround is same-day for most tweaks.
            </div>
          </div>
        </div>
      </Card>

      <div className="text-center py-4">
        <Link to="/admin/assistant" className="byrd-btn byrd-btn-dark" data-testid="guide-open-assistant">
          Open your Personal Assistant <ArrowRight size={14} />
        </Link>
      </div>
    </div>
  );
}
