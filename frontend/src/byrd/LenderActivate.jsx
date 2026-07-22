import React, { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function LenderActivate() {
  const { token } = useParams();
  const nav = useNavigate();
  const { activateLender } = useAuth();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/lender/activate/${token}`)
      .then((r) => setInfo(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Activation link invalid"));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (pw.length < 8) return toast.error("Password must be at least 8 characters");
    if (pw !== pw2) return toast.error("Passwords don't match");
    setBusy(true);
    try {
      await activateLender(token, pw);
      toast.success("Portal activated. Welcome aboard!");
      nav("/lender/portal");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Activation failed");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="min-h-screen bg-[#FBF8F1] grid place-items-center px-4" data-testid="activate-error">
        <div className="bg-white border border-[#E4DFD1] rounded-md p-8 text-center max-w-md">
          <div className="font-serif text-xl font-bold text-[#8A1F1A]">Link invalid or already used</div>
          <p className="text-sm text-[#6B6558] mt-2">{error}</p>
          <Link to="/portal/login" className="byrd-btn byrd-btn-outline mt-6 inline-flex">Go to login</Link>
        </div>
      </div>
    );
  }
  if (!info) return <div className="min-h-screen bg-[#FBF8F1] grid place-items-center"><div className="text-sm text-[#6B6558]">Loading…</div></div>;

  return (
    <div className="min-h-screen bg-[#FBF8F1] grid place-items-center px-4" data-testid="lender-activate-page">
      <div className="bg-white border border-[#E4DFD1] rounded-md p-8 w-full max-w-md">
        <div className="font-mono text-[11px] uppercase tracking-widest text-[#6B6558]">// Lender Portal</div>
        <h1 className="font-serif text-2xl font-bold mt-1">Welcome, {info.contact_name}</h1>
        <p className="text-sm text-[#6B6558] mt-2">
          Set a password for <b>{info.lender_name}</b> · {info.email}
        </p>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block">
            <div className="text-xs font-mono uppercase tracking-widest text-[#6B6558] mb-1">Password</div>
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} required minLength={8}
              className="w-full h-11 px-3 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
              data-testid="activate-pw-1" />
          </label>
          <label className="block">
            <div className="text-xs font-mono uppercase tracking-widest text-[#6B6558] mb-1">Confirm Password</div>
            <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} required minLength={8}
              className="w-full h-11 px-3 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
              data-testid="activate-pw-2" />
          </label>
          <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark w-full" data-testid="activate-submit-btn">
            {busy ? "Activating…" : "Activate Portal"}
          </button>
        </form>
      </div>
    </div>
  );
}
