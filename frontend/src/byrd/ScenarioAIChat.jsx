import React, { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "@/lib/api";
import { toast } from "sonner";
import {
  Sparkles, Send, RotateCcw, Check, Building2, MessageSquare,
  FileText, Search, Stethoscope,
} from "lucide-react";

const MODES = [
  { key: "interview", label: "Interview", icon: MessageSquare, hint: "Walk me through the deal" },
  { key: "parse", label: "Parse", icon: FileText, hint: "Paste an OM / term sheet" },
  { key: "analyst", label: "Analyst", icon: Stethoscope, hint: "Sanity-check this scenario" },
];

/**
 * Shared AI chat panel for scenario builder — used by both the dedicated tab
 * and the floating chat drawer. Handles streaming, message history, apply-updates,
 * and lender recommendations.
 */
export default function ScenarioAIChat({
  scenarioId,
  onApplyUpdates,   // (partial) => Promise – patches scenario
  onSendToLender,   // (lenderName) => void  – opens send-package flow
  compact = false,  // true when embedded in floating drawer
}) {
  const [messages, setMessages] = useState([]);
  const [mode, setMode] = useState("interview");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState(""); // live token buffer
  const [error, setError] = useState(null);
  const scrollerRef = useRef(null);
  const controllerRef = useRef(null);

  const loadHistory = async () => {
    try {
      const res = await api.get(`/admin/scenarios/${scenarioId}/ai/messages`);
      setMessages(res.data || []);
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to load chat history");
    }
  };

  useEffect(() => {
    loadHistory();
    return () => controllerRef.current?.abort();
  }, [scenarioId]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setInput("");
    setError(null);
    setStreaming("");
    setBusy(true);

    // Optimistically render the user message
    const optimisticUser = {
      id: `local-${Date.now()}`,
      role: "user",
      mode,
      content: msg,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, optimisticUser]);

    try {
      const controller = new AbortController();
      controllerRef.current = controller;
      const token = localStorage.getItem("ac_token");
      const res = await fetch(`${API_BASE}/admin/scenarios/${scenarioId}/ai/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ mode, message: msg }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({ detail: "Failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let liveBuf = "";

      let reading = true;
      while (reading) {
        const { value, done } = await reader.read();
        if (done) { reading = false; break; }
        buffer += decoder.decode(value, { stream: true });

        // Split on SSE record boundaries
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || ""; // last (possibly-partial) frame stays in buffer

        for (const chunk of parts) {
          const line = chunk.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let evt;
          try {
            evt = JSON.parse(payload);
          } catch { continue; }

          if (evt.type === "token") {
            liveBuf += evt.content;
            // Strip in-progress fenced blocks from what we show live
            const cutIdx = liveBuf.search(/```(updates|lenders)/);
            const visible = cutIdx >= 0 ? liveBuf.slice(0, cutIdx) : liveBuf;
            setStreaming(visible);
          } else if (evt.type === "done") {
            setMessages((m) => [
              ...m,
              {
                id: evt.message_id,
                role: "assistant",
                mode,
                content: evt.text,
                updates: evt.updates,
                lender_recs: evt.lender_recs,
                created_at: new Date().toISOString(),
              },
            ]);
            setStreaming("");
          } else if (evt.type === "error") {
            throw new Error(evt.message);
          }
        }
      }
    } catch (e) {
      if (e.name === "AbortError") {
        // silent
      } else {
        setError(e.message || "Streaming failed");
        toast.error(e.message || "Streaming failed");
      }
    } finally {
      setBusy(false);
      controllerRef.current = null;
    }
  };

  const reset = async () => {
    if (!window.confirm("Clear this conversation? The scenario itself is not affected.")) return;
    await api.post(`/admin/scenarios/${scenarioId}/ai/reset`);
    setMessages([]);
    setStreaming("");
    toast.success("Chat cleared");
  };

  const applyUpdates = async (m) => {
    if (!m.updates) return;
    try {
      await onApplyUpdates(m.updates);
      toast.success("Scenario updated");
      // Mark this message as applied locally
      setMessages((list) => list.map((x) => (x.id === m.id ? { ...x, _applied: true } : x)));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to apply updates");
    }
  };

  return (
    <div className={`flex flex-col ${compact ? "h-full" : "h-[70vh] min-h-[520px]"}`} data-testid="ai-chat-root">
      {/* Mode selector */}
      <div className="border-b border-[#E4DFD1] px-4 py-3 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5">
          {MODES.map((m) => {
            const active = mode === m.key;
            return (
              <button
                key={m.key}
                onClick={() => setMode(m.key)}
                className={`text-xs px-2.5 h-8 rounded-md border inline-flex items-center gap-1.5 ${
                  active
                    ? "bg-[#1A1A1A] text-white border-[#1A1A1A]"
                    : "bg-white text-[#2A2A2A] border-[#E4DFD1] hover:bg-[#F3EEE0]"
                }`}
                data-testid={`ai-mode-${m.key}`}
                title={m.hint}
              >
                <m.icon size={12} /> {m.label}
              </button>
            );
          })}
        </div>
        <button
          onClick={reset}
          className="text-[11px] text-[#6B6558] hover:text-[#8A1F1A] inline-flex items-center gap-1"
          data-testid="ai-reset-btn"
        >
          <RotateCcw size={12} /> Clear chat
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollerRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4 bg-[#FBF8F1]">
        {messages.length === 0 && !streaming && (
          <EmptyState mode={mode} />
        )}

        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            m={m}
            onApply={() => applyUpdates(m)}
            onSendToLender={onSendToLender}
          />
        ))}

        {streaming && (
          <MessageBubble
            m={{ role: "assistant", content: streaming, _streaming: true }}
          />
        )}

        {busy && !streaming && (
          <div className="text-xs text-[#6B6558] flex items-center gap-2">
            <Sparkles size={12} className="animate-pulse" /> Thinking…
          </div>
        )}

        {error && (
          <div className="text-xs text-[#8A1F1A] bg-[#FADCDA] border border-[#E38380] rounded-md px-3 py-2">
            {error}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-[#E4DFD1] px-4 py-3 bg-white">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={
              mode === "parse"
                ? "Paste the OM, term sheet or notes here…"
                : mode === "analyst"
                ? "Ask me to review this deal, e.g. 'Which lenders fit?' or 'Is my DSCR OK?'"
                : "Tell me about the deal, or answer my last question…"
            }
            rows={compact ? 2 : 3}
            className="flex-1 px-3 py-2 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] resize-none"
            data-testid="ai-input"
            disabled={busy}
          />
          <button
            onClick={send}
            disabled={busy || !input.trim()}
            className="byrd-btn byrd-btn-dark h-11 px-4 shrink-0"
            data-testid="ai-send-btn"
          >
            <Send size={14} /> {busy ? "…" : "Send"}
          </button>
        </div>
        <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mt-2">
          Claude Sonnet 4.5 · scenario &amp; lender directory in context · Enter to send
        </div>
      </div>
    </div>
  );
}

