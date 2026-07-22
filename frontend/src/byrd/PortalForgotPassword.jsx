import React, { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { KeyRound, ArrowLeft, Mail } from "lucide-react";

export default function PortalForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/public/password-reset/request", { email: email.trim().toLowerCase() });
      setSent(true);
    } catch (err) {
      // The endpoint always returns 200, but just in case
      toast.error(err?.response?.data?.detail || "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FBF8F1] grid place-items-center px-4" data-testid="forgot-password-page">
      <div className="bg-white border border-[#E4DFD1] rounded-md p-8 w-full max-w-md">
        <Link to="/portal/login" className="text-xs font-mono uppercase tracking-widest text-[#6B6558] hover:text-[#C89434] inline-flex items-center gap-1">
          <ArrowLeft size={12} /> Back to Login
        </Link>
        <div className="mt-6 flex items-center gap-3">
          <div className="w-10 h-10 rounded-md bg-[#F3EEE0] text-[#C89434] grid place-items-center">
            <KeyRound size={18} />
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Password Reset</div>
            <h1 className="font-serif text-2xl font-bold">Forgot your password?</h1>
          </div>
        </div>

        {sent ? (
          <div className="mt-6 space-y-4" data-testid="forgot-password-sent">
            <div className="p-4 bg-[#E5F0E5] border border-[#C9E1C9] rounded-md flex items-start gap-3">
              <Mail size={18} className="text-[#245C25] shrink-0 mt-0.5" />
              <div className="text-sm text-[#1A3A1A]">
                If an account exists for <b>{email}</b>, we've sent a reset link. Check your inbox
                (and your spam folder). The link expires in 60 minutes.
              </div>
            </div>
            <Link to="/portal/login" className="byrd-btn byrd-btn-outline w-full">
              Back to login
            </Link>
          </div>
        ) : (
          <>
            <p className="text-sm text-[#6B6558] mt-4">
              Enter your email and we'll send you a link to reset your password. Works for
              client, lender, and broker accounts.
            </p>
            <form onSubmit={submit} className="mt-6 space-y-4">
              <label className="block">
                <div className="text-xs font-mono uppercase tracking-widest text-[#6B6558] mb-1">Email</div>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  className="w-full h-11 px-3 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
                  data-testid="forgot-email"
                />
              </label>
              <button
                type="submit"
                disabled={busy || !email}
                className="byrd-btn byrd-btn-dark w-full"
                data-testid="forgot-submit-btn"
              >
                {busy ? "Sending…" : "Send reset link"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
