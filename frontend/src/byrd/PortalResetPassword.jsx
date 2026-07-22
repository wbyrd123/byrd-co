import React, { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { KeyRound } from "lucide-react";

export default function PortalResetPassword() {
  const { token } = useParams();
  const nav = useNavigate();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/public/password-reset/${token}`)
      .then((r) => setInfo(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Reset link invalid"));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (pw.length < 8) return toast.error("Password must be at least 8 characters");
    if (pw !== pw2) return toast.error("Passwords don't match");
    setBusy(true);
    try {
      const res = await api.post(`/public/password-reset/${token}`, { password: pw });
      localStorage.setItem("ac_token", res.data.token);
      toast.success("Password updated — you're signed in");
      // Route by role
      const dest = res.data.user?.role === "admin" ? "/admin"
                 : res.data.user?.role === "lender" ? "/lender/portal"
                 : "/portal";
      nav(dest);
      // Force a reload so AuthContext picks up new token
      setTimeout(() => window.location.reload(), 100);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="min-h-screen bg-[#FBF8F1] grid place-items-center px-4" data-testid="reset-error">
        <div className="bg-white border border-[#E4DFD1] rounded-md p-8 max-w-md text-center">
          <div className="font-serif text-xl font-bold text-[#8A1F1A]">Link invalid or expired</div>
          <p className="text-sm text-[#6B6558] mt-2">{error}</p>
          <Link to="/portal/forgot-password" className="byrd-btn byrd-btn-dark mt-6 inline-flex">
            Request a new link
          </Link>
        </div>
      </div>
    );
  }
  if (!info) return <div className="min-h-screen bg-[#FBF8F1] grid place-items-center"><div className="text-sm text-[#6B6558]">Loading…</div></div>;

  return (
    <div className="min-h-screen bg-[#FBF8F1] grid place-items-center px-4" data-testid="reset-password-page">
      <div className="bg-white border border-[#E4DFD1] rounded-md p-8 w-full max-w-md">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-md bg-[#F3EEE0] text-[#C89434] grid place-items-center">
            <KeyRound size={18} />
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Reset Password</div>
            <h1 className="font-serif text-2xl font-bold">Choose a new password</h1>
          </div>
        </div>
        <p className="text-sm text-[#6B6558] mt-3">
          Resetting the password for <b>{info.email_masked}</b>.
        </p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block">
            <div className="text-xs font-mono uppercase tracking-widest text-[#6B6558] mb-1">New Password</div>
            <input
              type="password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              required
              minLength={8}
              autoFocus
              className="w-full h-11 px-3 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
              data-testid="reset-pw-1"
            />
          </label>
          <label className="block">
            <div className="text-xs font-mono uppercase tracking-widest text-[#6B6558] mb-1">Confirm New Password</div>
            <input
              type="password"
              value={pw2}
              onChange={(e) => setPw2(e.target.value)}
              required
              minLength={8}
              className="w-full h-11 px-3 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
              data-testid="reset-pw-2"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="byrd-btn byrd-btn-dark w-full"
            data-testid="reset-submit-btn"
          >
            {busy ? "Updating…" : "Update password"}
          </button>
        </form>
      </div>
    </div>
  );
}
