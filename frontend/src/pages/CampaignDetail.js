import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Metric, SectionHeader, Chip, fmtMoney, fmtNum } from "@/components/Brutal";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, BarChart, Bar } from "recharts";
import { Play, Pause, Trash2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

export default function CampaignDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [c, setC] = useState(null);

  const load = () => api.get(`/campaigns/${id}`).then((r) => setC(r.data));

  useEffect(() => { load(); }, [id]);

  if (!c) return <div className="font-mono text-sm">loading…</div>;

  const toggle = async () => {
    const next = c.status === "active" ? "paused" : "active";
    await api.patch(`/campaigns/${id}`, { status: next });
    toast.success(`Campaign ${next}`);
    load();
  };

  const remove = async () => {
    if (!window.confirm("Delete this campaign?")) return;
    await api.delete(`/campaigns/${id}`);
    toast.success("Deleted");
    nav("/adscopilot/campaigns");
  };

  return (
    <div className="space-y-6" data-testid="campaign-detail-page">
      <button
        onClick={() => nav(-1)}
        className="font-mono text-xs uppercase flex items-center gap-2 hover:underline"
        data-testid="back-btn"
      >
        <ArrowLeft size={14} /> Back
      </button>

      <SectionHeader
        eyebrow={`campaign · ${c.objective}`}
        title={c.name}
        action={
          <div className="flex items-center gap-2">
            <Chip color={c.status === "active" ? "green" : c.status === "paused" ? "yellow" : "ghost"}>
              {c.status}
            </Chip>
            <button
              onClick={toggle}
              data-testid="detail-toggle"
              className="h-10 px-3 border-2 border-black font-mono uppercase text-xs flex items-center gap-2 hover:bg-black hover:text-white transition-colors"
            >
              {c.status === "active" ? <><Pause size={12} /> Pause</> : <><Play size={12} /> Enable</>}
            </button>
            <button
              onClick={remove}
              data-testid="detail-delete"
              className="h-10 px-3 border-2 border-black font-mono uppercase text-xs flex items-center gap-2 hover:bg-[#FF3B30] hover:text-white transition-colors"
            >
              <Trash2 size={12} /> Delete
            </button>
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <Metric label="Impressions" value={fmtNum(c.metrics.impressions)} />
        <Metric label="Clicks" value={fmtNum(c.metrics.clicks)} />
        <Metric label="Spend" value={fmtMoney(c.metrics.cost)} />
        <Metric label="CTR" value={c.metrics.ctr} unit="%" />
        <Metric label="CPC" value={fmtMoney(c.metrics.cpc)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 border-2 border-black bg-white p-6">
          <div className="font-mono text-[11px] uppercase text-[#555] mb-1">// performance / 30d</div>
          <h3 className="font-display text-2xl font-bold tracking-tight mb-4">Trend</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={c.performance}>
                <CartesianGrid stroke="#E5E5E5" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} stroke="#111" />
                <YAxis stroke="#111" />
                <Tooltip />
                <Line type="monotone" dataKey="clicks" stroke="#002FA7" strokeWidth={2.5} dot={false} />
                <Line type="monotone" dataKey="conversions" stroke="#00C853" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="border-2 border-black bg-white p-6">
          <div className="font-mono text-[11px] uppercase text-[#555] mb-1">// daily spend</div>
          <h3 className="font-display text-2xl font-bold tracking-tight mb-4">Cost</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={c.performance.slice(-14)}>
                <CartesianGrid stroke="#E5E5E5" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} stroke="#111" />
                <YAxis stroke="#111" />
                <Tooltip />
                <Bar dataKey="cost" fill="#111" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="border-2 border-black bg-white p-6">
          <div className="font-mono text-[11px] uppercase text-[#555] mb-2">// ad copy — headlines</div>
          <ul className="space-y-2">
            {c.headlines?.length ? c.headlines.map((h, i) => (
              <li key={i} className="border-2 border-black p-2 font-mono text-sm flex justify-between">
                <span>{h}</span>
                <span className="text-[#555]">{h.length}c</span>
              </li>
            )) : <li className="font-mono text-xs text-[#555]">// none</li>}
          </ul>
        </div>
        <div className="border-2 border-black bg-white p-6">
          <div className="font-mono text-[11px] uppercase text-[#555] mb-2">// ad copy — descriptions</div>
          <ul className="space-y-2">
            {c.descriptions?.length ? c.descriptions.map((d, i) => (
              <li key={i} className="border-2 border-black p-2 font-mono text-sm flex justify-between gap-4">
                <span className="flex-1">{d}</span>
                <span className="text-[#555] shrink-0">{d.length}c</span>
              </li>
            )) : <li className="font-mono text-xs text-[#555]">// none</li>}
          </ul>
        </div>
      </div>

      <div className="border-2 border-black bg-white p-6">
        <div className="font-mono text-[11px] uppercase text-[#555] mb-2">// keywords</div>
        <div className="flex flex-wrap gap-2">
          {c.keywords?.length ? c.keywords.map((k) => (
            <span key={k} className="border-2 border-black px-2 py-1 font-mono text-xs bg-[#F4F4F0]">{k}</span>
          )) : <span className="font-mono text-xs text-[#555]">// none</span>}
        </div>
      </div>
    </div>
  );
}
