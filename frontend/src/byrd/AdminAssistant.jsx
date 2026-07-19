import React, { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import {
  Sparkles, Send, RotateCcw, Check, Mail, User, Calendar, X, AlertCircle,
  ChevronRight, Trash2, Edit3, Plus,
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
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [greeted, setGreeted] = useState(false);
  const scrollerRef = useRef(null);
  const controllerRef = useRef(null);
  const today = new Date().toISOString().slice(0, 10);

  const loadAll = async () => {
    const [msgs, tasks] = await Promise.all([
      api.get("/admin/assistant/messages").then((r) => r.data),
      api.get("/admin/assistant/tasks").then((r) => r.data),
    ]);
    setMessages(msgs);
    setBuckets(tasks);
    return { msgs, tasks };
  };

  useEffect(() => {
    loadAll();
    return () => controllerRef.current?.abort();
  }, []);
  useEffect(() => {
    if (greeted || !user) return;
    if (messages.length === 0 || (buckets.overdue.length + buckets.due_today.length) > 0) {
      const name = firstName(user);
      const overdueN = buckets.overdue.length;
      const todayN = buckets.due_today.length;
      let greeting;
      if (overdueN > 0 || todayN > 0) {
        greeting = `Hi ${name} — you have ${overdueN ? `${overdueN} overdue` : ""}${overdueN && todayN ? " and " : ""}${todayN ? `${todayN} due today` : ""}. Did you handle any of these?`;
      } else if (messages.length === 0) {
        greeting = `Hi ${name}, how are you today? Anything you'd like to hand off to me — a client to follow up with, a note for Caleb, something you need reminded of?`;
      }
      if (greeting) {
        setMessages((m) => [
          {
            id: "greeting-" + Date.now(),
            role: "assistant",
            content: greeting,
            _greeting: true,
            created_at: new Date().toISOString(),
          },
          ...m,
        ]);
      }
      setGreeted(true);
    }
  }, [user, buckets, messages.length]);

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
    setGreeted(false);
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

  const sendEmail = async (draft, msgId) => {
    try {
      await api.post("/admin/assistant/email/send", draft);
      toast.success(`Email sent to ${draft.to}`);
      setMessages((m) => m.map((x) => (x.id === msgId ? { ...x, _emailSent: true } : x)));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Email failed");
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

          <div className="border-t border-[#E4DFD1] px-4 py-3 bg-white">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                }}
                placeholder="Tell me what's going on, or ask me to email a client…"
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
              Claude Sonnet 4.5 · Enter to send · your chat is private to your account
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

        {!isUser && m.email_draft && (
          <EmailDraftCard
            draft={m.email_draft}
            sent={m._emailSent}
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

function EmailDraftCard({ draft, sent, onSend }) {
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
                {busy ? "Sending…" : <><Send size={11} /> Send</>}
              </button>
            </>
          )}
        </div>
      </div>

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

function TaskRail({ buckets, today, openList, onComplete, onDismiss, onRefresh }) {
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
      />
      <TaskSection
        title="Due Today"
        tone="warn"
        icon={Calendar}
        items={buckets.due_today}
        today={today}
        onComplete={onComplete}
        onDismiss={onDismiss}
      />
      <TaskSection
        title="Upcoming"
        tone="default"
        icon={ChevronRight}
        items={buckets.upcoming}
        today={today}
        onComplete={onComplete}
        onDismiss={onDismiss}
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

function TaskSection({ title, tone, icon: Icon, items, today, onComplete, onDismiss, isDone }) {
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
          <div key={t.id} className="border border-[#E4DFD1] rounded-md p-2.5 text-xs bg-white" data-testid={`task-${t.id}`}>
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
              <div className="mt-2 flex items-center gap-1.5">
                <button
                  onClick={() => onComplete(t)}
                  className="flex-1 h-7 rounded-md border border-[#8DBE8F] bg-white text-[#245C25] hover:bg-[#E4F4E4] inline-flex items-center justify-center gap-1 text-[11px]"
                  data-testid={`task-complete-${t.id}`}
                >
                  <Check size={10} /> Done
                </button>
                <button
                  onClick={() => onDismiss(t)}
                  className="w-7 h-7 rounded-md border border-[#E4DFD1] hover:bg-[#FADCDA] hover:border-[#E38380] hover:text-[#8A1F1A] grid place-items-center"
                  title="Dismiss"
                  data-testid={`task-dismiss-${t.id}`}
                >
                  <X size={11} />
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
