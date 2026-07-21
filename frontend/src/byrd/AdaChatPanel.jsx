import React, { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "@/lib/api";
import { toast } from "sonner";
import {
  Sparkles, Send, RotateCcw, FileText, Check, Upload, MessageSquare, Loader2,
} from "lucide-react";

const firstName = (u) => (u?.name || u?.email?.split("@")[0] || "there").split(" ")[0];

export default function AdaChatPanel({ user, scenarios, onUploaded }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [expanded, setExpanded] = useState(true);
  const scrollerRef = useRef(null);
  const controllerRef = useRef(null);

  useEffect(() => {
    api.get("/client/ada/messages").then((r) => setMessages(r.data)).catch(() => {});
    return () => controllerRef.current?.abort();
  }, []);

  useEffect(() => {
    if (scrollerRef.current) scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [messages, streaming]);

  const send = async (msgOverride) => {
    const text = (msgOverride || input).trim();
    if (!text || busy) return;
    setBusy(true);
    setStreaming("");
    setMessages((m) => [...m, { id: `local-${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString() }]);
    if (!msgOverride) setInput("");
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const token = localStorage.getItem("ac_token");
      const res = await fetch(`${API_BASE}/client/ada/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
        body: JSON.stringify({ message: text }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "", liveBuf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          if (!chunk.startsWith("data: ")) continue;
          const evt = JSON.parse(chunk.slice(6));
          if (evt.type === "token") {
            liveBuf += evt.content;
            const cut = liveBuf.search(/```(generate_doc|upload_confirm|broker_note)/);
            setStreaming(cut >= 0 ? liveBuf.slice(0, cut) : liveBuf);
          } else if (evt.type === "done") {
            setMessages((m) => [...m, {
              id: evt.message_id, role: "assistant", content: evt.text,
              drafts_created: evt.drafts_created, uploads_done: evt.uploads_done,
              broker_notes: evt.broker_notes, created_at: new Date().toISOString(),
            }]);
            setStreaming("");
            if (evt.uploads_done?.length) onUploaded && onUploaded();
          } else if (evt.type === "error") {
            toast.error(evt.detail || "Ada hit an error");
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") toast.error(e.message || "Chat failed");
    } finally {
      setBusy(false); setStreaming("");
    }
  };

  const reset = async () => {
    if (!window.confirm("Clear your chat with Ada?")) return;
    await api.post("/client/ada/reset");
    setMessages([]);
  };

  const viewDraft = async (fileId) => {
    const res = await api.get(`/files/${fileId}`, { responseType: "blob" });
    window.open(URL.createObjectURL(res.data), "_blank");
  };

  const confirmUpload = async (draft) => {
    // Find target line: match by scenario_id + label
    const scen = scenarios.find((s) => s.id === draft.scenario_id);
    if (!scen) { toast.error("Couldn't match this to a scenario"); return; }
    const line = (scen.docs || []).find(
      (d) => d.label.toLowerCase() === (draft.target_doc_line_label || "").toLowerCase()
    );
    if (!line) { toast.error(`No "${draft.target_doc_line_label}" line on this scenario yet.`); return; }
    await send(`Yes, please upload the ${draft.target_doc_line_label} to my ${scen.name} checklist. Draft id ${draft.draft_id}, doc line id ${line.doc_line_id || line.id}.`);
  };

  const firstMsg = messages.length === 0 && !streaming;
  const hasPending = (scenarios || []).some((s) => (s.docs || []).some((d) => d.required && d.status === "pending"));

  return (
    <section className="byrd-card overflow-hidden" data-testid="ada-panel">
      <div className="border-b border-[#E4DFD1] bg-[#1A1A1A] text-[#FBF8F1] px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-[#C89434] text-[#1A1A1A] grid place-items-center">
            <Sparkles size={16} />
          </div>
          <div className="leading-tight">
            <div className="font-serif text-lg font-bold text-white">Ada</div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#E5B968]">
              Your Byrd &amp; CO document concierge
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={reset} className="text-[11px] text-[#C9C1AF] hover:text-white inline-flex items-center gap-1" data-testid="ada-reset">
            <RotateCcw size={11} /> Clear
          </button>
          <button onClick={() => setExpanded((x) => !x)} className="text-[11px] text-[#C9C1AF] hover:text-white" data-testid="ada-toggle">
            {expanded ? "Collapse" : "Expand"}
          </button>
        </div>
      </div>

      {expanded && (
        <>
          <div ref={scrollerRef} className="h-[42vh] min-h-[320px] overflow-y-auto bg-[#FBF8F1] px-4 py-4 space-y-3">
            {firstMsg && (
              <AdaGreeting name={firstName(user)} hasPending={hasPending} onQuickstart={(t) => send(t)} />
            )}
            {messages.map((m) => (
              <AdaBubble key={m.id} m={m} onViewDraft={viewDraft} onConfirmUpload={confirmUpload} />
            ))}
            {streaming && (
              <div className="flex gap-2">
                <div className="w-7 h-7 rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center shrink-0 border border-[#E4DFD1]">
                  <Sparkles size={12} />
                </div>
                <div className="max-w-[85%] rounded-lg border border-[#E4DFD1] bg-white text-sm p-3 whitespace-pre-wrap text-[#2A2A2A]">
                  {streaming}<span className="inline-block w-1 h-4 bg-[#C89434] ml-0.5 animate-pulse" />
                </div>
              </div>
            )}
            {busy && !streaming && (
              <div className="text-xs text-[#6B6558] inline-flex items-center gap-1">
                <Loader2 size={12} className="animate-spin" /> Ada is thinking…
              </div>
            )}
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); send(); }}
            className="border-t border-[#E4DFD1] p-3 flex items-center gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={`Ask Ada… ("What's a PFS?", "Build me a proforma")`}
              disabled={busy}
              data-testid="ada-input"
              className="flex-1 h-11 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              data-testid="ada-send"
              className="byrd-btn byrd-btn-dark h-11 px-4"
            >
              <Send size={14} /> Send
            </button>
          </form>
        </>
      )}
    </section>
  );
}

function AdaGreeting({ name, hasPending, onQuickstart }) {
  const suggestions = hasPending
    ? [
        "What's next on my checklist?",
        "Help me build my Personal Financial Statement",
        "I need a CRE resume — walk me through it",
        "Build me a proforma for this deal",
      ]
    : [
        "What does my broker do next?",
        "Can you explain what a T-12 is?",
        "Draft a Letter of Explanation for me",
        "Build me a proforma for this deal",
      ];
  return (
    <div className="rounded-lg border border-[#E4DFD1] bg-white p-4" data-testid="ada-greeting">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1]">
          <Sparkles size={14} />
        </div>
        <div className="font-serif text-base font-bold">Hi {name} — I'm Ada.</div>
      </div>
      <p className="text-sm text-[#6B6558] mt-2">
        I'm your Byrd &amp; CO document concierge. I can explain any checklist item, draft your PFS / resume /
        proforma / letters / rent roll — and upload them straight to the right place for you.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => onQuickstart(s)}
            className="text-xs px-3 py-1.5 rounded-full border border-[#E4DFD1] hover:bg-[#F3EEE0] text-[#2A2A2A]"
            data-testid={`ada-suggest-${s.slice(0, 20)}`}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function AdaBubble({ m, onViewDraft, onConfirmUpload }) {
  const isUser = m.role === "user";
  return (
    <div className={`flex gap-2 ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`w-7 h-7 rounded-full grid place-items-center shrink-0 border ${isUser ? "bg-[#1A1A1A] text-white border-[#1A1A1A]" : "bg-[#F3EEE0] text-[#C89434] border-[#E4DFD1]"}`}>
        {isUser ? <MessageSquare size={12} /> : <Sparkles size={12} />}
      </div>
      <div className={`max-w-[85%] flex flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
        <div className={`rounded-lg text-sm p-3 whitespace-pre-wrap ${isUser ? "bg-[#1A1A1A] text-[#FBF8F1]" : "bg-white border border-[#E4DFD1] text-[#2A2A2A]"}`}>
          {m.content}
        </div>

        {!isUser && (m.drafts_created || []).map((d) => (
          <div key={d.draft_id} className="border border-[#C89434] bg-[#FBEFD3]/50 rounded-md p-3 text-xs w-full" data-testid={`ada-draft-${d.draft_id}`}>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#7A5410] mb-1 inline-flex items-center gap-1">
              <FileText size={11} /> Draft ready — {d.target_doc_line_label}
            </div>
            <div className="text-[#2A2A2A]">{d.filename}</div>
            <div className="mt-2 flex gap-2">
              <button onClick={() => onViewDraft(d.preview_file_id)} className="byrd-btn byrd-btn-outline h-8 px-2 text-[11px]" data-testid="ada-view-draft">
                <FileText size={11} /> View
              </button>
              <button onClick={() => onConfirmUpload(d)} className="byrd-btn byrd-btn-dark h-8 px-2 text-[11px]" data-testid="ada-upload-draft">
                <Upload size={11} /> Approve &amp; Upload
              </button>
            </div>
          </div>
        ))}

        {!isUser && (m.uploads_done || []).map((u) => (
          <div key={u.draft_id} className="border border-[#245C25] bg-[#E5F0E5] rounded-md p-2 text-xs w-full inline-flex items-center gap-1.5 text-[#245C25]">
            <Check size={11} /> Uploaded {u.filename} to your checklist.
          </div>
        ))}

        {!isUser && (m.broker_notes || []).map((b, i) => (
          <div key={i} className="border border-[#23446E] bg-[#E5EEF6] rounded-md p-2 text-xs w-full text-[#23446E]">
            Sent to your broker — they'll follow up.
          </div>
        ))}
      </div>
    </div>
  );
}
