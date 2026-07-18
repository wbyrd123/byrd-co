import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Users, Inbox, FileCheck, ArrowRight, Plus, Sparkles } from "lucide-react";

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
