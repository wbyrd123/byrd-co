import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { API_BASE } from "@/lib/api";
import { LOGO_URL } from "@/byrd/data";
import { fmtMoney, fmtPct, fmtNum } from "@/byrd/dealData";
import { toast } from "sonner";
import {
  ShieldCheck, ArrowRight, FileText, Download, Lock, Mail, Building2, Send, Check,
} from "lucide-react";

// Simple fetch wrapper (public endpoints)
const publicFetch = async (path, options = {}) => {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
};

const SESSION_KEY = (token) => `lender_session_${token}`;

export default function LenderView() {
  const { token } = useParams();
  const [preflight, setPreflight] = useState(null);
  const [preflightError, setPreflightError] = useState(null);
  const [session, setSession] = useState(localStorage.getItem(SESSION_KEY(token)) || null);
  const [pkg, setPkg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [gate, setGate] = useState({ viewer_name: "", viewer_email: "", viewer_institution: "" });
  const [requestedNow, setRequestedNow] = useState(false);

  useEffect(() => {
    publicFetch(`/lender-view/${token}/preflight`)
      .then(setPreflight)
      .catch((e) => setPreflightError(e.message));
  }, [token]);

  const loadPackage = async (sess) => {
    try {
      const data = await publicFetch(`/lender-view/${token}?session_token=${encodeURIComponent(sess)}`);
      setPkg(data);
    } catch (e) {
      // session expired
      localStorage.removeItem(SESSION_KEY(token));
      setSession(null);
      toast.error("Session expired — please re-enter your details.");
    }
  };

  useEffect(() => {
    if (session) loadPackage(session);
  }, [session]);

  const submitGate = async (e) => {
    e.preventDefault();
    if (!gate.viewer_name || !gate.viewer_email || !gate.viewer_institution) {
      toast.error("All three fields are required");
      return;
    }
    setBusy(true);
    try {
      const res = await publicFetch(`/lender-view/${token}/gate`, {
        method: "POST",
        body: JSON.stringify(gate),
      });
      localStorage.setItem(SESSION_KEY(token), res.session_token);
      setSession(res.session_token);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  };

  const requestAll = async () => {
    try {
      await publicFetch(`/lender-view/${token}/request-docs?session_token=${encodeURIComponent(session)}`, { method: "POST" });
      setRequestedNow(true);
      toast.success("Request sent to the broker");
    } catch (e) {
      toast.error(e.message);
    }
  };

  const openDoc = async (docId) => {
    try {
      const res = await fetch(`${API_BASE}/lender-view/${token}/doc/${docId}?session_token=${encodeURIComponent(session)}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Not authorized");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    } catch (e) {
      toast.error(e.message);
    }
  };

  const downloadPdf = async () => {
    try {
      const res = await fetch(`${API_BASE}/lender-view/${token}/pdf?session_token=${encodeURIComponent(session)}`);
      if (!res.ok) throw new Error("Failed to generate PDF");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    } catch (e) {
      toast.error(e.message);
    }
  };

  const downloadZip = async () => {
    try {
      const res = await fetch(`${API_BASE}/lender-view/${token}/docs.zip?session_token=${encodeURIComponent(session)}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "No documents available to download");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `byrd-package-${token.slice(0, 8)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Package downloaded");
    } catch (e) {
      toast.error(e.message);
    }
  };

  if (preflightError) {
    return (
      <Shell>
        <div className="max-w-lg mx-auto byrd-card p-8 text-center">
          <div className="w-12 h-12 mx-auto rounded-full bg-[#FADCDA] text-[#8A1F1A] grid place-items-center">
            <Lock size={20} />
          </div>
          <h1 className="font-serif text-2xl font-bold mt-4">Link Unavailable</h1>
          <p className="text-sm text-[#6B6558] mt-2">{preflightError}</p>
          <p className="text-xs text-[#6B6558] mt-4">If you believe this is an error, contact your Byrd &amp; CO broker.</p>
        </div>
      </Shell>
    );
  }

  if (!preflight) {
    return <Shell><div className="text-sm text-[#6B6558]">Loading…</div></Shell>;
  }

  // Soft gate
  if (!session) {
    return (
      <Shell>
        <div className="max-w-lg mx-auto byrd-card p-8 md:p-10" data-testid="lender-gate">
          <div className="byrd-chip byrd-chip-gold"><ShieldCheck size={12} /> Confidential Loan Package</div>
          <h1 className="font-serif text-3xl font-bold mt-4">{preflight.scenario_name}</h1>
          <p className="text-sm text-[#6B6558] mt-3">
            You&apos;ve been sent a private loan package by Byrd &amp; CO. Please confirm your identity
            before viewing — this creates the audit trail your broker uses to track lender interest.
          </p>

          <form onSubmit={submitGate} className="mt-6 space-y-4">
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Your Name *</label>
              <input required value={gate.viewer_name} onChange={(e) => setGate({ ...gate, viewer_name: e.target.value })}
                data-testid="gate-name"
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]" />
            </div>
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Work Email *</label>
              <input required type="email" value={gate.viewer_email} onChange={(e) => setGate({ ...gate, viewer_email: e.target.value })}
                data-testid="gate-email"
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]" />
            </div>
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Institution *</label>
              <input required value={gate.viewer_institution} onChange={(e) => setGate({ ...gate, viewer_institution: e.target.value })}
                data-testid="gate-institution" placeholder="e.g. Frost Bank"
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]" />
            </div>
            <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark w-full" data-testid="gate-submit">
              {busy ? "Verifying…" : "View Package"} <ArrowRight size={14} />
            </button>
            <p className="text-[11px] text-[#6B6558]">
              By continuing you acknowledge this material is confidential, watermarked, and prepared for your use only.
            </p>
          </form>
        </div>
      </Shell>
    );
  }

  if (!pkg) return <Shell><div className="text-sm text-[#6B6558]">Opening package…</div></Shell>;

  const m = pkg.metrics || {};
  const prop = pkg.property_info || {};
  const loan = pkg.loan_request || {};
  const su = pkg.sources_uses || [];
  const sources = su.filter((s) => s.category === "source");
  const uses = su.filter((s) => s.category === "use");
  const onRequest = (pkg.docs || []).filter((d) => d.requires_request);
  const readyDocs = (pkg.docs || []).filter((d) => !d.requires_request && d.has_file);
  const anyPending = onRequest.length > 0;

  return (
    <Shell watermark={pkg.watermark}>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="byrd-card p-6 md:p-8">
          <div className="flex items-start justify-between flex-wrap gap-3">
            <div>
              <div className="byrd-chip byrd-chip-gold"><ShieldCheck size={12} /> Confidential — for {pkg.watermark}</div>
              <h1 className="font-serif text-3xl md:text-4xl font-bold mt-3">{pkg.name}</h1>
              <div className="text-sm text-[#6B6558] mt-1">
                {prop.address ? `${prop.address}, ` : ""}{[prop.city, prop.state, prop.zip].filter(Boolean).join(", ")}
              </div>
            </div>
            <button onClick={downloadPdf} className="byrd-btn byrd-btn-primary" data-testid="lender-download-pdf">
              <Download size={14} /> Download PDF
            </button>
          </div>
          {pkg.share_note && (
            <div className="mt-4 p-3 rounded-md bg-[#FBEFD3] border border-[#E5B968] text-sm text-[#7A5410]" data-testid="share-note">
              <b>From your broker:</b> {pkg.share_note}
            </div>
          )}
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {[
            ["Loan", fmtMoney(loan.loan_amount)],
            ["Value", fmtMoney(m.property_value)],
            ["LTV", fmtPct(m.ltv_pct, 1)],
            ["LTC", fmtPct(m.ltc_pct, 1)],
            ["DSCR", m.dscr ?? "—"],
            ["Debt Yield", fmtPct(m.debt_yield_pct, 2)],
            ["NOI", fmtMoney(m.noi)],
            ["Monthly P&I", fmtMoney(m.monthly_payment)],
            ["Rate", fmtPct(loan.requested_rate_pct, 3)],
            ["Amort", fmtNum(loan.amort_months)],
            ["Term", fmtNum(loan.term_months)],
            ["Recourse", loan.recourse || "—"],
          ].map(([label, val]) => (
            <div key={label} className="byrd-card p-3">
              <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</div>
              <div className="font-serif text-lg font-bold mt-1">{val}</div>
            </div>
          ))}
        </div>

        {/* Property + Loan Detail */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="byrd-card p-6">
            <h3 className="font-serif text-xl font-bold mb-3">Property</h3>
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-[#6B6558]">Type</dt><dd>{prop.property_type || "—"}</dd>
              <dt className="text-[#6B6558]">Year Built</dt><dd>{fmtNum(prop.year_built)}</dd>
              <dt className="text-[#6B6558]">Units</dt><dd>{fmtNum(prop.units)}</dd>
              <dt className="text-[#6B6558]">Sq Ft</dt><dd>{fmtNum(prop.sqft)}</dd>
              <dt className="text-[#6B6558]">Occupancy</dt><dd>{fmtPct(prop.occupancy_pct, 1)}</dd>
              <dt className="text-[#6B6558]">Purchase</dt><dd>{fmtMoney(prop.purchase_price)}</dd>
              <dt className="text-[#6B6558]">Current Value</dt><dd>{fmtMoney(prop.current_value)}</dd>
            </dl>
          </div>
          <div className="byrd-card p-6">
            <h3 className="font-serif text-xl font-bold mb-3">Loan Request</h3>
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-[#6B6558]">Type</dt><dd>{loan.loan_type || "—"}</dd>
              <dt className="text-[#6B6558]">Amount</dt><dd>{fmtMoney(loan.loan_amount)}</dd>
              <dt className="text-[#6B6558]">Rate</dt><dd>{fmtPct(loan.requested_rate_pct, 3)}</dd>
              <dt className="text-[#6B6558]">Amortization</dt><dd>{fmtNum(loan.amort_months)} mo</dd>
              <dt className="text-[#6B6558]">Term</dt><dd>{fmtNum(loan.term_months)} mo</dd>
              <dt className="text-[#6B6558]">Recourse</dt><dd>{loan.recourse || "—"}</dd>
              <dt className="text-[#6B6558]">Annual DS</dt><dd>{fmtMoney(m.annual_debt_service)}</dd>
            </dl>
          </div>
        </div>

        {/* Sponsors */}
        {(pkg.sponsors || []).length > 0 && (
          <div className="byrd-card p-6" data-testid="lender-sponsors">
            <h3 className="font-serif text-xl font-bold mb-3">
              Sponsors ({pkg.sponsors.length})
            </h3>
            <p className="text-[11px] text-[#6B6558] mb-3">Every guarantor listed here is on the loan.</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {pkg.sponsors.map((sp, idx) => (
                <div key={idx} className="border border-[#E4DFD1] rounded-md p-4 bg-white">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="font-semibold">{sp.name}</div>
                    <div className="flex items-center gap-1">
                      {sp.role === "managing" && <span className="byrd-chip byrd-chip-gold">Managing</span>}
                      {sp.is_guarantor && sp.role !== "managing" && <span className="byrd-chip">Guarantor</span>}
                      {sp.role === "passive" && <span className="byrd-chip">Passive</span>}
                    </div>
                  </div>
                  {sp.entity && <div className="text-xs text-[#6B6558] mt-1">Entity: {sp.entity}</div>}
                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    <div><span className="text-[#6B6558]">Ownership:</span> <b>{sp.ownership_pct != null ? `${sp.ownership_pct}%` : "—"}</b></div>
                    <div><span className="text-[#6B6558]">FICO:</span> {sp.credit_score || "—"}</div>
                    <div><span className="text-[#6B6558]">Liquidity:</span> {sp.liquidity != null ? fmtMoney(sp.liquidity) : "—"}</div>
                    <div><span className="text-[#6B6558]">Net Worth:</span> {sp.net_worth != null ? fmtMoney(sp.net_worth) : "—"}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Sources & Uses */}
        {su.length > 0 && (
          <div className="byrd-card p-6">
            <h3 className="font-serif text-xl font-bold mb-3">Sources &amp; Uses</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <SUList title="Sources" rows={sources} />
              <SUList title="Uses" rows={uses} />
            </div>
          </div>
        )}

        {/* Business plan */}
        {pkg.business_plan && (
          <div className="byrd-card p-6">
            <h3 className="font-serif text-xl font-bold mb-2">Business Plan</h3>
            <p className="text-sm whitespace-pre-wrap leading-relaxed">{pkg.business_plan}</p>
          </div>
        )}
        {pkg.notes && (
          <div className="byrd-card p-6">
            <h3 className="font-serif text-xl font-bold mb-2">Notes</h3>
            <p className="text-sm whitespace-pre-wrap leading-relaxed">{pkg.notes}</p>
          </div>
        )}

        {/* Documents */}
        <div className="byrd-card p-6" data-testid="lender-docs">
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <h3 className="font-serif text-xl font-bold">Documents</h3>
            <div className="flex items-center gap-2 flex-wrap">
              {readyDocs.length > 0 && (
                <button onClick={downloadZip} className="byrd-btn byrd-btn-outline" data-testid="lender-download-zip">
                  <Download size={14} /> Download All (ZIP)
                </button>
              )}
              {anyPending && !requestedNow && (
                <button onClick={requestAll} className="byrd-btn byrd-btn-dark" data-testid="request-docs-btn">
                  <Send size={14} /> Request Full Data Room
                </button>
              )}
              {requestedNow && (
                <div className="byrd-chip byrd-chip-green"><Check size={12} /> Request sent to broker</div>
              )}
            </div>
          </div>

          {readyDocs.length > 0 && (
            <>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Available Now</div>
              <div className="mt-2 space-y-2">
                {readyDocs.map((d) => (
                  <div key={d.id} className="flex items-center justify-between border border-[#E4DFD1] rounded-md p-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <FileText size={16} className="text-[#C89434] shrink-0" />
                      <div className="min-w-0">
                        <div className="font-semibold text-sm truncate">{d.label}</div>
                        <div className="text-xs text-[#6B6558]">{d.category}</div>
                      </div>
                    </div>
                    <button onClick={() => openDoc(d.id)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`lender-view-doc-${d.id}`}>
                      <Download size={12} /> View
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}

          {onRequest.length > 0 && (
            <>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] mt-6">// On Request</div>
              <div className="mt-2 space-y-2">
                {onRequest.map((d) => (
                  <div key={d.id} className="flex items-center justify-between border border-dashed border-[#E4DFD1] rounded-md p-3 bg-[#FBF8F1]">
                    <div className="flex items-center gap-3 min-w-0">
                      <Lock size={16} className="text-[#6B6558] shrink-0" />
                      <div className="min-w-0">
                        <div className="font-semibold text-sm truncate">{d.label}</div>
                        <div className="text-xs text-[#6B6558]">Broker will grant access on request</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {readyDocs.length === 0 && onRequest.length === 0 && (
            <div className="text-sm text-[#6B6558]">No documents have been attached to this package yet.</div>
          )}
        </div>
      </div>
    </Shell>
  );
}

function SUList({ title, rows }) {
  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] mb-1">// {title}</div>
      <div className="border border-[#E4DFD1] rounded-md overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-3 text-xs text-[#6B6558]">None</div>
        ) : (
          rows.map((r, i) => (
            <div key={i} className="flex justify-between px-3 py-2 border-b border-[#E4DFD1] last:border-b-0 text-sm">
              <span>{r.label}</span>
              <span className="font-mono">{fmtMoney(r.amount)}</span>
            </div>
          ))
        )}
        <div className="flex justify-between px-3 py-2 bg-[#FBF8F1] font-semibold text-sm">
          <span>Total</span>
          <span className="font-mono">{fmtMoney(total)}</span>
        </div>
      </div>
    </div>
  );
}

function Shell({ children, watermark }) {
  return (
    <div className="min-h-screen bg-[#FBF8F1] relative">
      <header className="border-b border-[#E4DFD1] bg-white/80 backdrop-blur">
        <div className="max-w-5xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-3">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-10 w-auto" />
            <div className="leading-tight hidden sm:block">
              <div className="font-serif text-lg font-bold">Byrd &amp; CO</div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Loan Package</div>
            </div>
          </a>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] hidden sm:block">
            Confidential
          </div>
        </div>
      </header>
      {watermark && (
        <div
          className="pointer-events-none fixed inset-0 z-0 flex items-center justify-center overflow-hidden select-none"
          style={{ zIndex: 0 }}
          aria-hidden="true"
        >
          <div
            className="font-serif font-bold whitespace-nowrap"
            style={{
              color: "rgba(200,148,52,0.10)",
              fontSize: "clamp(60px, 10vw, 140px)",
              transform: "rotate(-30deg)",
            }}
          >
            {watermark}
          </div>
        </div>
      )}
      <main className="relative z-10 px-5 sm:px-8 py-8 md:py-12">{children}</main>
    </div>
  );
}
