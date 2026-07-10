import React, { useState } from "react";
import { api } from "@/lib/api";
import { SectionHeader, Chip } from "@/components/Brutal";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Search, Sparkles } from "lucide-react";

const DIFF = { low: "green", medium: "yellow", high: "red" };
const MATCH = { broad: "ghost", phrase: "black", exact: "green" };

export default function KeywordLab() {
  const [seed, setSeed] = useState("");
  const [industry, setIndustry] = useState("");
  const [count, setCount] = useState(15);
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState(null);

  const run = async (e) => {
    e?.preventDefault?.();
    if (!seed) {
      toast.error("Enter a seed keyword");
      return;
    }
    setBusy(true);
    setRows(null);
    try {
      const res = await api.post("/ai/keywords", { seed, industry, count });
      const list = res.data?.keywords || [];
      setRows(list);
      if (!list.length) toast.error("No keywords returned");
    } catch (e) {
      toast.error("Keyword research failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="keywords-page">
      <SectionHeader eyebrow="keyword lab" title="Find intent, price it." />

      <form
        onSubmit={run}
        className="border-2 border-black bg-white p-6 grid grid-cols-1 md:grid-cols-[1.4fr_1fr_.6fr_auto] gap-4 items-end"
      >
        <div>
          <Label className="font-mono text-xs uppercase">Seed keyword</Label>
          <Input
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder='e.g. "project management software"'
            data-testid="kw-seed"
            className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
          />
        </div>
        <div>
          <Label className="font-mono text-xs uppercase">Industry (optional)</Label>
          <Input
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            placeholder="e.g. B2B SaaS, agencies"
            data-testid="kw-industry"
            className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
          />
        </div>
        <div>
          <Label className="font-mono text-xs uppercase">Count</Label>
          <Input
            type="number" min={5} max={40}
            value={count}
            onChange={(e) => setCount(parseInt(e.target.value) || 15)}
            data-testid="kw-count"
            className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          data-testid="kw-run"
          className="h-11 px-5 bg-black text-white font-mono uppercase text-xs hard-shadow-sm press-effect flex items-center gap-2 disabled:opacity-60"
        >
          {busy ? "…" : <><Sparkles size={14} /> Research</>}
        </button>
      </form>

      {rows === null && (
        <div className="border-2 border-dashed border-black p-8 text-center bg-white">
          <Search className="mx-auto" size={22} />
          <div className="font-mono text-xs uppercase text-[#555] mt-3">// ready when you are</div>
          <p className="mt-1">Enter a seed keyword to generate an AI-scored keyword plan.</p>
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="border-2 border-black bg-white overflow-x-auto" data-testid="kw-results">
          <div className="grid grid-cols-[2fr_.9fr_.9fr_1fr_1fr_.8fr] border-b-2 border-black font-mono text-[10px] uppercase text-[#555]">
            {["Keyword", "Match", "Intent", "Volume/mo", "CPC (USD)", "Difficulty"].map((h) => (
              <div key={h} className="p-3 border-r border-[#E5E5E5] last:border-r-0">{h}</div>
            ))}
          </div>
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[2fr_.9fr_.9fr_1fr_1fr_.8fr] border-b border-[#E5E5E5] last:border-b-0 hover:bg-[#F4F4F0] transition-colors">
              <div className="p-3 font-mono text-sm">{r.keyword}</div>
              <div className="p-3"><Chip color={MATCH[r.match_type] || "ghost"}>{r.match_type}</Chip></div>
              <div className="p-3 font-mono text-sm">{r.intent}</div>
              <div className="p-3 font-mono text-sm">{new Intl.NumberFormat().format(r.est_monthly_volume || 0)}</div>
              <div className="p-3 font-mono text-sm">${Number(r.est_cpc_usd || 0).toFixed(2)}</div>
              <div className="p-3"><Chip color={DIFF[r.difficulty] || "ghost"}>{r.difficulty}</Chip></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
