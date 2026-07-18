import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  fmtMoney, fmtPct, scenarioStatusChip,
} from "@/byrd/dealData";
import { FileText, Plus, ExternalLink } from "lucide-react";

export default function AdminScenarios() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  const load = () => api.get("/admin/scenarios").then((r) => setRows(r.data)).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const create = async () => {
    try {
      const res = await api.post("/admin/scenarios", { name: "Untitled Scenario" });
      toast.success("Scenario created");
      nav(`/admin/scenarios/${res.data.id}`);
    } catch (e) {
      toast.error("Failed");
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-scenarios">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Deal Engine</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Loan Scenarios.</h1>
        </div>
        <button onClick={create} className="byrd-btn byrd-btn-dark" data-testid="new-scenario-btn">
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
          <button onClick={create} className="byrd-btn byrd-btn-primary mt-5">
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
    </div>
  );
}
