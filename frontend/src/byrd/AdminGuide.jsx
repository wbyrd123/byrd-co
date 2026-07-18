/* eslint-disable react/no-unescaped-entities */
import React, { useState } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen, Copy, ArrowRight, Users, FileText, Building2, Share2,
  Inbox, Sparkles, ShieldCheck, ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import { CONTACT } from "@/byrd/data";

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
  { id: "clients", label: "Clients & Docs" },
  { id: "scenarios", label: "Building a Scenario" },
  { id: "lenders", label: "Lender Directory" },
  { id: "shopping", label: "Shopping a Deal" },
  { id: "quotes", label: "Quote Inbox" },
  { id: "ads", label: "Google Ads Portal" },
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
      <nav className="byrd-card p-4 grid grid-cols-2 md:grid-cols-4 gap-2">
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
          <p><b>Overview</b> — stats, roster shortcuts, recent quotes.</p>
          <p><b>Clients</b> — invite borrowers, curate their doc checklist, review uploads.</p>
          <p><b>Scenarios</b> — build a deal package, compute LTV/DSCR/etc., generate PDFs, share to lenders.</p>
          <p><b>Lenders</b> — your private lender directory (credit boxes, contacts).</p>
          <p><b>Quote Inbox</b> — website "Request a Quote" submissions.</p>
          <p><b>Google Ads Portal</b> — internal tool for building marketing campaigns.</p>
        </Step>
      </Card>

      <Card id="clients" icon={Users} title="Clients &amp; Documents">
        <Step n="1" title="Add a client">
          <p>Sidebar → <b>Clients</b> → <b>Add Client</b>. Fill in name + email (optionally company / phone / loan type). Click <b>Add Client</b>.</p>
          <p>The client is added to your roster immediately, and you get a shareable portal invite link. Copy it now to email/text them, or grab it later from their client page — no rush.</p>
        </Step>
        <Step n="2" title="The client sets a password">
          <p>They click the link, set their own password, and land in their portal. The default document checklist (18 items — Resume, personal + business tax returns for 3 years, entity docs, construction budget, etc.) is already attached to them.</p>
        </Step>
        <Step n="3" title="Curate their checklist">
          <p>Open a client → the document list is right there. Each line has a status dropdown: <b>Pending / Uploaded / Reviewed / Rejected</b> — change it as things move.</p>
          <p><b>Add Line</b> to require a document not in the default set. <b>Delete</b> to remove a line that isn't relevant to this deal.</p>
          <p>The <b>Notes</b> field is visible to the client — use it for rejection reasons or clarifications.</p>
        </Step>
        <Step n="4" title="Review uploads">
          <p>When the client uploads, the row flips to <b>Uploaded</b>. Click the filename to view. Set to <b>Reviewed</b> when it clears, or <b>Rejected</b> with a note if it needs a redo.</p>
        </Step>
      </Card>

      <Card id="scenarios" icon={FileText} title="Building a Loan Scenario">
        <Step n="1" title="Create the scenario">
          <p>Sidebar → <b>Scenarios</b> → <b>New Scenario</b>. Name it however you'd remember it — e.g. <i>"Sample MF Refi — Sugar Land"</i>.</p>
        </Step>
        <Step n="2" title="Fill in the Package tab">
          <p>Everything is field-by-field: sponsor, property, loan request, financials, construction, sources &amp; uses, and notes. Every field auto-saves when you leave it (no Save button).</p>
          <p>Numbers drive the sizing bar at the top: <b>LTV, LTC, DSCR, Debt Yield, NOI, monthly P&amp;I</b>. DSCR turns green if ≥1.25 and red if &lt;1.0.</p>
          <p>Optionally link the scenario to an existing client (dropdown at the top of the Package tab). Once linked, their uploaded docs become attachable in the next step.</p>
        </Step>
        <Step n="3" title="Attach documents (Documents tab)">
          <p>For each of the client's uploaded docs, pick one:</p>
          <p><b>Off</b> — not part of this package.</p>
          <p><b>On Request</b> — mentioned in the package but locked; a lender has to ask and you grant.</p>
          <p><b>Included</b> — rides with the shareable link automatically.</p>
          <p>Rule of thumb: property docs (rent roll, T-12, photos) = Included. Personal docs (PFS, tax returns, bank statements) = On Request.</p>
        </Step>
        <Step n="4" title="Generate the PDF">
          <p>Top-right of any scenario — click <b>PDF</b>. You get a branded Byrd &amp; CO loan package with all the numbers and sponsor/property/loan detail on it.</p>
        </Step>
      </Card>

      <Card id="lenders" icon={Building2} title="Lender Directory">
        <Step n="1" title="Add a lender">
          <p>Sidebar → <b>Lenders</b> → <b>Add Lender</b>. Fill in name, type (bank / credit union / private / agency / bridge / hard money), then their <b>credit box</b>: loan size range, max LTV / LTC, min DSCR / DY, property types they touch, geography (states or "Nationwide"), typical rate, term, recourse preference, decision speed.</p>
          <p>Add one or more contacts (name, title, phone, email). Notes field is for the human stuff — "prefers stabilized deals," "hates hotels in Q4."</p>
        </Step>
        <Step n="2" title="Set status">
          <p><b>Active</b> — regular placements. <b>Passive</b> — occasional. <b>Dormant</b> — inactive but kept for reference.</p>
        </Step>
        <Step n="3" title="Edit and prune over time">
          <p>Every card has Edit/Delete on the right. Keep the directory small and honest — the match engine is only as good as the credit boxes you enter.</p>
        </Step>
      </Card>

      <Card id="shopping" icon={Share2} title="Shopping a Deal to Lenders">
        <Step n="1" title="Run Match">
          <p>Inside a scenario → <b>Lenders</b> tab → click <b>Run Match</b>. Every lender in your directory is scored against this deal — you'll see reasons why they fit or miss (LTV %, DSCR, size, property type, geography).</p>
        </Step>
        <Step n="2" title="Share with the ones that fit">
          <p>Click <b>Share</b> next to any match. A per-lender link is created and copied to your clipboard. Paste it into an email to your lender contact.</p>
          <p>You can also share with someone not in the directory — pick "any lender" below the match list.</p>
        </Step>
        <Step n="3" title="The lender opens the link">
          <p>They see a soft gate — name, work email, institution — before viewing. This gives you a paper trail.</p>
          <p>The whole package is watermarked with their name across every screen and PDF. Deters forwarding.</p>
          <p>They see all "Included" docs immediately. On-Request docs are visible in the list but locked.</p>
        </Step>
        <Step n="4" title="Grant on-request docs, per lender">
          <p>If a serious lender clicks <b>Request Full Data Room</b>, the share card in the Lenders tab flips to show a "Requested" date. Now toggle each on-request doc to <b>Granted</b> for that lender only — other lenders don't see it.</p>
        </Step>
        <Step n="5" title="Watch the audit trail">
          <p>Every action (opened package, viewed a doc, downloaded PDF, requested docs) is logged per share. Great for knowing who's actually serious.</p>
        </Step>
      </Card>

      <Card id="quotes" icon={Inbox} title="Quote Inbox">
        <p className="text-sm">
          The "Request a Quote" form on your website drops submissions into <b>/admin/quotes</b>. Click a row to read; use the Reply button (opens your email app) or Call.
        </p>
        <p className="text-sm text-[#6B6558]">
          Heads-up: emails aren't auto-forwarded to your inboxes yet. When you add a Resend key we'll wire that up.
        </p>
      </Card>

      <Card id="ads" icon={Sparkles} title="Google Ads Portal">
        <p className="text-sm">
          Sidebar → <b>Google Ads Portal</b> (or the tile on Overview). Build search campaigns, generate ad copy with AI, research keywords, view performance analytics. It runs in demo mode today — campaigns live in Byrd &amp; CO's database, not on Google's servers. When you're ready to push to your real Google Ads account, ask us to wire in the Google Ads API.
        </p>
        <Link to="/adscopilot" className="byrd-btn byrd-btn-outline" data-testid="guide-open-ads">
          Open Google Ads Portal <ArrowRight size={14} />
        </Link>
      </Card>

      <Card id="faq" icon={BookOpen} title="Help &amp; FAQ">
        <div className="space-y-4 text-sm">
          <div>
            <div className="font-semibold">Someone is logged in but I need to switch users.</div>
            <div className="text-[#6B6558] mt-1">Click the door icon at the bottom-left of the sidebar to log out, then sign back in.</div>
          </div>
          <div>
            <div className="font-semibold">A client can't upload a file.</div>
            <div className="text-[#6B6558] mt-1">Cap is 15 MB per file. If they need bigger, ask us to swap in S3.</div>
          </div>
          <div>
            <div className="font-semibold">I revoked a lender's share by accident.</div>
            <div className="text-[#6B6558] mt-1">Just create a new share for that same lender — new token, they'll gate again with the same details.</div>
          </div>
          <div>
            <div className="font-semibold">The PDF is missing a section I need.</div>
            <div className="text-[#6B6558] mt-1">Tell us which field/section — the template is easy to extend.</div>
          </div>
          <div>
            <div className="font-semibold">I want to give a client access to more than one deal.</div>
            <div className="text-[#6B6558] mt-1">Same client, multiple scenarios — link each scenario to their profile in the Package tab.</div>
          </div>
          <div className="border-t border-[#E4DFD1] pt-4">
            <div className="font-semibold">Support</div>
            <div className="text-[#6B6558] mt-1">
              For product questions, features, or bug reports — reply to the message thread you use to build this
              with your Emergent agent. Turnaround is same-day for most tweaks.
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
