import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { SectionHeader } from "@/components/Brutal";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { ArrowRight, ArrowLeft, Sparkles, Check } from "lucide-react";

const OBJECTIVES = [
  { v: "search", label: "Search (text ads)" },
  { v: "display", label: "Display (banner)" },
  { v: "video", label: "Video (YouTube)" },
  { v: "shopping", label: "Shopping" },
  { v: "performance_max", label: "Performance Max" },
];

const STEPS = ["Basics", "Targeting", "Keywords", "Ad Copy", "Review"];

export default function CreateCampaign() {
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    name: "",
    objective: "search",
    daily_budget: 25,
    target_locations: ["United States"],
    keywords: [],
    headlines: [],
    descriptions: [],
    final_url: "https://",
  });
  const [kwInput, setKwInput] = useState("");
  const [genLoading, setGenLoading] = useState(false);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const addKeyword = () => {
    const trimmed = kwInput.trim();
    if (!trimmed) return;
    set("keywords", [...new Set([...form.keywords, trimmed])]);
    setKwInput("");
  };

  const removeKw = (kw) => set("keywords", form.keywords.filter((k) => k !== kw));

  const suggestCopy = async () => {
    if (!form.name) {
      toast.error("Add a campaign name first");
      return;
    }
    setGenLoading(true);
    try {
      const res = await api.post("/ai/adcopy", {
        product: form.name,
        keywords: form.keywords,
        num_headlines: 6,
        num_descriptions: 3,
      });
      const h = (res.data.headlines || []).map((x) => (typeof x === "string" ? x : x.text));
      const d = (res.data.descriptions || []).map((x) => (typeof x === "string" ? x : x.text));
      if (!h.length && !d.length) throw new Error("Empty response");
      set("headlines", h);
      set("descriptions", d);
      toast.success("Ad copy generated");
    } catch (e) {
      toast.error("Copy generation failed");
    } finally {
      setGenLoading(false);
    }
  };

  const submit = async () => {
    if (!form.name || !form.daily_budget) {
      toast.error("Missing required fields");
      return;
    }
    try {
      const res = await api.post("/campaigns", form);
      toast.success("Campaign created");
      nav(`/campaigns/${res.data.id}`);
    } catch (e) {
      toast.error("Failed to create campaign");
    }
  };

  return (
    <div className="max-w-3xl" data-testid="create-campaign-page">
      <SectionHeader eyebrow="new campaign / wizard" title="Compose Campaign." />

      {/* Stepper */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((s, i) => (
          <React.Fragment key={s}>
            <div
              className={`flex items-center gap-2 px-3 py-1.5 border-2 border-black font-mono text-[11px] uppercase ${
                i === step ? "bg-black text-white" : i < step ? "bg-[#00C853] text-black" : "bg-white"
              }`}
            >
              {i < step && <Check size={12} />}
              {String(i + 1).padStart(2, "0")} · {s}
            </div>
            {i < STEPS.length - 1 && <div className="flex-1 h-[2px] bg-black" />}
          </React.Fragment>
        ))}
      </div>

      <div className="border-2 border-black bg-white p-6 space-y-5">
        {step === 0 && (
          <>
            <div>
              <Label className="font-mono text-xs uppercase">Campaign name</Label>
              <Input
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="e.g. Cold Brew Launch — Search / US"
                data-testid="cc-name"
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
            <div>
              <Label className="font-mono text-xs uppercase">Objective</Label>
              <Select value={form.objective} onValueChange={(v) => set("objective", v)}>
                <SelectTrigger data-testid="cc-objective" className="mt-1 rounded-none border-2 border-black h-11 font-mono">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-none border-2 border-black">
                  {OBJECTIVES.map((o) => (
                    <SelectItem key={o.v} value={o.v} className="rounded-none font-mono">
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="font-mono text-xs uppercase">Daily budget (USD)</Label>
              <Input
                type="number"
                min={1}
                step="0.5"
                value={form.daily_budget}
                onChange={(e) => set("daily_budget", parseFloat(e.target.value) || 0)}
                data-testid="cc-budget"
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
            <div>
              <Label className="font-mono text-xs uppercase">Final URL</Label>
              <Input
                value={form.final_url}
                onChange={(e) => set("final_url", e.target.value)}
                placeholder="https://your-landing-page.com"
                data-testid="cc-url"
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <div>
              <Label className="font-mono text-xs uppercase">Locations (comma-separated)</Label>
              <Input
                value={form.target_locations.join(", ")}
                onChange={(e) =>
                  set(
                    "target_locations",
                    e.target.value.split(",").map((s) => s.trim()).filter(Boolean)
                  )
                }
                placeholder="United States, Canada"
                data-testid="cc-locations"
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
            <div className="font-mono text-xs text-[#555] border-2 border-dashed border-black p-3">
              // Advanced targeting (age, device, language) is available in the campaign detail page after creation.
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <Label className="font-mono text-xs uppercase">Add keywords</Label>
              <div className="flex gap-2 mt-1">
                <Input
                  value={kwInput}
                  onChange={(e) => setKwInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addKeyword();
                    }
                  }}
                  placeholder='"cold brew coffee", buy pour over kit …'
                  data-testid="cc-kw-input"
                  className="rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
                />
                <button
                  onClick={addKeyword}
                  data-testid="cc-kw-add"
                  className="h-11 px-4 bg-black text-white font-mono uppercase text-xs press-effect hard-shadow-sm"
                >
                  Add
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 min-h-[40px]">
              {form.keywords.length === 0 && (
                <div className="font-mono text-xs text-[#555]">// no keywords yet — try &quot;cold brew coffee&quot;</div>
              )}
              {form.keywords.map((k) => (
                <span
                  key={k}
                  className="inline-flex items-center gap-2 border-2 border-black px-2 py-1 font-mono text-xs bg-[#F4F4F0]"
                >
                  {k}
                  <button onClick={() => removeKw(k)} className="hover:text-[#FF3B30]" aria-label={`remove ${k}`}>
                    ×
                  </button>
                </span>
              ))}
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <div className="font-mono text-xs uppercase text-[#555]">// ad copy</div>
                <div className="font-display text-2xl font-bold tracking-tight">Headlines & descriptions</div>
              </div>
              <button
                onClick={suggestCopy}
                disabled={genLoading}
                data-testid="cc-generate-copy"
                className="h-11 px-4 bg-[#002FA7] text-white font-mono uppercase text-xs press-effect hard-shadow-sm flex items-center gap-2 disabled:opacity-60"
              >
                <Sparkles size={14} /> {genLoading ? "Generating…" : "AI Generate"}
              </button>
            </div>
            <div>
              <Label className="font-mono text-xs uppercase">Headlines (one per line, ≤30 chars)</Label>
              <Textarea
                value={form.headlines.join("\n")}
                onChange={(e) => set("headlines", e.target.value.split("\n").filter(Boolean))}
                rows={6}
                data-testid="cc-headlines"
                className="mt-1 rounded-none border-2 border-black font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
            <div>
              <Label className="font-mono text-xs uppercase">Descriptions (one per line, ≤90 chars)</Label>
              <Textarea
                value={form.descriptions.join("\n")}
                onChange={(e) => set("descriptions", e.target.value.split("\n").filter(Boolean))}
                rows={4}
                data-testid="cc-descriptions"
                className="mt-1 rounded-none border-2 border-black font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <div className="font-mono text-xs uppercase text-[#555]">// review</div>
            <div className="grid grid-cols-2 gap-4 font-mono text-sm">
              <div><span className="text-[#555]">Name</span><br/>{form.name}</div>
              <div><span className="text-[#555]">Objective</span><br/>{form.objective}</div>
              <div><span className="text-[#555]">Budget/day</span><br/>${form.daily_budget}</div>
              <div><span className="text-[#555]">Locations</span><br/>{form.target_locations.join(", ")}</div>
              <div className="col-span-2"><span className="text-[#555]">Final URL</span><br/>{form.final_url}</div>
              <div className="col-span-2">
                <span className="text-[#555]">Keywords ({form.keywords.length})</span><br/>
                {form.keywords.slice(0, 20).join(", ")}
              </div>
              <div className="col-span-2">
                <span className="text-[#555]">Headlines ({form.headlines.length}) · Descriptions ({form.descriptions.length})</span>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="mt-6 flex items-center justify-between">
        <button
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
          data-testid="cc-back"
          className="h-11 px-4 border-2 border-black font-mono uppercase text-xs flex items-center gap-2 disabled:opacity-40 hover:bg-black hover:text-white transition-colors"
        >
          <ArrowLeft size={14} /> Back
        </button>
        {step < STEPS.length - 1 ? (
          <button
            onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
            data-testid="cc-next"
            className="h-11 px-5 bg-black text-white font-mono uppercase text-xs hard-shadow-sm press-effect flex items-center gap-2"
          >
            Next <ArrowRight size={14} />
          </button>
        ) : (
          <button
            onClick={submit}
            data-testid="cc-submit"
            className="h-11 px-5 bg-[#002FA7] text-white font-mono uppercase text-xs hard-shadow press-effect flex items-center gap-2"
          >
            Launch Campaign <Sparkles size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
