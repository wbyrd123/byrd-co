import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Users, Inbox, FileCheck, ArrowRight, Plus, Sparkles, Mail, CheckCircle2, AlertTriangle, Send } from "lucide-react";

const Stat = ({ label, value, icon: Icon, testId }) => (
  <div className="byrd-card p-6" data-testid={testId}>
    <div className="flex items-center justify-between">
      <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">{label}</div>
      <div className="w-8 h-8 rounded-md bg-[#F3EEE0] grid place-items-center text-[#C89434]">
        <Icon size={14} />
      </div>
    </div>
    <div className="font-serif text-4xl font-bold mt-3">{value}</div>
  </div>
);

export default function AdminDashboard() {
  const [clients, setClients] = useState([]);
  const [quotes, setQuotes] = useState([]);

  useEffect(() => {
    api.get("/admin/clients").then((r) => setClients(r.data));
    api.get("/admin/quotes").then((r) => setQuotes(r.data));
  }, []);

  const totalDocs = clients.reduce((n, c) => n + (c.doc_summary?.total || 0), 0);
  const uploaded = clients.reduce((n, c) => n + (c.doc_summary?.uploaded || 0) + (c.doc_summary?.reviewed || 0), 0);
  const newQuotes = quotes.filter((q) => !q.read).length;

  const recentClients = clients.slice(0, 5);
  const recentQuotes = quotes.slice(0, 5);

  return (
    <div className="space-y-8" data-testid="admin-dashboard">
      <div>
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Broker Console</div>
        <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Overview.</h1>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Stat label="Active Clients" value={clients.length} icon={Users} testId="stat-clients" />
        <Stat label="Docs Received" value={`${uploaded}/${totalDocs}`} icon={FileCheck} testId="stat-docs" />
        <Stat label="New Quote Requests" value={newQuotes} icon={Inbox} testId="stat-quotes" />
      </div>

      <EmailStatusCard />

      {/* Marketing tools */}
      <div>
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest mb-3">// Marketing</div>
        <Link
          to="/adscopilot"
          data-testid="google-ads-portal-tile"
          className="byrd-card byrd-card-hover p-6 md:p-7 flex items-center gap-5 group"
        >
          <div className="w-14 h-14 shrink-0 rounded-md bg-[#1A1A1A] text-[#C89434] grid place-items-center">
            <Sparkles size={22} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-serif text-xl font-bold">Google Ads Portal</div>
            <div className="text-sm text-[#6B6558] mt-1">
              Create and manage Google Ads campaigns, generate ad copy with AI, and research keywords —
              all without leaving Byrd &amp; CO.
            </div>
          </div>
          <ArrowRight size={18} className="text-[#6B6558] group-hover:text-[#C89434] shrink-0" />
        </Link>
      </div>

      {/* Help tile */}
      <Link
        to="/admin/guide"
        data-testid="guide-tile"
        className="byrd-card byrd-card-hover p-5 flex items-center gap-4 group"
      >
        <div className="w-10 h-10 shrink-0 rounded-md bg-[#F3EEE0] text-[#C89434] grid place-items-center">
          <ArrowRight size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-serif text-lg font-bold">New here? Read the Guide</div>
          <div className="text-xs text-[#6B6558] mt-0.5">
            5-minute walkthrough of every screen — invites, scenarios, lender shopping.
          </div>
        </div>
      </Link>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="byrd-card p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">// Recent Clients</div>
              <h2 className="font-serif text-2xl font-bold mt-1">Client roster</h2>
            </div>
            <Link to="/admin/clients" className="byrd-btn byrd-btn-outline h-9 px-3 text-xs">
              <Plus size={12} /> Add
            </Link>
          </div>
          {recentClients.length === 0 ? (
            <div className="text-sm text-[#6B6558]">No clients yet. Invite your first client to get started.</div>
          ) : (
            <ul className="divide-y divide-[#E4DFD1]">
              {recentClients.map((c) => (
                <li key={c.id} className="py-3 flex items-center justify-between">
                  <Link to={`/admin/clients/${c.id}`} className="min-w-0 flex-1" data-testid={`recent-client-${c.id}`}>
                    <div className="font-semibold truncate hover:text-[#C89434]">{c.name}</div>
                    <div className="text-xs text-[#6B6558] truncate">{c.email}</div>
                  </Link>
                  <div className="text-xs font-mono text-[#6B6558] ml-3 shrink-0">
                    {c.doc_summary.reviewed}/{c.doc_summary.total} ✓
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="byrd-card p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">// Recent Quotes</div>
              <h2 className="font-serif text-2xl font-bold mt-1">Website inbox</h2>
            </div>
            <Link to="/admin/quotes" className="byrd-btn byrd-btn-outline h-9 px-3 text-xs">
              View all <ArrowRight size={12} />
            </Link>
          </div>
          {recentQuotes.length === 0 ? (
            <div className="text-sm text-[#6B6558]">No quote requests yet.</div>
          ) : (
            <ul className="divide-y divide-[#E4DFD1]">
              {recentQuotes.map((q) => (
                <li key={q.id} className="py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold truncate">{q.name} <span className="text-[#6B6558] font-normal">· {q.email}</span></div>
                    <div className="text-xs text-[#6B6558] truncate">{q.loan_type || "—"} · {q.loan_amount || "—"} · {q.property_type || "—"}</div>
                  </div>
                  {!q.read && <span className="byrd-chip byrd-chip-gold shrink-0">New</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function EmailStatusCard() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [testTo, setTestTo] = useState("waynebyrd11@gmail.com");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { ok, message }

  const load = () => {
    setLoading(true);
    api.get("/admin/settings/email/status")
      .then((r) => setStatus(r.data))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const sendTest = async () => {
    if (!testTo.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await api.post("/admin/settings/email/test", { to: testTo.trim() });
      setResult({ ok: true, message: `Sent to ${r.data.sent_to} (from ${r.data.from})` });
      toast.success("Test email dispatched");
      load();
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Send failed";
      setResult({ ok: false, message: detail });
      toast.error("Test failed — see error below");
      load();
    } finally {
      setBusy(false);
    }
  };

  const healthy = status && status.configured && (status.sent_30d > 0 || (status.failed_30d === 0 && status.sent_30d === 0));
  const hasRecentFailure = status && status.failed_30d > 0;
  const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");

  return (
    <div className="byrd-card p-6" data-testid="email-status-card">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">// Postmark Email</div>
          <div className="flex items-center gap-2 mt-1">
            <h3 className="font-serif text-xl font-bold">Email Delivery</h3>
            {loading ? (
              <span className="byrd-chip text-[#6B6558]">Checking…</span>
            ) : !status?.configured ? (
              <span className="byrd-chip byrd-chip-red"><AlertTriangle size={10} /> Not Configured</span>
            ) : hasRecentFailure ? (
              <span className="byrd-chip byrd-chip-gold"><AlertTriangle size={10} /> Recent Failures</span>
            ) : (
              <span className="byrd-chip byrd-chip-green"><CheckCircle2 size={10} /> Healthy</span>
            )}
          </div>
          {status && (
            <div className="text-xs text-[#6B6558] mt-1">
              From: <span className="font-mono">{status.from_name} &lt;{status.from_email}&gt;</span>
            </div>
          )}
        </div>
      </div>

      {status && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4">
          <div className="border border-[#E4DFD1] rounded-md p-3">
            <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">Sent · 30d</div>
            <div className="font-serif text-2xl font-bold mt-1 text-[#245C25]">{status.sent_30d}</div>
            <div className="text-[11px] text-[#6B6558] mt-0.5">Last: {fmtTime(status.last_success_at)}</div>
          </div>
          <div className="border border-[#E4DFD1] rounded-md p-3">
            <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">Failed · 30d</div>
            <div className={`font-serif text-2xl font-bold mt-1 ${status.failed_30d ? "text-[#8A1F1A]" : "text-[#6B6558]"}`}>{status.failed_30d}</div>
            <div className="text-[11px] text-[#6B6558] mt-0.5">Last: {fmtTime(status.last_failure_at)}</div>
          </div>
          <div className="border border-[#E4DFD1] rounded-md p-3">
            <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">Last Error</div>
            <div className="text-xs text-[#8A1F1A] mt-1 leading-snug line-clamp-3">
              {status.last_failure_error ? status.last_failure_error.slice(0, 180) : "—"}
            </div>
          </div>
        </div>
      )}

      <div className="mt-5 border-t border-[#E4DFD1] pt-4">
        <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest mb-2">// Send Test</div>
        <div className="flex items-end gap-2 flex-wrap">
          <div className="flex-1 min-w-[240px]">
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Recipient</label>
            <input
              type="email"
              value={testTo}
              onChange={(e) => setTestTo(e.target.value)}
              className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
              data-testid="email-test-to"
              placeholder="waynebyrd11@gmail.com"
            />
          </div>
          <button
            onClick={sendTest}
            disabled={busy || !testTo.trim()}
            className="byrd-btn byrd-btn-dark h-11 px-4"
            data-testid="email-test-send"
          >
            <Send size={14} /> {busy ? "Sending…" : "Send Test"}
          </button>
        </div>
        {result && (
          <div
            className={`mt-3 text-xs rounded-md px-3 py-2 leading-snug ${
              result.ok
                ? "bg-[#E4F4E4] border border-[#8DBE8F] text-[#245C25]"
                : "bg-[#FADCDA] border border-[#E38380] text-[#8A1F1A]"
            }`}
            data-testid="email-test-result"
          >
            <div className="font-semibold inline-flex items-center gap-1">
              {result.ok ? <><CheckCircle2 size={12} /> Test dispatched</> : <><AlertTriangle size={12} /> Postmark rejected the test</>}
            </div>
            <div className="mt-0.5 whitespace-pre-wrap">{result.message}</div>
          </div>
        )}
        <div className="text-[10px] text-[#6B6558] mt-2 leading-snug">
          Fires a canary email through your Postmark server. If Postmark rejects, you&apos;ll see the raw
          error here — the most common cause is the account still being in trial mode
          (fix: Postmark dashboard → Servers → your server → <b>Request approval</b>).
        </div>
      </div>
    </div>
  );
}
