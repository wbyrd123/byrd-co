import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api, API_BASE } from "@/lib/api";
import { toast } from "sonner";
import {
  LOAN_TYPES, PROPERTY_TYPES, PROPERTY_SUBTYPES, RECOURSE_OPTIONS, SCENARIO_STATUSES,
  fmtMoney, fmtPct, fmtNum, scenarioStatusChip,
} from "@/byrd/dealData";
import {
  ArrowLeft, Save, FileText, Trash2, Plus, Users, Share2, Copy,
  Download, Eye, EyeOff, Check, X, ExternalLink, Building2, RefreshCw,
  Archive, Sliders, Sparkles, PenLine, Send, ShieldCheck, Clock, AlertCircle,
} from "lucide-react";
import ScenarioAIChat from "@/byrd/ScenarioAIChat";
import ScenarioAIFab from "@/byrd/ScenarioAIFab";
import BulkUploadZone from "@/byrd/BulkUploadZone";
import AdminFinancialsTab from "@/byrd/AdminFinancialsTab";
import DealContactsPanel from "@/byrd/DealContactsPanel";
import NotesPanel, { DocNoteButton } from "@/byrd/NotesPanel";

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
  { key: "contacts", label: "Contacts" },
  { key: "financials", label: "Financials" },
  { key: "lenders", label: "Lenders" },
  { key: "termsheets", label: "Term Sheets" },
  { key: "ai", label: "AI Assist" },
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
  const [shareDialog, setShareDialog] = useState(null);
  const [termSheets, setTermSheets] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [shareActivity, setShareActivity] = useState({});
  // shareDialog shape: { mode: "create"|"edit", lenderId?, lenderName?, share?, overrides }

  const load = () => api.get(`/admin/scenarios/${id}`).then((r) => setScen(r.data));
  const loadTermSheets = () => api.get(`/admin/scenarios/${id}/term-sheets`).then((r) => setTermSheets(r.data)).catch(() => {});
  const loadSuggestions = () => api.get(`/admin/scenarios/${id}/match-suggestions`).then((r) => setSuggestions(r.data)).catch(() => setSuggestions([]));
  const loadActivity = () => api.get(`/admin/scenarios/${id}/shares/activity-summary`).then((r) => setShareActivity(r.data)).catch(() => setShareActivity({}));

  useEffect(() => { load(); loadTermSheets(); loadSuggestions(); loadActivity(); }, [id]);
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

  const runMatch = async ({ silent } = {}) => {
    const r = await api.get(`/admin/scenarios/${id}/match`);
    setMatches(r.data);
    if (!silent) toast.success(`${r.data.length} lenders scored`);
  };

  // Auto-run match the first time the user lands on the Lenders tab so the reasons
  // are visible without a manual click. Silent (no toast) since it's implicit.
  useEffect(() => {
    if (tab === "lenders" && matches.length === 0) {
      runMatch({ silent: true }).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const createShare = async (lenderId, docOverrides) => {
    try {
      const body = { lender_id: lenderId || null };
      if (docOverrides) body.doc_overrides = docOverrides;
      const res = await api.post(`/admin/scenarios/${id}/shares`, body);
      toast.success("Share created — link copied to clipboard");
      const url = `${window.location.origin}/lender/scenario/${res.data.token}`;
      navigator.clipboard.writeText(url).catch(() => {});
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const updateShareOverrides = async (shareId, docOverrides) => {
    try {
      await api.patch(`/admin/scenarios/${id}/shares/${shareId}/overrides`, { doc_overrides: docOverrides });
      toast.success("Visibility updated");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const openSendDialog = (lenderId) => {
    const lender = lenders.find((l) => l.id === lenderId);
    setShareDialog({
      mode: "create",
      lenderId,
      lenderName: lender?.name || "Lender",
      overrides: {},
    });
  };

  const openEditVisibilityDialog = (share) => {
    setShareDialog({
      mode: "edit",
      share,
      lenderName: share.lender_name || share.recipient_institution || "Lender",
      overrides: { ...(share.doc_overrides || {}) },
    });
  };

  const submitShareDialog = async (overrides) => {
    if (!shareDialog) return;
    if (shareDialog.mode === "create") {
      await createShare(shareDialog.lenderId, overrides);
    } else {
      await updateShareOverrides(shareDialog.share.id, overrides);
    }
    setShareDialog(null);
  };

  const revokeShare = async (shareId) => {
    if (!window.confirm("Revoke this lender's access?")) return;
    await api.delete(`/admin/scenarios/${id}/shares/${shareId}`);
    toast.success("Revoked");
    load();
  };

  const toggleDocVisibility = async (docId, newVis) => {
    // newVis: "included" | "on_request" | "hidden"
    await api.patch(`/admin/scenarios/${id}/docs/${docId}`, { lender_visibility: newVis });
    load();
  };

  const addDocLine = async (item) => {
    await api.post(`/admin/scenarios/${id}/docs`, item);
    load();
  };

  const updateDocLine = async (docId, patch) => {
    await api.patch(`/admin/scenarios/${id}/docs/${docId}`, patch);
    load();
  };

  const removeDocLine = async (docId, label) => {
    if (!window.confirm(`Remove "${label}"? Any uploaded file will be deleted.`)) return;
    await api.delete(`/admin/scenarios/${id}/docs/${docId}`);
    toast.success("Removed");
    load();
  };

  const copyDocs = async (sourceScenarioId, docIds) => {
    const res = await api.post(`/admin/scenarios/${id}/docs/copy`, {
      source_scenario_id: sourceScenarioId,
      doc_ids: docIds,
    });
    toast.success(`Copied ${res.data.count} document${res.data.count === 1 ? "" : "s"}`);
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

  const downloadZip = async () => {
    try {
      const res = await api.get(`/admin/scenarios/${id}/docs.zip`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `byrd-scenario-${id.slice(0, 8)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "No documents attached");
    }
  };

  // Deep-merge patch so nested field updates from AI don't wipe sibling fields
  const applyAIUpdates = async (updates) => {
    const merge = (base, next) => {
      const out = { ...(base || {}) };
      for (const [k, v] of Object.entries(next || {})) {
        if (v && typeof v === "object" && !Array.isArray(v) && base && typeof base[k] === "object" && !Array.isArray(base[k])) {
          out[k] = merge(base[k], v);
        } else if (v !== null && v !== "") {
          out[k] = v;
        }
      }
      return out;
    };
    // Build the merged payload from current scenario state
    const merged = {};
    for (const [k, v] of Object.entries(updates)) {
      if (v && typeof v === "object" && !Array.isArray(v)) {
        merged[k] = merge(scen[k], v);
      } else if (v !== null && v !== "") {
        merged[k] = v;
      }
    }
    await patch(merged);
  };

  const sendToLenderByName = (lenderName) => {
    const lender = lenders.find((l) => (l.name || "").toLowerCase() === lenderName.toLowerCase());
    if (!lender) {
      toast.error(`"${lenderName}" isn't in your directory yet`);
      return;
    }
    setTab("lenders");
    openSendDialog(lender.id);
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
          <button onClick={downloadZip} className="byrd-btn byrd-btn-outline" data-testid="scen-zip-btn">
            <Archive size={14} /> All Docs (ZIP)
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
        <div className="space-y-6">
          <NotesPanel scenarioId={id} title="Deal Notes" />
          <DocsTab
            scen={scen}
            onAddDoc={addDocLine}
            onUpdateDoc={updateDocLine}
            onRemoveDoc={removeDocLine}
            onToggleVisibility={toggleDocVisibility}
            onCopyDocs={copyDocs}
            onReload={load}
          />
        </div>
      )}

      {tab === "contacts" && (
        <div className="max-w-3xl">
          <p className="text-sm text-[#6B6558] mb-4 max-w-2xl">
            Title company, real estate broker, mortgage company, insurance, and any other outside contacts.
            The borrower can also add these from their portal. Invited lenders see this list read-only.
          </p>
          <DealContactsPanel scenarioId={id} />
        </div>
      )}

      {tab === "financials" && (
        <AdminFinancialsTab scenarioId={id} scen={scen} onScenReload={load} />
      )}

      {tab === "lenders" && (
        <LendersTab
          scen={scen}
          lenders={lenders}
          matches={matches}
          suggestions={suggestions}
          shareActivity={shareActivity}
          onReloadActivity={loadActivity}
          onInviteSelfReg={async (lender_ids) => {
            try {
              await api.post(`/admin/scenarios/${id}/invite-lenders`, { lender_ids, note: "" });
              toast.success(`Invited ${lender_ids.length} lender(s)`);
              loadSuggestions();
              load();
            } catch (e) { toast.error(e?.response?.data?.detail || "Invite failed"); }
          }}
          runMatch={runMatch}
          onOpenSendDialog={openSendDialog}
          onRevoke={revokeShare}
          onOpenEditVisibility={openEditVisibilityDialog}
          shareLenderId={shareLenderId}
          setShareLenderId={setShareLenderId}
        />
      )}

      {tab === "termsheets" && (
        <TermSheetsTab
          scenarioId={id}
          termSheets={termSheets}
          onReload={loadTermSheets}
        />
      )}

      {tab === "ai" && (
        <div className="byrd-card overflow-hidden" data-testid="scen-tab-ai-panel">
          <ScenarioAIChat
            scenarioId={id}
            onApplyUpdates={applyAIUpdates}
            onSendToLender={sendToLenderByName}
          />
        </div>
      )}

      {shareDialog && (
        <ShareVisibilityDialog
          scen={scen}
          dialog={shareDialog}
          onClose={() => setShareDialog(null)}
          onSubmit={submitShareDialog}
        />
      )}

      {tab !== "ai" && (
        <ScenarioAIFab
          scenarioId={id}
          onApplyUpdates={applyAIUpdates}
          onSendToLender={sendToLenderByName}
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
            <div><span className="text-[#6B6558]">Type</span><br/><b>{prop.property_type || "—"}{prop.property_subtype ? <span className="block text-xs text-[#6B6558] font-normal mt-0.5">{prop.property_subtype}</span> : null}</b></div>
            <div><span className="text-[#6B6558]">Units</span><br/><b>{fmtNum(prop.units)}</b></div>
            <div><span className="text-[#6B6558]">Purchase Price</span><br/><b>{fmtMoney(prop.purchase_price)}</b></div>
            <div><span className="text-[#6B6558]">Value</span><br/><b>{fmtMoney(m.property_value)}</b></div>
            {prop.leasehold != null && (
              <div><span className="text-[#6B6558]">Leasehold</span><br/><b>{prop.leasehold ? "Yes" : "No"}</b></div>
            )}
            {prop.short_term_rental != null && (
              <div><span className="text-[#6B6558]">Short-Term Rental</span><br/><b>{prop.short_term_rental ? "Yes" : "No"}</b></div>
            )}
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
  const sponsors = scen.sponsors || [];
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
        <div className="flex items-baseline justify-between mb-4">
          <div>
            <h3 className="font-serif text-xl font-bold">Sponsors ({sponsors.length})</h3>
            <p className="text-[11px] text-[#6B6558] mt-1">Anyone with ≥20% ownership typically needs to be on the loan. Link each sponsor to a client account so they get their own document portal + can sign their own fee agreement.</p>
          </div>
          <button
            type="button"
            onClick={() => {
              const next = [...sponsors, {
                id: (crypto?.randomUUID?.() || Math.random().toString(36).slice(2)),
                name: "", entity: "", state: "", credit_score: null, liquidity: null, net_worth: null,
                ownership_pct: null,
                role: sponsors.length === 0 ? "managing" : "guarantor",
                is_guarantor: true,
                client_user_id: null,
              }];
              patch({ sponsors: next });
            }}
            className="byrd-btn byrd-btn-dark h-9 px-3 text-xs"
            data-testid="add-sponsor-btn"
          >
            + Add Sponsor
          </button>
        </div>
        {sponsors.length === 0 && (
          <div className="text-sm text-[#6B6558] italic border border-dashed border-[#E4DFD1] rounded-md p-4 text-center">
            No sponsors yet. Click <b>Add Sponsor</b> to add the first one.
          </div>
        )}
        <div className="space-y-4">
          {sponsors.map((sp, idx) => {
            const updateSp = (patchObj) => {
              const next = [...sponsors];
              next[idx] = { ...next[idx], ...patchObj };
              // If role changes to managing, demote any other managing to guarantor
              if (patchObj.role === "managing") {
                next.forEach((s, i) => { if (i !== idx && s.role === "managing") next[i] = { ...s, role: "guarantor" }; });
              }
              // Auto-flag guarantor if ownership_pct changes
              if ("ownership_pct" in patchObj) {
                const op = patchObj.ownership_pct;
                if (op != null && op >= 20) next[idx].is_guarantor = true;
              }
              patch({ sponsors: next });
            };
            const removeSp = () => {
              if (!window.confirm(`Remove ${sp.name || "this sponsor"}?`)) return;
              const next = sponsors.filter((_, i) => i !== idx);
              patch({ sponsors: next });
            };
            return (
              <div key={sp.id || idx} className="border border-[#E4DFD1] rounded-md p-4 bg-white" data-testid={`sponsor-card-${idx}`}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Sponsor #{idx + 1}</span>
                    {sp.role === "managing" && <span className="byrd-chip byrd-chip-gold">Managing</span>}
                    {sp.is_guarantor && sp.role !== "managing" && <span className="byrd-chip">Guarantor</span>}
                    {sp.role === "passive" && <span className="byrd-chip">Passive</span>}
                  </div>
                  <button type="button" onClick={removeSp} className="text-[11px] text-[#8A1F1A] hover:underline" data-testid={`sponsor-remove-${idx}`}>Remove</button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <Field label="Sponsor Name">
                    <Inp defaultValue={sp.name || ""} onBlur={(e) => updateSp({ name: e.target.value })} data-testid={`sp-name-${idx}`} />
                  </Field>
                  <Field label="Entity / Borrower">
                    <Inp defaultValue={sp.entity || ""} onBlur={(e) => updateSp({ entity: e.target.value })} />
                  </Field>
                  <Field label="State (residence)">
                    <Inp
                      defaultValue={sp.state || ""}
                      placeholder="TX"
                      maxLength={2}
                      onBlur={(e) => updateSp({ state: e.target.value.toUpperCase() })}
                      data-testid={`sp-state-${idx}`}
                    />
                  </Field>
                  <Field label="Ownership %">
                    <Inp
                      type="number"
                      step="0.1"
                      defaultValue={sp.ownership_pct ?? ""}
                      onBlur={(e) => {
                        const v = e.target.value === "" ? null : Number(e.target.value);
                        updateSp({ ownership_pct: v });
                      }}
                      data-testid={`sp-ownership-${idx}`}
                    />
                  </Field>
                  <Field label="FICO">
                    <Inp type="number" defaultValue={sp.credit_score ?? ""} onBlur={(e) => updateSp({ credit_score: e.target.value === "" ? null : parseInt(e.target.value) })} />
                  </Field>
                  <Field label="Liquidity ($)">
                    <Inp type="number" defaultValue={sp.liquidity ?? ""} onBlur={(e) => updateSp({ liquidity: e.target.value === "" ? null : Number(e.target.value) })} />
                  </Field>
                  <Field label="Net Worth ($)">
                    <Inp type="number" defaultValue={sp.net_worth ?? ""} onBlur={(e) => updateSp({ net_worth: e.target.value === "" ? null : Number(e.target.value) })} />
                  </Field>
                  <Field label="Role">
                    <Sel value={sp.role || "guarantor"} onChange={(e) => updateSp({ role: e.target.value })} data-testid={`sp-role-${idx}`}>
                      <option value="managing">Managing Sponsor</option>
                      <option value="guarantor">Guarantor</option>
                      <option value="passive">Passive</option>
                    </Sel>
                  </Field>
                  <Field label="Guarantor?">
                    <label className="inline-flex items-center gap-2 h-10 text-sm">
                      <input
                        type="checkbox"
                        checked={!!sp.is_guarantor}
                        onChange={(e) => updateSp({ is_guarantor: e.target.checked })}
                        data-testid={`sp-guarantor-${idx}`}
                      />
                      <span className="text-[#2A2A2A]">{sp.is_guarantor ? "Signs the note" : "Not on the loan"}</span>
                    </label>
                  </Field>
                  <Field label="Link to Client Account">
                    <Sel
                      value={sp.client_user_id || ""}
                      onChange={(e) => updateSp({ client_user_id: e.target.value || null })}
                      data-testid={`sp-client-link-${idx}`}
                    >
                      <option value="">— No portal access (you upload for them)</option>
                      {clients.map((c) => <option key={c.id} value={c.id}>{c.name} — {c.email}</option>)}
                    </Sel>
                  </Field>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="byrd-card p-6">
        <h3 className="font-serif text-xl font-bold mb-4">Property</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Field label="Address" className="md:col-span-2"><Inp defaultValue={prop.address || ""} onBlur={prSet("address")} data-testid="pr-address" /></Field>
          <Field label="Property Type">
            <Sel value={prop.property_type || ""} onChange={(e) => patchSection("property_info")({ property_type: e.target.value, property_subtype: "" })} data-testid="pr-type">
              <option value="">Select…</option>
              {PROPERTY_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
            </Sel>
          </Field>
          {PROPERTY_SUBTYPES[prop.property_type]?.length > 0 && (
            <Field label="Property Sub-Type">
              <Sel value={prop.property_subtype || ""} onChange={(e) => patchSection("property_info")({ property_subtype: e.target.value })} data-testid="pr-subtype">
                <option value="">Select…</option>
                {PROPERTY_SUBTYPES[prop.property_type].map((s) => <option key={s} value={s}>{s}</option>)}
              </Sel>
            </Field>
          )}
          <Field label="City"><Inp defaultValue={prop.city || ""} onBlur={prSet("city")} /></Field>
          <Field label="State"><Inp defaultValue={prop.state || ""} onBlur={prSet("state")} placeholder="TX" /></Field>
          <Field label="ZIP"><Inp defaultValue={prop.zip || ""} onBlur={prSet("zip")} /></Field>
          <Field label="Year Built"><Inp type="number" defaultValue={prop.year_built ?? ""} onBlur={prSet("year_built", int)} /></Field>
          <Field label="Units"><Inp type="number" defaultValue={prop.units ?? ""} onBlur={prSet("units", int)} /></Field>
          <Field label="Sq Ft"><Inp type="number" defaultValue={prop.sqft ?? ""} onBlur={prSet("sqft", num)} /></Field>
          <Field label="Purchase Price ($)"><Inp type="number" defaultValue={prop.purchase_price ?? ""} onBlur={prSet("purchase_price", num)} data-testid="pr-price" /></Field>
          <Field label="Current Value ($)"><Inp type="number" defaultValue={prop.current_value ?? ""} onBlur={prSet("current_value", num)} /></Field>
          <Field label="Occupancy (%)"><Inp type="number" step="0.1" defaultValue={prop.occupancy_pct ?? ""} onBlur={prSet("occupancy_pct", num)} /></Field>
          <Field label="Occupancy Type">
            <Sel value={prop.occupancy_type || ""} onChange={(e) => patchSection("property_info")({ occupancy_type: e.target.value || null })} data-testid="pr-occupancy-type">
              <option value="">Select…</option>
              <option value="owner_occupied">Owner-Occupied</option>
              <option value="non_owner_occupied">Non-Owner-Occupied</option>
            </Sel>
          </Field>
          <Field label="Leasehold?">
            <Sel value={prop.leasehold == null ? "" : (prop.leasehold ? "yes" : "no")}
                 onChange={(e) => patchSection("property_info")({ leasehold: e.target.value === "" ? null : e.target.value === "yes" })}
                 data-testid="pr-leasehold">
              <option value="">Select…</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </Sel>
          </Field>
          <Field label="Short-Term Rental?">
            <Sel value={prop.short_term_rental == null ? "" : (prop.short_term_rental ? "yes" : "no")}
                 onChange={(e) => patchSection("property_info")({ short_term_rental: e.target.value === "" ? null : e.target.value === "yes" })}
                 data-testid="pr-str">
              <option value="">Select…</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </Sel>
          </Field>
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
          <Field label="Estimated Closing Date">
            <Inp type="date" defaultValue={loan.estimated_closing_date || ""} onBlur={(e) => patchSection("loan_request")({ estimated_closing_date: e.target.value || null })} data-testid="ln-closing-date" />
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
        <h3 className="font-serif text-xl font-bold mb-4">Business Plan &amp; Internal Notes</h3>
        <div className="space-y-4">
          <Field label="Business Plan (shown on Loan Package + Executive Summary)">
            <TA rows={4} defaultValue={scen.business_plan || ""} onBlur={(e) => patch({ business_plan: e.target.value })} />
          </Field>
          <Field label="Internal Notes (not shared with lenders)">
            <TA rows={3} defaultValue={scen.notes || ""} onBlur={(e) => patch({ notes: e.target.value })} />
          </Field>
        </div>
      </section>
    </div>
  );
}

// --------------- FEE AGREEMENT CARD ---------------
function FeeAgreementCard({ scen, feeDoc, onReload }) {
  const [fee, setFee] = useState(scen.broker_fee_pct != null ? String(scen.broker_fee_pct) : "");
  const [feeStatus, setFeeStatus] = useState(null); // {status, signed_at, ...} — from /fee-agreement endpoint
  const [busy, setBusy] = useState(false);
  // Sponsor selection for multi-sponsor scenarios
  const sponsors = scen.sponsors || [];
  const signableSponsors = sponsors.filter((s) => s.is_guarantor && s.client_user_id);
  const managingSponsor = sponsors.find((s) => s.role === "managing");
  const defaultSponsorId = managingSponsor?.id || (signableSponsors[0]?.id) || "";
  const [selectedSponsorId, setSelectedSponsorId] = useState(defaultSponsorId);
  useEffect(() => { setSelectedSponsorId(defaultSponsorId); }, [defaultSponsorId]);

  const loadStatus = () => {
    api.get(`/admin/scenarios/${scen.id}/fee-agreement`)
      .then((r) => setFeeStatus(r.data.fee_agreement))
      .catch(() => setFeeStatus(null));
  };
  useEffect(() => {
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scen.id, feeDoc?.status, feeDoc?.file_id]);

  useEffect(() => {
    setFee(scen.broker_fee_pct != null ? String(scen.broker_fee_pct) : "");
  }, [scen.broker_fee_pct]);

  const canSend = !!scen.client_id && !!fee && parseFloat(fee) > 0 && parseFloat(fee) <= 10;

  const previewUrl = `${API_BASE}/admin/scenarios/${scen.id}/fee-agreement/preview.pdf`;
  const preview = async () => {
    if (!scen.client_id) { toast.error("Link a client first"); return; }
    // Save fee value first if it's changed, so the preview reflects it
    if (fee && parseFloat(fee) !== scen.broker_fee_pct) {
      try { await api.patch(`/admin/scenarios/${scen.id}`, { broker_fee_pct: parseFloat(fee) }); } catch { /* ignore */ }
    }
    const res = await api.get(`/admin/scenarios/${scen.id}/fee-agreement/preview.pdf`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    window.open(url, "_blank");
  };

  const send = async () => {
    if (!canSend) return;
    if (feeStatus && feeStatus.status === "sent") {
      if (!window.confirm("A signature request is already pending. Send a new one? The old link will stop working.")) return;
    }
    setBusy(true);
    try {
      await api.post(`/admin/scenarios/${scen.id}/fee-agreement/send`, {
        broker_fee_pct: parseFloat(fee),
        sponsor_id: selectedSponsorId || null,
      });
      toast.success(`Sent for signature${selectedSponsorId ? " to selected sponsor" : ""}`);
      loadStatus();
      onReload && onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Send failed");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!window.confirm("Cancel the pending signature request? The client's link will stop working.")) return;
    try {
      await api.post(`/admin/scenarios/${scen.id}/fee-agreement/cancel`);
      toast.success("Canceled");
      loadStatus();
      onReload && onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Cancel failed");
    }
  };

  const isSigned = feeDoc?.status === "reviewed" && !!feeDoc?.file_id;
  const isSent = !isSigned && feeStatus?.status === "sent";

  const downloadSigned = async () => {
    if (!feeDoc?.file?.id) return;
    const res = await api.get(`/files/${feeDoc.file.id}`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    window.open(url, "_blank");
  };

  return (
    <div className="byrd-card p-5 border-l-4 border-l-[#C89434]" data-testid="fee-agreement-card">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-md bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1]">
              <PenLine size={14} />
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Fee Agreement</div>
              <div className="font-serif text-xl font-bold leading-tight">Broker fee &amp; e-signature</div>
            </div>
          </div>
          <p className="text-sm text-[#6B6558] mt-2 max-w-xl">
            Signed fee agreement must be in place before we shop this deal. Enter the fee, preview the draft,
            then send to the borrower — Byrd &amp; CO countersigns automatically once they sign.
          </p>
        </div>
        <FeeStatusBadge signed={isSigned} sent={isSent} feeStatus={feeStatus} feeDoc={feeDoc} />
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-[180px_1fr] gap-4">
        <div>
          <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Broker Fee %</label>
          <div className="mt-1 relative">
            <input
              type="number"
              min="0.01"
              max="10"
              step="0.05"
              value={fee}
              onChange={(e) => setFee(e.target.value)}
              placeholder="e.g. 1.25"
              disabled={isSigned}
              data-testid="fee-pct-input"
              className="w-full h-11 pl-3 pr-8 rounded-md border border-[#E4DFD1] bg-white text-sm disabled:bg-[#F3EEE0] disabled:cursor-not-allowed"
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-[#6B6558]">%</div>
          </div>
          <div className="text-[11px] text-[#6B6558] mt-1">Of total loan amount, paid at closing.</div>
        </div>
        <div className="flex items-end gap-2 flex-wrap">
          {signableSponsors.length > 0 && !isSigned && (
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Send to Sponsor</label>
              <select
                value={selectedSponsorId}
                onChange={(e) => setSelectedSponsorId(e.target.value)}
                data-testid="fee-sponsor-select"
                className="mt-1 h-11 min-w-[220px] px-3 rounded-md border border-[#E4DFD1] bg-white text-sm"
              >
                {signableSponsors.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name || "Sponsor"}{s.ownership_pct != null ? ` (${s.ownership_pct}%)` : ""}{s.role === "managing" ? " · Managing" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          {!isSigned && (
            <>
              <button
                onClick={preview}
                disabled={!scen.client_id}
                className="byrd-btn byrd-btn-outline"
                data-testid="fee-preview-btn"
                title={scen.client_id ? "" : "Link a client to this scenario first"}
              >
                <FileText size={14} /> View Draft
              </button>
              {isSent ? (
                <>
                  <button
                    onClick={send}
                    disabled={busy || !canSend}
                    className="byrd-btn byrd-btn-dark"
                    data-testid="fee-resend-btn"
                  >
                    <RefreshCw size={14} /> {busy ? "Sending…" : "Resend"}
                  </button>
                  <button
                    onClick={cancel}
                    className="byrd-btn byrd-btn-outline text-[#8A1F1A] border-[#E38380] hover:bg-[#FADCDA]"
                    data-testid="fee-cancel-btn"
                  >
                    <X size={14} /> Cancel Request
                  </button>
                </>
              ) : (
                <button
                  onClick={send}
                  disabled={busy || !canSend}
                  className="byrd-btn byrd-btn-dark"
                  data-testid="fee-send-btn"
                >
                  <Send size={14} /> {busy ? "Sending…" : "Send for Signature"}
                </button>
              )}
            </>
          )}
          {isSigned && (
            <>
              <button
                onClick={downloadSigned}
                className="byrd-btn byrd-btn-dark"
                data-testid="fee-download-signed-btn"
              >
                <Download size={14} /> Download Signed
              </button>
            </>
          )}
        </div>
      </div>

      {!scen.client_id && (scen.sponsors || []).length === 0 && (
        <div className="mt-3 text-[12px] text-[#8A1F1A] inline-flex items-center gap-1">
          <AlertCircle size={12} /> Link a client to this scenario before sending the fee agreement.
        </div>
      )}
      {(scen.sponsors || []).length > 0 && signableSponsors.length === 0 && (
        <div className="mt-3 text-[12px] text-[#8A1F1A] inline-flex items-center gap-1">
          <AlertCircle size={12} /> No sponsor has a linked client account yet. Add a client link on the Overview tab so they can sign.
        </div>
      )}
      {(scen.fee_agreements || []).length > 0 && (
        <div className="mt-4 border-t border-[#E4DFD1] pt-3">
          <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-2">// Fee Agreements ({scen.fee_agreements.length})</div>
          <div className="space-y-1">
            {scen.fee_agreements.map((fa) => {
              const sp = (scen.sponsors || []).find((s) => s.id === fa.sponsor_id);
              return (
                <div key={fa.id} className="text-xs flex items-center justify-between border border-[#E4DFD1] rounded-md px-3 py-2 bg-white">
                  <div>
                    <b>{sp?.name || fa.borrower_name_at_send || "Signer"}</b>
                    <span className="text-[#6B6558] ml-2">{fa.broker_fee_pct}%</span>
                    <span className={`ml-2 byrd-chip text-[10px] ${fa.status === "signed" ? "byrd-chip-green" : fa.status === "sent" ? "byrd-chip-gold" : ""}`}>{fa.status}</span>
                  </div>
                  <div className="text-[10px] text-[#6B6558]">{fa.signed_at ? new Date(fa.signed_at).toLocaleDateString() : new Date(fa.created_at).toLocaleDateString()}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function FeeStatusBadge({ signed, sent, feeStatus, feeDoc }) {
  if (signed) {
    const when = feeDoc?.updated_at ? feeDoc.updated_at.slice(0, 10) : "";
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full border border-[#245C25] bg-[#E5F0E5] text-[#245C25] px-3 py-1 text-[11px] font-semibold" data-testid="fee-status-signed">
        <ShieldCheck size={12} /> Signed{when && ` · ${when}`}
      </div>
    );
  }
  if (sent) {
    const when = feeStatus?.created_at ? feeStatus.created_at.slice(0, 10) : "";
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full border border-[#C89434] bg-[#FBEFD3] text-[#7A5410] px-3 py-1 text-[11px] font-semibold" data-testid="fee-status-sent">
        <Clock size={12} /> Awaiting borrower{when && ` · sent ${when}`}
      </div>
    );
  }
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-[#E4DFD1] bg-white text-[#6B6558] px-3 py-1 text-[11px]" data-testid="fee-status-not-sent">
      Not sent
    </div>
  );
}


function DocsTab({ scen, onAddDoc, onUpdateDoc, onRemoveDoc, onToggleVisibility, onCopyDocs, onReload }) {
  const allDocs = scen.docs || scen.client_docs || [];
  const sponsors = scen.sponsors || [];
  // Split the pinned fee-agreement line out — it renders in its own card at the top
  const feeAgreementDoc = allDocs.find((d) => d.label === "Signed Fee Agreement");
  const nonFeeDocs = allDocs.filter((d) => d.label !== "Signed Fee Agreement");
  const [copyOpen, setCopyOpen] = useState(false);
  const [sponsorFilter, setSponsorFilter] = useState("all");
  // Per-doc notes: badge counts + inline expanded panels
  const [docNoteCounts, setDocNoteCounts] = useState({});
  const [openDocNotes, setOpenDocNotes] = useState({});
  const toggleDocNotes = (did) => setOpenDocNotes((m) => ({ ...m, [did]: !m[did] }));
  const refreshNoteCounts = React.useCallback(async () => {
    try {
      const r = await api.get(`/scenarios/${scen.id}/notes/doc-counts`);
      setDocNoteCounts(r.data?.counts || {});
    } catch { /* silent — badges just won't update */ }
  }, [scen.id]);
  useEffect(() => { refreshNoteCounts(); }, [refreshNoteCounts]);
  // Apply sponsor filter
  const docs = nonFeeDocs.filter((d) => {
    if (sponsorFilter === "all") return true;
    if (sponsorFilter === "shared") return !d.sponsor_id;
    return d.sponsor_id === sponsorFilter;
  });
  const uploaded = docs.filter((d) => (d.files && d.files.length) || d.file_id).length;
  const reviewed = docs.filter((d) => d.status === "reviewed").length;
  const pct = docs.length ? Math.round((reviewed / docs.length) * 100) : 0;

  const sponsorLookup = {};
  sponsors.forEach((s) => { sponsorLookup[s.id] = s; });

  return (
    <div className="space-y-4">
      <FeeAgreementCard scen={scen} feeDoc={feeAgreementDoc} onReload={onReload} />

      <div className="byrd-card p-5 flex items-center justify-between flex-wrap gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Documents for this scenario</div>
          <div className="font-serif text-lg font-bold mt-0.5">
            {docs.length} lines · {uploaded} uploaded · {reviewed} reviewed
          </div>
          <div className="mt-2 h-1.5 bg-[#F3EEE0] rounded-full overflow-hidden max-w-md">
            <div className="h-full bg-[#C89434] transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {sponsors.length > 0 && (
            <div className="flex items-center gap-2">
              <label className="text-[11px] font-mono uppercase tracking-widest text-[#6B6558]">Viewing docs for</label>
              <Sel value={sponsorFilter} onChange={(e) => setSponsorFilter(e.target.value)} data-testid="docs-sponsor-filter" className="h-9 w-[240px]">
                <option value="all">All sponsors + shared</option>
                <option value="shared">Property &amp; business only</option>
                {sponsors.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name || "Sponsor"} ({s.ownership_pct != null ? `${s.ownership_pct}%` : "—"})
                  </option>
                ))}
              </Sel>
            </div>
          )}
          {scen.client_id && (
            <button
              onClick={() => setCopyOpen(true)}
              className="byrd-btn byrd-btn-outline"
              data-testid="copy-from-scenario-btn"
            >
              <Copy size={14} /> Copy from Another Scenario
            </button>
          )}
        </div>
      </div>

      <AddDocForm onAdd={onAddDoc} sponsors={sponsors} defaultSponsorId={sponsorFilter !== "all" && sponsorFilter !== "shared" ? sponsorFilter : ""} />

      <BulkUploadZone
        scenarioId={scen.id}
        docs={allDocs}
        sponsors={sponsors}
        sponsorFilter={sponsorFilter}
        onReload={onReload}
      />

      <div className="byrd-card overflow-hidden">
        <div className="hidden md:grid grid-cols-[2fr_.9fr_1fr_1.4fr_1.2fr] border-b border-[#E4DFD1] bg-[#FBF8F1]">
          {[
            { label: "Document" },
            { label: "Category" },
            { label: "Status" },
            { label: "File / Notes" },
            { label: "Lender Visibility", tip: "Default for lenders: Hidden / On Request / Included. You can also override per-lender when you Share." },
          ].map((h) => (
            <div
              key={h.label}
              className="px-4 py-3 text-[11px] uppercase font-mono tracking-widest text-[#6B6558]"
              title={h.tip || ""}
            >
              {h.label}
            </div>
          ))}
        </div>
        {docs.length === 0 && (
          <div className="p-8 text-center text-sm text-[#6B6558]">
            No document lines yet. Add one above, or copy from another scenario.
          </div>
        )}
        {docs.map((d) => (
          <ScenarioDocRow
            key={d.id}
            doc={d}
            scenarioId={scen.id}
            sponsors={sponsors}
            sponsorLookup={sponsorLookup}
            onUpdate={onUpdateDoc}
            onRemove={() => onRemoveDoc(d.id, d.label)}
            onToggleVisibility={onToggleVisibility}
            onReload={onReload}
            noteCount={docNoteCounts[d.id] || 0}
            notesOpen={!!openDocNotes[d.id]}
            onToggleNotes={() => toggleDocNotes(d.id)}
            onNotesChanged={refreshNoteCounts}
          />
        ))}
      </div>

      {copyOpen && (
        <CopyDocsDialog
          scenarioId={scen.id}
          onClose={() => setCopyOpen(false)}
          onCopy={async (sid, ids) => { await onCopyDocs(sid, ids); setCopyOpen(false); }}
        />
      )}
    </div>
  );
}

function AddDocForm({ onAdd, sponsors = [], defaultSponsorId = "" }) {
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("Other");
  const [required, setRequired] = useState(true);
  const [sponsorId, setSponsorId] = useState(defaultSponsorId);
  const [busy, setBusy] = useState(false);

  // Follow filter changes
  useEffect(() => { setSponsorId(defaultSponsorId || ""); }, [defaultSponsorId]);

  const submit = async (e) => {
    e.preventDefault();
    if (!label.trim()) { toast.error("Give it a name"); return; }
    setBusy(true);
    try {
      await onAdd({ label: label.trim(), category, required, sponsor_id: sponsorId || null });
      setLabel(""); setCategory("Other"); setRequired(true);
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="byrd-card p-4 flex flex-col md:flex-row gap-3 md:items-end flex-wrap" data-testid="add-doc-form">
      <div className="flex-1 min-w-[200px]">
        <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Document label</label>
        <input value={label} onChange={(e) => setLabel(e.target.value)}
          data-testid="add-doc-label"
          className="mt-1 w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm"
          placeholder="e.g. STAR Report, PIP Budget, Franchise Agreement"
        />
      </div>
      <div>
        <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Category</label>
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          data-testid="add-doc-category"
          className="mt-1 w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm">
          <option>Personal</option>
          <option>Business</option>
          <option>Financial</option>
          <option>Property</option>
          <option>Other</option>
        </select>
      </div>
      {sponsors.length > 0 && (
        <div>
          <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Sponsor</label>
          <select value={sponsorId} onChange={(e) => setSponsorId(e.target.value)}
            data-testid="add-doc-sponsor"
            className="mt-1 w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm">
            <option value="">Shared (property/business)</option>
            {sponsors.map((s) => <option key={s.id} value={s.id}>{s.name || "Sponsor"}</option>)}
          </select>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
        Required
      </label>
      <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark" data-testid="add-doc-submit">
        <Plus size={14} /> Add Line
      </button>
    </form>
  );
}

const DOC_STATUS_OPTIONS = [
  { v: "pending", label: "Pending" },
  { v: "uploaded", label: "Uploaded" },
  { v: "reviewed", label: "Reviewed" },
  { v: "rejected", label: "Rejected" },
];

function ScenarioDocRow({ doc, scenarioId, sponsors = [], sponsorLookup = {}, onUpdate, onRemove, onToggleVisibility, onReload, noteCount = 0, notesOpen = false, onToggleNotes, onNotesChanged }) {
  const [notes, setNotes] = useState(doc.notes || "");
  const [status, setStatus] = useState(doc.status);
  const [dirty, setDirty] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [labelEditing, setLabelEditing] = useState(false);
  const [labelDraft, setLabelDraft] = useState(doc.label);

  useEffect(() => { setNotes(doc.notes || ""); setStatus(doc.status); setLabelDraft(doc.label); setDirty(false); }, [doc.id, doc.status, doc.notes, doc.label]);

  const save = async () => { await onUpdate(doc.id, { status, notes }); setDirty(false); };
  const quickStatus = async (s) => { setStatus(s); await onUpdate(doc.id, { status: s, notes }); setDirty(false); };

  const saveLabel = async () => {
    const next = labelDraft.trim();
    if (!next || next === doc.label) { setLabelDraft(doc.label); setLabelEditing(false); return; }
    try {
      await onUpdate(doc.id, { label: next });
      setLabelEditing(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't rename document");
      setLabelDraft(doc.label);
      setLabelEditing(false);
    }
  };

  const downloadFile = async (fileId) => {
    const res = await api.get(`/files/${fileId}`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    window.open(url, "_blank");
  };

  const uploadFile = async (file) => {
    if (!file) return;
    if (file.size > 15 * 1024 * 1024) { toast.error("File exceeds 15 MB limit"); return; }
    setUploading(true);
    try {
      const reader = new FileReader();
      const b64 = await new Promise((resolve, reject) => {
        reader.onload = () => {
          const s = reader.result;
          const idx = s.indexOf(",");
          resolve(s.substring(idx + 1));
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      // Admin upload-on-behalf: appends to files[] (doesn't overwrite prior uploads)
      await api.post(`/admin/scenarios/${scenarioId}/docs/${doc.id}/upload`, {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        data_b64: b64,
      });
      toast.success("Uploaded on borrower's behalf");
      onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const removeFile = async (fileId, filename) => {
    if (!window.confirm(`Remove "${filename}" from this line?`)) return;
    try {
      await api.delete(`/admin/scenarios/${scenarioId}/docs/${doc.id}/files/${fileId}`);
      toast.success("File removed");
      onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to remove file");
    }
  };

  const currentVis = doc.lender_visibility || "on_request";

  return (
    <div className="border-b border-[#E4DFD1] last:border-b-0" data-testid={`scen-doc-${doc.id}`}>
      <div className="grid grid-cols-1 md:grid-cols-[2fr_.9fr_1fr_1.4fr_1.2fr] items-center">
      <div className="px-4 py-3">
        {labelEditing ? (
          <input
            autoFocus
            value={labelDraft}
            onChange={(e) => setLabelDraft(e.target.value)}
            onBlur={saveLabel}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); saveLabel(); }
              if (e.key === "Escape") { setLabelDraft(doc.label); setLabelEditing(false); }
            }}
            data-testid={`doc-label-input-${doc.id}`}
            className="w-full h-8 px-2 rounded-md border border-[#C89434] bg-white text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-[#C89434]/40"
          />
        ) : (
          <button
            type="button"
            onClick={() => setLabelEditing(true)}
            data-testid={`doc-label-edit-${doc.id}`}
            className="group text-left w-full inline-flex items-center gap-1.5"
            title="Click to rename"
          >
            <span className="font-semibold">{doc.label}</span>
            <PenLine size={11} className="text-[#6B6558] opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
        )}
        <div className="flex items-center gap-2 mt-0.5 flex-wrap">
          {doc.required && <div className="text-[10px] font-mono uppercase text-[#C89434] tracking-widest">Required</div>}
          {sponsors.length > 0 && (
            doc.sponsor_id && sponsorLookup[doc.sponsor_id]
              ? <span className="byrd-chip byrd-chip-gold text-[10px]" data-testid={`doc-sponsor-chip-${doc.id}`}>👤 {sponsorLookup[doc.sponsor_id].name || "Sponsor"}</span>
              : <span className="byrd-chip text-[10px]">Shared</span>
          )}
          {sponsors.length > 0 && !doc.system && (
            <select
              value={doc.sponsor_id || ""}
              onChange={(e) => onUpdate(doc.id, { sponsor_id: e.target.value || "" })}
              className="text-[10px] h-6 px-1 rounded border border-[#E4DFD1] bg-white ml-1"
              data-testid={`doc-sponsor-select-${doc.id}`}
              title="Change scope"
            >
              <option value="">Shared</option>
              {sponsors.map((s) => <option key={s.id} value={s.id}>{s.name || "Sponsor"}</option>)}
            </select>
          )}
        </div>
      </div>
      <div className="px-4 py-3 text-sm text-[#6B6558]">{doc.category}</div>
      <div className="px-4 py-3">
        <select
          value={status}
          onChange={(e) => quickStatus(e.target.value)}
          data-testid={`doc-status-${doc.id}`}
          className="h-9 w-full px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
        >
          {DOC_STATUS_OPTIONS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
        </select>
      </div>
      <div className="px-4 py-3">
        {(() => {
          const files = doc.files && doc.files.length
            ? doc.files
            : (doc.file ? [{ id: doc.file.id, filename: doc.file.filename, size: doc.file.size, uploaded_by: "client" }] : []);
          if (!files.length) {
            return (
              <label className="inline-flex items-center gap-1 text-[11px] text-[#6B6558] cursor-pointer hover:text-[#1A1A1A]" data-testid={`doc-upload-${doc.id}`}>
                <input type="file" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); e.target.value = ""; }} disabled={uploading} />
                {uploading ? "Uploading…" : "Upload for client"}
              </label>
            );
          }
          return (
            <div className="space-y-1" data-testid={`doc-files-${doc.id}`}>
              {files.map((fi) => (
                <div key={fi.id} className="flex items-center gap-1 text-sm group" data-testid={`admin-file-row-${fi.id}`}>
                  <button
                    onClick={() => downloadFile(fi.id)}
                    className="inline-flex items-center gap-1 text-[#1A1A1A] hover:text-[#C89434] min-w-0 flex-1"
                    title={fi.filename}
                    data-testid={`doc-download-${fi.id}`}
                  >
                    <Download size={12} className="shrink-0" />
                    <span className="truncate">{fi.filename}</span>
                  </button>
                  <span className="text-[10px] text-[#6B6558] shrink-0">{formatSize(fi.size)}</span>
                  {fi.uploaded_by === "broker" && (
                    <span className="text-[9px] font-mono uppercase text-[#7A5410] tracking-widest shrink-0">Broker</span>
                  )}
                  {fi.uploaded_by === "ada" && (
                    <span className="text-[9px] font-mono uppercase text-[#23446E] tracking-widest shrink-0">Ada</span>
                  )}
                  {!doc.system && (
                    <button
                      onClick={() => removeFile(fi.id, fi.filename)}
                      className="text-[#8A1F1A] hover:text-[#5A0F0A] shrink-0 opacity-60 group-hover:opacity-100 transition-opacity"
                      title="Remove this file"
                      data-testid={`admin-delete-file-${fi.id}`}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              ))}
              {!doc.system && (
                <label
                  className="inline-flex items-center gap-1 text-[10px] text-[#6B6558] cursor-pointer hover:text-[#1A1A1A] mt-1"
                  data-testid={`doc-add-file-${doc.id}`}
                >
                  <input type="file" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); e.target.value = ""; }} disabled={uploading} />
                  {uploading ? "Uploading…" : "+ Add another file"}
                </label>
              )}
            </div>
          );
        })()}
        <input
          value={notes}
          onChange={(e) => { setNotes(e.target.value); setDirty(true); }}
          onBlur={() => dirty && save()}
          placeholder="Note (visible to client)"
          data-testid={`doc-client-note-${doc.id}`}
          className="mt-2 w-full h-8 px-2 rounded-md border border-[#E4DFD1] bg-white text-xs"
        />
      </div>
      <div className="px-4 py-3 flex items-center gap-2 flex-wrap">
        <div
          className="inline-flex rounded-md border border-[#E4DFD1] overflow-hidden text-[10px]"
          title="Default lender visibility for this document: Hidden = lenders never see it. On Request = lenders see the line title and can ask for it. Included = auto-shared with every lender who gets this deal package."
        >
          {[
            { v: "hidden", label: "Hidden", icon: EyeOff, tip: "Lenders won't see this doc at all." },
            { v: "on_request", label: "On Request", icon: Eye, tip: "Lenders see the line title and can request it." },
            { v: "included", label: "Included", icon: Check, tip: "Lenders auto-see & download this doc." },
          ].map((opt) => {
            const active = currentVis === opt.v;
            return (
              <button
                key={opt.v}
                onClick={() => onToggleVisibility(doc.id, opt.v)}
                data-testid={`viz-${doc.id}-${opt.v}`}
                title={opt.tip}
                className={`px-2 h-8 inline-flex items-center gap-1 whitespace-nowrap ${active ? "bg-[#1A1A1A] text-white" : "bg-white text-[#2A2A2A] hover:bg-[#F3EEE0]"}`}
              >
                <opt.icon size={10} /> {opt.label}
              </button>
            );
          })}
        </div>
        <DocNoteButton
          scenarioId={scenarioId}
          docId={doc.id}
          count={noteCount}
          open={notesOpen}
          onToggle={onToggleNotes}
        />
        <button
          onClick={onRemove}
          data-testid={`doc-remove-${doc.id}`}
          className="w-8 h-8 grid place-items-center rounded-md border border-[#E4DFD1] hover:bg-[#FADCDA] hover:border-[#E38380] hover:text-[#8A1F1A] transition-colors"
          title="Delete line"
        >
          <Trash2 size={12} />
        </button>
      </div>
      </div>
      {notesOpen && (
        <div className="px-4 pb-4 pt-1 bg-[#FBF8F1]/50" data-testid={`scen-doc-notes-wrap-${doc.id}`}>
          <NotesPanel
            scenarioId={scenarioId}
            docId={doc.id}
            title={`Notes on ${doc.label}`}
            compact
            onCountsChanged={onNotesChanged}
          />
        </div>
      )}
    </div>
  );
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function CopyDocsDialog({ scenarioId, onClose, onCopy }) {
  const [sources, setSources] = useState(null);
  const [selectedScen, setSelectedScen] = useState(null); // scenario_id
  const [picked, setPicked] = useState(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/admin/scenarios/${scenarioId}/docs/copy-source`)
      .then((r) => {
        setSources(r.data);
        if (r.data.length === 1) setSelectedScen(r.data[0].scenario_id);
      })
      .catch(() => setSources([]));
  }, [scenarioId]);

  const toggle = (docId) => {
    const next = new Set(picked);
    if (next.has(docId)) next.delete(docId); else next.add(docId);
    setPicked(next);
  };

  const currentDocs = sources?.find((s) => s.scenario_id === selectedScen)?.docs || [];
  const allSelected = currentDocs.length > 0 && currentDocs.every((d) => picked.has(d.id));
  const toggleAll = () => {
    if (allSelected) setPicked(new Set());
    else setPicked(new Set(currentDocs.map((d) => d.id)));
  };

  const submit = async () => {
    if (!selectedScen || picked.size === 0) return;
    setBusy(true);
    try {
      await onCopy(selectedScen, Array.from(picked));
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose} data-testid="copy-docs-dialog">
      <div onClick={(e) => e.stopPropagation()} className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col">
        <div className="px-6 py-4 border-b border-[#E4DFD1] flex items-center justify-between">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Copy Documents</div>
            <h2 className="font-serif text-2xl font-bold mt-1">From another scenario</h2>
          </div>
          <button onClick={onClose} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]"><X size={16} /></button>
        </div>
        <div className="px-6 py-4 space-y-3 overflow-y-auto flex-1">
          {sources === null && <div className="text-sm text-[#6B6558]">Loading…</div>}
          {sources && sources.length === 0 && (
            <div className="text-sm text-[#6B6558] py-8 text-center">
              This client has no other scenarios with documents yet.
            </div>
          )}
          {sources && sources.length > 0 && (
            <>
              <div>
                <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Source scenario</label>
                <select
                  value={selectedScen || ""}
                  onChange={(e) => { setSelectedScen(e.target.value); setPicked(new Set()); }}
                  data-testid="copy-source-scen"
                  className="mt-1 w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm"
                >
                  <option value="">— Pick a scenario —</option>
                  {sources.map((s) => (
                    <option key={s.scenario_id} value={s.scenario_id}>
                      {s.scenario_name} ({s.docs.length} docs)
                    </option>
                  ))}
                </select>
              </div>
              {selectedScen && (
                <>
                  <div className="flex items-center justify-between text-xs text-[#6B6558]">
                    <span>{picked.size} selected of {currentDocs.length}</span>
                    <button onClick={toggleAll} className="underline hover:text-[#1A1A1A]" data-testid="copy-select-all">
                      {allSelected ? "Clear all" : "Select all"}
                    </button>
                  </div>
                  <div className="border border-[#E4DFD1] rounded-md overflow-hidden max-h-[45vh] overflow-y-auto">
                    {currentDocs.map((d) => (
                      <label
                        key={d.id}
                        className={`flex items-center gap-2 px-3 py-2 border-b border-[#E4DFD1] last:border-b-0 hover:bg-[#FBF8F1] cursor-pointer text-sm ${picked.has(d.id) ? "bg-[#FBEFD3]/50" : "bg-white"}`}
                        data-testid={`copy-pick-${d.id}`}
                      >
                        <input type="checkbox" checked={picked.has(d.id)} onChange={() => toggle(d.id)} />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium truncate">{d.label}</div>
                          <div className="text-[11px] text-[#6B6558]">
                            {d.category}
                            {(() => {
                              const cnt = (d.files && d.files.length) || (d.file ? 1 : 0);
                              if (!cnt) return " · not yet uploaded";
                              if (cnt === 1) return ` · ${(d.files?.[0]?.filename) || d.file?.filename || "1 file"}`;
                              return ` · ${cnt} files attached`;
                            })()}
                          </div>
                        </div>
                        {((d.files && d.files.length) || d.file) && <span className="byrd-chip byrd-chip-blue text-[10px]">{(d.files?.length || 1)} file{(d.files?.length || 1) > 1 ? "s" : ""}</span>}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>
        <div className="px-6 py-4 border-t border-[#E4DFD1] flex items-center gap-2">
          <button onClick={onClose} className="byrd-btn byrd-btn-outline flex-1">Cancel</button>
          <button
            onClick={submit}
            disabled={busy || !selectedScen || picked.size === 0}
            className="byrd-btn byrd-btn-dark flex-1"
            data-testid="copy-submit"
          >
            {busy ? "Copying…" : `Copy ${picked.size} doc${picked.size === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// --------------- LENDERS TAB ---------------
function MatchReasonChips({ fits = [], misses = [], testId }) {
  const hasAny = (fits.length + misses.length) > 0;
  if (!hasAny) {
    return <div className="text-[11px] text-[#6B6558] italic mt-1">No credit-box data on this lender yet — add property types, geography, and size on their profile to score them.</div>;
  }
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" data-testid={testId}>
      {fits.map((f, i) => (
        <span key={`f${i}`}
              className="inline-flex items-center gap-1 rounded-full border border-[#B8D3B8] bg-[#EFF6EF] text-[#245C25] px-2 py-0.5 text-[10px] font-medium"
              data-testid={testId ? `${testId}-fit-${i}` : undefined}>
          <Check size={9} strokeWidth={3} /> {f}
        </span>
      ))}
      {misses.map((m, i) => (
        <span key={`m${i}`}
              className="inline-flex items-center gap-1 rounded-full border border-[#E38380] bg-[#FADCDA] text-[#8A1F1A] px-2 py-0.5 text-[10px] font-medium"
              data-testid={testId ? `${testId}-miss-${i}` : undefined}>
          <X size={9} strokeWidth={3} /> {m}
        </span>
      ))}
    </div>
  );
}

function LendersTab({ scen, lenders, matches, suggestions, shareActivity = {}, onReloadActivity, onInviteSelfReg, runMatch, onOpenSendDialog, onRevoke, onOpenEditVisibility, shareLenderId, setShareLenderId }) {
  const [onlyFits, setOnlyFits] = useState(false);
  const scenDocs = scen.docs || scen.client_docs || [];
  const clientDocMap = {};
  scenDocs.forEach((d) => { clientDocMap[d.id] = d; });
  // Any scenario doc is a candidate for lender visibility now.
  const attached = scenDocs;

  const copyLink = (token) => {
    const url = `${window.location.origin}/lender/scenario/${token}`;
    navigator.clipboard.writeText(url);
    toast.success("Link copied to clipboard");
  };

  // Compute effective visibility counts per share (mirrors backend logic)
  const shareCounts = (sh) => {
    const overrides = sh.doc_overrides || {};
    const grants = new Set(sh.doc_grants || []);
    let included = 0, onReq = 0, hidden = 0;
    scenDocs.forEach((d) => {
      let eff;
      if (d.id in overrides) {
        const v = overrides[d.id];
        eff = v === "include" ? "included" : v === "hidden" ? "hidden" : "on_request";
      } else if (grants.has(d.id)) {
        eff = "included";
      } else {
        eff = (d.lender_visibility || "on_request") === "included" ? "included" : "on_request";
      }
      if (eff === "included") included++;
      else if (eff === "on_request") onReq++;
      else hidden++;
    });
    return { included, onReq, hidden };
  };

  return (
    <div className="space-y-6">
      {/* Auto-match suggestions (self-registered lenders) */}
      {(suggestions || []).length > 0 && (
        <div className="byrd-card p-6 border-l-4 border-[#245C25]" data-testid="marketplace-suggestions">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#245C25]">// Marketplace Matches</div>
              <h3 className="font-serif text-xl font-bold">Self-registered lenders that fit this deal</h3>
              <p className="text-xs text-[#6B6558] mt-1">Approved marketplace lenders — one-click invite sends them straight to their portal.</p>
            </div>
            <button
              onClick={() => onInviteSelfReg(suggestions.map((s) => s.lender.id))}
              className="byrd-btn byrd-btn-dark"
              data-testid="invite-all-suggested-btn"
            >
              <Share2 size={14} /> Invite all {suggestions.length}
            </button>
          </div>
          <div className="mt-4 space-y-3">
            {suggestions.map((m) => (
              <div key={m.lender.id} className="border border-[#C9E1C9] bg-[#F5F9F5] rounded-md p-4 flex items-start justify-between gap-3" data-testid={`suggest-${m.lender.id}`}>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-semibold">{m.lender.name}</div>
                    <span className={m.verdict === "fit" ? "byrd-chip byrd-chip-green" : "byrd-chip byrd-chip-gold"}>{m.verdict}</span>
                    <span className="byrd-chip">Marketplace</span>
                  </div>
                  <MatchReasonChips fits={m.fits} misses={m.misses} testId={`suggest-reasons-${m.lender.id}`} />
                </div>
                <button
                  onClick={() => onInviteSelfReg([m.lender.id])}
                  className="byrd-btn byrd-btn-outline h-9 px-3 text-xs shrink-0"
                  data-testid={`invite-suggest-${m.lender.id}`}
                >
                  Invite
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Matching */}
      <div className="byrd-card p-6">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Match Engine</div>
            <h3 className="font-serif text-xl font-bold">Lenders that fit this deal</h3>
            <p className="text-[11px] text-[#6B6558] mt-1">Green chips = why it fits. Red chips = why it doesn't. Score = fits &minus; 2× misses.</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => setOnlyFits((v) => !v)}
              data-testid="match-toggle-fits"
              className={`inline-flex items-center gap-1 rounded-md border px-2 h-8 text-[11px] font-mono uppercase tracking-widest ${
                onlyFits ? "bg-[#245C25] text-white border-[#245C25]" : "border-[#E4DFD1] bg-white text-[#2A2A2A] hover:bg-[#F3EEE0]"
              }`}
            >
              <Check size={10} /> Fits only
            </button>
            <button onClick={() => runMatch()} className="byrd-btn byrd-btn-outline" data-testid="run-match-btn">
              <RefreshCw size={14} /> Re-run Match
            </button>
          </div>
        </div>
        {matches.length === 0 ? (
          <div className="text-sm text-[#6B6558] mt-4" data-testid="match-empty">
            Click &quot;Re-run Match&quot; to score your lender directory against this scenario.
            {(!scen.property_info?.property_type || !scen.property_info?.state) && (
              <div className="mt-2 text-[#8A1F1A]">
                Tip: add a <b>property type</b> and <b>state</b> on the Package tab so the engine has something to score against.
              </div>
            )}
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {(onlyFits ? matches.filter((m) => m.verdict === "fit" || m.verdict === "partial") : matches).slice(0, 20).map((m) => (
              <div key={m.lender.id} className="border border-[#E4DFD1] rounded-md p-4 flex items-start justify-between gap-3" data-testid={`match-${m.lender.id}`}>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-semibold">{m.lender.name}</div>
                    <span className={m.verdict === "fit" ? "byrd-chip byrd-chip-green" : m.verdict === "partial" ? "byrd-chip byrd-chip-gold" : "byrd-chip byrd-chip-red"}>
                      {m.verdict}
                    </span>
                    {(m.lender.property_subtypes?.length > 0) && (
                      <span className="byrd-chip text-[10px]">specialist</span>
                    )}
                  </div>
                  <MatchReasonChips fits={m.fits} misses={m.misses} testId={`match-reasons-${m.lender.id}`} />
                </div>
                <button onClick={() => onOpenSendDialog(m.lender.id)} className="byrd-btn byrd-btn-dark h-9 px-3 text-xs shrink-0" data-testid={`match-share-${m.lender.id}`}>
                  <Share2 size={12} /> Send Package
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
          <button onClick={() => shareLenderId && onOpenSendDialog(shareLenderId)} disabled={!shareLenderId} className="byrd-btn byrd-btn-dark" data-testid="create-share-btn">
            <Share2 size={14} /> Send Package…
          </button>
        </div>
        <div className="text-[11px] text-[#6B6558] mt-2">
          You&apos;ll be able to set per-document visibility (Include / On Request / Hidden) for this specific lender before sending.
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
              const c = shareCounts(sh);
              const act = shareActivity[sh.id] || {};
              const lastAct = act.last_activity_at ? new Date(act.last_activity_at) : null;
              const daysAgo = lastAct ? Math.floor((Date.now() - lastAct.getTime()) / 86400000) : null;
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
                      {/* Activity chip: opened / downloads / last activity */}
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                        {act.scenario_opens > 0 ? (
                          <span className="byrd-chip byrd-chip-green" data-testid={`share-${sh.id}-activity`}>
                            <Eye size={10} /> Opened {act.scenario_opens}× · {act.doc_downloads || 0} downloads · {daysAgo === 0 ? "today" : daysAgo === 1 ? "yesterday" : `${daysAgo} days ago`}
                          </span>
                        ) : (
                          <span className="byrd-chip" data-testid={`share-${sh.id}-not-opened`}>Not yet opened</span>
                        )}
                        {attached.length > 0 && (
                          <>
                            <span className="byrd-chip byrd-chip-green" data-testid={`share-${sh.id}-included-count`}><Check size={10} /> {c.included} Included</span>
                            <span className="byrd-chip byrd-chip-gold" data-testid={`share-${sh.id}-onrequest-count`}><Eye size={10} /> {c.onReq} On Request</span>
                            {c.hidden > 0 && (
                              <span className="byrd-chip byrd-chip-red" data-testid={`share-${sh.id}-hidden-count`}><EyeOff size={10} /> {c.hidden} Hidden</span>
                            )}
                          </>
                        )}
                      </div>
                      {/* Editable per-lender note */}
                      <ShareNoteEditor share={sh} scenarioId={scen.id} onSaved={onReloadActivity} />
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      {attached.length > 0 && (
                        <button onClick={() => onOpenEditVisibility(sh)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`manage-visibility-${sh.id}`}>
                          <Sliders size={12} /> Manage Visibility
                        </button>
                      )}
                      <button onClick={() => copyLink(sh.token)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`copy-share-${sh.id}`}>
                        <Copy size={12} /> Copy Link
                      </button>
                      <button onClick={() => onRevoke(sh.id)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs text-[#8A1F1A] border-[#E38380]" data-testid={`revoke-share-${sh.id}`}>
                        <X size={12} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// --------------- SHARE VISIBILITY DIALOG ---------------
function ShareVisibilityDialog({ scen, dialog, onClose, onSubmit }) {
  const scenDocs = scen.docs || scen.client_docs || [];

  // Every scenario doc is a candidate — the lender either sees it, must request it, or it's hidden.
  const rows = scenDocs.map((d) => ({
    doc_id: d.id,
    doc: d,
    default_visibility: d.lender_visibility || "on_request",
  }));

  // Initial per-row state: explicit override > legacy grant > doc's own lender_visibility default.
  const initial = {};
  const startOverrides = dialog.overrides || {};
  const legacyGrants = new Set(dialog.share?.doc_grants || []);
  rows.forEach((r) => {
    if (r.doc_id in startOverrides) {
      initial[r.doc_id] = startOverrides[r.doc_id];
    } else if (legacyGrants.has(r.doc_id)) {
      initial[r.doc_id] = "include";
    } else {
      initial[r.doc_id] = r.default_visibility === "included" ? "include" : (r.default_visibility === "hidden" ? "hidden" : "on_request");
    }
  });

  const [state, setState] = useState(initial);
  const [busy, setBusy] = useState(false);

  const setAll = (v) => {
    const next = {};
    rows.forEach((r) => { next[r.doc_id] = v; });
    setState(next);
  };

  const submit = async () => {
    setBusy(true);
    try {
      await onSubmit(state);
    } finally {
      setBusy(false);
    }
  };

  const counts = Object.values(state).reduce(
    (acc, v) => {
      if (v === "include") acc.include++;
      else if (v === "hidden") acc.hidden++;
      else acc.onReq++;
      return acc;
    },
    { include: 0, onReq: 0, hidden: 0 }
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      role="dialog"
      onClick={onClose}
      data-testid="share-visibility-dialog"
    >
      <div
        className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#E4DFD1] flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">
              {dialog.mode === "create" ? "// Send Package" : "// Manage Visibility"}
            </div>
            <h2 className="font-serif text-2xl font-bold truncate">{dialog.lenderName}</h2>
            <p className="text-xs text-[#6B6558] mt-1">
              Set exactly which documents this lender can see, request, or never know about.
            </p>
          </div>
          <button onClick={onClose} className="text-[#6B6558] hover:text-[#1A1A1A]" data-testid="dialog-close">
            <X size={18} />
          </button>
        </div>

        {/* Bulk actions */}
        <div className="px-6 py-3 border-b border-[#E4DFD1] bg-[#FBF8F1] flex items-center justify-between flex-wrap gap-2 text-xs">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="byrd-chip byrd-chip-green"><Check size={10} /> {counts.include} Included</span>
            <span className="byrd-chip byrd-chip-gold"><Eye size={10} /> {counts.onReq} On Request</span>
            {counts.hidden > 0 && <span className="byrd-chip byrd-chip-red"><EyeOff size={10} /> {counts.hidden} Hidden</span>}
          </div>
          <div className="flex items-center gap-1 text-[11px] text-[#6B6558]">
            <span className="mr-1">All:</span>
            <button onClick={() => setAll("include")} className="underline hover:text-[#1A1A1A]" data-testid="bulk-include">Include</button>
            <span>·</span>
            <button onClick={() => setAll("on_request")} className="underline hover:text-[#1A1A1A]" data-testid="bulk-on-request">On Request</button>
            <span>·</span>
            <button onClick={() => setAll("hidden")} className="underline hover:text-[#1A1A1A]" data-testid="bulk-hidden">Hide</button>
          </div>
        </div>

        {/* Doc list */}
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-2">
          {rows.length === 0 && (
            <div className="text-sm text-[#6B6558] py-6 text-center">
              This scenario has no documents yet. Add lines in the Documents tab first.
            </div>
          )}
          {rows.map((r) => {
            const d = r.doc;
            const cur = state[r.doc_id];
            const options = [
              { v: "include", label: "Include", icon: Check, tone: "bg-[#245C25] text-white border-[#245C25]" },
              { v: "on_request", label: "On Request", icon: Eye, tone: "bg-[#7A5410] text-white border-[#7A5410]" },
              { v: "hidden", label: "Hide", icon: EyeOff, tone: "bg-[#8A1F1A] text-white border-[#8A1F1A]" },
            ];
            return (
              <div key={r.doc_id} className="border border-[#E4DFD1] rounded-md p-3 flex items-start justify-between gap-3" data-testid={`viz-row-${r.doc_id}`}>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText size={14} className="text-[#C89434] shrink-0" />
                    <div className="font-semibold text-sm truncate">{d.label}</div>
                  </div>
                  <div className="text-[11px] text-[#6B6558] mt-0.5 truncate">
                    {d.category}
                    {(() => {
                      const cnt = (d.files && d.files.length) || (d.file ? 1 : 0);
                      if (cnt === 1) return <> · {d.files?.[0]?.filename || d.file?.filename}</>;
                      if (cnt > 1) return <> · {cnt} files</>;
                      return <> · <span className="text-[#8A1F1A]">Not uploaded yet</span></>;
                    })()}
                  </div>
                </div>
                <div className="inline-flex rounded-md border border-[#E4DFD1] overflow-hidden text-[11px]">
                  {options.map((opt) => {
                    const active = cur === opt.v;
                    return (
                      <button
                        key={opt.v}
                        onClick={() => setState({ ...state, [r.doc_id]: opt.v })}
                        className={`px-2.5 h-8 flex items-center gap-1 border-r border-[#E4DFD1] last:border-r-0 ${
                          active ? opt.tone : "bg-white text-[#2A2A2A] hover:bg-[#F3EEE0]"
                        }`}
                        data-testid={`viz-${r.doc_id}-${opt.v}`}
                      >
                        <opt.icon size={11} /> {opt.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#E4DFD1] flex items-center justify-between gap-3 flex-wrap">
          <div className="text-[11px] text-[#6B6558]">
            {dialog.mode === "create"
              ? "A shareable link will be generated and copied to your clipboard."
              : "The lender's link stays the same — visibility updates immediately."}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="byrd-btn byrd-btn-outline" data-testid="dialog-cancel">
              Cancel
            </button>
            <button onClick={submit} disabled={busy} className="byrd-btn byrd-btn-dark" data-testid="dialog-submit">
              {busy ? "Saving…" : dialog.mode === "create" ? <>Send Package <Share2 size={14} /></> : <>Save Visibility <Save size={14} /></>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


// ================= TermSheetsTab (marketplace) =================
function TermSheetsTab({ scenarioId, termSheets, onReload }) {
  const [actingOn, setActingOn] = useState(null); // {id, status, note}
  const [deleting, setDeleting] = useState(null); // {id, lender_name}

  const setStatus = async () => {
    if (!actingOn) return;
    try {
      await api.patch(`/admin/term-sheets/${actingOn.id}`, {
        status: actingOn.status,
        broker_note: actingOn.note || "",
      });
      toast.success(`Term sheet ${actingOn.status}`);
      setActingOn(null);
      onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    try {
      await api.delete(`/admin/term-sheets/${deleting.id}`);
      toast.success("Term sheet deleted");
      setDeleting(null);
      onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  const fmtM = (v) => v == null ? "—" : `$${Number(v).toLocaleString()}`;
  const fmtP = (v) => v == null ? "—" : `${v}%`;

  return (
    <div className="space-y-6" data-testid="term-sheets-tab">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Term Sheets</div>
          <h2 className="font-serif text-2xl font-bold">Lender submissions ({termSheets.length})</h2>
          <p className="text-xs text-[#6B6558] mt-1">Side-by-side view of every term sheet submitted through the Lender Marketplace. Acting on a term sheet emails the lender + is visible to the borrower in their portal.</p>
        </div>
      </div>

      {termSheets.length === 0 ? (
        <div className="byrd-card p-10 text-center" data-testid="ts-empty">
          <div className="text-sm text-[#6B6558]">No term sheets submitted yet.</div>
          <p className="text-xs text-[#6B6558] mt-2 max-w-md mx-auto">Invite lenders from the Lenders tab. Once they submit, term sheets show up here for you to accept, counter, or pass on.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {termSheets.map((t) => (
            <div key={t.id} className="byrd-card p-5" data-testid={`admin-ts-${t.id}`}>
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-serif text-lg font-bold">{t.lender_name}</div>
                    <TSStatusChip status={t.status} />
                  </div>
                  <div className="text-xs text-[#6B6558] mt-0.5">Submitted {new Date(t.submitted_at).toLocaleString()}</div>
                </div>
                <button
                  type="button"
                  onClick={() => setDeleting({ id: t.id, lender_name: t.lender_name })}
                  className="text-[#8A1F1A] hover:text-[#5A0F0A] p-1 -m-1 opacity-70 hover:opacity-100 transition"
                  title="Delete this term sheet"
                  data-testid={`ts-delete-${t.id}`}
                >
                  <Trash2 size={14} />
                </button>
              </div>
              <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-2 text-sm">
                <KV2 label="Rate">{t.interest_rate_pct != null ? `${t.interest_rate_pct}%` : "—"}{t.rate_type ? <span className="text-[10px] text-[#6B6558]"> {t.rate_type}</span> : null}</KV2>
                <KV2 label="Loan">{fmtM(t.loan_amount)}</KV2>
                <KV2 label="LTV">{fmtP(t.ltv_pct)}</KV2>
                <KV2 label="LTC">{fmtP(t.ltc_pct)}</KV2>
                <KV2 label="Amort">{t.amortization_years ? `${t.amortization_years} yr` : "—"}</KV2>
                <KV2 label="Term">{t.term_months ? `${t.term_months} mo` : "—"}</KV2>
                <KV2 label="IO">{t.io_months ? `${t.io_months} mo` : "—"}</KV2>
                {t.fixed_period_months != null && (
                  <KV2 label="Fixed period">{`${t.fixed_period_months} mo`}</KV2>
                )}
                <KV2 label="Recourse">{t.recourse || "—"}</KV2>
                <KV2 label="Orig fee">{fmtP(t.origination_fee_pct)}</KV2>
                <KV2 label="Exit fee">{fmtP(t.exit_fee_pct)}</KV2>
                <KV2 label="Prepay">{t.prepay || "—"}</KV2>
                <KV2 label="Expires">{t.expiration_date || "—"}</KV2>
              </div>
              {t.rate_adjustment_notes && (
                <div className="mt-3 text-xs">
                  <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-0.5">Rate Adjustment</div>
                  <div className="text-[#2A2A2A]">{t.rate_adjustment_notes}</div>
                </div>
              )}
              {t.document && (
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const r = await api.get(`/term-sheets/${t.id}/document`, { responseType: "blob" });
                        const url = URL.createObjectURL(r.data);
                        window.open(url, "_blank");
                      } catch (e) { toast.error(e?.response?.data?.detail || "Download failed"); }
                    }}
                    className="byrd-btn byrd-btn-outline h-8 px-3 text-xs"
                    data-testid={`admin-ts-${t.id}-doc-download`}
                  >
                    <Download size={12} /> {t.document.filename}
                  </button>
                </div>
              )}
              {t.contingencies && (
                <div className="mt-3 text-xs">
                  <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-0.5">Contingencies</div>
                  <div className="text-[#2A2A2A]">{t.contingencies}</div>
                </div>
              )}
              {t.notes && (
                <div className="mt-3 text-xs bg-[#F3EEE0] border-l-2 border-[#C89434] p-2 italic">"{t.notes}"</div>
              )}
              {t.broker_note && t.status !== "submitted" && (
                <div className="mt-3 text-xs bg-white border-l-2 border-[#245C25] p-2">
                  <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-0.5">// Your Note</div>
                  {t.broker_note}
                </div>
              )}
              {t.status === "submitted" && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <button onClick={() => setActingOn({ id: t.id, status: "accepted", note: "" })}
                    className="byrd-btn byrd-btn-dark h-9 px-3 text-xs" data-testid={`ts-accept-${t.id}`}>
                    <Check size={12} /> Accept
                  </button>
                  <button onClick={() => setActingOn({ id: t.id, status: "countered", note: "" })}
                    className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`ts-counter-${t.id}`}>
                    Counter with note…
                  </button>
                  <button onClick={() => setActingOn({ id: t.id, status: "passed", note: "" })}
                    className="byrd-btn byrd-btn-outline h-9 px-3 text-xs text-[#8A1F1A] border-[#E38380]" data-testid={`ts-pass-${t.id}`}>
                    Pass
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {actingOn && (
        <div className="fixed inset-0 bg-black/40 z-50 grid place-items-center p-4" data-testid="ts-action-modal">
          <div className="bg-white rounded-md border border-[#E4DFD1] w-full max-w-md p-6">
            <div className="font-serif text-xl font-bold capitalize">{actingOn.status} term sheet</div>
            <p className="text-xs text-[#6B6558] mt-1">
              The lender will be emailed with your note. The borrower will also see this in their portal.
            </p>
            <textarea
              value={actingOn.note}
              onChange={(e) => setActingOn({ ...actingOn, note: e.target.value })}
              placeholder={actingOn.status === "countered" ? "Client wants 65% LTV, 5-year term, non-recourse…" : "Optional note to the lender."}
              className="w-full min-h-[100px] mt-3 px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
              data-testid="ts-action-note"
            />
            <div className="mt-4 flex items-center justify-end gap-2">
              <button onClick={() => setActingOn(null)} className="byrd-btn byrd-btn-outline">Cancel</button>
              <button onClick={setStatus} className="byrd-btn byrd-btn-dark" data-testid="ts-action-confirm">
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      {deleting && (
        <div className="fixed inset-0 bg-black/40 z-50 grid place-items-center p-4" data-testid="ts-delete-modal">
          <div className="bg-white rounded-md border border-[#E4DFD1] w-full max-w-md p-6">
            <div className="font-serif text-xl font-bold">Delete term sheet?</div>
            <p className="text-sm text-[#2A2A2A] mt-2">
              This permanently removes <b>{deleting.lender_name}</b>&apos;s term sheet from this scenario. It will disappear from your admin view and the borrower&apos;s portal. The lender is not notified.
            </p>
            <p className="text-xs text-[#8A1F1A] mt-2">This action cannot be undone.</p>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button onClick={() => setDeleting(null)} className="byrd-btn byrd-btn-outline" data-testid="ts-delete-cancel">Cancel</button>
              <button onClick={confirmDelete} className="byrd-btn byrd-btn-dark bg-[#8A1F1A] border-[#8A1F1A] hover:bg-[#5A0F0A]" data-testid="ts-delete-confirm">
                <Trash2 size={12} /> Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ------------- ShareNoteEditor (per-lender broker note) -------------
function ShareNoteEditor({ share, scenarioId, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(share.note || "");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/admin/scenarios/${scenarioId}/shares/${share.id}/note`, { note });
      toast.success("Note saved");
      setEditing(false);
      onSaved && onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    } finally {
      setSaving(false);
    }
  };
  if (!editing) {
    return (
      <div className="mt-2 text-[11px] text-[#6B6558] flex items-start gap-2">
        {share.note ? (
          <div className="flex-1 italic bg-[#F3EEE0] border-l-2 border-[#C89434] px-2 py-1">"{share.note}"</div>
        ) : (
          <div className="flex-1 italic text-[#B8B0A0]">No private note</div>
        )}
        <button onClick={() => { setNote(share.note || ""); setEditing(true); }} className="text-[#C89434] hover:underline text-[10px]" data-testid={`edit-note-${share.id}`}>
          {share.note ? "Edit" : "Add note"}
        </button>
      </div>
    );
  }
  return (
    <div className="mt-2">
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Private context you want to remember about this share (e.g. 'Promised T-12 by Friday')"
        className="w-full min-h-[50px] text-xs p-2 border border-[#E4DFD1] rounded-md focus:outline-none focus:border-[#C89434]"
        maxLength={2000}
        data-testid={`note-input-${share.id}`}
      />
      <div className="flex gap-2 mt-1 justify-end">
        <button onClick={() => setEditing(false)} className="text-[10px] text-[#6B6558] hover:underline">Cancel</button>
        <button onClick={save} disabled={saving} className="text-[10px] text-[#C89434] hover:underline font-semibold" data-testid={`save-note-${share.id}`}>{saving ? "Saving…" : "Save note"}</button>
      </div>
    </div>
  );
}

function TSStatusChip({ status }) {
  const map = {
    submitted: "byrd-chip byrd-chip-gold",
    accepted: "byrd-chip byrd-chip-green",
    countered: "byrd-chip byrd-chip-gold",
    passed: "byrd-chip byrd-chip-red",
    withdrawn: "byrd-chip byrd-chip-red",
  };
  return <span className={map[status] || "byrd-chip"}>{status}</span>;
}

function KV2({ label, children }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</div>
      <div className="text-sm font-semibold">{children}</div>
    </div>
  );
}
