import React, { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  LayoutGrid,
  Megaphone,
  Type,
  Search,
  BarChart3,
  Sparkles,
  LogOut,
  Plus,
  Bot,
  X,
} from "lucide-react";
import CopilotPanel from "@/components/CopilotPanel";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true, testId: "nav-overview" },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone, testId: "nav-campaigns" },
  { to: "/ad-copy", label: "Ad Copy Studio", icon: Type, testId: "nav-adcopy" },
  { to: "/keywords", label: "Keyword Lab", icon: Search, testId: "nav-keywords" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, testId: "nav-analytics" },
];

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [copilotOpen, setCopilotOpen] = useState(true);

  return (
    <div className="min-h-screen flex bg-[#F4F4F0] text-[#111]">
      {/* Sidebar */}
      <aside className="w-[240px] shrink-0 border-r-2 border-black bg-[#F4F4F0] flex flex-col">
        <div className="px-5 py-6 border-b-2 border-black">
          <div className="flex items-center gap-3 font-display text-lg font-bold">
            <div className="w-8 h-8 bg-black text-white grid place-items-center hard-shadow-sm">
              <Sparkles size={16} />
            </div>
            AdsCopilot
          </div>
          <div className="font-mono text-[10px] uppercase mt-2 text-[#555]">
            v1.0 // demo mode
          </div>
        </div>
        <nav className="p-3 space-y-1 flex-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              data-testid={item.testId}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
            >
              <item.icon size={16} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t-2 border-black">
          <button
            data-testid="new-campaign-btn"
            onClick={() => nav("/campaigns/new")}
            className="w-full h-11 bg-[#002FA7] text-white font-mono uppercase text-xs hard-shadow-sm press-effect flex items-center justify-center gap-2"
          >
            <Plus size={14} /> New Campaign
          </button>
        </div>
        <div className="p-3 border-t-2 border-black flex items-center gap-3">
          <div className="w-9 h-9 bg-black text-white grid place-items-center font-mono text-sm font-bold shrink-0">
            {(user?.name || user?.email || "U")[0].toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold truncate" data-testid="user-name">{user?.name}</div>
            <div className="text-[11px] font-mono text-[#555] truncate">{user?.email}</div>
          </div>
          <button
            onClick={() => { logout(); nav("/auth"); }}
            data-testid="logout-btn"
            title="Log out"
            className="w-9 h-9 border-2 border-black grid place-items-center hover:bg-black hover:text-white transition-colors"
          >
            <LogOut size={14} />
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 flex flex-col">
        {/* Top bar */}
        <header className="h-14 border-b-2 border-black px-6 flex items-center justify-between bg-white">
          <div className="font-mono text-xs uppercase text-[#555]">
            <span className="text-black font-semibold">ADSCOPILOT</span> / management console
          </div>
          <div className="flex items-center gap-3">
            <div className="font-mono text-[11px] uppercase px-2 py-1 border-2 border-black">
              connection: <span className="text-[#00C853] font-semibold">demo</span>
            </div>
            <button
              onClick={() => setCopilotOpen((o) => !o)}
              data-testid="toggle-copilot-btn"
              className="h-9 px-3 border-2 border-black font-mono uppercase text-xs flex items-center gap-2 hover:bg-black hover:text-white transition-colors"
            >
              <Bot size={14} />
              {copilotOpen ? "Hide" : "Show"} Copilot
            </button>
          </div>
        </header>

        <div className="flex-1 flex min-h-0">
          <section className="flex-1 min-w-0 overflow-y-auto p-6 fade-up">
            <Outlet />
          </section>
          {copilotOpen && (
            <aside
              className="w-[380px] shrink-0 border-l-2 border-black bg-white flex flex-col"
              data-testid="copilot-panel"
            >
              <div className="h-12 border-b-2 border-black px-4 flex items-center justify-between">
                <div className="flex items-center gap-2 font-mono text-xs uppercase font-semibold">
                  <Bot size={14} /> AI Copilot
                </div>
                <button
                  onClick={() => setCopilotOpen(false)}
                  data-testid="close-copilot-btn"
                  className="w-7 h-7 grid place-items-center hover:bg-black hover:text-white transition-colors"
                >
                  <X size={14} />
                </button>
              </div>
              <CopilotPanel />
            </aside>
          )}
        </div>
      </main>
    </div>
  );
}
