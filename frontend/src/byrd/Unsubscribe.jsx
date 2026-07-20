import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { API_BASE } from "@/lib/api";
import { CheckCircle2, AlertCircle } from "lucide-react";

export default function Unsubscribe() {
  const [sp] = useSearchParams();
  const t = sp.get("t");
  const [state, setState] = useState({ loading: true, ok: false, message: "" });
  useEffect(() => {
    if (!t) { setState({ loading: false, ok: false, message: "Missing token." }); return; }
    fetch(`${API_BASE}/public/unsubscribe?t=${encodeURIComponent(t)}`)
      .then(async (r) => {
        const j = await r.json().catch(() => ({}));
        if (r.ok) setState({ loading: false, ok: true, message: j.email || "you" });
        else setState({ loading: false, ok: false, message: j.detail || "Unable to process." });
      })
      .catch(() => setState({ loading: false, ok: false, message: "Network error." }));
  }, [t]);
  return (
    <div className="min-h-screen bg-[#FBF8F1] flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-white border border-[#E4DFD1] rounded-lg p-8 text-center">
        {state.loading ? (
          <div className="text-[#6B6558] text-sm">Processing…</div>
        ) : state.ok ? (
          <>
            <div className="w-14 h-14 mx-auto rounded-full bg-[#E4F4E4] grid place-items-center text-[#245C25]"><CheckCircle2 size={24} /></div>
            <h1 className="font-serif text-2xl font-bold mt-4">You&apos;re unsubscribed.</h1>
            <p className="text-sm text-[#6B6558] mt-2"><span className="font-mono">{state.message}</span> won&apos;t receive marketing emails from Byrd &amp; CO anymore. Loan-specific correspondence is unaffected.</p>
          </>
        ) : (
          <>
            <div className="w-14 h-14 mx-auto rounded-full bg-[#FADCDA] grid place-items-center text-[#8A1F1A]"><AlertCircle size={24} /></div>
            <h1 className="font-serif text-2xl font-bold mt-4">Something went wrong.</h1>
            <p className="text-sm text-[#6B6558] mt-2">{state.message}</p>
          </>
        )}
      </div>
    </div>
  );
}
