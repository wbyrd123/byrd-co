import React, { useState } from "react";
import { api } from "@/lib/api";
import { SectionHeader } from "@/components/Brutal";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Sparkles, Copy } from "lucide-react";

const TONES = ["professional", "playful", "urgent", "premium", "friendly", "bold"];

export default function AdCopyStudio() {
  const [form, setForm] = useState({
    product: "",
    audience: "",
    tone: "professional",
    keywords: "",
    num_headlines: 6,
    num_descriptions: 3,
  });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const generate = async () => {
    if (!form.product) {
      toast.error("Add a product/service description");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const res = await api.post("/ai/adcopy", {
        product: form.product,
        audience: form.audience,
        tone: form.tone,
        keywords: form.keywords.split(",").map((k) => k.trim()).filter(Boolean),
        num_headlines: form.num_headlines,
        num_descriptions: form.num_descriptions,
      });
      setResult(res.data);
    } catch (e) {
      toast.error("Generation failed");
    } finally {
      setBusy(false);
    }
  };

  const copy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copied");
  };

  return (
    <div className="space-y-6" data-testid="adcopy-page">
      <SectionHeader eyebrow="ad copy studio" title="Draft copy that ships." />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="border-2 border-black bg-white p-6 space-y-4">
          <div>
            <Label className="font-mono text-xs uppercase">Product / service</Label>
            <Input
              value={form.product}
              onChange={(e) => set("product", e.target.value)}
              placeholder="e.g. Cold-pressed juice subscription"
              data-testid="ac-product"
              className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
            />
          </div>
          <div>
            <Label className="font-mono text-xs uppercase">Target audience</Label>
            <Input
              value={form.audience}
              onChange={(e) => set("audience", e.target.value)}
              placeholder="e.g. Busy urban professionals 25-45"
              data-testid="ac-audience"
              className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
            />
          </div>
          <div>
            <Label className="font-mono text-xs uppercase">Tone</Label>
            <Select value={form.tone} onValueChange={(v) => set("tone", v)}>
              <SelectTrigger data-testid="ac-tone" className="mt-1 rounded-none border-2 border-black h-11 font-mono">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="rounded-none border-2 border-black">
                {TONES.map((t) => (
                  <SelectItem key={t} value={t} className="rounded-none font-mono">{t}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="font-mono text-xs uppercase">Keywords (comma-separated)</Label>
            <Input
              value={form.keywords}
              onChange={(e) => set("keywords", e.target.value)}
              placeholder="cold pressed juice, healthy delivery, detox"
              data-testid="ac-keywords"
              className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="font-mono text-xs uppercase"># Headlines</Label>
              <Input
                type="number" min={1} max={15}
                value={form.num_headlines}
                onChange={(e) => set("num_headlines", parseInt(e.target.value) || 1)}
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
              />
            </div>
            <div>
              <Label className="font-mono text-xs uppercase"># Descriptions</Label>
              <Input
                type="number" min={1} max={8}
                value={form.num_descriptions}
                onChange={(e) => set("num_descriptions", parseInt(e.target.value) || 1)}
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0"
              />
            </div>
          </div>
          <button
            onClick={generate}
            disabled={busy}
            data-testid="ac-generate"
            className="w-full h-12 bg-black text-white font-mono uppercase text-sm hard-shadow press-effect flex items-center justify-center gap-2 disabled:opacity-60"
          >
            <Sparkles size={16} /> {busy ? "Generating…" : "Generate Ad Copy"}
          </button>
        </div>

        <div className="space-y-4">
          <div className="border-2 border-black bg-white p-6" data-testid="ac-headlines-out">
            <div className="font-mono text-[11px] uppercase text-[#555] mb-2">// headlines ≤ 30 chars</div>
            {!result && <div className="font-mono text-xs text-[#555]">Awaiting generation…</div>}
            <ul className="space-y-2">
              {result?.headlines?.map((h, i) => {
                const text = typeof h === "string" ? h : h.text;
                const chars = text?.length || 0;
                const over = chars > 30;
                return (
                  <li key={i} className={`border-2 border-black p-2 font-mono text-sm flex items-center justify-between gap-2 ${over ? "bg-[#FFECEC]" : ""}`}>
                    <span>{text}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[11px] ${over ? "text-[#FF3B30]" : "text-[#555]"}`}>{chars}c</span>
                      <button onClick={() => copy(text)} className="w-7 h-7 border-2 border-black grid place-items-center hover:bg-black hover:text-white transition-colors">
                        <Copy size={12} />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="border-2 border-black bg-white p-6" data-testid="ac-descriptions-out">
            <div className="font-mono text-[11px] uppercase text-[#555] mb-2">// descriptions ≤ 90 chars</div>
            {!result && <div className="font-mono text-xs text-[#555]">Awaiting generation…</div>}
            <ul className="space-y-2">
              {result?.descriptions?.map((d, i) => {
                const text = typeof d === "string" ? d : d.text;
                const chars = text?.length || 0;
                const over = chars > 90;
                return (
                  <li key={i} className={`border-2 border-black p-2 font-mono text-sm flex items-start justify-between gap-2 ${over ? "bg-[#FFECEC]" : ""}`}>
                    <span className="flex-1">{text}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[11px] ${over ? "text-[#FF3B30]" : "text-[#555]"}`}>{chars}c</span>
                      <button onClick={() => copy(text)} className="w-7 h-7 border-2 border-black grid place-items-center hover:bg-black hover:text-white transition-colors">
                        <Copy size={12} />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
