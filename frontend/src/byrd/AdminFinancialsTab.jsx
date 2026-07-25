import React, { useEffect, useState, useMemo } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Upload, Sparkles, FileText, Download, Image as ImageIcon, X, Save } from "lucide-react";

const fmtMoney = (v) => (v == null || v === "" ? "—" : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`);
const fmtNum = (v) => (v == null || v === "" ? "—" : Number(v).toLocaleString());
const fmtPct = (v, d = 2) => (v == null || v === "" ? "—" : `${Number(v).toFixed(d)}%`);

const INCOME_ROWS = [
  { key: "gross_potential_rent", label: "Gross Potential Rent" },
  { key: "vacancy_loss", label: "Vacancy / Credit Loss", note: "(subtracted)" },
  { key: "other_income", label: "Other Income" },
];

const EXPENSE_ROWS = [
  { key: "taxes", label: "Property Taxes" },
  { key: "insurance", label: "Insurance" },
  { key: "utilities", label: "Utilities" },
  { key: "repairs_maintenance", label: "Repairs & Maintenance" },
  { key: "management", label: "Property Management" },
  { key: "payroll", label: "Payroll" },
  { key: "marketing", label: "Marketing / Leasing" },
  { key: "reserves_capex", label: "Reserves / CapEx" },
  { key: "general_admin", label: "General & Admin" },
  { key: "other_expense", label: "Other" },
];

function NumberCell({ value, onChange, testId }) {
  return (
    <input
      type="number"
      inputMode="decimal"
      step="0.01"
      value={value == null ? "" : value}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      className="w-full px-2 py-1 text-right border border-transparent hover:border-[#E4DFD1] focus:border-[#C89434] focus:outline-none rounded-sm text-sm bg-transparent"
      placeholder="—"
      data-testid={testId}
    />
  );
}

export default function AdminFinancialsTab({ scenarioId, scen, onScenReload }) {
  const [data, setData] = useState(null); // {periods, selected_period_id, uw_assumptions, metrics}
  const [savingPid, setSavingPid] = useState(null);
  const [addMode, setAddMode] = useState(null); // null | "manual" | "upload"
  const [proposal, setProposal] = useState(null); // parsed Ada proposal
  const [summary, setSummary] = useState({ config: null, photos: [] });
  const [previewUrl, setPreviewUrl] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.get(`/admin/scenarios/${scenarioId}/financials`).then((r) => setData(r.data));
  const loadSummary = () => api.get(`/admin/scenarios/${scenarioId}/summary`).then((r) => setSummary(r.data));

  useEffect(() => { load(); loadSummary(); }, [scenarioId]);

  const periods = data?.periods || [];
  const selectedId = data?.selected_period_id;
  const uw = data?.uw_assumptions || {};
  const m = data?.metrics || {};

  // ---- period line edits (debounced would be better; keep simple onBlur pattern) ----
  const patchPeriod = async (pid, changes) => {
    setSavingPid(pid);
    try {
      const r = await api.patch(`/admin/scenarios/${scenarioId}/financials/periods/${pid}`, changes);
      setData((prev) => ({
        ...prev,
        periods: prev.periods.map((p) => (p.id === pid ? r.data : p)),
      }));
      // Recompute deal-level metrics only if changes might affect selected
      if (pid === selectedId) load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSavingPid(null);
    }
  };

  const patchIncomeCell = (pid, key, value) => {
    const p = periods.find((x) => x.id === pid);
    if (!p) return;
    patchPeriod(pid, { income: { ...(p.income || {}), [key]: value } });
  };
  const patchExpenseCell = (pid, key, value) => {
    const p = periods.find((x) => x.id === pid);
    if (!p) return;
    patchPeriod(pid, { expenses: { ...(p.expenses || {}), [key]: value } });
  };

  const setSelected = async (pid) => {
    await api.post(`/admin/scenarios/${scenarioId}/financials/select`, { period_id: pid });
    setData((prev) => ({ ...prev, selected_period_id: pid }));
    load();
    onScenReload?.();
  };

  const deletePeriod = async (pid) => {
    if (!window.confirm("Delete this period? This cannot be undone.")) return;
    await api.delete(`/admin/scenarios/${scenarioId}/financials/periods/${pid}`);
    toast.success("Period deleted");
    load();
    onScenReload?.();
  };

  const patchUW = async (changes) => {
    const r = await api.patch(`/admin/scenarios/${scenarioId}/financials/assumptions`, changes);
    setData((prev) => ({ ...prev, uw_assumptions: r.data.uw_assumptions }));
    load();
  };

  // ---- Add period ----
  const addPeriod = async (period) => {
    const r = await api.post(`/admin/scenarios/${scenarioId}/financials/periods`, period);
    toast.success(`Added ${r.data.label}`);
    setAddMode(null);
    setProposal(null);
    load();
    onScenReload?.();
  };

  // ---- Executive Summary ----
  const patchSummary = async (changes) => {
    await api.patch(`/admin/scenarios/${scenarioId}/summary`, changes);
    loadSummary();
  };

  const uploadPhoto = async (file) => {
    if (!file) return;
    const b64 = await fileToB64(file);
    try {
      await api.post(`/admin/scenarios/${scenarioId}/summary/photos`, {
        filename: file.name, content_type: file.type || "image/jpeg", data_b64: b64,
      });
      loadSummary();
      toast.success("Photo added");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    }
  };

  const deletePhoto = async (pid) => {
    await api.delete(`/admin/scenarios/${scenarioId}/summary/photos/${pid}`);
    loadSummary();
  };

  const generatePreview = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/admin/scenarios/${scenarioId}/summary/generate`, {}, { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      setPreviewUrl(url);
      // Use a hidden anchor click instead of window.open() to avoid popup blockers after an await.
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Generate failed");
    } finally {
      setBusy(false);
    }
  };

  const saveToPortal = async () => {
    setBusy(true);
    try {
      await api.post(`/admin/scenarios/${scenarioId}/summary/save-to-portal`, {});
      toast.success("Loan Summary pinned to top of document portal");
      onScenReload?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return <div className="text-sm text-[#6B6558] p-6">Loading financials…</div>;
  }

  return (
    <div className="space-y-8" data-testid="financials-tab">
      {/* Header */}
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Financials</div>
          <h2 className="font-serif text-2xl font-bold">Underwriting Table</h2>
          <p className="text-xs text-[#6B6558] mt-1 max-w-2xl">
            Build a per-period income/expense table from tax returns, P&amp;Ls, and pro forma. Pick which
            column feeds the lender view and the Loan Executive Summary.
          </p>
        </div>
        <button
          onClick={() => setAddMode("choose")}
          className="byrd-btn byrd-btn-dark"
          data-testid="add-period-btn"
        >
          <Plus size={14} /> Add Period
        </button>
      </div>

      {/* UW Assumptions bar */}
      <div className="byrd-card p-4">
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] mb-2">// Underwriting Assumptions (for DSCR)</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <UWField label="Rate (%)" value={uw.rate_pct} step="0.01"
            onSave={(v) => patchUW({ rate_pct: v })} testId="uw-rate" />
          <UWField label="Amortization (months)" value={uw.amort_months}
            onSave={(v) => patchUW({ amort_months: v == null ? null : parseInt(v) })} testId="uw-amort" />
          <UWField label="Term (months)" value={uw.term_months}
            onSave={(v) => patchUW({ term_months: v == null ? null : parseInt(v) })} testId="uw-term" />
        </div>
        <p className="text-[10px] text-[#6B6558] mt-2">
          These are broker-set for lender review — independent from the borrower&apos;s target rate on
          the loan request. DSCR shown to lenders uses these numbers.
        </p>
      </div>

      {/* Periods table */}
      {periods.length === 0 ? (
        <div className="byrd-card p-10 text-center" data-testid="periods-empty">
          <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]">
            <FileText size={22} />
          </div>
          <h3 className="font-serif text-2xl font-bold mt-4">No periods yet.</h3>
          <p className="text-[#6B6558] mt-2 max-w-md mx-auto text-sm">
            Add a period manually or upload a tax return / P&amp;L and let Ada extract the numbers.
          </p>
          <button onClick={() => setAddMode("choose")} className="byrd-btn byrd-btn-dark mt-4">
            <Plus size={14} /> Add First Period
          </button>
        </div>
      ) : (
        <PeriodsGrid
          periods={periods}
          selectedId={selectedId}
          uw={uw}
          savingPid={savingPid}
          onIncome={patchIncomeCell}
          onExpense={patchExpenseCell}
          onSelect={setSelected}
          onDelete={deletePeriod}
          onPatch={patchPeriod}
        />
      )}

      {/* Executive Summary section */}
      {summary.config && (
        <SummarySection
          scen={scen}
          scenarioId={scenarioId}
          summary={summary}
          onPatch={patchSummary}
          onUploadPhoto={uploadPhoto}
          onDeletePhoto={deletePhoto}
          onPreview={generatePreview}
          onSaveToPortal={saveToPortal}
          busy={busy}
          selectedPeriod={periods.find((p) => p.id === selectedId)}
          uwSet={!!uw.rate_pct}
        />
      )}

      {/* Add period modal */}
      {addMode === "choose" && (
        <AddPeriodChooser onClose={() => setAddMode(null)} onManual={() => setAddMode("manual")} onUpload={() => setAddMode("upload")} />
      )}
      {addMode === "manual" && (
        <ManualPeriodModal onCancel={() => setAddMode(null)} onSubmit={addPeriod} />
      )}
      {addMode === "upload" && (
        <UploadParseModal
          scenarioId={scenarioId}
          scen={scen}
          onCancel={() => { setAddMode(null); setProposal(null); }}
          onProposal={(p) => { setProposal(p); }}
          proposal={proposal}
          onAccept={addPeriod}
        />
      )}
    </div>
  );
}

