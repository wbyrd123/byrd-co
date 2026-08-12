import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Send, Sparkles, Trash2, Download, FileText, Wand2, Loader2, Save, User, Home } from "lucide-react";

const PROPERTY_TYPES = [
  "Multifamily", "Office", "Retail", "Industrial", "Hotel",
  "Mixed-Use", "Self-Storage", "Medical Office", "Special Purpose",
];

const emptyState = () => ({
  property_info: {
    name: "", property_type: "", address: "", city: "", state: "",
    estimated_value: null, noi: null, cap_rate_pct: null, occupancy_type: null,
  },
  listing_agent: { name: "", email: "", phone: "", brokerage: "" },
  options: [],
  research_note: null,
  research_citations: [],
});

const fmtMoney = (v) => (v == null || v === "" ? "—" : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`);
const fmtPct = (v, d = 2) => (v == null || v === "" ? "—" : `${Number(v).toFixed(d)}%`);

// Safe error message extractor — FastAPI validation returns an array of objects that would crash toast otherwise.
const errMsg = (e, fallback = "Something went wrong") => {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length && typeof d[0]?.msg === "string") return d.map((x) => x.msg).join("; ");
  return e?.message || fallback;
};

export default function AdminLoanQuoteStudio() {
  const [state, setState] = useState(emptyState());
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([{
    role: "ada",
    text: "Hi — I'm Ada. Let's build a Loan Quote for your listing agent. What's the property name?",
  }]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [proposing, setProposing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [library, setLibrary] = useState([]);
  const chatEndRef = useRef(null);

  const loadLibrary = () => api.get("/admin/marketing/quotes").then((r) => setLibrary(r.data || []));
  useEffect(() => { loadLibrary(); }, []);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // ---- Chat ----
  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setMessages((m) => [...m, { role: "broker", text }]);
    setSending(true);
    try {
      const r = await api.post("/admin/marketing/quote/chat", {
        session_id: sessionId, message: text, state,
      });
      setSessionId(r.data.session_id);
      setState(r.data.state || state);
      setMessages((m) => [...m, {
        role: "ada", text: r.data.reply,
        ready_for_rates: r.data.ready_for_rates, has_agent: r.data.has_agent,
      }]);
      if (r.data.ready_for_rates) {
        // Auto-scroll a hint suggestion
      }
    } catch (e) {
      toast.error(errMsg(e, "Ada couldn't reply"));
    } finally {
      setSending(false);
    }
  };

  // ---- Propose options (Perplexity → Claude) ----
  const proposeOptions = async () => {
    setProposing(true);
    try {
      const r = await api.post("/admin/marketing/quote/propose-options", { state });
      setState((s) => ({
        ...s,
        options: r.data.options,
        research_note: r.data.research_note || null,
        research_citations: r.data.research_citations || [],
      }));
      setMessages((m) => [...m, {
        role: "ada",
        text: r.data.research_note
          ? `Pulled live market rates and drafted 3 options. Rates are indicative — edit any cell in the preview if you have a lender quote that differs.`
          : `Drafted 3 options using industry-typical ranges. Rates are estimates — edit any cell as needed.`,
      }]);
    } catch (e) {
      toast.error(errMsg(e, "Rate research failed"));
    } finally {
      setProposing(false);
    }
  };

  // ---- Live preview ----
  const refreshPreview = async () => {
    try {
      const r = await api.post("/admin/marketing/quote/preview", { state }, { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      // Revoke old URL to prevent leaks
      setPreviewUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return url; });
    } catch (e) { /* silent — preview is best-effort */ }
  };
  useEffect(() => {
    // Regenerate preview when state changes and we have enough data
    if (state.property_info.estimated_value && state.options.length > 0) {
      const t = setTimeout(refreshPreview, 400);
      return () => clearTimeout(t);
    }
  }, [state.property_info, state.options]);

  // ---- Generate & save ----
  const generateAndSave = async () => {
    setGenerating(true);
    try {
      const r = await api.post("/admin/marketing/quote/generate", {
        state, add_listing_agent_to_crm: true,
      });
      toast.success(`Quote saved${r.data.contact_id ? " · Listing agent added to CRM" : ""}`);
      loadLibrary();
      // Open the freshly-saved PDF
      window.open(`${api.defaults.baseURL}/admin/marketing/quotes/${r.data.id}/pdf`, "_blank", "noopener");
    } catch (e) {
      toast.error(errMsg(e, "Save failed"));
    } finally {
      setGenerating(false);
    }
  };

  const startNewQuote = () => {
    if (!window.confirm("Discard current quote and start a new one?")) return;
    setState(emptyState());
    setSessionId(null);
    setPreviewUrl((p) => { if (p) URL.revokeObjectURL(p); return null; });
    setMessages([{
      role: "ada",
      text: "Fresh start. What's the property name?",
    }]);
  };

  // ---- Manual field edits (all fields can be edited inline in the preview panel) ----
  const setProp = (k, v) => setState((s) => ({ ...s, property_info: { ...s.property_info, [k]: v } }));
  const setAgent = (k, v) => setState((s) => ({ ...s, listing_agent: { ...s.listing_agent, [k]: v } }));
  const setOption = (i, k, v) => setState((s) => ({
    ...s, options: s.options.map((o, idx) => idx === i ? { ...o, [k]: v } : o),
  }));

  // Auto cap-rate / NOI math (client mirror of server)
  useEffect(() => {
    const p = state.property_info;
    if (!p.estimated_value) return;
    if (p.noi && !p.cap_rate_pct) {
      const cr = Number(((p.noi / p.estimated_value) * 100).toFixed(2));
      setProp("cap_rate_pct", cr);
    } else if (p.cap_rate_pct && !p.noi) {
      const noi = Math.round(p.estimated_value * p.cap_rate_pct / 100);
      setProp("noi", noi);
    }
  }, [state.property_info.estimated_value, state.property_info.noi, state.property_info.cap_rate_pct]);

  const canPropose = !!(state.property_info.estimated_value
    && (state.property_info.noi || state.property_info.cap_rate_pct));
  const canGenerate = state.options.length >= 1;
  const lastReadyMsg = [...messages].reverse().find((m) => m.role === "ada" && m.ready_for_rates);

  return (
    <div className="min-h-screen bg-[#FBF8F1] p-6" data-testid="loan-quote-studio">
      <div className="max-w-[1440px] mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-baseline justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Marketing</div>
            <h1 className="font-serif text-3xl font-bold">Loan Quote Studio</h1>
            <p className="text-sm text-[#6B6558] mt-1">
              Chat with Ada to build a branded Loan Quote PDF for a listing agent. Live web rates via Perplexity.
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={startNewQuote} className="byrd-btn byrd-btn-outline" data-testid="lq-new">
              <FileText size={14} /> New Quote
            </button>
          </div>
        </div>

        {/* Main split — chat + preview */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Chat pane */}
          <div className="byrd-card flex flex-col h-[640px]">
            <div className="p-4 border-b border-[#E4DFD1] flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-[#C89434] text-white grid place-items-center">
                <Sparkles size={14} />
              </div>
              <div>
                <div className="font-serif font-bold">Ada</div>
                <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">// Live rate lookup ready</div>
              </div>
              {lastReadyMsg && !state.options.length && (
                <button onClick={proposeOptions} disabled={proposing}
                  className="ml-auto byrd-btn byrd-btn-dark text-xs"
                  data-testid="lq-propose">
                  {proposing ? (<><Loader2 size={12} className="animate-spin" /> Researching…</>) : (<><Wand2 size={12} /> Research rates &amp; propose</>)}
                </button>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "broker" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[85%] px-3 py-2 rounded-md text-sm whitespace-pre-wrap ${
                    m.role === "broker"
                      ? "bg-[#1A1A1A] text-white"
                      : "bg-[#F3EEE0] text-[#1A1A1A]"
                  }`}>
                    {m.text}
                    {m.ready_for_rates && !state.options.length && (
                      <button onClick={proposeOptions} disabled={proposing}
                        className="mt-2 block text-[#C89434] font-mono text-[10px] uppercase tracking-widest hover:text-[#8A6821]"
                        data-testid="lq-propose-inline">
                        {proposing ? "Researching…" : "→ Yes, research rates now"}
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div className="bg-[#F3EEE0] px-3 py-2 rounded-md text-sm text-[#6B6558]">
                    <Loader2 size={12} className="animate-spin inline mr-2" /> Ada is thinking…
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
            <div className="p-3 border-t border-[#E4DFD1] flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                placeholder="Type your reply…"
                className="flex-1 px-3 py-2 border border-[#E4DFD1] rounded-md text-sm focus:outline-none focus:border-[#C89434]"
                data-testid="lq-input"
              />
              <button onClick={sendMessage} disabled={sending || !input.trim()}
                className="byrd-btn byrd-btn-dark" data-testid="lq-send">
                <Send size={14} />
              </button>
            </div>
          </div>

          {/* Preview / manual edit pane */}
          <div className="space-y-4">
            <QuoteFieldsPanel state={state} setProp={setProp} setAgent={setAgent} setOption={setOption} />

            {previewUrl ? (
              <div className="byrd-card p-2">
                <div className="flex items-center justify-between mb-2 px-2">
                  <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Live preview</div>
                  <div className="flex gap-2">
                    <button onClick={refreshPreview} className="text-[11px] text-[#C89434] font-mono">Refresh</button>
                    <button onClick={generateAndSave} disabled={!canGenerate || generating}
                      className="byrd-btn byrd-btn-dark text-xs" data-testid="lq-save">
                      {generating ? "Saving…" : (<><Save size={12} /> Save &amp; Download</>)}
                    </button>
                  </div>
                </div>
                <iframe src={previewUrl} title="Preview" className="w-full h-[520px] border border-[#E4DFD1] rounded" />
              </div>
            ) : (
              <div className="byrd-card p-10 text-center">
                <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]">
                  <FileText size={22} />
                </div>
                <h3 className="font-serif text-xl font-bold mt-4">Preview will appear here</h3>
                <p className="text-[#6B6558] mt-2 text-sm max-w-sm mx-auto">
                  Once Ada has property + rate options, the PDF preview will populate here. Or click&nbsp;
                  <b>Propose</b> to trigger live rate research.
                </p>
                {canPropose && !state.options.length && (
                  <button onClick={proposeOptions} disabled={proposing}
                    className="byrd-btn byrd-btn-dark mt-4" data-testid="lq-propose-empty">
                    {proposing ? "Researching…" : (<><Wand2 size={14} /> Research rates &amp; propose</>)}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Library */}
        <div className="byrd-card p-6">
          <div className="flex items-baseline justify-between mb-4">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Marketing Library</div>
              <h2 className="font-serif text-2xl font-bold">Saved Loan Quotes</h2>
            </div>
            <div className="text-xs text-[#6B6558]">{library.length} saved</div>
          </div>
          {library.length === 0 ? (
            <div className="text-sm text-[#6B6558]">No saved quotes yet. Build one above and click <b>Save &amp; Download</b>.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="lq-library">
                <thead>
                  <tr className="text-left border-b border-[#E4DFD1] text-[10px] uppercase tracking-widest text-[#6B6558]">
                    <th className="p-2">Property</th>
                    <th className="p-2">Listing Agent</th>
                    <th className="p-2">Value</th>
                    <th className="p-2">Created</th>
                    <th className="p-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {library.map((q) => (
                    <tr key={q.id} className="border-b border-[#F3EEE0]">
                      <td className="p-2">
                        <div className="font-semibold">{q.property_info?.name || "—"}</div>
                        <div className="text-[11px] text-[#6B6558]">
                          {q.property_info?.property_type || ""} · {[q.property_info?.city, q.property_info?.state].filter(Boolean).join(", ")}
                        </div>
                      </td>
                      <td className="p-2">
                        <div>{q.listing_agent?.name || "—"}</div>
                        <div className="text-[11px] text-[#6B6558]">{q.listing_agent?.email || ""}</div>
                      </td>
                      <td className="p-2">{fmtMoney(q.property_info?.estimated_value)}</td>
                      <td className="p-2 text-[11px] text-[#6B6558]">{new Date(q.created_at).toLocaleString()}</td>
                      <td className="p-2 text-right">
                        <a href={`${api.defaults.baseURL}/admin/marketing/quotes/${q.id}/pdf`}
                          target="_blank" rel="noopener noreferrer"
                          className="byrd-btn byrd-btn-outline text-xs" data-testid={`lq-dl-${q.id}`}>
                          <Download size={12} /> PDF
                        </a>
                        <button onClick={async () => {
                          if (!window.confirm("Delete this saved quote?")) return;
                          await api.delete(`/admin/marketing/quotes/${q.id}`);
                          loadLibrary();
                        }} className="byrd-btn byrd-btn-outline text-xs ml-2 text-[#8A1F1A] border-[#E38380]" data-testid={`lq-del-${q.id}`}>
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function QuoteFieldsPanel({ state, setProp, setAgent, setOption }) {
  const p = state.property_info || {};
  const a = state.listing_agent || {};
  return (
    <div className="byrd-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <Home size={14} className="text-[#C89434]" />
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Property</div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Inp label="Property Name" value={p.name} onChange={(v) => setProp("name", v)} />
        <Sel label="Property Type" value={p.property_type} onChange={(v) => setProp("property_type", v)}>
          <option value="">Select…</option>
          {PROPERTY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </Sel>
        <Inp label="Address" value={p.address} onChange={(v) => setProp("address", v)} />
        <div className="grid grid-cols-2 gap-2">
          <Inp label="City" value={p.city} onChange={(v) => setProp("city", v)} />
          <Inp label="State" value={p.state} onChange={(v) => setProp("state", v)} />
        </div>
        <Sel label="Occupancy Type" value={p.occupancy_type || ""} onChange={(v) => setProp("occupancy_type", v || null)}>
          <option value="">Select…</option>
          <option value="owner_occupied">Owner-Occupied</option>
          <option value="non_owner_occupied">Non-Owner-Occupied</option>
        </Sel>
        <NumInp label="Est. Value ($)" value={p.estimated_value} onChange={(v) => setProp("estimated_value", v)} />
        <NumInp label="NOI ($)" value={p.noi} onChange={(v) => setProp("noi", v)} />
        <NumInp label="Cap Rate (%)" step="0.01" value={p.cap_rate_pct} onChange={(v) => setProp("cap_rate_pct", v)} />
      </div>

      <div className="flex items-center gap-2 mt-4 mb-2">
        <User size={14} className="text-[#C89434]" />
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Listing Agent</div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <Inp label="Name" value={a.name} onChange={(v) => setAgent("name", v)} />
        <Inp label="Email" value={a.email} onChange={(v) => setAgent("email", v)} />
        <Inp label="Phone" value={a.phone} onChange={(v) => setAgent("phone", v)} />
        <Inp label="Brokerage" value={a.brokerage} onChange={(v) => setAgent("brokerage", v)} />
      </div>

      {state.options.length > 0 && (
        <>
          <div className="flex items-center gap-2 mt-4 mb-2">
            <Sparkles size={14} className="text-[#C89434]" />
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Financing Options — edit any cell</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] uppercase tracking-widest text-[#6B6558]">
                  <th></th>
                  {state.options.map((o, i) => (
                    <th key={i} className="p-1 text-center">
                      <input value={o.label || ""} onChange={(e) => setOption(i, "label", e.target.value)}
                        className="w-full text-center bg-transparent border-b border-[#E4DFD1] focus:border-[#C89434] focus:outline-none font-serif font-bold text-sm text-[#C89434]" />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { key: "ltv_pct", label: "LTV (%)", type: "num", step: "1" },
                  { key: "loan_amount", label: "Loan Amount", type: "num" },
                  { key: "loan_program", label: "Program", type: "text" },
                  { key: "interest_rate_pct", label: "Rate (%)", type: "num", step: "0.01" },
                  { key: "monthly_payment", label: "Monthly P&I", type: "num" },
                  { key: "recourse", label: "Recourse", type: "select", options: ["Yes", "No", "Partial"] },
                ].map((row) => (
                  <tr key={row.key} className="border-b border-[#F3EEE0]">
                    <td className="p-1 text-[#6B6558]">{row.label}</td>
                    {state.options.map((o, i) => (
                      <td key={i} className="p-1">
                        {row.type === "select" ? (
                          <select value={o[row.key] || ""} onChange={(e) => setOption(i, row.key, e.target.value || null)}
                            className="w-full px-1 py-0.5 bg-transparent border-b border-[#E4DFD1] focus:border-[#C89434] focus:outline-none">
                            <option value="">—</option>
                            {row.options.map((op) => <option key={op} value={op}>{op}</option>)}
                          </select>
                        ) : (
                          <input
                            type={row.type === "num" ? "number" : "text"}
                            step={row.step}
                            value={o[row.key] == null ? "" : o[row.key]}
                            onChange={(e) => setOption(i, row.key, row.type === "num" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value)}
                            className="w-full px-1 py-0.5 bg-transparent border-b border-[#E4DFD1] focus:border-[#C89434] focus:outline-none text-right"
                          />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {state.research_citations?.length > 0 && (
            <details className="mt-3 text-[11px] text-[#6B6558]">
              <summary className="cursor-pointer font-mono uppercase tracking-widest">// Sources from Perplexity</summary>
              <ul className="mt-2 space-y-1">
                {state.research_citations.map((u, i) => (
                  <li key={i}><a href={u} target="_blank" rel="noopener noreferrer" className="underline hover:text-[#C89434] break-all">{u}</a></li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function Inp({ label, value, onChange }) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</span>
      <input value={value || ""} onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full px-2 py-1.5 border border-[#E4DFD1] rounded text-sm focus:outline-none focus:border-[#C89434]" />
    </label>
  );
}

function NumInp({ label, value, onChange, step }) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</span>
      <input type="number" step={step || "1"} value={value == null ? "" : value}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="mt-0.5 w-full px-2 py-1.5 border border-[#E4DFD1] rounded text-sm focus:outline-none focus:border-[#C89434]" />
    </label>
  );
}

function Sel({ label, value, onChange, children }) {
  return (
    <label className="block">
      <span className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</span>
      <select value={value || ""} onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full px-2 py-1.5 border border-[#E4DFD1] rounded text-sm focus:outline-none focus:border-[#C89434]">
        {children}
      </select>
    </label>
  );
}
