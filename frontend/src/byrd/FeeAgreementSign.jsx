import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "@/lib/api";
import { LOGO_URL } from "@/byrd/data";
import { CheckCircle2, FileText, ShieldCheck, AlertCircle, PenLine } from "lucide-react";

// Public (no-auth) fee agreement signing page. Loaded via /fee-agreement/:token
export default function FeeAgreementSign() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [typedName, setTypedName] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    axios.get(`${API_BASE}/fee-agreement/${token}`)
      .then((r) => {
        setData(r.data);
        setTypedName(r.data.client?.name || "");
      })
      .catch((e) => setError(e?.response?.data?.detail || "This link is invalid or expired."));
  }, [token]);

  const submit = async () => {
    if (!agree || typedName.trim().length < 2) return;
    setBusy(true);
    try {
      await axios.post(`${API_BASE}/fee-agreement/${token}/sign`, {
        typed_name: typedName.trim(),
        agree: true,
      });
      setDone(true);
    } catch (e) {
      setError(e?.response?.data?.detail || "Signing failed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <ShellHeaderContainer>
        <div className="byrd-card p-8 md:p-10 text-center" data-testid="fee-agreement-error">
          <AlertCircle size={40} className="text-[#8A1F1A] mx-auto" />
          <h2 className="font-serif text-2xl font-bold mt-3">We couldn&apos;t open this agreement.</h2>
          <p className="text-[#6B6558] mt-2">{error}</p>
          <p className="text-[#6B6558] mt-2 text-sm">
            If you were sent a fresh link, use the newest one. Otherwise reach out to your broker.
          </p>
        </div>
      </ShellHeaderContainer>
    );
  }
  if (!data) {
    return (
      <ShellHeaderContainer>
        <div className="byrd-card p-8 text-center text-[#6B6558]">Loading your agreement…</div>
      </ShellHeaderContainer>
    );
  }

  const alreadySigned = data.status === "signed" || done;
  const canceled = data.status === "canceled" || data.status === "superseded";
  const pdfUrl = `${API_BASE}/fee-agreement/${token}/preview.pdf`;

  return (
    <ShellHeaderContainer>
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6" data-testid="fee-agreement-page">
        <div className="byrd-card overflow-hidden">
          <div className="border-b border-[#E4DFD1] px-5 py-4 flex items-center justify-between gap-3 flex-wrap">
            <div className="inline-flex items-center gap-2">
              <div className="w-8 h-8 rounded-md bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1]">
                <FileText size={14} />
              </div>
              <div>
                <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Fee Agreement</div>
                <div className="font-serif text-lg font-bold leading-tight">{data.scenario.name}</div>
              </div>
            </div>
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="byrd-btn byrd-btn-outline h-9 px-3 text-xs"
              data-testid="fee-download"
            >
              Download PDF
            </a>
          </div>
          <object
            data={pdfUrl}
            type="application/pdf"
            className="w-full h-[75vh] bg-[#FBF8F1]"
            aria-label="Fee agreement PDF"
          >
            <div className="p-8 text-center text-[#6B6558] text-sm">
              Your browser can&apos;t preview PDFs inline.{" "}
              <a className="underline text-[#1A1A1A]" href={pdfUrl} target="_blank" rel="noopener noreferrer">
                Open it here.
              </a>
            </div>
          </object>
        </div>

        <aside className="space-y-4">
          <div className="byrd-card p-5" data-testid="fee-summary">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Summary</div>
            <div className="mt-2 space-y-2 text-sm">
              <SumRow label="Borrower" value={data.client.name} />
              {data.client.company && <SumRow label="Entity" value={data.client.company} />}
              <SumRow label="Property" value={data.scenario.property_address} />
              {data.scenario.property_type && <SumRow label="Type" value={data.scenario.property_type} />}
              {data.scenario.loan_type && <SumRow label="Loan" value={data.scenario.loan_type} />}
              <SumRow label="Broker Fee" value={`${data.broker_fee_pct}% of loan amount at closing`} highlight />
              <SumRow label="Agreement Date" value={data.agreement_date} />
              <SumRow label="Broker" value={`${data.broker.name}, Byrd & CO`} />
            </div>
          </div>

          {alreadySigned ? (
            <div className="byrd-card p-5 bg-[#E5F0E5] border-[#245C25]" data-testid="fee-signed-state">
              <div className="flex items-start gap-2">
                <CheckCircle2 size={20} className="text-[#245C25] shrink-0 mt-0.5" />
                <div>
                  <div className="font-serif text-lg font-bold text-[#245C25]">Signed & Executed</div>
                  <p className="text-sm text-[#2A2A2A] mt-1">
                    This agreement is fully executed by both sides. A signed copy is available above and has been
                    emailed to you. You&apos;re all set — your broker will begin shopping the loan.
                  </p>
                </div>
              </div>
            </div>
          ) : canceled ? (
            <div className="byrd-card p-5" data-testid="fee-canceled-state">
              <div className="flex items-start gap-2">
                <AlertCircle size={20} className="text-[#8A1F1A] shrink-0 mt-0.5" />
                <div>
                  <div className="font-serif text-lg font-bold text-[#8A1F1A]">This link is no longer active.</div>
                  <p className="text-sm text-[#6B6558] mt-1">
                    Your broker either canceled it or sent a newer version. Please use the most recent link
                    from your inbox, or reach out to them.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div className="byrd-card p-5" data-testid="fee-sign-form">
              <div className="inline-flex items-center gap-2 text-[#C89434]">
                <PenLine size={16} />
                <span className="font-mono text-[10px] uppercase tracking-widest">// Sign electronically</span>
              </div>
              <label className="block mt-3 text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">
                Type your full legal name
              </label>
              <input
                value={typedName}
                onChange={(e) => setTypedName(e.target.value)}
                data-testid="fee-typed-name"
                placeholder="e.g. Sample Borrower"
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm"
              />
              {typedName.trim().length >= 2 && (
                <div className="mt-2 border border-dashed border-[#C89434] bg-[#FBEFD3]/50 rounded-md p-3 text-center">
                  <div className="font-mono text-[9px] uppercase tracking-widest text-[#7A5410]">Preview</div>
                  <div className="italic font-serif text-2xl mt-1 text-[#1A1A1A]">{typedName.trim()}</div>
                </div>
              )}
              <label className="mt-3 flex items-start gap-2 text-sm text-[#2A2A2A] cursor-pointer">
                <input
                  type="checkbox"
                  checked={agree}
                  onChange={(e) => setAgree(e.target.checked)}
                  data-testid="fee-agree-checkbox"
                  className="mt-0.5"
                />
                <span>
                  I have read the agreement above and agree that typing my name and clicking &ldquo;Agree
                  &amp; Sign&rdquo; constitutes my legally binding electronic signature. I understand the broker
                  fee is <b>{data.broker_fee_pct}%</b> of the total loan amount, paid at closing directly through escrow.
                </span>
              </label>
              <button
                onClick={submit}
                disabled={busy || !agree || typedName.trim().length < 2}
                className="byrd-btn byrd-btn-dark w-full mt-4"
                data-testid="fee-sign-submit"
              >
                {busy ? "Signing…" : "Agree & Sign"}
              </button>
              <div className="mt-2 text-[11px] text-[#6B6558] inline-flex items-center gap-1">
                <ShieldCheck size={11} /> Byrd &amp; CO will countersign automatically and email you the executed copy.
              </div>
            </div>
          )}

          <div className="text-[11px] text-[#6B6558] px-1">
            Questions? Email {data.broker.email} or call {data.broker.phone}.
          </div>
        </aside>
      </div>
    </ShellHeaderContainer>
  );
}

function SumRow({ label, value, highlight }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] w-24 shrink-0 pt-0.5">{label}</div>
      <div className={`min-w-0 flex-1 ${highlight ? "font-semibold text-[#C89434]" : "text-[#1A1A1A]"}`}>{value || "—"}</div>
    </div>
  );
}

function ShellHeaderContainer({ children }) {
  return (
    <div className="min-h-screen bg-[#FBF8F1]">
      <header className="border-b border-[#E4DFD1] bg-white/80 backdrop-blur">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 h-16 flex items-center gap-3">
          <img src={LOGO_URL} alt="Byrd & CO" className="h-9 w-auto" />
          <div className="leading-tight">
            <div className="font-serif text-lg font-bold">Byrd &amp; CO</div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">
              Broker Fee Agreement
            </div>
          </div>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-5 sm:px-8 py-8 md:py-10">{children}</main>
    </div>
  );
}
