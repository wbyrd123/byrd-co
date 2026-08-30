import React from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LOGO_URL } from "@/byrd/data";
import { ArrowLeft, LogOut } from "lucide-react";
import SecuritySettings from "@/byrd/SecuritySettings";

/**
 * Standalone /portal/security and /lender/portal/security page.
 * Same SecuritySettings component the admin uses — just wrapped in the
 * portal chrome so clients + lenders have a place to enroll in 2FA.
 */
export default function PortalSecurityPage({ backPath = "/portal", label = "Client Portal" }) {
  const { user, logout } = useAuth();
  return (
    <div className="min-h-screen bg-[#FBF8F1]">
      <header className="border-b border-[#E4DFD1] bg-white/80 backdrop-blur sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-10 w-auto" />
            <div className="leading-tight hidden sm:block">
              <div className="font-serif text-lg font-bold">Byrd &amp; CO</div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">{label}</div>
            </div>
          </Link>
          <div className="flex items-center gap-3">
            <div className="hidden sm:block text-right">
              <div className="text-sm font-semibold">{user?.name}</div>
              <div className="text-xs text-[#6B6558]">{user?.email}</div>
            </div>
            <button
              onClick={logout}
              className="byrd-btn byrd-btn-outline h-10 px-3"
              data-testid="portal-security-logout"
            >
              <LogOut size={14} /> Log out
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-5 sm:px-8 py-10 md:py-14">
        <Link
          to={backPath}
          data-testid="portal-security-back"
          className="inline-flex items-center gap-1 text-xs text-[#6B6558] hover:text-[#1A1A1A] mb-6"
        >
          <ArrowLeft size={12} /> Back to {label}
        </Link>
        <SecuritySettings />
      </main>
    </div>
  );
}
