import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Metric, SectionHeader, Chip, fmtMoney, fmtNum } from "@/components/Brutal";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { ArrowRight, Plus } from "lucide-react";

export default function Overview() {
  const [data, setData] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.get("/analytics/overview").then((r) => setData(r.data));
  }, []);

  if (!data) {
    return <div className="font-mono text-sm">loading…</div>;
  }

  const empty = data.campaigns.length === 0;

  return (
    <div className="space-y-8" data-testid="overview-page">
      <SectionHeader
        eyebrow="dashboard / overview"
        title="Command Center."
        action={
          <button
            onClick={() => nav("/adscopilot/campaigns/new")}
            data-testid="overview-new-campaign"
            className="h-11 px-4 bg-black text-white font-mono uppercase text-xs hard-shadow-sm press-effect flex items-center gap-2"
          >
            <Plus size={14} /> New Campaign
          </button>
        }
      />

      {empty ? (
        <div className="border-2 border-black bg-white p-10 text-center">
          <div className="font-mono text-xs uppercase text-[#555]">// no campaigns yet</div>
          <h3 className="font-display text-3xl font-bold tracking-tight mt-3">
            Spin up your first campaign.
          </h3>
          <p className="text-sm mt-2 max-w-md mx-auto text-[#555]">
            Draft targeting, keywords and ad copy in minutes. AdsCopilot fills in the boring parts.
          </p>
          <button
            onClick={() => nav("/adscopilot/campaigns/new")}
            data-testid="empty-new-campaign-btn"
            className="mt-6 h-11 px-4 bg-[#002FA7] text-white font-mono uppercase text-xs hard-shadow press-effect inline-flex items-center gap-2"
          >
            Create Campaign <ArrowRight size={14} />
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Metric label="Impressions" value={fmtNum(data.summary.impressions)} testId="metric-impressions" />
            <Metric label="Clicks" value={fmtNum(data.summary.clicks)} testId="metric-clicks" />
            <Metric label="Spend" value={fmtMoney(data.summary.cost)} testId="metric-spend" />
            <Metric label="Conversions" value={fmtNum(data.summary.conversions)} testId="metric-conversions" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 border-2 border-black bg-white p-6">
              <div className="flex items-baseline justify-between mb-4">
                <div>
                  <div className="font-mono text-[11px] uppercase text-[#555]">// performance / 30d</div>
                  <h3 className="font-display text-2xl font-bold tracking-tight">Clicks & Spend</h3>
                </div>
                <div className="font-mono text-xs">
                  CTR <span className="font-bold">{data.summary.ctr}%</span> · CPC{" "}
                  <span className="font-bold">{fmtMoney(data.summary.cpc)}</span>
                </div>
              </div>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.daily} margin={{ left: 0, right: 8, top: 8, bottom: 8 }}>
                    <CartesianGrid stroke="#E5E5E5" strokeDasharray="0" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} tick={{ fontSize: 11 }} stroke="#111" />
                    <YAxis stroke="#111" tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Line type="monotone" dataKey="clicks" stroke="#002FA7" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="cost" stroke="#FF3B30" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="border-2 border-black bg-white p-6">
              <div className="font-mono text-[11px] uppercase text-[#555] mb-2">// top campaigns</div>
              <h3 className="font-display text-2xl font-bold tracking-tight mb-4">By Spend</h3>
              <div className="space-y-3">
                {[...data.campaigns].sort((a, b) => b.cost - a.cost).slice(0, 5).map((c) => (
                  <div
                    key={c.id}
                    className="border-2 border-black p-3 cursor-pointer hover:translate-x-[-2px] hover:translate-y-[-2px] hover:hard-shadow-sm transition-transform"
                    onClick={() => nav(`/adscopilot/campaigns/${c.id}`)}
                    data-testid={`top-campaign-${c.id}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-semibold truncate mr-2">{c.name}</div>
                      <Chip color={c.status === "active" ? "green" : c.status === "paused" ? "yellow" : "ghost"}>
                        {c.status}
                      </Chip>
                    </div>
                    <div className="mt-2 font-mono text-xs flex justify-between">
                      <span>{fmtMoney(c.cost)}</span>
                      <span className="text-[#555]">{fmtNum(c.clicks)} clicks</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
