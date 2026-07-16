import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LOGO_URL } from "@/byrd/data";
import { useAuth } from "@/context/AuthContext";
import { Menu, X } from "lucide-react";

const NAV_ITEMS = [
  { href: "#programs", label: "Programs" },
  { href: "#properties", label: "Properties" },
  { href: "#process", label: "Process" },
  { href: "#principals", label: "Team" },
  { href: "#testimonials", label: "Reviews" },
  { href: "#contact", label: "Contact" },
];

export default function BrandNav() {
  const nav = useNavigate();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);

  const dashboardHref = user?.role === "admin" ? "/admin" : "/portal";

  return (
    <header className="sticky top-0 z-40 border-b border-[#E4DFD1] bg-[#FBF8F1]/85 backdrop-blur">
      <div className="max-w-7xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-3" data-testid="brand-logo">
          <img src={LOGO_URL} alt="Byrd & CO" className="h-10 w-auto" />
          <div className="hidden sm:block leading-tight">
            <div className="font-serif text-lg font-bold text-[#1A1A1A]">Byrd &amp; CO</div>
            <div className="font-mono text-[10px] uppercase text-[#6B6558] tracking-widest">
              Commercial RE Lending
            </div>
          </div>
        </Link>

        <nav className="hidden lg:flex items-center gap-7">
          {NAV_ITEMS.map((n) => (
            <a
              key={n.href}
              href={n.href}
              className="text-sm text-[#2A2A2A] hover:text-[#C89434] transition-colors"
              data-testid={`nav-${n.label.toLowerCase()}`}
            >
              {n.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          {user ? (
            <button
              onClick={() => nav(dashboardHref)}
              className="byrd-btn byrd-btn-outline hidden sm:inline-flex"
              data-testid="nav-dashboard"
            >
              Open Portal
            </button>
          ) : (
            <Link
              to="/portal/login"
              className="byrd-btn byrd-btn-outline hidden sm:inline-flex"
              data-testid="nav-login"
            >
              Client Login
            </Link>
          )}
          <a href="#contact" className="byrd-btn byrd-btn-primary hidden sm:inline-flex" data-testid="nav-quote">
            Request Quote
          </a>
          <button
            className="lg:hidden w-10 h-10 grid place-items-center border border-[#E4DFD1] rounded-md"
            onClick={() => setOpen((o) => !o)}
            data-testid="mobile-menu-toggle"
            aria-label="menu"
          >
            {open ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>

      {open && (
        <div className="lg:hidden border-t border-[#E4DFD1] bg-[#FBF8F1]">
          <div className="max-w-7xl mx-auto px-5 py-4 flex flex-col gap-1">
            {NAV_ITEMS.map((n) => (
              <a
                key={n.href}
                href={n.href}
                className="py-2 text-sm text-[#1A1A1A]"
                onClick={() => setOpen(false)}
              >
                {n.label}
              </a>
            ))}
            {user ? (
              <button onClick={() => nav(dashboardHref)} className="byrd-btn byrd-btn-outline mt-2 w-full">
                Open Portal
              </button>
            ) : (
              <Link to="/portal/login" className="byrd-btn byrd-btn-outline mt-2 w-full">
                Client Login
              </Link>
            )}
            <a href="#contact" className="byrd-btn byrd-btn-primary mt-2 w-full" onClick={() => setOpen(false)}>
              Request Quote
            </a>
          </div>
        </div>
      )}
    </header>
  );
}
