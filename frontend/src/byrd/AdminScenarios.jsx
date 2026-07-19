import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  fmtMoney, fmtPct, scenarioStatusChip, LOAN_TYPES,
} from "@/byrd/dealData";
import { FileText, Plus, X } from "lucide-react";

export default function AdminScenarios() {
  const [rows, setRows] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(false);
  const nav = useNavigate();

  const load = () => api.get("/admin/scenarios").then((r) => setRows(r.data)).finally(() => setLoading(false));
  useEffect(() => {
    load();
    api.get("/admin/clients").then((r) => setClients(r.data));
  }, []);

  const openDialog = () => setDialog(true);
  const closeDialog = () => setDialog(false);

  const create = async (payload) => {
    try {
      const res = await api.post("/admin/scenarios", payload);
      toast.success("Scenario created");
      nav(`/admin/scenarios/${res.data.id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-scenarios">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Deal Engine</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Loan Scenarios.</h1>
        </div>
        <button onClick={openDialog} className="byrd-btn byrd-btn-dark" data-testid="new-scenario-btn">
          <Plus size={14} /> New Scenario
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-[#6B6558]">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="byrd-card p-10 text-center">
          <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]">
            <FileText size={22} />
          </div>
          <h3 className="font-serif text-2xl font-bold mt-4">No scenarios yet.</h3>
          <p className="text-[#6B6558] mt-2 max-w-md mx-auto">
            Build a loan scenario to shop to lenders. Attach documents, generate a branded PDF, and share a
            watermarked link.
          </p>
          <button onClick={openDialog} className="byrd-btn byrd-btn-primary mt-5">
            Create First Scenario <Plus size={14} />
          </button>
        </div>
      ) : (
        <div className="byrd-card overflow-hidden">
          <div className="hidden md:grid grid-cols-[1.8fr_1fr_1fr_.9fr_.9fr_.8fr_.7fr] border-b border-[#E4DFD1] bg-[#FBF8F1]">
            {["Scenario", "Property", "Client", "Loan", "LTV/DSCR", "Status", "Shares"].map((h) => (
              <div key={h} className="px-4 py-3 text-[11px] uppercase font-mono tracking-widest text-[#6B6558]">{h}</div>
            ))}
          </div>
          {rows.map((s) => {
            const stat = scenarioStatusChip(s.status);
            return (
              <Link
                key={s.id}
                to={`/admin/scenarios/${s.id}`}
                data-testid={`scenario-row-${s.id}`}
                className="grid grid-cols-1 md:grid-cols-[1.8fr_1fr_1fr_.9fr_.9fr_.8fr_.7fr] border-b border-[#E4DFD1] last:border-b-0 hover:bg-[#FBF8F1]"
              >
                <div className="px-4 py-4">
                  <div className="font-semibold">{s.name}</div>
                  <div className="text-xs text-[#6B6558]">{s.loan_request?.loan_type || "—"}</div>
                </div>
                <div className="px-4 py-4 text-sm">
                  {s.property_info?.city ? `${s.property_info.city}, ${s.property_info.state || ""}` : "—"}
                  <div className="text-xs text-[#6B6558]">{s.property_info?.property_type || "—"}</div>
                </div>
                <div className="px-4 py-4 text-sm">
                  {s.client ? <span>{s.client.name}</span> : <span className="text-[#6B6558] italic">standalone</span>}
                </div>
                <div className="px-4 py-4 font-mono text-sm">{fmtMoney(s.loan_request?.loan_amount)}</div>
                <div className="px-4 py-4 font-mono text-sm">
                  {fmtPct(s.metrics?.ltv_pct, 1)} / {s.metrics?.dscr ?? "—"}
                </div>
                <div className="px-4 py-4"><span className={stat.chip}>{stat.label}</span></div>
                <div className="px-4 py-4 font-mono text-sm">{s.share_count || 0}</div>
              </Link>
            );
          })}
        </div>
      )}

      {dialog && (
        <NewScenarioDialog
          clients={clients}
          onClose={closeDialog}
          onCreate={create}
        />
      )}
    </div>
  );
}

function NewScenarioDialog({ clients, onClose, onCreate }) {
  const [form, setForm] = useState({
    name: "",
    client_id: "",
    loan_type: "",
  });
  const [busy, setBusy] = useState(false);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    const payload = {
      name: (form.name || "").trim() || "Untitled Scenario",
    };
    if (form.client_id) payload.client_id = form.client_id;
    if (form.loan_type) payload.loan_request = { loan_type: form.loan_type };
    await onCreate(payload);
    setBusy(false);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={onClose}
      role="dialog"
      data-testid="new-scenario-dialog"
    >
      <div
        className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-md"
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

        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">
              Scenario Name
            </label>
            <input
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="e.g. 12-Unit MF Refi — Sugar Land"
              data-testid="new-scen-name"
              className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
            />
            <div className="text-[11px] text-[#6B6558] mt-1">
              You can rename it later. Leave blank to name it &quot;Untitled Scenario&quot;.
            </div>
          </div>

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
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} — {c.email}
                </option>
              ))}
            </select>
            <div className="text-[11px] text-[#6B6558] mt-1">
              Linking a client makes their uploaded documents available to attach in the Documents tab.
            </div>
          </div>

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

          <div className="flex items-center gap-2 pt-2">
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
