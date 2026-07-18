import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api, API_BASE } from "@/lib/api";
import { toast } from "sonner";
import {
  LOAN_TYPES, PROPERTY_TYPES, RECOURSE_OPTIONS, SCENARIO_STATUSES,
  fmtMoney, fmtPct, fmtNum, scenarioStatusChip,
} from "@/byrd/dealData";
import {
  ArrowLeft, Save, FileText, Trash2, Plus, Users, Share2, Copy,
  Download, Eye, EyeOff, Check, X, ExternalLink, Building2, RefreshCw,
} from "lucide-react";

const useDebouncedSave = (fn, delay = 800) => {
  const [timer, setTimer] = useState(null);
  return useCallback((val) => {
    if (timer) clearTimeout(timer);
    const t = setTimeout(() => fn(val), delay);
    setTimer(t);
  }, [fn, delay, timer]);
};

const Field = ({ label, children, hint, className = "" }) => (
  <div className={className}>
    <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</label>
    <div className="mt-1">{children}</div>
    {hint && <div className="text-[10px] text-[#6B6558] mt-1">{hint}</div>}
  </div>
);

const Inp = React.forwardRef(function Inp(props, ref) {
  return (
    <input
      ref={ref}
      {...props}
      className={`w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] ${props.className || ""}`}
    />
  );
});

const Sel = ({ children, ...props }) => (
  <select
    {...props}
    className={`w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] ${props.className || ""}`}
  >
    {children}
  </select>
);

const TA = (props) => (
  <textarea
    {...props}
    className={`w-full px-3 py-2 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] ${props.className || ""}`}
  />
);

const MetricCard = ({ label, value, tone = "default" }) => {
  const toneMap = {
    default: "bg-white border-[#E4DFD1]",
    good: "bg-[#E4F4E4] border-[#8DBE8F]",
    warn: "bg-[#FBEFD3] border-[#E5B968]",
    bad: "bg-[#FADCDA] border-[#E38380]",
  };
  return (
    <div className={`border rounded-md p-3 ${toneMap[tone]}`}>
      <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</div>
      <div className="font-serif text-xl font-bold mt-1">{value}</div>
    </div>
  );
};

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "package", label: "Package" },
  { key: "docs", label: "Documents" },
  { key: "lenders", label: "Lenders" },
];

