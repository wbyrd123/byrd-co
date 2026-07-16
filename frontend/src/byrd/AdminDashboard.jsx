import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Users, Inbox, FileCheck, ArrowRight, Plus, ExternalLink, Sparkles } from "lucide-react";

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

      {/* Marketing tools */}
      <div>
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest mb-3">// Marketing Tools</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <a
            href="https://ads.google.com"
            target="_blank"
            rel="noopener noreferrer"
            data-testid="google-ads-tile"
            className="byrd-card byrd-card-hover p-6 flex items-center gap-4 group"
          >
            <div className="w-12 h-12 shrink-0 rounded-md bg-white border border-[#E4DFD1] grid place-items-center overflow-hidden">
              {/* Google G */}
              <svg viewBox="0 0 48 48" width="24" height="24" aria-hidden="true">
                <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-serif text-lg font-bold">Google Ads Portal</div>
              <div className="text-xs text-[#6B6558] mt-0.5">
                Sign in with your Google account to manage live campaigns on ads.google.com
              </div>
            </div>
            <ExternalLink size={16} className="text-[#6B6558] group-hover:text-[#C89434] shrink-0" />
          </a>
          <Link
            to="/adscopilot"
            data-testid="adscopilot-tile"
            className="byrd-card byrd-card-hover p-6 flex items-center gap-4 group"
          >
            <div className="w-12 h-12 shrink-0 rounded-md bg-[#1A1A1A] text-[#C89434] grid place-items-center">
              <Sparkles size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-serif text-lg font-bold">AdsCopilot</div>
              <div className="text-xs text-[#6B6558] mt-0.5">
                AI ad-copy & keyword tools, plus a campaign performance dashboard.
              </div>
            </div>
            <ArrowRight size={16} className="text-[#6B6558] group-hover:text-[#C89434] shrink-0" />
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="byrd-card p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">// Recent Clients</div>
              <h2 className="font-serif text-2xl font-bold mt-1">Client roster</h2>
            </div>
            <Link to="/admin/clients" className="byrd-btn byrd-btn-outline h-9 px-3 text-xs">
              <Plus size={12} /> Invite
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
