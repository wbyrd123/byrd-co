import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LOGO_URL } from "@/byrd/data";
import { toast } from "sonner";
import { ArrowRight, ArrowLeft } from "lucide-react";

export default function PortalLogin() {
  const nav = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const user = await login(email, pw);
      toast.success(`Welcome back, ${user.name}`);
      const dest = user.role === "admin" ? "/admin"
                 : user.role === "lender" ? "/lender/portal"
                 : "/portal";
      nav(dest);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Invalid credentials");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FBF8F1] flex flex-col">
      <div className="max-w-6xl w-full mx-auto px-5 sm:px-8 py-6">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-[#6B6558] hover:text-[#1A1A1A]" data-testid="back-home">
          <ArrowLeft size={14} /> Back to home
        </Link>
      </div>

      <div className="flex-1 flex items-center justify-center px-5 pb-16">
        <div className="w-full max-w-md byrd-card p-8 md:p-10" data-testid="login-card">
          <div className="flex items-center gap-3 mb-8">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-12 w-auto" />
            <div>
              <div className="font-serif text-xl font-bold">Byrd &amp; CO</div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Client Portal</div>
            </div>
          </div>

          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Sign In</div>
          <h1 className="font-serif text-3xl font-bold mt-2">Welcome back.</h1>
          <p className="text-sm text-[#6B6558] mt-2">
            Enter the credentials you set up when you accepted your invite.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Email</label>
              <input
                type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                data-testid="login-email"
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Password</label>
              <input
                type="password" required value={pw} onChange={(e) => setPw(e.target.value)}
                data-testid="login-password"
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                placeholder="•••••••"
              />
            </div>
            <button type="submit" disabled={busy} data-testid="login-submit" className="byrd-btn byrd-btn-dark w-full">
              {busy ? "Signing in…" : "Sign In"} <ArrowRight size={16} />
            </button>
          </form>

          <div className="text-xs text-[#6B6558] mt-6 leading-relaxed">
            Don&apos;t have an account? Byrd &amp; CO invites clients directly — reach out to your loan officer to
            get a portal invite link.
          </div>
        </div>
      </div>
    </div>
  );
}