// ---------------- Sub-components ----------------

function UWField({ label, value, step, onSave, testId }) {
  const [v, setV] = useState(value ?? "");
  useEffect(() => { setV(value ?? ""); }, [value]);
  return (
    <div>
      <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</label>
      <input
        type="number"
        step={step || "1"}
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          const num = v === "" ? null : Number(v);
          if (num !== value) onSave(num);
        }}
        className="mt-1 w-full px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
        data-testid={testId}
      />
    </div>
  );
}

function PeriodsGrid({ periods, selectedId, uw, savingPid, onIncome, onExpense, onSelect, onDelete, onPatch }) {
  return (
    <div className="byrd-card overflow-hidden" data-testid="periods-grid">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E4DFD1] bg-[#FBF8F1]">
              <th className="text-left p-3 font-mono text-[10px] uppercase tracking-widest text-[#6B6558] sticky left-0 bg-[#FBF8F1]">Line Item</th>
              {periods.map((p) => (
                <th key={p.id} className="p-3 text-right min-w-[160px]" data-testid={`period-header-${p.id}`}>
                  <div className="flex items-center justify-end gap-1 flex-wrap">
                    <label className="flex items-center gap-1 cursor-pointer">
                      <input
                        type="radio"
                        checked={selectedId === p.id}
                        onChange={() => onSelect(p.id)}
                        className="accent-[#C89434]"
                        data-testid={`period-select-${p.id}`}
                      />
                    </label>
                    <div className="font-serif text-base font-bold">{p.label}</div>
                    {selectedId === p.id && <span className="byrd-chip byrd-chip-gold text-[9px]">SELECTED</span>}
                    {p.is_pro_forma && <span className="byrd-chip text-[9px]">PRO FORMA</span>}
                    <button
                      onClick={() => onDelete(p.id)}
                      className="text-[#8A1F1A] opacity-60 hover:opacity-100 ml-1"
                      title="Delete period"
                      data-testid={`period-delete-${p.id}`}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  <div className="text-[10px] text-[#6B6558] mt-0.5 font-normal">
                    {p.doc_type?.replace(/_/g, " ")}
                    {p.year ? ` · ${p.year}` : ""}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <SectionHeader label="Income" cols={periods.length} />
            {INCOME_ROWS.map((row) => (
              <tr key={row.key} className="border-b border-[#F3EEE0]">
                <td className="p-2 text-[#6B6558] sticky left-0 bg-white">
                  {row.label}
                  {row.note && <span className="text-[10px] ml-1 text-[#8A8578]">{row.note}</span>}
                </td>
                {periods.map((p) => (
                  <td key={p.id} className="p-1 text-right">
                    <NumberCell
                      value={p.income?.[row.key]}
                      onChange={(v) => onIncome(p.id, row.key, v)}
                      testId={`p-${p.id}-inc-${row.key}`}
                    />
                  </td>
                ))}
              </tr>
            ))}
            <tr className="border-b border-[#E4DFD1] bg-[#FBF8F1]">
              <td className="p-2 font-semibold sticky left-0 bg-[#FBF8F1]">Effective Gross Income</td>
              {periods.map((p) => (
                <td key={p.id} className="p-2 text-right font-semibold">
                  {fmtMoney(p._computed?.egi)}
                </td>
              ))}
            </tr>

            <SectionHeader label="Operating Expenses" cols={periods.length} />
            {EXPENSE_ROWS.map((row) => (
              <tr key={row.key} className="border-b border-[#F3EEE0]">
                <td className="p-2 text-[#6B6558] sticky left-0 bg-white">{row.label}</td>
                {periods.map((p) => (
                  <td key={p.id} className="p-1 text-right">
                    <NumberCell
                      value={p.expenses?.[row.key]}
                      onChange={(v) => onExpense(p.id, row.key, v)}
                      testId={`p-${p.id}-exp-${row.key}`}
                    />
                  </td>
                ))}
              </tr>
            ))}
            <tr className="border-b border-[#F3EEE0]">
              <td className="p-2 text-[#6B6558] text-xs sticky left-0 bg-white">Reserves in OpEx?</td>
              {periods.map((p) => (
                <td key={p.id} className="p-2 text-right">
                  <input
                    type="checkbox"
                    checked={p.include_reserves_in_opex !== false}
                    onChange={(e) => onPatch(p.id, { include_reserves_in_opex: e.target.checked })}
                    className="accent-[#C89434]"
                    data-testid={`p-${p.id}-inc-reserves`}
                  />
                </td>
              ))}
            </tr>
            <tr className="border-b border-[#E4DFD1] bg-[#FBF8F1]">
              <td className="p-2 font-semibold sticky left-0 bg-[#FBF8F1]">Total Operating Expenses</td>
              {periods.map((p) => (
                <td key={p.id} className="p-2 text-right font-semibold">
                  {fmtMoney(p._computed?.total_expenses)}
                </td>
              ))}
            </tr>

            {/* Computed footer */}
            <tr className="bg-[#F3EEE0] border-t-2 border-[#C89434]">
              <td className="p-2 font-serif text-base font-bold sticky left-0 bg-[#F3EEE0]">NOI</td>
              {periods.map((p) => (
                <td key={p.id} className="p-2 text-right font-bold text-base" data-testid={`p-${p.id}-noi`}>
                  {fmtMoney(p._computed?.noi)}
                </td>
              ))}
            </tr>
            <tr className="bg-[#F3EEE0]">
              <td className="p-2 text-[#6B6558] sticky left-0 bg-[#F3EEE0]">DSCR<span className="text-[10px] ml-1">(at UW rate)</span></td>
              {periods.map((p) => (
                <td key={p.id} className="p-2 text-right">
                  {computeDSCR(p, uw)}
                </td>
              ))}
            </tr>
            <tr className="bg-[#F3EEE0]">
              <td className="p-2 text-[#6B6558] sticky left-0 bg-[#F3EEE0]">Debt Yield</td>
              {periods.map((p) => (
                <td key={p.id} className="p-2 text-right">
                  {computeDebtYield(p)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {savingPid && <div className="p-2 text-[10px] text-[#6B6558] font-mono">Saving…</div>}
    </div>
  );
}

function SectionHeader({ label, cols }) {
  return (
    <tr className="border-b border-[#E4DFD1]">
      <td colSpan={cols + 1} className="p-2 font-mono text-[10px] uppercase tracking-widest text-[#6B6558] bg-white sticky left-0">
        {label}
      </td>
    </tr>
  );
}

function computeDSCR(period, uw) {
  // Attempt local DSCR — needs loan amount from parent. Skip for row (parent-level shown separately).
  // Here we just show a placeholder that uses NOI + parent uw. We need loan amount too, but we don't have it here.
  // Show "—" if uw incomplete; actual comparison is in deal metrics.
  if (!period._computed?.noi || !uw?.rate_pct || !uw?.amort_months) return <span className="text-[#8A8578]">—</span>;
  // We'd need loan_amount here to compute DSCR. Since we don't, show NOI-based ratio hint only.
  return <span className="text-[#8A8578]">—</span>;
}

function computeDebtYield(period) {
  // Same — needs loan amount; skip
  return <span className="text-[#8A8578]">—</span>;
}

// ---- Add Period Modals ----

function AddPeriodChooser({ onClose, onManual, onUpload }) {
  return (
    <Modal onClose={onClose} testId="add-period-chooser">
      <div className="font-serif text-2xl font-bold mb-2">Add a period</div>
      <p className="text-sm text-[#6B6558] mb-5">Two ways to add data — pick whichever fits.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <button onClick={onUpload} className="border border-[#E4DFD1] rounded-md p-5 text-left hover:border-[#C89434] hover:bg-[#FBF8F1] transition" data-testid="add-mode-upload">
          <div className="flex items-center gap-2 mb-2 text-[#C89434]">
            <Sparkles size={16} /> <span className="font-mono text-[10px] uppercase tracking-widest">// Ada</span>
          </div>
          <div className="font-serif text-lg font-bold">Upload &amp; auto-parse</div>
          <div className="text-sm text-[#6B6558] mt-1">Drop a tax return or P&amp;L. Ada extracts each line item, adds back depreciation &amp; interest, and shows you the result before saving.</div>
        </button>
        <button onClick={onManual} className="border border-[#E4DFD1] rounded-md p-5 text-left hover:border-[#C89434] hover:bg-[#FBF8F1] transition" data-testid="add-mode-manual">
          <div className="flex items-center gap-2 mb-2 text-[#6B6558]">
            <FileText size={16} /> <span className="font-mono text-[10px] uppercase tracking-widest">// Manual</span>
          </div>
          <div className="font-serif text-lg font-bold">Enter numbers directly</div>
          <div className="text-sm text-[#6B6558] mt-1">Create an empty column and type the figures. Good for pro forma or when you already have the numbers.</div>
        </button>
      </div>
    </Modal>
  );
}

function ManualPeriodModal({ onCancel, onSubmit }) {
  const [form, setForm] = useState({
    label: "", doc_type: "manual", year: null, is_pro_forma: false, include_reserves_in_opex: true,
  });
  const submit = () => {
    if (!form.label.trim()) { toast.error("Label required"); return; }
    onSubmit({ ...form, income: {}, expenses: {} });
  };
  return (
    <Modal onClose={onCancel} testId="manual-period-modal">
      <div className="font-serif text-2xl font-bold mb-4">New period</div>
      <div className="space-y-3">
        <div>
          <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Label</label>
          <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })}
            placeholder="e.g., 2024 Tax Return, Year 1 Pro Forma"
            className="mt-1 w-full px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]" data-testid="new-period-label" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Doc Type</label>
            <select value={form.doc_type} onChange={(e) => setForm({ ...form, doc_type: e.target.value })}
              className="mt-1 w-full px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]">
              <option value="manual">Manual</option>
              <option value="tax_return">Tax Return</option>
              <option value="p_and_l">P&amp;L</option>
              <option value="pro_forma">Pro Forma</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Year</label>
            <input type="number" value={form.year ?? ""} onChange={(e) => setForm({ ...form, year: e.target.value ? Number(e.target.value) : null })}
              className="mt-1 w-full px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]" />
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.is_pro_forma} onChange={(e) => setForm({ ...form, is_pro_forma: e.target.checked })} className="accent-[#C89434]" />
          Mark as pro forma / projected
        </label>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <button onClick={onCancel} className="byrd-btn byrd-btn-outline">Cancel</button>
        <button onClick={submit} className="byrd-btn byrd-btn-dark" data-testid="create-period-confirm">Create</button>
      </div>
    </Modal>
  );
}

function UploadParseModal({ scenarioId, scen, onCancel, onProposal, proposal, onAccept }) {
  const [file, setFile] = useState(null);
  const [docType, setDocType] = useState("tax_return");
  const [parsing, setParsing] = useState(false);
  const [uploadedFileId, setUploadedFileId] = useState(null);

  const upload = async () => {
    if (!file) return;
    setParsing(true);
    try {
      const b64 = await fileToB64(file);
      // Upload as a "temporary" client doc line + file OR reuse an existing "Property Financial Statements" doc?
      // Simpler: use a scenario-scoped intake — reuse /admin/scenarios/{sid}/docs to create a doc line labeled "Financial Source Doc",
      // then upload against it, then parse. But that clutters the checklist.
      // Cleanest: post directly to a scratch endpoint. We don't have one — use the doc line path.
      const label = `${docType === "tax_return" ? "Tax Return" : "P&L"} — ${file.name}`;
      const created = await api.post(`/admin/scenarios/${scenarioId}/docs`, {
        label, category: "Financials", required: false,
      });
      const doc = created.data;
      const up = await api.post(`/admin/scenarios/${scenarioId}/docs/${doc.id}/upload`, {
        filename: file.name, content_type: file.type || "application/pdf", data_b64: b64,
      });
      const fid = up.data.file_id || up.data.file?.file_id || up.data.id;
      setUploadedFileId(fid);
      // Parse
      const r = await api.post(`/admin/scenarios/${scenarioId}/financials/parse-doc`, {
        file_id: fid, doc_type: docType,
      });
      onProposal(r.data.proposal);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Parse failed");
    } finally {
      setParsing(false);
    }
  };

  const accept = () => {
    if (!proposal) return;
    onAccept(proposal);
  };

  return (
    <Modal onClose={onCancel} testId="upload-parse-modal">
      <div className="font-serif text-2xl font-bold mb-1">Upload &amp; parse with Ada</div>
      <p className="text-sm text-[#6B6558] mb-4">Drop a tax return or P&amp;L. Ada strips depreciation &amp; interest expense so the NOI reflects true operating cash flow.</p>

      {!proposal ? (
        <>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Doc Type</label>
              <select value={docType} onChange={(e) => setDocType(e.target.value)}
                className="mt-1 w-full px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]">
                <option value="tax_return">Tax Return</option>
                <option value="p_and_l">P&amp;L / Operating Statement</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">File (PDF)</label>
              <input type="file" accept=".pdf,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="mt-1 w-full text-sm" data-testid="parse-file-input" />
            </div>
          </div>
          <div className="text-[11px] text-[#6B6558] mb-3">
            The document also gets attached to the scenario&apos;s document checklist under &quot;Financials&quot; so lenders/borrower can see the source.
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={onCancel} className="byrd-btn byrd-btn-outline">Cancel</button>
            <button onClick={upload} disabled={!file || parsing} className="byrd-btn byrd-btn-dark" data-testid="parse-start">
              {parsing ? "Ada is reading…" : (<><Sparkles size={14} /> Parse with Ada</>)}
            </button>
          </div>
        </>
      ) : (
        <ProposalReview proposal={proposal} onEdit={(next) => onProposal(next)} onAccept={accept} onCancel={onCancel} />
      )}
    </Modal>
  );
}

function ProposalReview({ proposal, onEdit, onAccept, onCancel }) {
  const [p, setP] = useState(proposal);
  useEffect(() => { setP(proposal); }, [proposal]);

  const setIncome = (k, v) => setP({ ...p, income: { ...(p.income || {}), [k]: v } });
  const setExp = (k, v) => setP({ ...p, expenses: { ...(p.expenses || {}), [k]: v } });

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <div className="byrd-chip byrd-chip-gold">Ada&apos;s draft — review before saving</div>
        {p.confidence && <div className="text-[10px] text-[#6B6558] font-mono">Confidence: {p.confidence}</div>}
      </div>
      {p.notes && (
        <div className="p-2 text-xs bg-[#FBEFD3] border-l-2 border-[#E5B968] mb-3">
          <b>Adjustments:</b> {p.notes}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Label</label>
          <input value={p.label || ""} onChange={(e) => setP({ ...p, label: e.target.value })}
            className="mt-1 w-full px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]" />
        </div>
        <div>
          <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Year</label>
          <input type="number" value={p.year ?? ""} onChange={(e) => setP({ ...p, year: e.target.value ? Number(e.target.value) : null })}
            className="mt-1 w-full px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]" />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[50vh] overflow-y-auto">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] mb-2">Income</div>
          {INCOME_ROWS.map((r) => (
            <ProposalRow key={r.key} label={r.label} value={p.income?.[r.key]}
              onChange={(v) => setIncome(r.key, v)} />
          ))}
        </div>
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] mb-2">Expenses</div>
          {EXPENSE_ROWS.map((r) => (
            <ProposalRow key={r.key} label={r.label} value={p.expenses?.[r.key]}
              onChange={(v) => setExp(r.key, v)} />
          ))}
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onCancel} className="byrd-btn byrd-btn-outline">Cancel</button>
        <button onClick={() => onEdit(p)} className="byrd-btn byrd-btn-outline">Refresh</button>
        <button onClick={() => onAccept()} className="byrd-btn byrd-btn-dark" data-testid="proposal-accept">
          <Plus size={14} /> Save Period
        </button>
      </div>
    </div>
  );
}

function ProposalRow({ label, value, onChange }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <div className="flex-1 text-xs text-[#6B6558]">{label}</div>
      <input type="number" step="0.01" value={value == null ? "" : value}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-32 px-2 py-1 border border-[#E4DFD1] rounded text-right text-sm focus:outline-none focus:border-[#C89434]" />
    </div>
  );
}

// ---------------- Executive Summary section ----------------

function SummarySection({ scen, scenarioId, summary, onPatch, onUploadPhoto, onDeletePhoto, onPreview, onSaveToPortal, busy, selectedPeriod, uwSet }) {
  const cfg = summary.config || {};
  const photos = summary.photos || [];
  const canGenerate = !!selectedPeriod && uwSet;

  return (
    <div className="byrd-card p-6 space-y-5" data-testid="summary-section">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Loan Executive Summary</div>
          <h3 className="font-serif text-2xl font-bold">Generate the 1-2 page lender-facing summary</h3>
          <p className="text-xs text-[#6B6558] mt-1 max-w-2xl">
            Combines the selected financial period, sponsor snapshot, up to 4 property photos, a Google/OSM-based location map, and Census demographics.
          </p>
        </div>
      </div>

      {!canGenerate && (
        <div className="p-3 bg-[#FBEFD3] border border-[#E5B968] rounded-md text-sm text-[#7A5410]">
          <b>Not ready:</b> {!selectedPeriod && "Select a financial period. "}
          {!uwSet && "Set the underwriting rate & amortization above."}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Narrative */}
        <div>
          <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Deal Narrative <span className="text-[#8A8578] normal-case">— override for the Executive Summary</span></label>
          <NarrativeBox
            value={cfg.narrative || ""}
            businessPlan={scen?.business_plan || ""}
            onSave={(v) => onPatch({ narrative: v })}
          />
          <div className="mt-3 space-y-1 text-sm">
            <ToggleRow label="Include property photos" checked={cfg.include_photos !== false} onChange={(v) => onPatch({ include_photos: v })} />
            <ToggleRow label="Include location map" checked={cfg.include_map !== false} onChange={(v) => onPatch({ include_map: v })} />
            <ToggleRow label="Include Census demographics" checked={cfg.include_census !== false} onChange={(v) => onPatch({ include_census: v })} />
            <ToggleRow label="Include sponsor snapshot" checked={cfg.include_sponsor_snapshot !== false} onChange={(v) => onPatch({ include_sponsor_snapshot: v })} />
          </div>
        </div>

        {/* Photos */}
        <div>
          <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Property Photos <span className="text-[#8A8578]">(up to 4)</span></label>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {photos.map((p) => (
              <div key={p.id} className="relative group border border-[#E4DFD1] rounded-md overflow-hidden aspect-video bg-[#FBF8F1]">
                <img src={`${api.defaults.baseURL}/admin/scenarios/${scenarioId}/summary/photos/${p.id}`}
                  alt={p.filename} className="w-full h-full object-cover" />
                <button onClick={() => onDeletePhoto(p.id)}
                  className="absolute top-1 right-1 bg-white/90 hover:bg-white text-[#8A1F1A] rounded p-1 opacity-0 group-hover:opacity-100 transition"
                  title="Remove photo" data-testid={`photo-delete-${p.id}`}>
                  <X size={12} />
                </button>
              </div>
            ))}
            {photos.length < 4 && (
              <label className="border-2 border-dashed border-[#E4DFD1] rounded-md aspect-video grid place-items-center cursor-pointer hover:border-[#C89434] hover:bg-[#FBF8F1] transition">
                <div className="text-center text-[#6B6558]">
                  <ImageIcon size={20} className="mx-auto mb-1" />
                  <div className="text-xs">Add photo</div>
                </div>
                <input type="file" accept="image/*" className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) onUploadPhoto(f); e.target.value = ""; }}
                  data-testid="photo-upload-input" />
              </label>
            )}
          </div>
        </div>
      </div>

      <div className="pt-4 border-t border-[#E4DFD1] flex flex-wrap gap-2 justify-end">
        <button onClick={onPreview} disabled={!canGenerate || busy}
          className="byrd-btn byrd-btn-outline" data-testid="summary-preview">
          <Download size={14} /> Preview PDF
        </button>
        <button onClick={onSaveToPortal} disabled={!canGenerate || busy}
          className="byrd-btn byrd-btn-dark" data-testid="summary-save-portal">
          <Save size={14} /> Save to Document Portal
        </button>
      </div>
    </div>
  );
}

