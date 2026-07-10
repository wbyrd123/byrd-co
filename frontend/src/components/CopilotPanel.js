import React, { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { Send, User, Bot } from "lucide-react";
import { toast } from "sonner";

const SUGGESTIONS = [
  "Draft a search campaign for a DTC coffee brand.",
  "Give me 5 headlines for a tax software targeting freelancers.",
  "How do I improve CTR on branded keywords?",
  "Suggest negative keywords for a SaaS trial signup campaign.",
];

const SESSION_KEY = "ac_chat_session";

function getSession() {
  let sid = localStorage.getItem(SESSION_KEY);
  if (!sid) {
    sid = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

export default function CopilotPanel() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef(null);
  const sessionId = useRef(getSession());

  useEffect(() => {
    fetch(`${API_BASE}/chat/history?session_id=${sessionId.current}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("ac_token")}` },
    })
      .then((r) => r.json())
      .then((data) => Array.isArray(data) && setMessages(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const send = async (text) => {
    const content = (text ?? input).trim();
    if (!content || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content }]);
    setMessages((m) => [...m, { role: "assistant", content: "", streaming: true }]);
    setStreaming(true);

    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("ac_token")}`,
        },
        body: JSON.stringify({ session_id: sessionId.current, message: content }),
      });
      if (!res.ok || !res.body) throw new Error("stream failed");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let acc = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const p of parts) {
          const line = p.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            const evt = JSON.parse(payload);
            if (evt.type === "delta") {
              acc += evt.content;
              setMessages((m) => {
                const copy = [...m];
                copy[copy.length - 1] = { role: "assistant", content: acc, streaming: true };
                return copy;
              });
            } else if (evt.type === "done") {
              setMessages((m) => {
                const copy = [...m];
                copy[copy.length - 1] = { role: "assistant", content: acc, streaming: false };
                return copy;
              });
            } else if (evt.type === "error") {
              throw new Error(evt.message);
            }
          } catch (_) {
            // ignore parse errors
          }
        }
      }
    } catch (err) {
      toast.error("Copilot error — check backend");
      setMessages((m) => {
        const copy = [...m];
        if (copy[copy.length - 1]?.streaming) copy.pop();
        return copy;
      });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-1 overflow-y-auto p-4 space-y-4" data-testid="copilot-messages">
        {messages.length === 0 && (
          <div className="space-y-3">
            <div className="font-mono text-[11px] uppercase text-[#555]">// try one</div>
            {SUGGESTIONS.map((s, i) => (
              <button
                key={i}
                data-testid={`suggestion-${i}`}
                onClick={() => send(s)}
                className="w-full text-left text-sm border-2 border-black p-3 hover:bg-black hover:text-white transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-2 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && (
              <div className="w-7 h-7 shrink-0 border-2 border-black bg-black text-white grid place-items-center">
                <Bot size={14} />
              </div>
            )}
            <div
              className={`max-w-[85%] px-3 py-2 text-sm whitespace-pre-wrap border-2 border-black ${
                m.role === "user" ? "bg-[#002FA7] text-white" : "bg-[#F4F4F0]"
              }`}
            >
              {m.content}
              {m.streaming && <span className="caret" />}
            </div>
            {m.role === "user" && (
              <div className="w-7 h-7 shrink-0 border-2 border-black bg-white grid place-items-center">
                <User size={14} />
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="border-t-2 border-black p-3 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about campaigns, copy, keywords…"
          data-testid="copilot-input"
          className="flex-1 h-10 px-3 border-2 border-black font-mono text-sm outline-none focus:ring-0"
        />
        <button
          type="submit"
          data-testid="copilot-send-btn"
          disabled={streaming}
          className="h-10 w-10 bg-black text-white grid place-items-center disabled:opacity-50 press-effect hard-shadow-sm"
        >
          <Send size={14} />
        </button>
      </form>
    </div>
  );
}
