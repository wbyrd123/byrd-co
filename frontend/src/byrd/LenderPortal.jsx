import React, { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
  Building2, LogOut, Sliders, Inbox, FileText, Check, X as XIcon,
  Send, Edit3, ExternalLink, Upload, Paperclip, Download,
} from "lucide-react";

const PROPERTY_TYPES = [
  "Multifamily", "Office", "Retail", "Industrial", "Hospitality",
  "Self-storage", "Mixed-use", "Medical Office", "Mobile Home Park", "Land",
  "New Construction",
];

const Input = (p) => (
  <input {...p} className={`w-full h-10 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm focus:outline-none focus:border-[#C89434] ${p.className || ""}`} />
);
const Textarea = (p) => (
  <textarea {...p} className={`w-full min-h-[70px] px-3 py-2 border border-[#E4DFD1] bg-white rounded-md text-sm focus:outline-none focus:border-[#C89434] ${p.className || ""}`} />
);
const Sel = (p) => (
  <select {...p} className={`w-full h-10 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm ${p.className || ""}`}>{p.children}</select>
);
function Field({ label, children, hint }) {
  return (
    <label className="block">
      <div className="text-[11px] font-mono uppercase tracking-widest text-[#6B6558] mb-1">{label}</div>
      {children}
      {hint && <div className="text-[10px] text-[#6B6558] mt-1">{hint}</div>}
    </label>
  );
}

const fmtMoney = (v) => v == null ? "—" : `$${Number(v).toLocaleString()}`;
const fmtPct = (v, suffix = "%") => v == null ? "—" : `${v}${suffix}`;

