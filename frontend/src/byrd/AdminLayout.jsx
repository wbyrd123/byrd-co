import React from "react";
import { NavLink, Outlet, Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LOGO_URL } from "@/byrd/data";
import {
  LayoutDashboard, Users, Inbox, Sparkles, LogOut, FileText, Building2, BookOpen, MessageSquareQuote,
  Bot, Contact, ShieldCheck, ScrollText,
} from "lucide-react";

const NAV = [
  { to: "/admin", label: "Overview", icon: LayoutDashboard, end: true, testId: "admin-nav-overview" },
  { to: "/admin/assistant", label: "Personal Assistant", icon: Bot, testId: "admin-nav-assistant" },
  { to: "/admin/clients", label: "Clients", icon: Users, testId: "admin-nav-clients" },
  { to: "/admin/contacts", label: "Contacts", icon: Contact, testId: "admin-nav-contacts" },
  { to: "/admin/scenarios", label: "Scenarios", icon: FileText, testId: "admin-nav-scenarios" },
  { to: "/admin/lenders", label: "Lenders", icon: Building2, testId: "admin-nav-lenders" },
  { to: "/admin/quotes", label: "Quote Inbox", icon: Inbox, testId: "admin-nav-quotes" },
  { to: "/admin/testimonials", label: "Testimonials", icon: MessageSquareQuote, testId: "admin-nav-testimonials" },
  { to: "/admin/security", label: "Security", icon: ShieldCheck, testId: "admin-nav-security" },
  { to: "/admin/audit-log", label: "Audit Log", icon: ScrollText, testId: "admin-nav-audit-log" },
  { to: "/admin/guide", label: "Guide", icon: BookOpen, testId: "admin-nav-guide" },
];

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  return (
    <div className="min-h-screen bg-[#FBF8F1] flex">
      <aside className="w-[260px] shrink-0 border-r border-[#E4DFD1] bg-white flex flex-col">
        <div className="px-5 py-5 border-b border-[#E4DFD1]">
          <Link to="/" className="flex items-center gap-3">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-10 w-auto" />
            <div className="leading-tight">
              <div className="font-serif text-lg font-bold">Byrd &amp; CO</div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Broker Console</div>
            </div>
          </Link>
        </div>
        <nav className="p-3 space-y-1 flex-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              data-testid={n.testId}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
                  isActive
                    ? "bg-[#1A1A1A] text-white"
                    : "text-[#2A2A2A] hover:bg-[#F3EEE0]"
                }`
              }
            >
              <n.icon size={16} /> {n.label}
            </NavLink>
          ))}
          <div className="pt-4 mt-4 border-t border-[#E4DFD1]">
            <div className="px-3 pb-2 font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">
              // Marketing
            </div>
            <button
              onClick={() => nav("/admin/marketing/loan-quote")}
              data-testid="admin-open-loan-quote-studio"
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-[#2A2A2A] hover:bg-[#F3EEE0]"
            >
              <FileText size={16} /> Loan Quote Studio
            </button>
            <button
              onClick={() => nav("/adscopilot")}
              data-testid="admin-open-google-ads-portal"
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-[#2A2A2A] hover:bg-[#F3EEE0]"
            >
              <Sparkles size={16} /> Google Ads Portal
            </button>
          </div>
        </nav>
        <div className="p-3 border-t border-[#E4DFD1] flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-[#C89434] text-[#1A1A1A] grid place-items-center font-semibold shrink-0">
            {(user?.name || "A")[0].toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold truncate">{user?.name}</div>
            <div className="text-[11px] text-[#6B6558] truncate">{user?.email}</div>
          </div>
          <button
            onClick={() => { logout(); nav("/portal/login"); }}
            data-testid="admin-logout"
            className="w-9 h-9 rounded-md border border-[#E4DFD1] grid place-items-center hover:bg-[#1A1A1A] hover:text-white transition-colors"
            title="Log out"
          >
            <LogOut size={14} />
          </button>
        </div>
      </aside>
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <div className="max-w-6xl mx-auto p-6 md:p-10 fade-up">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
