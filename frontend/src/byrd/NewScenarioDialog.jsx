import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { LOAN_TYPES } from "@/byrd/dealData";
import { X, Plus, FileText, Check } from "lucide-react";

/**
 * Shared "New Scenario" dialog.
 * Props:
 *   - clientId?: string  (pre-selects client, hides the client picker if provided)
 *   - clients?: array    (only used when clientId is not provided)
 *   - onClose(): void
 *   - onCreated(scenarioId): void
 */
export default function NewScenarioDialog({ clientId, clients, onClose, onCreated }) {
  const [templates, setTemplates] = useState([]);
  const [form, setForm] = useState({
    name: "",
    client_id: clientId || "",
    loan_type: "",
    doc_template: "purchase",
  });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    api.get("/admin/scenarios/doc-templates").then((r) => setTemplates(r.data)).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    const payload = {
      name: (form.name || "").trim() || "Untitled Scenario",
      doc_template: form.doc_template || "purchase",
    };
    if (form.client_id) payload.client_id = form.client_id;
    if (form.loan_type) payload.loan_request = { loan_type: form.loan_type };
    try {
      const res = await api.post("/admin/scenarios", payload);
      toast.success("Scenario created");
      onCreated(res.data.id);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={onClose}
      role="dialog"
      data-testid="new-scenario-dialog"
    >
      <div
        className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-lg max-h-[92vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-[#E4DFD1] flex items-start justify-between gap-2">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// New Scenario</div>
            <h2 className="font-serif text-2xl font-bold mt-1">Start a Deal</h2>
          </div>
          <button
            onClick={onClose}
            className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]"
            data-testid="new-scenario-close"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4 overflow-y-auto">
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">
              Scenario Name
            </label>
            <input
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. Hotel Purchase — Miami or 12-Unit MF Refi — Sugar Land"
              data-testid="new-scen-name"
              className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
            />
            <div className="text-[11px] text-[#6B6558] mt-1">
              You can rename it later. Leave blank to name it &quot;Untitled Scenario&quot;.
            </div>
          </div>

          {!clientId && (
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">
                Link to Client <span className="normal-case text-[#6B6558]">(optional)</span>
              </label>
              <select
                value={form.client_id}
                onChange={(e) => set("client_id", e.target.value)}
                data-testid="new-scen-client"
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
              >
                <option value="">Standalone (no client)</option>
                {(clients || []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} — {c.email}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">
              Loan Type <span className="normal-case text-[#6B6558]">(optional)</span>
            </label>
            <select
              value={form.loan_type}
              onChange={(e) => set("loan_type", e.target.value)}
              data-testid="new-scen-loan-type"
              className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
            >
              <option value="">Pick later</option>
              {LOAN_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">
              Document Checklist
            </label>
            <div className="mt-2 grid grid-cols-1 gap-2">
              {templates.map((t) => {
                const active = form.doc_template === t.key;
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => set("doc_template", t.key)}
                    data-testid={`template-${t.key}`}
                    className={`text-left rounded-md border px-3 py-2.5 transition-colors ${
                      active
                        ? "border-[#C89434] bg-[#FBEFD3]/50 ring-1 ring-[#C89434]"
                        : "border-[#E4DFD1] hover:bg-[#FBF8F1]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-semibold text-sm inline-flex items-center gap-1.5">
                          <FileText size={12} className={active ? "text-[#C89434]" : "text-[#6B6558]"} />
                          {t.label}
                        </div>
                        <div className="text-[11px] text-[#6B6558] mt-0.5">{t.description}</div>
                      </div>
                      <div className="flex items-center gap-2 text-[11px] font-mono text-[#6B6558]">
                        {t.item_count} {t.item_count === 1 ? "line" : "lines"}
                        {active && <Check size={13} className="text-[#C89434]" />}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2 sticky bottom-0 bg-white pb-1">
            <button
              type="button"
              onClick={onClose}
              className="byrd-btn byrd-btn-outline flex-1"
              data-testid="new-scen-cancel"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="byrd-btn byrd-btn-dark flex-1"
              data-testid="new-scen-submit"
            >
              {busy ? "Creating…" : <>Create Scenario <Plus size={14} /></>}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