export default function LenderPortal() {
  const { user, logout } = useAuth();
  const [tab, setTab] = useState("invites");
  const [me, setMe] = useState(null);
  const [invites, setInvites] = useState([]);
  const [termSheets, setTermSheets] = useState([]);

  const loadAll = useCallback(async () => {
    try {
      const [m, i, t] = await Promise.all([
        api.get("/lender/me"),
        api.get("/lender/invites"),
        api.get("/lender/term-sheets"),
      ]);
      setMe(m.data);
      setInvites(i.data || []);
      setTermSheets(t.data || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load portal");
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  return (
    <div className="min-h-screen bg-[#FBF8F1]" data-testid="lender-portal">
      {/* Header */}
      <header className="bg-white border-b border-[#E4DFD1]">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-[#1A1A1A] text-[#C89434] grid place-items-center">
              <Building2 size={16} />
            </div>
            <div>
              <div className="font-serif font-bold text-base">Byrd &amp; CO</div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Lender Portal</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="text-sm font-semibold" data-testid="lender-name">{me?.name || "…"}</div>
              <div className="text-[11px] text-[#6B6558]">{user?.email}</div>
            </div>
            <button onClick={logout} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid="lender-logout">
              <LogOut size={12} /> Log out
            </button>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="max-w-6xl mx-auto px-4 pt-6">
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Your Portal</div>
        <h1 className="font-serif text-3xl font-bold">Welcome back, {me?.name || "Lender"}</h1>
        <div className="mt-6 flex flex-wrap gap-2 border-b border-[#E4DFD1]">
          <TabBtn active={tab === "credit"} onClick={() => setTab("credit")} testId="tab-credit">
            <Sliders size={13} /> My Credit Box
          </TabBtn>
          <TabBtn active={tab === "invites"} onClick={() => setTab("invites")} testId="tab-invites">
            <Inbox size={13} /> Active Invites ({invites.length})
          </TabBtn>
          <TabBtn active={tab === "sheets"} onClick={() => setTab("sheets")} testId="tab-sheets">
            <FileText size={13} /> My Term Sheets ({termSheets.length})
          </TabBtn>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-4 py-6">
        {tab === "invites" && <InvitesTab invites={invites} termSheets={termSheets} onReload={loadAll} />}
        {tab === "sheets" && <TermSheetsTab termSheets={termSheets} onReload={loadAll} />}
        {tab === "credit" && me && <CreditBoxTab me={me} onSaved={loadAll} />}
      </div>
    </div>
  );
}

function TabBtn({ children, active, onClick, testId }) {
  return (
    <button
      onClick={onClick}
      data-testid={testId}
      className={`px-4 py-2 text-sm font-mono uppercase tracking-widest flex items-center gap-2 border-b-2 -mb-[1px] ${active ? "border-[#C89434] text-[#1A1A1A]" : "border-transparent text-[#6B6558] hover:text-[#1A1A1A]"}`}
    >
      {children}
    </button>
  );
}

// ------------- Invites Tab -------------
function InvitesTab({ invites, termSheets, onReload }) {
  const [openId, setOpenId] = useState(null);
  const tsMap = {};
  termSheets.forEach((t) => { tsMap[t.scenario_id] = t; });

  if (!invites.length) {
    return (
      <div className="byrd-card p-8 text-center" data-testid="invites-empty">
        <div className="text-sm text-[#6B6558]">No active invites yet.</div>
        <p className="text-xs text-[#6B6558] mt-2">
          The brokers at Byrd &amp; CO will send you deals that fit your credit box. You'll get an
          email when a new invite arrives.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {invites.map((inv) => {
        const ts = inv.term_sheet || tsMap[inv.scenario.id];
        return (
          <div key={inv.share_id} className="byrd-card p-5" data-testid={`invite-${inv.share_id}`}>
            <div className="flex items-start justify-between flex-wrap gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="font-serif text-lg font-bold">{inv.scenario.name}</div>
                  <span className="byrd-chip byrd-chip-gold">{inv.scenario.loan_type || "Loan"}</span>
                  {ts && <span className="byrd-chip byrd-chip-green" data-testid={`invite-${inv.share_id}-ts-status`}>Term sheet: {ts.status}</span>}
                </div>
                <div className="text-xs text-[#6B6558] mt-1">
                  {inv.scenario.property_type} · {inv.scenario.location} · Loan {fmtMoney(inv.scenario.loan_amount)}
                </div>
                {inv.broker_note && (
                  <div className="mt-2 text-xs bg-[#F3EEE0] border-l-2 border-[#C89434] p-2 italic">
                    "{inv.broker_note}"
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Link to={`/lender/scenario/${inv.token}`}
                  className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`invite-${inv.share_id}-view`}>
                  <ExternalLink size={12} /> View Deal Package
                </Link>
                <button
                  onClick={() => setOpenId(openId === inv.share_id ? null : inv.share_id)}
                  className="byrd-btn byrd-btn-dark h-9 px-3 text-xs"
                  data-testid={`invite-${inv.share_id}-submit`}
                >
                  <Send size={12} /> {ts ? "Update Term Sheet" : "Submit Term Sheet"}
                </button>
              </div>
            </div>
            {openId === inv.share_id && (
              <TermSheetForm
                scenarioId={inv.scenario.id}
                scenarioName={inv.scenario.name}
                existing={ts}
                onClose={() => setOpenId(null)}
                onSaved={() => { setOpenId(null); onReload(); }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ------------- Term Sheet Form -------------
function TermSheetForm({ scenarioId, existing, onClose, onSaved }) {
  const [f, setF] = useState({
    rate_type: existing?.rate_type || "fixed",
    interest_rate_pct: existing?.interest_rate_pct ?? "",
    floating_index: existing?.floating_index || "",
    floating_spread_bps: existing?.floating_spread_bps ?? "",
    loan_amount: existing?.loan_amount ?? "",
    ltv_pct: existing?.ltv_pct ?? "",
    ltc_pct: existing?.ltc_pct ?? "",
    amortization_years: existing?.amortization_years ?? "",
    term_months: existing?.term_months ?? "",
    io_months: existing?.io_months ?? "",
    fixed_period_months: existing?.fixed_period_months ?? "",
    rate_adjustment_notes: existing?.rate_adjustment_notes || "",
    recourse: existing?.recourse || "",
    prepay: existing?.prepay || "",
    origination_fee_pct: existing?.origination_fee_pct ?? "",
    exit_fee_pct: existing?.exit_fee_pct ?? "",
    expiration_date: existing?.expiration_date || "",
    contingencies: existing?.contingencies || "",
    notes: existing?.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const [pdfFileId, setPdfFileId] = useState(existing?.pdf_file_id || null);
  const [pdfFilename, setPdfFilename] = useState(existing?.document?.filename || "");
  const [pdfSize, setPdfSize] = useState(existing?.document?.size || 0);
  const [uploading, setUploading] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const num = (v) => (v === "" || v == null ? null : Number(v));

  const uploadDoc = async (file) => {
    if (!file) return;
    if (file.size > 15 * 1024 * 1024) { toast.error("File exceeds 15 MB limit"); return; }
    setUploading(true);
    try {
      const reader = new FileReader();
      const b64 = await new Promise((resolve, reject) => {
        reader.onload = () => resolve(reader.result.substring(reader.result.indexOf(",") + 1));
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const r = await api.post(`/lender/scenarios/${scenarioId}/term-sheet/upload`, {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        data_b64: b64,
      });
      setPdfFileId(r.data.file_id);
      setPdfFilename(r.data.filename);
      setPdfSize(r.data.size);
      toast.success("Document uploaded — you can submit as-is or fill out any fields below.");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = {
        rate_type: f.rate_type,
        interest_rate_pct: num(f.interest_rate_pct),
        floating_index: f.rate_type === "floating" ? f.floating_index : null,
        floating_spread_bps: f.rate_type === "floating" ? num(f.floating_spread_bps) : null,
        loan_amount: num(f.loan_amount),
        ltv_pct: num(f.ltv_pct),
        ltc_pct: num(f.ltc_pct),
        amortization_years: num(f.amortization_years),
        term_months: num(f.term_months),
        io_months: num(f.io_months),
        fixed_period_months: f.rate_type === "hybrid" ? num(f.fixed_period_months) : null,
        rate_adjustment_notes: (f.rate_type === "hybrid" || f.rate_type === "floating") ? (f.rate_adjustment_notes || null) : null,
        recourse: f.recourse || null,
        prepay: f.prepay || null,
        origination_fee_pct: num(f.origination_fee_pct),
        exit_fee_pct: num(f.exit_fee_pct),
        expiration_date: f.expiration_date || null,
        contingencies: f.contingencies || null,
        notes: f.notes || null,
        pdf_file_id: pdfFileId,
      };
      await api.post(`/lender/scenarios/${scenarioId}/term-sheet`, payload);
      toast.success("Term sheet submitted");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to submit");
    } finally {
      setBusy(false);
    }
  };

  const hasDoc = !!pdfFileId;
  const fmtSize = (b) => !b ? "" : b < 1024 ? `${b} B` : b < 1024 * 1024 ? `${(b / 1024).toFixed(1)} kB` : `${(b / 1024 / 1024).toFixed(2)} MB`;

  return (
    <form onSubmit={submit} className="mt-5 pt-5 border-t border-[#E4DFD1] space-y-4" data-testid="ts-form">
      {/* Upload block — prominent, comes first */}
      <div className={`border-2 ${hasDoc ? "border-[#245C25] bg-[#E5F0E5]/30" : "border-dashed border-[#C89434] bg-[#FBEFD3]/20"} rounded-md p-4`} data-testid="ts-upload-block">
        <div className="flex items-start gap-3">
          <div className={`w-9 h-9 shrink-0 rounded-md grid place-items-center border ${hasDoc ? "border-[#245C25] bg-white text-[#245C25]" : "border-[#C89434] bg-white text-[#C89434]"}`}>
            {hasDoc ? <Check size={16} /> : <Upload size={16} />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-serif text-base font-bold">
              {hasDoc ? "Term sheet document attached" : "Upload your term sheet document (optional)"}
            </div>
            {hasDoc ? (
              <div className="text-xs text-[#2A2A2A] mt-1 flex items-center gap-2 flex-wrap" data-testid="ts-doc-info">
                <Paperclip size={12} />
                <span className="font-semibold truncate max-w-[300px]" title={pdfFilename}>{pdfFilename}</span>
                <span className="text-[#6B6558]">· {fmtSize(pdfSize)}</span>
                <button
                  type="button"
                  onClick={() => { setPdfFileId(null); setPdfFilename(""); setPdfSize(0); }}
                  className="text-[#8A1F1A] hover:text-[#5A0F0A] inline-flex items-center gap-1"
                  data-testid="ts-doc-remove"
                >
                  <XIcon size={12} /> Remove
                </button>
              </div>
            ) : (
              <div className="text-xs text-[#6B6558] mt-1">
                Many lenders send term sheets as a PDF or Word doc. Attach yours here and you can leave the structured fields below blank (or fill in the fields you want to highlight — both work). Max 15&nbsp;MB.
              </div>
            )}
          </div>
          {!hasDoc && (
            <label className="byrd-btn byrd-btn-outline cursor-pointer text-xs h-9 px-3" data-testid="ts-doc-upload-btn">
              <Upload size={12} />
              {uploading ? "Uploading…" : "Choose file"}
              <input
                type="file"
                className="hidden"
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/*"
                onChange={(e) => { const file = e.target.files?.[0]; if (file) uploadDoc(file); e.target.value = ""; }}
                disabled={uploading}
                data-testid="ts-doc-file-input"
              />
            </label>
          )}
        </div>
      </div>

      {hasDoc && (
        <div className="text-xs text-[#6B6558]" data-testid="ts-optional-note">
          Below fields are optional when a document is attached — fill in any that help the broker compare offers at a glance.
        </div>
      )}

      <div className="grid sm:grid-cols-3 gap-3">
        <Field label="Rate Type">
          <Sel value={f.rate_type} onChange={set("rate_type")} data-testid="ts-rate-type">
            <option value="fixed">Fixed</option>
            <option value="floating">Floating</option>
            <option value="hybrid">Hybrid</option>
          </Sel>
        </Field>
        <Field label="Interest Rate (%)">
          <Input type="number" step="0.01" value={f.interest_rate_pct} onChange={set("interest_rate_pct")} data-testid="ts-rate" />
        </Field>
        <Field label="Loan Amount ($)">
          <Input type="number" value={f.loan_amount} onChange={set("loan_amount")} data-testid="ts-loan-amount" />
        </Field>
        {f.rate_type === "floating" && (
          <>
            <Field label="Index"><Input value={f.floating_index} onChange={set("floating_index")} placeholder="e.g. SOFR" /></Field>
            <Field label="Spread (bps)"><Input type="number" value={f.floating_spread_bps} onChange={set("floating_spread_bps")} /></Field>
            <div />
          </>
        )}
        <Field label="LTV (%)"><Input type="number" step="0.1" value={f.ltv_pct} onChange={set("ltv_pct")} data-testid="ts-ltv" /></Field>
        <Field label="LTC (%)"><Input type="number" step="0.1" value={f.ltc_pct} onChange={set("ltc_pct")} /></Field>
        <Field label="Amortization (years)"><Input type="number" value={f.amortization_years} onChange={set("amortization_years")} /></Field>
        <Field label="Term (months)"><Input type="number" value={f.term_months} onChange={set("term_months")} /></Field>
        <Field label="IO Period (months)"><Input type="number" value={f.io_months} onChange={set("io_months")} /></Field>
        {f.rate_type === "hybrid" && (
          <Field label="Fixed Period (months)" testId="ts-fixed-period-field">
            <Input type="number" value={f.fixed_period_months} onChange={set("fixed_period_months")}
              placeholder="e.g. 60 for 5-year fixed" data-testid="ts-fixed-period" />
          </Field>
        )}
        <Field label="Recourse">
          <Sel value={f.recourse} onChange={set("recourse")}>
            <option value="">—</option>
            <option value="full">Full Recourse</option>
            <option value="partial">Partial (Bad-boy carveout)</option>
            <option value="non-recourse">Non-Recourse</option>
          </Sel>
        </Field>
        <Field label="Origination Fee (%)"><Input type="number" step="0.01" value={f.origination_fee_pct} onChange={set("origination_fee_pct")} /></Field>
        <Field label="Exit Fee (%)"><Input type="number" step="0.01" value={f.exit_fee_pct} onChange={set("exit_fee_pct")} /></Field>
        <Field label="Prepay"><Input value={f.prepay} onChange={set("prepay")} placeholder="e.g. 3-2-1 stepdown" /></Field>
        <Field label="Expiration Date"><Input type="date" value={f.expiration_date} onChange={set("expiration_date")} /></Field>
      </div>
      {f.rate_type === "hybrid" && (
        <div className="bg-[#FBEFD3]/40 border border-[#C89434]/40 rounded-md p-3 text-[11px] text-[#7A5410]" data-testid="ts-hybrid-hint">
          <b>Hybrid ARM example:</b> a 5/20 with 20-yr amortization → <i>Fixed Period</i> = 60 months, <i>Term</i> = 240 months, <i>Amortization</i> = 20 years. Put the initial fixed rate in <i>Interest Rate</i> and describe the reset in <i>Rate Adjustment Notes</i> below.
        </div>
      )}
      {(f.rate_type === "hybrid" || f.rate_type === "floating") && (
        <Field label={f.rate_type === "hybrid" ? "Rate Adjustment Notes (after fixed period)" : "Rate Adjustment Notes"}>
          <Textarea
            value={f.rate_adjustment_notes}
            onChange={set("rate_adjustment_notes")}
            placeholder={f.rate_type === "hybrid"
              ? "e.g. Annual reset to SOFR + 250 bps after fixed period. Caps 2/2/5 (initial / annual / lifetime)."
              : "e.g. Monthly reset, no caps, floor at 3.00%"}
            data-testid="ts-adjustment-notes"
          />
        </Field>
      )}
      <Field label="Contingencies">
        <Textarea value={f.contingencies} onChange={set("contingencies")} placeholder="e.g. Third-party appraisal, environmental Phase I, executed leases" />
      </Field>
      <Field label="Notes to Broker">
        <Textarea value={f.notes} onChange={set("notes")} placeholder="Anything you'd like the broker to know…" />
      </Field>
      <div className="flex items-center justify-end gap-2 pt-2">
        <button type="button" onClick={onClose} className="byrd-btn byrd-btn-outline" data-testid="ts-cancel">Cancel</button>
        <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark" data-testid="ts-submit">
          <Send size={14} /> {busy ? "Submitting…" : (existing ? "Update Term Sheet" : "Submit Term Sheet")}
        </button>
      </div>
    </form>
  );
}

// ------------- My Term Sheets Tab -------------
function TermSheetsTab({ termSheets, onReload }) {
  const withdraw = async (id) => {
    if (!window.confirm("Withdraw this term sheet?")) return;
    try {
      await api.delete(`/lender/term-sheets/${id}`);
      toast.success("Withdrawn");
      onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };
  if (!termSheets.length) {
    return (
      <div className="byrd-card p-8 text-center" data-testid="ts-empty">
        <div className="text-sm text-[#6B6558]">You haven't submitted any term sheets yet.</div>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {termSheets.map((t) => (
        <div key={t.id} className="byrd-card p-5" data-testid={`ts-${t.id}`}>
          <div className="flex items-start justify-between flex-wrap gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="font-serif text-lg font-bold">{t.scenario_name}</div>
                <StatusChip status={t.status} />
              </div>
              <div className="text-xs text-[#6B6558] mt-1">Submitted {new Date(t.submitted_at).toLocaleString()}</div>
              <div className="mt-3 grid sm:grid-cols-3 gap-3 text-sm">
                <KV label="Rate">{t.interest_rate_pct != null ? `${t.interest_rate_pct}% ${t.rate_type || ""}` : "—"}</KV>
                <KV label="Loan Amount">{fmtMoney(t.loan_amount)}</KV>
                <KV label="LTV">{fmtPct(t.ltv_pct)}</KV>
                <KV label="Amortization">{t.amortization_years ? `${t.amortization_years} yr` : "—"}</KV>
                <KV label="Term">{t.term_months ? `${t.term_months} mo` : "—"}</KV>
                <KV label="Recourse">{t.recourse || "—"}</KV>
              </div>
              {t.document && (
                <div className="mt-3 text-xs">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const r = await api.get(`/term-sheets/${t.id}/document`, { responseType: "blob" });
                        const url = URL.createObjectURL(r.data);
                        window.open(url, "_blank");
                      } catch (e) { toast.error(e?.response?.data?.detail || "Download failed"); }
                    }}
                    className="inline-flex items-center gap-1.5 text-[#23446E] hover:text-[#1A2E4E] underline"
                    data-testid={`ts-${t.id}-doc-download`}
                  >
                    <Download size={12} /> {t.document.filename}
                  </button>
                </div>
              )}
              {t.broker_note && (
                <div className="mt-3 text-xs bg-[#F3EEE0] border-l-2 border-[#C89434] p-2">
                  <b className="font-mono uppercase tracking-widest text-[10px] text-[#6B6558] block mb-1">// Broker Note</b>
                  {t.broker_note}
                </div>
              )}
            </div>
            {t.status !== "accepted" && t.status !== "withdrawn" && (
              <button onClick={() => withdraw(t.id)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs text-[#8A1F1A] border-[#E38380]" data-testid={`ts-${t.id}-withdraw`}>
                <XIcon size={12} /> Withdraw
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function StatusChip({ status }) {
  const map = {
    submitted: "byrd-chip byrd-chip-gold",
    accepted: "byrd-chip byrd-chip-green",
    countered: "byrd-chip byrd-chip-gold",
    passed: "byrd-chip byrd-chip-red",
    withdrawn: "byrd-chip byrd-chip-red",
  };
  return <span className={map[status] || "byrd-chip"}>{status}</span>;
}

function KV({ label, children }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</div>
      <div className="text-sm font-semibold">{children}</div>
    </div>
  );
}

// ------------- Credit Box Tab -------------
function CreditBoxTab({ me, onSaved }) {
  const [f, setF] = useState({
    lender_name: me.name || "",
    institution_type: me.institution_type || "bank",
    property_types: me.property_types || [],
    geography: (me.geography || []).join(", "),
    min_loan: me.min_loan ?? "",
    max_loan: me.max_loan ?? "",
    max_ltv: me.max_ltv ?? "",
    max_ltc: me.max_ltc ?? "",
    min_dscr: me.min_dscr ?? "",
    min_debt_yield: me.min_debt_yield ?? "",
    rate_min: me.rate_min ?? "",
    rate_max: me.rate_max ?? "",
    typical_term_months: me.typical_term_months ?? "",
    recourse_preference: me.recourse_preference || "",
    decision_speed_days: me.decision_speed_days ?? "",
    typical_fees: me.typical_fees || "",
    notes: me.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggle = (arr, val) => (arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);
  const num = (v) => (v === "" || v == null ? null : Number(v));

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const geo = f.geography.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
      const payload = {
        lender_name: f.lender_name,
        institution_type: f.institution_type,
        property_types: f.property_types,
        geography: geo,
        min_loan: num(f.min_loan), max_loan: num(f.max_loan),
        max_ltv: num(f.max_ltv), max_ltc: num(f.max_ltc),
        min_dscr: num(f.min_dscr), min_debt_yield: num(f.min_debt_yield),
        rate_min: num(f.rate_min), rate_max: num(f.rate_max),
        typical_term_months: num(f.typical_term_months),
        recourse_preference: f.recourse_preference,
        decision_speed_days: num(f.decision_speed_days),
        typical_fees: f.typical_fees, notes: f.notes,
      };
      await api.patch("/lender/me/credit-box", payload);
      toast.success("Credit box saved");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="byrd-card p-6 space-y-6" data-testid="credit-box-form">
      <div>
        <Field label="Lender Name"><Input value={f.lender_name} onChange={set("lender_name")} data-testid="cb-name" /></Field>
      </div>
      <Field label="Property Types">
        <div className="flex flex-wrap gap-2 mt-1">
          {PROPERTY_TYPES.map((p) => {
            const active = f.property_types.includes(p);
            return (
              <button type="button" key={p}
                onClick={() => setF({ ...f, property_types: toggle(f.property_types, p) })}
                className={`px-3 py-1.5 rounded-full text-xs border ${active ? "bg-[#1A1A1A] text-white border-[#1A1A1A]" : "border-[#E4DFD1] text-[#2A2A2A] hover:bg-[#F3EEE0]"}`}
              >{p}</button>
            );
          })}
        </div>
      </Field>
      <Field label="Geography (comma-separated states, or NATIONWIDE)">
        <Input value={f.geography} onChange={set("geography")} data-testid="cb-geo" />
      </Field>
      <div className="grid sm:grid-cols-3 gap-3">
        <Field label="Min Loan ($)"><Input type="number" value={f.min_loan} onChange={set("min_loan")} data-testid="cb-min-loan" /></Field>
        <Field label="Max Loan ($)"><Input type="number" value={f.max_loan} onChange={set("max_loan")} data-testid="cb-max-loan" /></Field>
        <Field label="Max LTV (%)"><Input type="number" step="0.1" value={f.max_ltv} onChange={set("max_ltv")} data-testid="cb-max-ltv" /></Field>
        <Field label="Max LTC (%)"><Input type="number" step="0.1" value={f.max_ltc} onChange={set("max_ltc")} /></Field>
        <Field label="Min DSCR"><Input type="number" step="0.01" value={f.min_dscr} onChange={set("min_dscr")} data-testid="cb-min-dscr" /></Field>
        <Field label="Min Debt Yield (%)"><Input type="number" step="0.1" value={f.min_debt_yield} onChange={set("min_debt_yield")} /></Field>
        <Field label="Rate Min (%)"><Input type="number" step="0.01" value={f.rate_min} onChange={set("rate_min")} /></Field>
        <Field label="Rate Max (%)"><Input type="number" step="0.01" value={f.rate_max} onChange={set("rate_max")} /></Field>
        <Field label="Typical Term (months)"><Input type="number" value={f.typical_term_months} onChange={set("typical_term_months")} /></Field>
        <Field label="Decision Speed (days)"><Input type="number" value={f.decision_speed_days} onChange={set("decision_speed_days")} /></Field>
        <Field label="Recourse Preference">
          <Sel value={f.recourse_preference} onChange={set("recourse_preference")}>
            <option value="">—</option>
            <option value="recourse">Recourse</option>
            <option value="non-recourse">Non-Recourse</option>
            <option value="either">Either</option>
          </Sel>
        </Field>
        <Field label="Typical Fees"><Input value={f.typical_fees} onChange={set("typical_fees")} /></Field>
      </div>
      <Field label="Notes"><Textarea value={f.notes} onChange={set("notes")} /></Field>
      <div className="flex justify-end">
        <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark" data-testid="cb-save">
          <Edit3 size={14} /> {busy ? "Saving…" : "Save Credit Box"}
        </button>
      </div>
    </form>
  );
}