function EmptyState({ mode }) {
  const copy = {
    interview: {
      title: "Let's build a deal together.",
      body: "Tell me what you know — property type, location, loan size, sponsor. I'll ask for what's missing and fill the scenario as we go.",
      example: "e.g. \"Refi request. 12-unit multifamily in Sugar Land TX. NOI $180k. Looking for $2M.\"",
    },
    parse: {
      title: "Drop in your source material.",
      body: "Paste an OM, term sheet, email, or napkin notes. I'll extract the scenario fields — conservatively, leaving anything uncertain blank.",
      example: "e.g. paste \"Class B office · 45k SF · Houston · 82% occupied · $310k NOI · $2.9M balance…\"",
    },
    analyst: {
      title: "I'll pressure-test this deal.",
      body: "I'll flag metric issues (DSCR, LTV, debt yield), suggest fixes, and recommend which lenders from your directory fit best.",
      example: "e.g. \"Which lenders fit this best?\" or \"Anything I should fix before I shop it?\"",
    },
  }[mode];

  return (
    <div className="text-center py-10 max-w-md mx-auto">
      <div className="w-12 h-12 mx-auto rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1]">
        <Sparkles size={20} />
      </div>
      <h3 className="font-serif text-xl font-bold mt-4">{copy.title}</h3>
      <p className="text-sm text-[#6B6558] mt-2">{copy.body}</p>
      <div className="text-[11px] text-[#6B6558] italic mt-3 border-l-2 border-[#E4DFD1] pl-3 text-left">
        {copy.example}
      </div>
    </div>
  );
}

