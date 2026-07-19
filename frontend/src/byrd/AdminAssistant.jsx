import React, { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import {
  Sparkles, Send, RotateCcw, Check, Mail, User, Calendar, X, AlertCircle,
  ChevronRight, Edit3, Plus, ArrowRight, Users as UsersIcon, Reply,
} from "lucide-react";

const firstName = (u) => (u?.name || u?.email || "there").split(" ")[0].split("@")[0];

const fmtDue = (iso) => {
  if (!iso) return "";
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
};

const dueColor = (iso, today) => {
  if (!iso) return "text-[#6B6558]";
  if (iso < today) return "text-[#8A1F1A]";
  if (iso === today) return "text-[#7A5410]";
  return "text-[#6B6558]";
};

export default function AdminAssistant() {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [buckets, setBuckets] = useState({ overdue: [], due_today: [], upcoming: [], done: [], dismissed: [] });
  const [teammates, setTeammates] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [mentionQuery, setMentionQuery] = useState(null); // null | { text: string, caret: number }
  const [mentionIdx, setMentionIdx] = useState(0);
  const scrollerRef = useRef(null);
  const inputRef = useRef(null);
  const controllerRef = useRef(null);
  const today = new Date().toISOString().slice(0, 10);

  const buildGreeting = (name, msgs, tasks) => {
    const overdueN = tasks.overdue.length;
    const todayN = tasks.due_today.length;
    const openList = [...tasks.overdue, ...tasks.due_today, ...tasks.upcoming];
    const handoffs = openList.filter((t) => t.assigned_by_name);
    const handoffByPerson = {};
    handoffs.forEach((t) => {
      const from = (t.assigned_by_name || "").split(" ")[0];
      handoffByPerson[from] = (handoffByPerson[from] || 0) + 1;
    });
    const handoffSummary = Object.entries(handoffByPerson)
      .map(([n, c]) => `${c} from ${n}`).join(", ");
    if (overdueN > 0 || todayN > 0) {
      return `Hi ${name} — you have ${overdueN ? `${overdueN} overdue` : ""}${overdueN && todayN ? " and " : ""}${todayN ? `${todayN} due today` : ""}${handoffSummary ? ` (including ${handoffSummary})` : ""}. Did you handle any of these?`;
    }
    if (handoffs.length > 0) {
      return `Hi ${name} — ${handoffSummary} on your list. Want to talk through any of them?`;
    }
    if (msgs.length === 0) {
      return `Hi ${name}, how are you today? Anything you'd like to hand off to me — a client to follow up with, a note for a teammate, something you need reminded of?`;
    }
    return null;
  };

  const loadAll = async () => {
    const [msgs, tasks] = await Promise.all([
      api.get("/admin/assistant/messages").then((r) => r.data),
      api.get("/admin/assistant/tasks").then((r) => r.data),
    ]);
    // Compute greeting once, use functional setState so strict-mode double-fires
    // don't wipe the greeting.
    setMessages((prev) => {
      const hasGreeting = prev.some((m) => m._greeting);
      if (hasGreeting) return msgs.length ? [prev.find((m) => m._greeting), ...msgs] : prev;
      if (!user) return msgs;
      const greeting = buildGreeting(firstName(user), msgs, tasks);
      if (!greeting) return msgs;
      return [
        {
          id: "greeting-" + Date.now(),
          role: "assistant",
          content: greeting,
          _greeting: true,
          created_at: new Date().toISOString(),
        },
        ...msgs,
      ];
    });
    setBuckets(tasks);
    return { msgs, tasks };
  };

  useEffect(() => {
    if (user) loadAll();
    api.get("/admin/assistant/teammates").then((r) => setTeammates(r.data)).catch(() => {});
    return () => controllerRef.current?.abort();
  }, [user]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setInput("");
    setStreaming("");
    setBusy(true);

    setMessages((m) => [
      ...m,
      { id: `local-${Date.now()}`, role: "user", content: msg, created_at: new Date().toISOString() },
    ]);

    try {
      const controller = new AbortController();
      controllerRef.current = controller;
      const token = localStorage.getItem("ac_token");
      const res = await fetch(`${API_BASE}/admin/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: msg }),
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
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const chunk of parts) {
          const line = chunk.trim();
          if (!line.startsWith("data:")) continue;
          let evt;
          try { evt = JSON.parse(line.slice(5).trim()); } catch { continue; }
          if (evt.type === "token") {
            liveBuf += evt.content;
            const cutIdx = liveBuf.search(/```(new_tasks|complete_tasks|email_draft|suggest_client)/);
            setStreaming(cutIdx >= 0 ? liveBuf.slice(0, cutIdx) : liveBuf);
          } else if (evt.type === "done") {
            setMessages((m) => [
              ...m,
              {
                id: evt.message_id,
                role: "assistant",
                content: evt.text,
                email_draft: evt.email_draft,
                suggest_client: evt.suggest_client,
                created_tasks: evt.created_tasks,
                completed_task_ids: evt.completed_task_ids,
                handoffs_sent: evt.handoffs_sent,
                created_at: new Date().toISOString(),
              },
            ]);
            setStreaming("");
            // Refresh tasks
            api.get("/admin/assistant/tasks").then((r) => setBuckets(r.data));
          } else if (evt.type === "error") {
            throw new Error(evt.message);
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") toast.error(e.message || "Failed");
    } finally {
      setBusy(false);
      controllerRef.current = null;
    }
  };

  const reset = async () => {
    if (!window.confirm("Clear this conversation? Your tasks are safe.")) return;
    await api.post("/admin/assistant/reset");
    setMessages([]);
    toast.success("Conversation cleared");
  };

  const completeTask = async (t) => {
    await api.patch(`/admin/assistant/tasks/${t.id}`, { status: "done" });
    api.get("/admin/assistant/tasks").then((r) => setBuckets(r.data));
    toast.success("Marked done");
  };

  const dismissTask = async (t) => {
    await api.patch(`/admin/assistant/tasks/${t.id}`, { status: "dismissed" });
    api.get("/admin/assistant/tasks").then((r) => setBuckets(r.data));
  };

  const replyToTask = async (t, message, markDone) => {
    try {
      await api.post(`/admin/assistant/tasks/${t.id}/reply`, { message, mark_done: markDone });
      api.get("/admin/assistant/tasks").then((r) => setBuckets(r.data));
      toast.success(`Reply sent to ${t.assigned_by_name.split(" ")[0]}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Reply failed");
    }
  };

  const sendEmail = async (draft, msgId) => {
    try {
      await api.post("/admin/assistant/email/send", draft);
      toast.success(`Email sent to ${draft.to}`);
      setMessages((m) => m.map((x) => (x.id === msgId ? { ...x, _emailSent: true, _emailError: null } : x)));
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Email failed";
      // Persist the error on the draft card so it stays visible after the toast fades
      setMessages((m) => m.map((x) => (x.id === msgId ? { ...x, _emailError: detail } : x)));
      toast.error("Email failed — see the draft card for details");
    }
  };

  const createClientFromSuggestion = async (name, msgId) => {
    // Prompt for email (required)
    const email = window.prompt(`Email address for ${name}?\n\n(Required to create a portal invite.)`, "");
    if (!email) return;
    try {
      const res = await api.post("/admin/invites", { name, email });
      toast.success(`${name} added — invite link copied`);
      const url = `${window.location.origin}${res.data.invite_url_path}`;
      navigator.clipboard.writeText(url).catch(() => {});
      setMessages((m) => m.map((x) => (x.id === msgId ? { ...x, _clientAdded: true } : x)));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to add client");
    }
  };

  const openList = [...buckets.overdue, ...buckets.due_today, ...buckets.upcoming];

  // Mention autocomplete: derive matches based on current @query
  const filteredMentions = mentionQuery === null
    ? []
    : teammates.filter((tm) => tm.first_name.toLowerCase().startsWith(mentionQuery.text.toLowerCase())).slice(0, 6);

  const handleInputChange = (value, caret) => {
    setInput(value);
    // Look backwards from caret to find an @ that starts a mention token
    const upToCaret = value.slice(0, caret);
    const match = upToCaret.match(/(?:^|\s)@([A-Za-z]*)$/);
    if (match) {
      setMentionQuery({ text: match[1], caret });
      setMentionIdx(0);
    } else {
      setMentionQuery(null);
    }
  };

  const insertMention = (tm) => {
    const caret = mentionQuery?.caret ?? input.length;
    const before = input.slice(0, caret);
    const after = input.slice(caret);
    // Replace the partial "@abc" that immediately precedes the caret
    const replaced = before.replace(/@[A-Za-z]*$/, `@${tm.first_name} `);
    const nextValue = replaced + after;
    setInput(nextValue);
    setMentionQuery(null);
    setMentionIdx(0);
    // Restore focus + caret
    setTimeout(() => {
      const el = inputRef.current;
      if (el) {
        const pos = replaced.length;
        el.focus();
        el.setSelectionRange(pos, pos);
      }
    }, 0);
  };

  const handleInputKeyDown = (e) => {
    if (mentionQuery !== null && filteredMentions.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setMentionIdx((i) => Math.min(i + 1, filteredMentions.length - 1)); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setMentionIdx((i) => Math.max(i - 1, 0)); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); insertMention(filteredMentions[mentionIdx]); return; }
      if (e.key === "Escape")    { e.preventDefault(); setMentionQuery(null); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <div className="space-y-6" data-testid="admin-assistant">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// AI · Private to you</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Personal Assistant.</h1>
          <p className="text-sm text-[#6B6558] mt-2 max-w-xl">
            A private space just for you, {firstName(user)}. Tell me what&apos;s on your plate — I&apos;ll track it,
            remind you when it&apos;s due, and help you email clients.
          </p>
        </div>
        <div className="text-right">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Today</div>
          <div className="font-serif text-lg font-bold">
            {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
        {/* Chat panel */}
        <div className="byrd-card flex flex-col h-[72vh] min-h-[560px] overflow-hidden">
          <div className="border-b border-[#E4DFD1] px-4 py-3 flex items-center justify-between">
            <div className="inline-flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1]">
                <Sparkles size={14} />
              </div>
              <div className="leading-tight">
                <div className="font-serif text-lg font-bold">Assistant</div>
                <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">
                  {firstName(user)}&apos;s private chat
                </div>
              </div>
            </div>
            <button
              onClick={reset}
              className="text-[11px] text-[#6B6558] hover:text-[#8A1F1A] inline-flex items-center gap-1"
              data-testid="assistant-reset"
            >
              <RotateCcw size={12} /> Clear chat
            </button>
          </div>

          <div ref={scrollerRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-[#FBF8F1]">
            {messages.map((m) => (
              <Bubble
                key={m.id}
                m={m}
                onSendEmail={sendEmail}
                onCreateClient={createClientFromSuggestion}
              />
            ))}

            {streaming && <Bubble m={{ role: "assistant", content: streaming, _streaming: true }} />}

            {busy && !streaming && (
              <div className="text-xs text-[#6B6558] flex items-center gap-2">
                <Sparkles size={12} className="animate-pulse text-[#C89434]" /> Thinking…
              </div>
            )}
          </div>

          <div className="border-t border-[#E4DFD1] px-4 py-3 bg-white relative">
            {/* Mention autocomplete popover */}
            {mentionQuery !== null && filteredMentions.length > 0 && (
              <div
                className="absolute bottom-full left-4 mb-2 bg-white border border-[#E4DFD1] rounded-md shadow-lg min-w-[220px] py-1 z-10"
                data-testid="mention-popover"
              >
                <div className="px-2 pt-1 pb-0.5 font-mono text-[9px] uppercase tracking-widest text-[#6B6558]">
                  Hand off to…
                </div>
                {filteredMentions.map((tm, i) => (
                  <button
                    key={tm.id}
                    onMouseDown={(e) => { e.preventDefault(); insertMention(tm); }}
                    onMouseEnter={() => setMentionIdx(i)}
                    className={`w-full text-left px-2 py-1.5 flex items-center gap-2 text-sm ${
                      i === mentionIdx ? "bg-[#F3EEE0]" : "hover:bg-[#FBF8F1]"
                    }`}
                    data-testid={`mention-option-${tm.first_name.toLowerCase()}`}
                  >
                    <div className="w-6 h-6 rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1] font-serif font-bold text-[11px]">
                      {tm.first_name[0]}
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold leading-tight">{tm.first_name}</div>
                      <div className="text-[10px] text-[#6B6558] leading-tight">{tm.email}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => handleInputChange(e.target.value, e.target.selectionStart)}
                onKeyDown={handleInputKeyDown}
                onBlur={() => setTimeout(() => setMentionQuery(null), 150)}
                placeholder="Tell me what's going on, ask me to email a client, or type @name to hand off…"
                rows={2}
                disabled={busy}
                data-testid="assistant-input"
                className="flex-1 px-3 py-2 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] resize-none"
              />
              <button
                onClick={send}
                disabled={busy || !input.trim()}
                className="byrd-btn byrd-btn-dark h-11 px-4 shrink-0"
                data-testid="assistant-send"
              >
                <Send size={14} /> {busy ? "…" : "Send"}
              </button>
            </div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mt-2">
              Claude Sonnet 4.5 · Enter to send · <span className="normal-case tracking-normal">type <code className="font-mono bg-[#F3EEE0] px-1 rounded">@name</code> to hand off</span>
            </div>
          </div>
        </div>

        {/* Task rail */}
        <TaskRail
          buckets={buckets}
          today={today}
          openList={openList}
          onComplete={completeTask}
          onDismiss={dismissTask}
          onReply={replyToTask}
          onRefresh={() => api.get("/admin/assistant/tasks").then((r) => setBuckets(r.data))}
        />
      </div>
    </div>
  );
}

function Bubble({ m, onSendEmail, onCreateClient }) {
  const isUser = m.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[92%] ${isUser ? "" : "space-y-2 w-full"}`}>
        <div
          className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap leading-relaxed ${
            isUser ? "bg-[#1A1A1A] text-white" : "bg-white border border-[#E4DFD1] text-[#2A2A2A]"
          }`}
        >
          {!isUser && (
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-1 inline-flex items-center gap-1">
              <Sparkles size={10} className="text-[#C89434]" /> Assistant
              {m._streaming && <span className="animate-pulse ml-1">▍</span>}
            </div>
          )}
          {m.content}
        </div>

        {!isUser && m.created_tasks && m.created_tasks.length > 0 && (
          <div className="border border-[#8DBE8F] bg-[#E4F4E4]/40 rounded-md p-2.5 text-xs">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#245C25] mb-1 inline-flex items-center gap-1">
              <Check size={10} /> Tasks added ({m.created_tasks.length})
            </div>
            {m.created_tasks.map((t) => (
              <div key={t.id} className="text-[#2A2A2A]">
                • {t.title}
                {t.due_date && <span className="text-[#6B6558]"> — due {fmtDue(t.due_date)}</span>}
              </div>
            ))}
          </div>
        )}

        {!isUser && m.handoffs_sent && m.handoffs_sent.length > 0 && (
          <div className="border border-[#1A1A1A] bg-[#F3EEE0] rounded-md p-3 text-xs" data-testid="handoff-sent-card">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#1A1A1A] mb-1.5 inline-flex items-center gap-1">
              <ArrowRight size={10} /> Handed off ({m.handoffs_sent.length})
            </div>
            {m.handoffs_sent.map((h) => (
              <div key={h.task_id} className="mt-1 pt-1 first:mt-0 first:pt-0 border-t border-[#E4DFD1] first:border-t-0">
                <div className="inline-flex items-center gap-1 font-semibold text-[#2A2A2A]">
                  <UsersIcon size={11} /> To {h.to_name}
                  {h.due_date && <span className="text-[#6B6558] font-normal">· due {fmtDue(h.due_date)}</span>}
                </div>
                <div className="text-[#2A2A2A] mt-0.5">{h.title}</div>
                {h.note && (
                  <div className="mt-1 text-[11px] text-[#6B6558] italic bg-white/60 border border-[#E4DFD1] rounded-sm px-2 py-1">
                    &ldquo;{h.note}&rdquo;
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {!isUser && m.email_draft && (
          <EmailDraftCard
            draft={m.email_draft}
            sent={m._emailSent}
            error={m._emailError}
            onSend={(d) => onSendEmail(d, m.id)}
          />
        )}

        {!isUser && m.suggest_client && !m._clientAdded && (
          <div className="border border-[#C89434] bg-[#FBEFD3]/60 rounded-md p-3 text-xs" data-testid="suggest-client-card">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="inline-flex items-center gap-2 text-[#7A5410]">
                <User size={12} />
                <span className="font-semibold">Add {m.suggest_client.name} as a client?</span>
              </div>
              <button
                onClick={() => onCreateClient(m.suggest_client.name, m.id)}
                className="byrd-btn byrd-btn-dark h-8 px-3 text-[11px]"
                data-testid="create-client-suggested"
              >
                <Plus size={11} /> Add Client
              </button>
            </div>
            {m.suggest_client.hint && (
              <div className="text-[11px] text-[#7A5410] mt-1">{m.suggest_client.hint}</div>
            )}
          </div>
        )}

        {!isUser && m._clientAdded && (
          <div className="text-[11px] text-[#245C25] inline-flex items-center gap-1">
            <Check size={11} /> Client added — invite link copied to clipboard
          </div>
        )}
      </div>
    </div>
  );
}

function EmailDraftCard({ draft, sent, error, onSend }) {
  const [d, setD] = useState(draft);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    setBusy(true);
    try {
      await onSend(d);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border border-[#C89434] bg-[#FBEFD3]/40 rounded-lg p-3" data-testid="email-draft-card">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
        <div className="inline-flex items-center gap-2 text-[#7A5410]">
          <Mail size={13} />
          <span className="text-xs font-semibold">Email draft</span>
        </div>
        <div className="flex items-center gap-2">
          {sent ? (
            <span className="byrd-chip byrd-chip-green"><Check size={10} /> Sent</span>
          ) : (
            <>
              <button
                onClick={() => setEditing((v) => !v)}
                className="text-[11px] text-[#7A5410] underline"
                data-testid="email-edit-toggle"
              >
                <Edit3 size={11} className="inline mr-1" />
                {editing ? "Preview" : "Edit"}
              </button>
              <button
                onClick={send}
                disabled={busy}
                className="byrd-btn byrd-btn-dark h-8 px-3 text-[11px]"
                data-testid="email-send"
              >
                {busy ? "Sending…" : error ? <><Send size={11} /> Retry</> : <><Send size={11} /> Send</>}
              </button>
            </>
          )}
        </div>
      </div>

      {error && !sent && (
        <div
          className="mb-2 text-[11px] bg-[#FADCDA] border border-[#E38380] text-[#8A1F1A] rounded-md px-2 py-1.5 leading-snug"
          data-testid="email-error"
        >
          <div className="font-semibold inline-flex items-center gap-1 mb-0.5">
            <AlertCircle size={11} /> Not sent
          </div>
          {error}
        </div>
      )}

      {editing ? (
        <div className="space-y-2">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">To</div>
            <input
              value={d.to}
              onChange={(e) => setD({ ...d, to: e.target.value })}
              className="w-full h-9 px-2 rounded-md border border-[#E4DFD1] bg-white text-xs"
              data-testid="email-to"
            />
          </div>
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Subject</div>
            <input
              value={d.subject}
              onChange={(e) => setD({ ...d, subject: e.target.value })}
              className="w-full h-9 px-2 rounded-md border border-[#E4DFD1] bg-white text-xs"
              data-testid="email-subject"
            />
          </div>
          <div>
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Body</div>
            <textarea
              value={d.body}
              onChange={(e) => setD({ ...d, body: e.target.value })}
              rows={6}
              className="w-full px-2 py-1.5 rounded-md border border-[#E4DFD1] bg-white text-xs font-mono resize-y"
              data-testid="email-body"
            />
          </div>
        </div>
      ) : (
        <div className="text-xs space-y-1">
          <div><span className="text-[#6B6558]">To:</span> <span className="font-mono">{d.to}</span></div>
          <div><span className="text-[#6B6558]">Subject:</span> <span className="font-semibold">{d.subject}</span></div>
          <div className="mt-2 whitespace-pre-wrap bg-white border border-[#E4DFD1] rounded-md p-2 text-[#2A2A2A] leading-relaxed">
            {d.body}
          </div>
        </div>
      )}
    </div>
  );
}

function TaskRail({ buckets, today, openList, onComplete, onDismiss, onReply, onRefresh }) {
  return (
    <aside className="byrd-card p-4 space-y-5 h-fit sticky top-6" data-testid="task-rail">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Task list</div>
          <h3 className="font-serif text-lg font-bold mt-0.5">
            {openList.length} open {openList.length === 1 ? "task" : "tasks"}
          </h3>
        </div>
        <button
          onClick={onRefresh}
          className="text-[10px] text-[#6B6558] hover:text-[#1A1A1A] font-mono uppercase tracking-widest"
          data-testid="task-refresh"
        >
          Refresh
        </button>
      </div>

      <TaskSection
        title="Overdue"
        tone="bad"
        icon={AlertCircle}
        items={buckets.overdue}
        today={today}
        onComplete={onComplete}
        onDismiss={onDismiss}
        onReply={onReply}
      />
      <TaskSection
        title="Due Today"
        tone="warn"
        icon={Calendar}
        items={buckets.due_today}
        today={today}
        onComplete={onComplete}
        onDismiss={onDismiss}
        onReply={onReply}
      />
      <TaskSection
        title="Upcoming"
        tone="default"
        icon={ChevronRight}
        items={buckets.upcoming}
        today={today}
        onComplete={onComplete}
        onDismiss={onDismiss}
        onReply={onReply}
      />
      {buckets.done.length > 0 && (
        <TaskSection
          title="Recently Done"
          tone="good"
          icon={Check}
          items={buckets.done}
          today={today}
          isDone
        />
      )}

      {openList.length === 0 && buckets.done.length === 0 && (
        <div className="text-xs text-[#6B6558] text-center py-4">
          Nothing on your list yet. Chat with your assistant and I&apos;ll pin things here.
        </div>
      )}
    </aside>
  );
}

function TaskSection({ title, tone, icon: Icon, items, today, onComplete, onDismiss, onReply, isDone }) {
  if (!items || items.length === 0) return null;
  const chipCls = {
    bad: "byrd-chip byrd-chip-red",
    warn: "byrd-chip byrd-chip-gold",
    good: "byrd-chip byrd-chip-green",
    default: "byrd-chip",
  }[tone];
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] inline-flex items-center gap-1">
          <Icon size={10} /> {title}
        </div>
        <span className={chipCls}>{items.length}</span>
      </div>
      <div className="space-y-2">
        {items.map((t) => (
          <TaskCard
            key={t.id}
            t={t}
            today={today}
            onComplete={onComplete}
            onDismiss={onDismiss}
            onReply={onReply}
            isDone={isDone}
          />
        ))}
      </div>
    </div>
  );
}

function TaskCard({ t, today, onComplete, onDismiss, onReply, isDone }) {
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [markDone, setMarkDone] = useState(true);
  const [sending, setSending] = useState(false);
  const isHandoff = !!t.assigned_by_name;

  const submitReply = async () => {
    if (!replyText.trim()) return;
    setSending(true);
    try {
      await onReply(t, replyText.trim(), markDone);
      setReplyOpen(false);
      setReplyText("");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="border border-[#E4DFD1] rounded-md p-2.5 text-xs bg-white" data-testid={`task-${t.id}`}>
      {isHandoff && (
        <div className="mb-1.5 -mt-0.5 -mx-0.5 rounded-sm bg-[#F3EEE0] px-2 py-1 border border-[#E4DFD1]">
          <div className="font-mono text-[9px] uppercase tracking-widest text-[#1A1A1A] inline-flex items-center gap-1">
            <ArrowRight size={9} /> From {t.assigned_by_name.split(" ")[0]}
          </div>
          {t.handoff_note && (
            <div className="text-[11px] text-[#2A2A2A] italic mt-0.5 leading-snug">
              &ldquo;{t.handoff_note}&rdquo;
            </div>
          )}
        </div>
      )}
      <div className="font-semibold text-[#2A2A2A] leading-snug">{t.title}</div>
      {(t.related_name || t.due_date) && (
        <div className="mt-1 flex items-center gap-2 flex-wrap">
          {t.related_name && <span className="text-[#6B6558]">{t.related_name}</span>}
          {t.due_date && (
            <span className={`font-mono text-[10px] ${dueColor(t.due_date, today)}`}>
              {fmtDue(t.due_date)}
            </span>
          )}
        </div>
      )}
      {!isDone && (
        <>
          <div className="mt-2 flex items-center gap-1.5">
            <button
              onClick={() => onComplete(t)}
              className="flex-1 h-7 rounded-md border border-[#8DBE8F] bg-white text-[#245C25] hover:bg-[#E4F4E4] inline-flex items-center justify-center gap-1 text-[11px]"
              data-testid={`task-complete-${t.id}`}
            >
              <Check size={10} /> Done
            </button>
            {isHandoff && (
              <button
                onClick={() => setReplyOpen((v) => !v)}
                className={`h-7 px-2 rounded-md border inline-flex items-center gap-1 text-[11px] ${
                  replyOpen
                    ? "bg-[#1A1A1A] text-white border-[#1A1A1A]"
                    : "bg-white border-[#E4DFD1] hover:bg-[#F3EEE0]"
                }`}
                title={`Reply to ${t.assigned_by_name.split(" ")[0]}`}
                data-testid={`task-reply-${t.id}`}
              >
                <Reply size={11} /> Reply
              </button>
            )}
            <button
              onClick={() => onDismiss(t)}
              className="w-7 h-7 rounded-md border border-[#E4DFD1] hover:bg-[#FADCDA] hover:border-[#E38380] hover:text-[#8A1F1A] grid place-items-center"
              title="Dismiss"
              data-testid={`task-dismiss-${t.id}`}
            >
              <X size={11} />
            </button>
          </div>
          {replyOpen && (
            <div className="mt-2 border border-[#E4DFD1] rounded-md p-2 bg-[#FBF8F1]" data-testid={`task-reply-box-${t.id}`}>
              <div className="font-mono text-[9px] uppercase tracking-widest text-[#6B6558] mb-1">
                Reply to {t.assigned_by_name.split(" ")[0]}
              </div>
              <textarea
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                placeholder="Called Rod at 3pm — he's putting the docs together and will send tomorrow."
                rows={3}
                className="w-full px-2 py-1.5 rounded-md border border-[#E4DFD1] bg-white text-[11px] focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] resize-y"
                data-testid={`task-reply-text-${t.id}`}
              />
              <label className="mt-1.5 inline-flex items-center gap-1.5 text-[11px] text-[#2A2A2A] cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={markDone}
                  onChange={(e) => setMarkDone(e.target.checked)}
                  className="accent-[#245C25]"
                  data-testid={`task-reply-mark-done-${t.id}`}
                />
                Also mark this task done
              </label>
              <div className="mt-2 flex items-center gap-1.5">
                <button
                  onClick={submitReply}
                  disabled={sending || !replyText.trim()}
                  className="flex-1 h-7 rounded-md bg-[#1A1A1A] text-white hover:bg-[#2A2A2A] inline-flex items-center justify-center gap-1 text-[11px] disabled:opacity-50"
                  data-testid={`task-reply-send-${t.id}`}
                >
                  <Send size={10} /> {sending ? "Sending…" : "Send Reply"}
                </button>
                <button
                  onClick={() => { setReplyOpen(false); setReplyText(""); }}
                  className="h-7 px-2 rounded-md border border-[#E4DFD1] hover:bg-[#F3EEE0] text-[11px]"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
