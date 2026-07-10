import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { SectionHeader, Chip, fmtMoney, fmtNum } from "@/components/Brutal";
import { Plus, Play, Pause, Trash2 } from "lucide-react";
import { toast } from "sonner";

export default function Campaigns() {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  const load = () => api.get("/campaigns").then((r) => setList(r.data)).finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  const toggle = async (c) => {
    const next = c.status === "active" ? "paused" : "active";
    await api.patch(`/campaigns/${c.id}`, { status: next });
    toast.success(`Campaign ${next}`);
    load();
  };

  const remove = async (c) => {
    if (!window.confirm(`Delete "${c.name}"? This can't be undone.`)) return;
    await api.delete(`/campaigns/${c.id}`);
    toast.success("Campaign deleted");
    load();
  };

  return (
    <div className="space-y-6" data-testid="campaigns-page">
      <SectionHeader
        eyebrow="campaigns"
        title="All Campaigns."
        action={
          <button
            onClick={() => nav("/campaigns/new")}
            data-testid="campaigns-new-btn"
            className="h-11 px-4 bg-black text-white font-mono uppercase text-xs hard-shadow-sm press-effect flex items-center gap-2"
          >
            <Plus size={14} /> New Campaign
          </button>
        }
      />

      <div className="border-2 border-black bg-white">
        <div className="grid grid-cols-[1.6fr_.7fr_.7fr_.9fr_.9fr_.9fr_.9fr_1fr] border-b-2 border-black font-mono text-[10px] uppercase text-[#555]">
          {["Name", "Status", "Objective", "Budget/day", "Impressions", "Clicks", "Spend", "Actions"].map((h) => (
            <div key={h} className="p-3 border-r border-[#E5E5E5] last:border-r-0">{h}</div>
          ))}
        </div>
        {loading ? (
          <div className="p-6 font-mono text-sm">loading…</div>
        ) : list.length === 0 ? (
          <div className="p-8 text-center">
            <div className="font-mono text-xs uppercase text-[#555]">// empty</div>
            <p className="mt-2">No campaigns yet.</p>
            <button
              onClick={() => nav("/campaigns/new")}
              className="mt-4 h-10 px-4 bg-[#002FA7] text-white font-mono uppercase text-xs hard-shadow-sm press-effect"
              data-testid="campaigns-empty-new"
            >
              Create your first campaign
            </button>
          </div>
        ) : (
          list.map((c) => (
            <div
              key={c.id}
              data-testid={`campaign-row-${c.id}`}
              className="grid grid-cols-[1.6fr_.7fr_.7fr_.9fr_.9fr_.9fr_.9fr_1fr] border-b border-[#E5E5E5] last:border-b-0 hover:bg-[#F4F4F0] transition-colors"
            >
              <div className="p-3 min-w-0">
                <button
                  onClick={() => nav(`/campaigns/${c.id}`)}
                  className="text-left font-semibold hover:underline underline-offset-4 truncate block w-full"
                  data-testid={`campaign-name-${c.id}`}
                >
                  {c.name}
                </button>
                <div className="font-mono text-[11px] text-[#555] mt-0.5 truncate">
                  {c.target_locations?.[0] || "US"} · {c.keywords?.length || 0} keywords
                </div>
              </div>
              <div className="p-3">
                <Chip color={c.status === "active" ? "green" : c.status === "paused" ? "yellow" : "ghost"}>
                  {c.status}
                </Chip>
              </div>
              <div className="p-3 font-mono text-sm capitalize">{c.objective.replace("_", " ")}</div>
              <div className="p-3 font-mono text-sm">{fmtMoney(c.daily_budget)}</div>
              <div className="p-3 font-mono text-sm">{fmtNum(c.metrics.impressions)}</div>
              <div className="p-3 font-mono text-sm">{fmtNum(c.metrics.clicks)}</div>
              <div className="p-3 font-mono text-sm">{fmtMoney(c.metrics.cost)}</div>
              <div className="p-3 flex items-center gap-2">
                <button
                  onClick={() => toggle(c)}
                  data-testid={`toggle-${c.id}`}
                  className="w-8 h-8 border-2 border-black grid place-items-center hover:bg-black hover:text-white transition-colors"
                  title={c.status === "active" ? "Pause" : "Enable"}
                >
                  {c.status === "active" ? <Pause size={12} /> : <Play size={12} />}
                </button>
                <button
                  onClick={() => remove(c)}
                  data-testid={`delete-${c.id}`}
                  className="w-8 h-8 border-2 border-black grid place-items-center hover:bg-[#FF3B30] hover:text-white transition-colors"
                  title="Delete"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
