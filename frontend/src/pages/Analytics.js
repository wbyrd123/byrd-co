import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Metric, SectionHeader, fmtMoney, fmtNum } from "@/components/Brutal";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, BarChart, Bar, Legend } from "recharts";

export default function Analytics() {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/analytics/overview").then((r) => setData(r.data));
  }, []);

  if (!data) return <div className="font-mono text-sm">loading…</div>;

  return (
    <div className="space-y-6" data-testid="analytics-page">
      <SectionHeader eyebrow="analytics / 30 days" title="Numbers, in ink." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Metric label="Impressions" value={fmtNum(data.summary.impressions)} />
        <Metric label="Clicks" value={fmtNum(data.summary.clicks)} />
        <Metric label="Spend" value={fmtMoney(data.summary.cost)} />
        <Metric label="Conv. Rate" value={data.summary.conversion_rate} unit="%" />
      </div>

      <div className="border-2 border-black bg-white p-6">
        <div className="font-mono text-[11px] uppercase text-[#555]">// impressions vs clicks</div>
        <h3 className="font-display text-2xl font-bold tracking-tight mb-4">Reach & Engagement</h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.daily}>
              <CartesianGrid stroke="#E5E5E5" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} stroke="#111" />
              <YAxis stroke="#111" />
              <Tooltip />
              <Legend wrapperStyle={{ fontFamily: "IBM Plex Mono", fontSize: 12 }} />
              <Line type="monotone" dataKey="impressions" stroke="#111" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="clicks" stroke="#002FA7" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="border-2 border-black bg-white p-6">
          <div className="font-mono text-[11px] uppercase text-[#555]">// daily spend</div>
          <h3 className="font-display text-2xl font-bold tracking-tight mb-4">Spend</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.daily}>
                <CartesianGrid stroke="#E5E5E5" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} stroke="#111" />
                <YAxis stroke="#111" />
                <Tooltip />
                <Bar dataKey="cost" fill="#FF3B30" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="border-2 border-black bg-white p-6">
          <div className="font-mono text-[11px] uppercase text-[#555]">// conversions</div>
          <h3 className="font-display text-2xl font-bold tracking-tight mb-4">Conversions</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.daily}>
                <CartesianGrid stroke="#E5E5E5" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} stroke="#111" />
                <YAxis stroke="#111" />
                <Tooltip />
                <Bar dataKey="conversions" fill="#00C853" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="border-2 border-black bg-white">
        <div className="grid grid-cols-[2fr_.8fr_.8fr_.8fr_.8fr_.8fr_.9fr] border-b-2 border-black font-mono text-[10px] uppercase text-[#555]">
          {["Campaign", "Status", "Impr.", "Clicks", "CTR", "CPC", "Spend"].map((h) => (
            <div key={h} className="p-3 border-r border-[#E5E5E5] last:border-r-0">{h}</div>
          ))}
        </div>
        {data.campaigns.length === 0 && (
          <div className="p-6 font-mono text-xs text-[#555]">// no campaigns yet</div>
        )}
        {data.campaigns.map((c) => (
          <div key={c.id} className="grid grid-cols-[2fr_.8fr_.8fr_.8fr_.8fr_.8fr_.9fr] border-b border-[#E5E5E5] last:border-b-0">
            <div className="p-3 font-semibold truncate">{c.name}</div>
            <div className="p-3 font-mono text-sm capitalize">{c.status}</div>
            <div className="p-3 font-mono text-sm">{fmtNum(c.impressions)}</div>
            <div className="p-3 font-mono text-sm">{fmtNum(c.clicks)}</div>
            <div className="p-3 font-mono text-sm">{c.ctr}%</div>
            <div className="p-3 font-mono text-sm">{fmtMoney(c.cpc)}</div>
            <div className="p-3 font-mono text-sm">{fmtMoney(c.cost)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