function NarrativeBox({ value, businessPlan, onSave }) {
  const [v, setV] = useState(value);
  useEffect(() => { setV(value); }, [value]);
  const isEmpty = !v || !v.trim();
  const bpTrimmed = (businessPlan || "").trim();
  const copyFromBP = () => {
    setV(bpTrimmed);
    onSave(bpTrimmed);
  };
  return (
    <div>
      <textarea
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => { if (v !== value) onSave(v); }}
        placeholder={
          bpTrimmed
            ? `Leave blank to use the Business Plan from the Package tab, or type a shorter version here for the 1-pager.`
            : `Value-add multifamily acquisition in the Third Ward submarket. In-place cash flowing at 92% occupancy with room to push rents post-renovation...`
        }
        className="mt-1 w-full h-40 px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434] resize-y"
        data-testid="summary-narrative"
      />
      {isEmpty && bpTrimmed && (
        <div className="mt-1 flex items-start justify-between gap-3 text-[11px] p-2 rounded-md bg-[#FBEFD3] border border-[#E5B968]">
          <div className="text-[#7A5410]">
            <b>Using Business Plan from Package tab:</b><br />
            <span className="italic">{bpTrimmed.length > 140 ? bpTrimmed.slice(0, 140) + "…" : bpTrimmed}</span>
          </div>
          <button onClick={copyFromBP} className="shrink-0 text-[#7A5410] underline hover:no-underline" data-testid="narrative-copy-bp">
            Edit here
          </button>
        </div>
      )}
      {isEmpty && !bpTrimmed && (
        <div className="mt-1 text-[11px] text-[#6B6558]">Empty. The Deal Narrative section will be omitted from the PDF.</div>
      )}
    </div>
  );
}

function ToggleRow({ label, checked, onChange }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-[#C89434]" />
      {label}
    </label>
  );
}

function Modal({ children, onClose, testId }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 grid place-items-center p-4" data-testid={testId}>
      <div className="bg-white rounded-md border border-[#E4DFD1] w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto relative">
        <button onClick={onClose} className="absolute top-3 right-3 text-[#6B6558] hover:text-[#1A1A1A]" data-testid="modal-close">
          <X size={16} />
        </button>
        {children}
      </div>
    </div>
  );
}

async function fileToB64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const s = reader.result || "";
      const comma = s.indexOf(",");
      resolve(comma >= 0 ? s.slice(comma + 1) : s);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
