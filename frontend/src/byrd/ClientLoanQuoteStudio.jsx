import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LOGO_URL } from "@/byrd/data";
import { ArrowLeft, LogOut } from "lucide-react";
import AdminLoanQuoteStudio from "@/byrd/AdminLoanQuoteStudio";

/**
 * Client-side wrapper around the shared Loan Quote Studio so listing-agent-type
 * clients can build their own quotes. Same UI + endpoints as the admin studio,
 * except the backend restricts list/get/patch/delete to `created_by_user_id == me`.
 */
export default function ClientLoanQuoteStudio() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  return (
    <div className="min-h-screen bg-[#FBF8F1]" data-testid="client-quote-studio">
      <header className="border-b border-[#E4DFD1] bg-white/80 backdrop-blur sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-10 w-auto" />
            <div className="leading-tight hidden sm:block">
              <div className="font-serif text-lg font-bold">Byrd &amp; CO</div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Agent Studio</div>
            </div>
          </Link>
          <div className="flex items-center gap-3">
            <Link
              to="/portal"
              className="byrd-btn byrd-btn-outline h-10 px-3"
              data-testid="back-to-portal"
            >
              <ArrowLeft size={14} /> My Documents
            </Link>
            <div className="hidden sm:block text-right">
              <div className="text-sm font-semibold">{user?.name}</div>
              <div className="text-xs text-[#6B6558]">{user?.email}</div>
            </div>
            <button
              onClick={() => { logout(); nav("/"); }}
              className="byrd-btn byrd-btn-outline h-10 px-3"
              data-testid="client-studio-logout"
              title="Log out"
            >
              <LogOut size={14} /> Log out
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-5 sm:px-8 py-10 md:py-14">
        <AdminLoanQuoteStudio />
      </main>
    </div>
  );
}