export default function AdminScenarioDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [scen, setScen] = useState(null);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState("overview");
  const [clients, setClients] = useState([]);
  const [lenders, setLenders] = useState([]);
  const [matches, setMatches] = useState([]);
  const [shareLenderId, setShareLenderId] = useState("");

  const load = () => api.get(`/admin/scenarios/${id}`).then((r) => setScen(r.data));

  useEffect(() => { load(); }, [id]);
  useEffect(() => {
    api.get("/admin/clients").then((r) => setClients(r.data));
    api.get("/admin/lenders").then((r) => setLenders(r.data));
  }, []);

  const patch = async (fields) => {
    setSaving(true);
    try {
      const res = await api.patch(`/admin/scenarios/${id}`, fields);
      setScen((s) => ({ ...s, ...res.data, metrics: res.data.metrics }));
    } finally {
      setSaving(false);
    }
  };

  const patchSection = (section) => (partial) =>
    patch({ [section]: { ...(scen[section] || {}), ...partial } });

  const runMatch = async () => {
    const r = await api.get(`/admin/scenarios/${id}/match`);
    setMatches(r.data);
    toast.success(`${r.data.length} lenders scored`);
  };

  const createShare = async (lenderId) => {
    try {
      const res = await api.post(`/admin/scenarios/${id}/shares`, { lender_id: lenderId || null });
      toast.success("Share created — copy the link");
      const url = `${window.location.origin}/lender/scenario/${res.data.token}`;
      navigator.clipboard.writeText(url).catch(() => {});
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const revokeShare = async (shareId) => {
    if (!window.confirm("Revoke this lender's access?")) return;
    await api.delete(`/admin/scenarios/${id}/shares/${shareId}`);
    toast.success("Revoked");
    load();
  };

  const toggleAttachDoc = async (docId, currentAttached, newVisibility) => {
    const list = [...(scen.attached_docs || [])];
    const idx = list.findIndex((x) => x.doc_id === docId);
    if (currentAttached && newVisibility === "remove") {
      if (idx >= 0) list.splice(idx, 1);
    } else {
      const entry = { doc_id: docId, visibility: newVisibility };
      if (idx >= 0) list[idx] = entry; else list.push(entry);
    }
    await patch({ attached_docs: list });
  };

  const grantDoc = async (shareId, docId, on) => {
    if (on) await api.post(`/admin/scenarios/${id}/shares/${shareId}/grant/${docId}`);
    else await api.delete(`/admin/scenarios/${id}/shares/${shareId}/grant/${docId}`);
    load();
  };

  const del = async () => {
    if (!window.confirm("Delete this scenario? This cannot be undone.")) return;
    await api.delete(`/admin/scenarios/${id}`);
    toast.success("Deleted");
    nav("/admin/scenarios");
  };

  const downloadPdf = () => {
    // We use axios so we send Authorization header, then open blob
    api.get(`/admin/scenarios/${id}/pdf`, { responseType: "blob" }).then((res) => {
      const url = URL.createObjectURL(res.data);
      window.open(url, "_blank");
    });
  };

  if (!scen) return <div className="text-sm text-[#6B6558]">Loading…</div>;

  const m = scen.metrics || {};
  const stat = scenarioStatusChip(scen.status);

  return (
    <div className="space-y-6" data-testid="scenario-detail">
      <button onClick={() => nav("/admin/scenarios")} className="text-sm text-[#6B6558] hover:text-[#1A1A1A] inline-flex items-center gap-2">
        <ArrowLeft size={14} /> All scenarios
      </button>

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="flex-1 min-w-0">
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Loan Scenario</div>
          <input
            value={scen.name}
            onChange={(e) => setScen({ ...scen, name: e.target.value })}
            onBlur={() => patch({ name: scen.name })}
            data-testid="scen-name"
            className="w-full font-serif text-3xl md:text-4xl font-bold mt-1 leading-tight bg-transparent focus:outline-none focus:bg-[#F3EEE0] rounded-md px-1 -mx-1"
          />
          <div className="mt-3 flex items-center gap-3 flex-wrap">
            <span className={stat.chip} data-testid="scen-status-chip">{stat.label}</span>
            <Sel value={scen.status || "draft"} onChange={(e) => patch({ status: e.target.value })}
              className="h-8 w-auto text-xs" data-testid="scen-status-select">
              {SCENARIO_STATUSES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
            </Sel>
            {saving && <span className="text-xs text-[#6B6558]">Saving…</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={downloadPdf} className="byrd-btn byrd-btn-outline" data-testid="scen-pdf-btn">
            <Download size={14} /> PDF
          </button>
          <button onClick={del} className="byrd-btn byrd-btn-outline text-[#8A1F1A] border-[#E38380] hover:bg-[#FADCDA]" data-testid="scen-delete-btn">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Metrics strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3" data-testid="scen-metrics">
        <MetricCard label="LTV" value={fmtPct(m.ltv_pct, 1)} />
        <MetricCard label="LTC" value={fmtPct(m.ltc_pct, 1)} />
        <MetricCard label="DSCR" value={m.dscr ?? "—"} tone={m.dscr && m.dscr >= 1.25 ? "good" : m.dscr && m.dscr < 1 ? "bad" : "default"} />
        <MetricCard label="Debt Yield" value={fmtPct(m.debt_yield_pct, 2)} />
        <MetricCard label="NOI" value={fmtMoney(m.noi)} />
        <MetricCard label="Monthly P&I" value={fmtMoney(m.monthly_payment)} />
      </div>

      {/* Tabs */}
      <div className="border-b border-[#E4DFD1] flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            data-testid={`scen-tab-${t.key}`}
            className={`px-4 py-2 text-sm border-b-2 -mb-px ${
              tab === t.key
                ? "border-[#C89434] text-[#1A1A1A] font-semibold"
                : "border-transparent text-[#6B6558] hover:text-[#1A1A1A]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <OverviewTab scen={scen} m={m} />
      )}

      {tab === "package" && (
        <PackageTab scen={scen} clients={clients} patch={patch} patchSection={patchSection} setScen={setScen} />
      )}

      {tab === "docs" && (
        <DocsTab scen={scen} onToggle={toggleAttachDoc} />
      )}

      {tab === "lenders" && (
        <LendersTab
          scen={scen}
          lenders={lenders}
          matches={matches}
          runMatch={runMatch}
          onCreateShare={createShare}
          onRevoke={revokeShare}
          onGrantDoc={grantDoc}
          shareLenderId={shareLenderId}
          setShareLenderId={setShareLenderId}
        />
      )}
    </div>
  );
}

// --------------- OVERVIEW TAB ---------------
function OverviewTab({ scen, m }) {
  const prop = scen.property_info || {};
  const loan = scen.loan_request || {};
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-6">
        <div className="byrd-card p-6">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Property</div>
          <h3 className="font-serif text-xl font-bold mt-1">
            {prop.address ? `${prop.address}, ` : ""}{[prop.city, prop.state, prop.zip].filter(Boolean).join(", ") || "Address TBD"}
          </h3>
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div><span className="text-[#6B6558]">Type</span><br/><b>{prop.property_type || "—"}</b></div>
            <div><span className="text-[#6B6558]">Units</span><br/><b>{fmtNum(prop.units)}</b></div>
            <div><span className="text-[#6B6558]">Purchase Price</span><br/><b>{fmtMoney(prop.purchase_price)}</b></div>
            <div><span className="text-[#6B6558]">Value</span><br/><b>{fmtMoney(m.property_value)}</b></div>
          </div>
        </div>
        <div className="byrd-card p-6">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Loan Request</div>
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div><span className="text-[#6B6558]">Type</span><br/><b>{loan.loan_type || "—"}</b></div>
            <div><span className="text-[#6B6558]">Amount</span><br/><b>{fmtMoney(loan.loan_amount)}</b></div>
            <div><span className="text-[#6B6558]">Rate</span><br/><b>{fmtPct(loan.requested_rate_pct, 3)}</b></div>
            <div><span className="text-[#6B6558]">Amort / Term</span><br/><b>{fmtNum(loan.amort_months)}/{fmtNum(loan.term_months)}<span className="text-[#6B6558] text-xs"> mo</span></b></div>
            <div><span className="text-[#6B6558]">Annual DS</span><br/><b>{fmtMoney(m.annual_debt_service)}</b></div>
            <div><span className="text-[#6B6558]">Recourse</span><br/><b>{loan.recourse || "—"}</b></div>
          </div>
        </div>
        {scen.business_plan && (
          <div className="byrd-card p-6">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Business Plan</div>
            <p className="mt-2 text-sm whitespace-pre-wrap leading-relaxed">{scen.business_plan}</p>
          </div>
        )}
      </div>
      <div className="space-y-4">
        <div className="byrd-card p-6 bg-[#1A1A1A] text-[#FBF8F1]">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#E5B968]">// Snapshot</div>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between border-b border-[#3A3A3A] py-1"><span className="text-[#C9C1AF]">LTV</span><b>{fmtPct(m.ltv_pct, 1)}</b></div>
            <div className="flex justify-between border-b border-[#3A3A3A] py-1"><span className="text-[#C9C1AF]">LTC</span><b>{fmtPct(m.ltc_pct, 1)}</b></div>
            <div className="flex justify-between border-b border-[#3A3A3A] py-1"><span className="text-[#C9C1AF]">DSCR</span><b>{m.dscr ?? "—"}</b></div>
            <div className="flex justify-between border-b border-[#3A3A3A] py-1"><span className="text-[#C9C1AF]">Debt Yield</span><b>{fmtPct(m.debt_yield_pct, 2)}</b></div>
            <div className="flex justify-between border-b border-[#3A3A3A] py-1"><span className="text-[#C9C1AF]">NOI</span><b>{fmtMoney(m.noi)}</b></div>
            <div className="flex justify-between border-b border-[#3A3A3A] py-1"><span className="text-[#C9C1AF]">Cash-on-Cash</span><b>{fmtPct(m.cash_on_cash_pct, 2)}</b></div>
            <div className="flex justify-between py-1"><span className="text-[#C9C1AF]">Sources = Uses</span><b>{m.sources_uses_balanced ? "✓" : "✗"}</b></div>
          </div>
        </div>
      </div>
    </div>
  );
}

// --------------- PACKAGE TAB (edit) ---------------
function PackageTab({ scen, clients, patch, patchSection, setScen }) {
  const sponsor = scen.sponsor || {};
  const prop = scen.property_info || {};
  const loan = scen.loan_request || {};
  const fin = scen.financials || {};
  const con = scen.construction || {};
  const su = scen.sources_uses || [];
  const set = (section, patchFn) => (k, cast = (v) => v) => (e) => {
    const raw = e.target.value;
    const v = raw === "" ? null : cast(raw);
    patchFn({ [k]: v });
  };
  const spSet = set("sponsor", patchSection("sponsor"));
  const prSet = set("property_info", patchSection("property_info"));
  const lnSet = set("loan_request", patchSection("loan_request"));
  const fnSet = set("financials", patchSection("financials"));
  const cnSet = (k, cast = (v) => v) => (e) => {
    const raw = e.target.value; const v = raw === "" ? null : cast(raw);
    patch({ construction: { ...(scen.construction || {}), [k]: v } });
  };

  const num = (v) => (Number.isNaN(Number(v)) ? null : Number(v));
  const int = (v) => (Number.isNaN(parseInt(v)) ? null : parseInt(v));

  const suUpdate = (i, patch2) => {
    const list = [...su];
    list[i] = { ...list[i], ...patch2 };
    patch({ sources_uses: list });
  };
  const suAdd = (category) => patch({ sources_uses: [...su, { label: "", amount: 0, category }] });
  const suRemove = (i) => {
    const list = [...su]; list.splice(i, 1); patch({ sources_uses: list });
  };

  return (
    <div className="space-y-6">
      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Client Link</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Link this scenario to a client (optional)">
            <Sel value={scen.client_id || ""} onChange={(e) => patch({ client_id: e.target.value || null })} data-testid="scen-client-select">
              <option value="">Standalone (no client)</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name} — {c.email}</option>)}
            </Sel>
          </Field>
          {scen.client && (
            <Field label="Client">
              <Link to={`/admin/clients/${scen.client.id}`} className="text-sm hover:text-[#C89434] inline-flex items-center gap-1">
                <Users size={12} /> {scen.client.name} <ExternalLink size={12} />
              </Link>
            </Field>
          )}
        </div>
      </section>

      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Sponsor</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Sponsor Name"><Inp defaultValue={sponsor.name || ""} onBlur={spSet("name")} data-testid="sp-name" /></Field>
          <Field label="Entity / Borrower"><Inp defaultValue={sponsor.entity || ""} onBlur={spSet("entity")} /></Field>
          <Field label="FICO"><Inp type="number" defaultValue={sponsor.credit_score ?? ""} onBlur={spSet("credit_score", int)} /></Field>
          <Field label="Liquidity ($)"><Inp type="number" defaultValue={sponsor.liquidity ?? ""} onBlur={spSet("liquidity", num)} /></Field>
          <Field label="Net Worth ($)"><Inp type="number" defaultValue={sponsor.net_worth ?? ""} onBlur={spSet("net_worth", num)} /></Field>
        </div>
      </section>

      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Property</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Address" className="md:col-span-2"><Inp defaultValue={prop.address || ""} onBlur={prSet("address")} data-testid="pr-address" /></Field>
          <Field label="Property Type">
            <Sel value={prop.property_type || ""} onChange={(e) => patchSection("property_info")({ property_type: e.target.value })} data-testid="pr-type">
              <option value="">Select…</option>
              {PROPERTY_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
            </Sel>
          </Field>
          <Field label="City"><Inp defaultValue={prop.city || ""} onBlur={prSet("city")} /></Field>
          <Field label="State"><Inp defaultValue={prop.state || ""} onBlur={prSet("state")} placeholder="TX" /></Field>
          <Field label="ZIP"><Inp defaultValue={prop.zip || ""} onBlur={prSet("zip")} /></Field>
          <Field label="Year Built"><Inp type="number" defaultValue={prop.year_built ?? ""} onBlur={prSet("year_built", int)} /></Field>
          <Field label="Units"><Inp type="number" defaultValue={prop.units ?? ""} onBlur={prSet("units", int)} /></Field>
          <Field label="Sq Ft"><Inp type="number" defaultValue={prop.sqft ?? ""} onBlur={prSet("sqft", num)} /></Field>
          <Field label="Purchase Price ($)"><Inp type="number" defaultValue={prop.purchase_price ?? ""} onBlur={prSet("purchase_price", num)} data-testid="pr-price" /></Field>
          <Field label="Current Value ($)"><Inp type="number" defaultValue={prop.current_value ?? ""} onBlur={prSet("current_value", num)} /></Field>
          <Field label="Occupancy (%)"><Inp type="number" step="0.1" defaultValue={prop.occupancy_pct ?? ""} onBlur={prSet("occupancy_pct", num)} /></Field>
        </div>
      </section>

      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Loan Request</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Loan Type">
            <Sel value={loan.loan_type || ""} onChange={(e) => patchSection("loan_request")({ loan_type: e.target.value })} data-testid="ln-type">
              <option value="">Select…</option>
              {LOAN_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
            </Sel>
          </Field>
          <Field label="Loan Amount ($)"><Inp type="number" defaultValue={loan.loan_amount ?? ""} onBlur={lnSet("loan_amount", num)} data-testid="ln-amount" /></Field>
          <Field label="Requested Rate (%)"><Inp type="number" step="0.001" defaultValue={loan.requested_rate_pct ?? ""} onBlur={lnSet("requested_rate_pct", num)} data-testid="ln-rate" /></Field>
          <Field label="Amortization (months)"><Inp type="number" defaultValue={loan.amort_months ?? ""} onBlur={lnSet("amort_months", int)} data-testid="ln-amort" /></Field>
          <Field label="Term (months)"><Inp type="number" defaultValue={loan.term_months ?? ""} onBlur={lnSet("term_months", int)} /></Field>
          <Field label="Recourse">
            <Sel value={loan.recourse || ""} onChange={(e) => patchSection("loan_request")({ recourse: e.target.value })}>
              <option value="">Select…</option>
              {RECOURSE_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
            </Sel>
          </Field>
        </div>
      </section>

      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Financials (annual)</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Gross Income ($)"><Inp type="number" defaultValue={fin.gross_income ?? ""} onBlur={fnSet("gross_income", num)} data-testid="fn-gross" /></Field>
          <Field label="Vacancy (%)"><Inp type="number" step="0.1" defaultValue={fin.vacancy_pct ?? ""} onBlur={fnSet("vacancy_pct", num)} /></Field>
          <Field label="Operating Expenses ($)"><Inp type="number" defaultValue={fin.operating_expenses ?? ""} onBlur={fnSet("operating_expenses", num)} data-testid="fn-opex" /></Field>
          <Field label="CapEx Reserves ($)"><Inp type="number" defaultValue={fin.capex_reserves ?? ""} onBlur={fnSet("capex_reserves", num)} /></Field>
          <Field label="Override NOI ($) — optional" hint="Set to bypass the computed NOI"><Inp type="number" defaultValue={fin.override_noi ?? ""} onBlur={fnSet("override_noi", num)} /></Field>
        </div>
      </section>

      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Construction Budget (optional)</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Total Project Cost ($)"><Inp type="number" defaultValue={con.total_project_cost ?? ""} onBlur={cnSet("total_project_cost", num)} /></Field>
          <Field label="Land ($)"><Inp type="number" defaultValue={con.land_cost ?? ""} onBlur={cnSet("land_cost", num)} /></Field>
          <Field label="Hard Costs ($)"><Inp type="number" defaultValue={con.hard_costs ?? ""} onBlur={cnSet("hard_costs", num)} /></Field>
          <Field label="Soft Costs ($)"><Inp type="number" defaultValue={con.soft_costs ?? ""} onBlur={cnSet("soft_costs", num)} /></Field>
          <Field label="Contingency ($)"><Inp type="number" defaultValue={con.contingency ?? ""} onBlur={cnSet("contingency", num)} /></Field>
        </div>
      </section>

      <section className="byrd-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-serif text-xl font-bold">Sources &amp; Uses</h3>
          <div className="flex gap-2">
            <button onClick={() => suAdd("source")} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid="su-add-source"><Plus size={12} /> Source</button>
            <button onClick={() => suAdd("use")} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid="su-add-use"><Plus size={12} /> Use</button>
          </div>
        </div>
        {su.length === 0 ? (
          <div className="text-sm text-[#6B6558]">Add sources (loan, sponsor equity, existing debt) and uses (purchase, closing costs, reserves).</div>
        ) : (
          <div className="space-y-2">
            {su.map((row, i) => (
              <div key={i} className="grid grid-cols-[1fr_.8fr_.6fr_auto] gap-2 items-center" data-testid={`su-row-${i}`}>
                <Inp defaultValue={row.label} onBlur={(e) => suUpdate(i, { label: e.target.value })} placeholder="Label (e.g. Sponsor Equity)" />
                <Inp type="number" defaultValue={row.amount} onBlur={(e) => suUpdate(i, { amount: parseFloat(e.target.value) || 0 })} placeholder="Amount" />
                <Sel value={row.category} onChange={(e) => suUpdate(i, { category: e.target.value })}>
                  <option value="source">Source</option>
                  <option value="use">Use</option>
                </Sel>
                <button onClick={() => suRemove(i)} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1] hover:bg-[#FADCDA] hover:border-[#E38380] hover:text-[#8A1F1A]">
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Notes &amp; Business Plan</h3>
        <div className="space-y-4">
          <Field label="Business Plan (visible on package)">
            <TA rows={4} defaultValue={scen.business_plan || ""} onBlur={(e) => patch({ business_plan: e.target.value })} />
          </Field>
          <Field label="Notes (visible on package)">
            <TA rows={3} defaultValue={scen.notes || ""} onBlur={(e) => patch({ notes: e.target.value })} />
          </Field>
        </div>
      </section>
    </div>
  );
}

// --------------- DOCS TAB ---------------
function DocsTab({ scen, onToggle }) {
  const attached = scen.attached_docs || [];
  const attachedMap = {};
  attached.forEach((a) => { attachedMap[a.doc_id] = a.visibility; });
  const clientDocs = scen.client_docs || [];

  if (!scen.client_id) {
    return (
      <div className="byrd-card p-8 text-center">
        <div className="text-sm text-[#6B6558]">Link a client to this scenario in the Package tab to attach their documents.</div>
      </div>
    );
  }
  if (clientDocs.length === 0) {
    return (
      <div className="byrd-card p-8 text-center">
        <div className="text-sm text-[#6B6558]">This client has no documents yet. Ask them to upload via their portal.</div>
      </div>
    );
  }

  const uploaded = clientDocs.filter((d) => d.file_id);

  return (
    <div className="space-y-4">
      <div className="byrd-card p-6">
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// How this works</div>
        <p className="text-sm mt-1">
          Attach the client&apos;s uploaded docs to this scenario. Tag each as
          <b> Included</b> (rides with the lender link) or <b>On Request</b> (lender must ask; you approve per lender).
          Personal / financial docs should stay On Request. Property docs are safe to Include.
        </p>
      </div>

      <div className="byrd-card overflow-hidden">
        <div className="hidden md:grid grid-cols-[2fr_1fr_1fr_1.5fr] border-b border-[#E4DFD1] bg-[#FBF8F1]">
          {["Document", "Category", "Uploaded", "Include in Package"].map((h) => (
            <div key={h} className="px-4 py-3 text-[11px] uppercase font-mono tracking-widest text-[#6B6558]">{h}</div>
          ))}
        </div>
        {uploaded.map((d) => {
          const current = attachedMap[d.id];
          return (
            <div key={d.id} className="grid grid-cols-1 md:grid-cols-[2fr_1fr_1fr_1.5fr] border-b border-[#E4DFD1] last:border-b-0 items-center" data-testid={`attach-row-${d.id}`}>
              <div className="px-4 py-3">
                <div className="font-semibold text-sm">{d.label}</div>
                {d.file && <div className="text-xs text-[#6B6558]">{d.file.filename}</div>}
              </div>
              <div className="px-4 py-3 text-xs text-[#6B6558]">{d.category}</div>
              <div className="px-4 py-3">
                {d.status === "reviewed" ? <span className="byrd-chip byrd-chip-green">Reviewed</span> :
                 d.status === "uploaded" ? <span className="byrd-chip byrd-chip-blue">Uploaded</span> :
                 <span className="byrd-chip">{d.status}</span>}
              </div>
              <div className="px-4 py-3">
                <div className="inline-flex rounded-md border border-[#E4DFD1] overflow-hidden text-xs">
                  {[
                    { v: "remove", label: "Off", icon: EyeOff },
                    { v: "on_request", label: "On Request", icon: Eye },
                    { v: "included", label: "Included", icon: Check },
                  ].map((opt) => {
                    const active = current === opt.v || (opt.v === "remove" && !current);
                    return (
                      <button
                        key={opt.v}
                        onClick={() => onToggle(d.id, !!current, opt.v)}
                        data-testid={`attach-${d.id}-${opt.v}`}
                        className={`px-3 h-9 flex items-center gap-1 ${
                          active ? "bg-[#1A1A1A] text-white" : "bg-white text-[#2A2A2A] hover:bg-[#F3EEE0]"
                        }`}
                      >
                        <opt.icon size={12} /> {opt.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --------------- LENDERS TAB ---------------
function LendersTab({ scen, lenders, matches, runMatch, onCreateShare, onRevoke, onGrantDoc, shareLenderId, setShareLenderId }) {
  const attached = scen.attached_docs || [];
  const clientDocMap = {};
  (scen.client_docs || []).forEach((d) => { clientDocMap[d.id] = d; });
  const onRequestDocs = attached.filter((a) => a.visibility === "on_request").map((a) => clientDocMap[a.doc_id]).filter(Boolean);

  const copyLink = (token) => {
    const url = `${window.location.origin}/lender/scenario/${token}`;
    navigator.clipboard.writeText(url);
    toast.success("Link copied to clipboard");
  };

  return (
    <div className="space-y-6">
      {/* Matching */}
      <div className="byrd-card p-6">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Match Engine</div>
            <h3 className="font-serif text-xl font-bold">Lenders that fit this deal</h3>
          </div>
          <button onClick={runMatch} className="byrd-btn byrd-btn-outline" data-testid="run-match-btn">
            <RefreshCw size={14} /> Run Match
          </button>
        </div>
        {matches.length === 0 ? (
          <div className="text-sm text-[#6B6558] mt-4">Click &quot;Run Match&quot; to score your lender directory against this scenario.</div>
        ) : (
          <div className="mt-4 space-y-3">
            {matches.slice(0, 10).map((m) => (
              <div key={m.lender.id} className="border border-[#E4DFD1] rounded-md p-4 flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="font-semibold">{m.lender.name}</div>
                    <span className={m.verdict === "fit" ? "byrd-chip byrd-chip-green" : m.verdict === "partial" ? "byrd-chip byrd-chip-gold" : "byrd-chip byrd-chip-red"}>
                      {m.verdict}
                    </span>
                  </div>
                  <div className="text-xs text-[#6B6558] mt-1">
                    {m.fits.length > 0 && <div>✓ {m.fits.join(" · ")}</div>}
                    {m.misses.length > 0 && <div className="text-[#8A1F1A]">✗ {m.misses.join(" · ")}</div>}
                  </div>
                </div>
                <button onClick={() => onCreateShare(m.lender.id)} className="byrd-btn byrd-btn-dark h-9 px-3 text-xs shrink-0" data-testid={`match-share-${m.lender.id}`}>
                  <Share2 size={12} /> Share
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Direct share */}
      <div className="byrd-card p-6">
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Share Manually</div>
        <div className="mt-3 flex flex-col sm:flex-row gap-3">
          <Sel value={shareLenderId} onChange={(e) => setShareLenderId(e.target.value)} data-testid="pick-lender">
            <option value="">Pick a lender from directory…</option>
            {lenders.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </Sel>
          <button onClick={() => shareLenderId && onCreateShare(shareLenderId)} disabled={!shareLenderId} className="byrd-btn byrd-btn-dark" data-testid="create-share-btn">
            <Share2 size={14} /> Create Share Link
          </button>
        </div>
      </div>

      {/* Existing shares */}
      <div className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Active Shares</h3>
        {(scen.shares || []).length === 0 ? (
          <div className="text-sm text-[#6B6558]">No lenders have this scenario yet.</div>
        ) : (
          <div className="space-y-4">
            {scen.shares.map((sh) => {
              const grantSet = new Set(sh.doc_grants || []);
              return (
                <div key={sh.id} className="border border-[#E4DFD1] rounded-md p-4" data-testid={`share-${sh.id}`}>
                  <div className="flex items-start justify-between flex-wrap gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold flex items-center gap-2">
                        <Building2 size={14} /> {sh.lender_name || sh.recipient_institution || "Lender"}
                      </div>
                      <div className="text-xs text-[#6B6558]">
                        {sh.recipient_email || "—"} · shared {new Date(sh.created_at).toLocaleDateString()}
                        {sh.requested_at && <> · <span className="text-[#7A5410]">Requested docs {new Date(sh.requested_at).toLocaleDateString()}</span></>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button onClick={() => copyLink(sh.token)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`copy-share-${sh.id}`}>
                        <Copy size={12} /> Copy Link
                      </button>
                      <button onClick={() => onRevoke(sh.id)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs text-[#8A1F1A] border-[#E38380]" data-testid={`revoke-share-${sh.id}`}>
                        <X size={12} />
                      </button>
                    </div>
                  </div>

                  {onRequestDocs.length > 0 && (
                    <div className="mt-4 pt-4 border-t border-[#E4DFD1]">
                      <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] mb-2">
                        // On-Request Documents · grant per lender
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {onRequestDocs.map((d) => {
                          const granted = grantSet.has(d.id);
                          return (
                            <button
                              key={d.id}
                              onClick={() => onGrantDoc(sh.id, d.id, !granted)}
                              data-testid={`grant-${sh.id}-${d.id}`}
                              className={`text-left px-3 py-2 rounded-md border text-sm flex items-center gap-2 ${
                                granted
                                  ? "bg-[#E4F4E4] border-[#8DBE8F] text-[#245C25]"
                                  : "bg-white border-[#E4DFD1] hover:bg-[#F3EEE0]"
                              }`}
                            >
                              {granted ? <Check size={14} /> : <Eye size={14} />}
                              <span className="truncate">{d.label}</span>
                              <span className="ml-auto text-[10px] font-mono">{granted ? "GRANTED" : "GRANT"}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