function MessageBubble({ m, onApply, onSendToLender }) {
  const isUser = m.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`} data-testid={`ai-msg-${m.role}`}>
      <div className={`max-w-[85%] ${isUser ? "" : "space-y-2 w-full"}`}>
        <div
          className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap leading-relaxed ${
            isUser
              ? "bg-[#1A1A1A] text-white"
              : "bg-white border border-[#E4DFD1] text-[#2A2A2A]"
          }`}
        >
          {!isUser && (
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-1 inline-flex items-center gap-1">
              <Sparkles size={10} className="text-[#C89434]" /> Claude {m.mode ? `· ${m.mode}` : ""}
              {m._streaming && <span className="animate-pulse ml-1">▍</span>}
            </div>
          )}
          {m.content}
        </div>

        {/* Proposed updates card */}
        {!isUser && m.updates && Object.keys(m.updates).length > 0 && (
          <UpdatesCard updates={m.updates} applied={m._applied} onApply={onApply} />
        )}

        {/* Lender recommendations */}
        {!isUser && m.lender_recs && m.lender_recs.length > 0 && (
          <LenderRecs recs={m.lender_recs} onSendToLender={onSendToLender} />
        )}
      </div>
    </div>
  );
}

function UpdatesCard({ updates, applied, onApply }) {
  const [expanded, setExpanded] = useState(false);
  // Count non-empty leaf values for a nice summary chip count
  const countFields = (obj) => {
    let n = 0;
    for (const v of Object.values(obj || {})) {
      if (v === null || v === undefined || v === "") continue;
      if (Array.isArray(v)) { if (v.length) n += 1; }
      else if (typeof v === "object") n += countFields(v);
      else n += 1;
    }
    return n;
  };
  const fieldCount = countFields(updates);

  return (
    <div className="border border-[#C89434] rounded-lg bg-[#FBEFD3]/60 p-3" data-testid="ai-updates-card">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-sm font-semibold text-[#7A5410] inline-flex items-center gap-2">
          <Sparkles size={14} /> Proposed field updates ({fieldCount})
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[11px] underline text-[#7A5410]"
            data-testid="ai-updates-toggle"
          >
            {expanded ? "Hide diff" : "Show diff"}
          </button>
          {applied ? (
            <span className="byrd-chip byrd-chip-green"><Check size={10} /> Applied</span>
          ) : (
            <button
              onClick={onApply}
              className="byrd-btn byrd-btn-dark h-8 px-3 text-xs"
              data-testid="ai-apply-updates"
            >
              <Check size={12} /> Apply to Scenario
            </button>
          )}
        </div>
      </div>
      {expanded && (
        <pre className="mt-2 text-[11px] bg-white border border-[#E4DFD1] rounded-md p-2 overflow-x-auto max-h-64 overflow-y-auto text-[#2A2A2A]">
          {JSON.stringify(updates, null, 2)}
        </pre>
      )}
    </div>
  );
}

function LenderRecs({ recs, onSendToLender }) {
  return (
    <div className="border border-[#8DBE8F] rounded-lg bg-[#E4F4E4]/50 p-3" data-testid="ai-lender-recs">
      <div className="text-sm font-semibold text-[#245C25] inline-flex items-center gap-2 mb-2">
        <Search size={14} /> Recommended lenders ({recs.length})
      </div>
      <div className="space-y-2">
        {recs.map((r, i) => (
          <div
            key={i}
            className="flex items-start justify-between gap-2 bg-white border border-[#E4DFD1] rounded-md px-3 py-2"
            data-testid={`ai-lender-rec-${i}`}
          >
            <div className="min-w-0">
              <div className="text-sm font-semibold inline-flex items-center gap-1.5">
                <Building2 size={12} /> {r.name}
              </div>
              {r.reason && <div className="text-[11px] text-[#6B6558] mt-0.5">{r.reason}</div>}
            </div>
            {onSendToLender && (
              <button
                onClick={() => onSendToLender(r.name)}
                className="byrd-btn byrd-btn-outline h-8 px-3 text-[11px] shrink-0"
                data-testid={`ai-send-lender-${i}`}
              >
                Send Package
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
