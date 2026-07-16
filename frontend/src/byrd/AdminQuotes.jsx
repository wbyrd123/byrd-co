import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Mail, Phone, Inbox } from "lucide-react";

const fmtDate = (iso) => {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch { return iso; }
};

export default function AdminQuotes() {
  const [quotes, setQuotes] = useState([]);
  const [active, setActive] = useState(null);

  const load = () => api.get("/admin/quotes").then((r) => {
    setQuotes(r.data);
    if (!active && r.data.length) setActive(r.data[0]);
  });
  useEffect(() => { load(); }, []);

  const markRead = async (q) => {
    if (q.read) return;
    await api.patch(`/admin/quotes/${q.id}`, { read: true });
    setQuotes((prev) => prev.map((x) => (x.id === q.id ? { ...x, read: true } : x)));
  };

  return (
    <div className="space-y-6" data-testid="admin-quotes">
      <div>
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Inbox</div>
        <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Quote Requests.</h1>
      </div>

      {quotes.length === 0 ? (
        <div className="byrd-card p-10 text-center">
          <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]">
            <Inbox size={22} />
          </div>
          <h3 className="font-serif text-2xl font-bold mt-4">Inbox is empty.</h3>
          <p className="text-[#6B6558] mt-2">Quote requests from the website land here.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-6">
          <ul className="byrd-card overflow-hidden divide-y divide-[#E4DFD1] max-h-[70vh] overflow-y-auto">
            {quotes.map((q) => (
              <li key={q.id}>
                <button
                  onClick={() => { setActive(q); markRead(q); }}
                  data-testid={`quote-item-${q.id}`}
                  className={`w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-[#FBF8F1] ${active?.id === q.id ? "bg-[#FBF8F1]" : ""}`}
                >
                  <div className="w-9 h-9 rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center shrink-0 font-semibold text-sm">
                    {q.name?.[0]?.toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div className="font-semibold truncate">{q.name}</div>
                      {!q.read && <span className="w-2 h-2 rounded-full bg-[#C89434] shrink-0" />}
                    </div>
                    <div className="text-xs text-[#6B6558] truncate">{q.email}</div>
                    <div className="text-xs text-[#6B6558] mt-1">{fmtDate(q.created_at)}</div>
                  </div>
                </button>
              </li>
            ))}
          </ul>

          {active && (
            <div className="byrd-card p-6 md:p-8" data-testid="quote-detail">
              <div className="flex items-start justify-between flex-wrap gap-4">
                <div>
                  <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// From</div>
                  <h2 className="font-serif text-3xl font-bold mt-1">{active.name}</h2>
                  <div className="mt-2 flex flex-wrap gap-4 text-sm">
                    <a href={`mailto:${active.email}`} className="inline-flex items-center gap-1 hover:text-[#C89434]">
                      <Mail size={12} /> {active.email}
                    </a>
                    {active.phone && (
                      <a href={`tel:${active.phone}`} className="inline-flex items-center gap-1 hover:text-[#C89434]">
                        <Phone size={12} /> {active.phone}
                      </a>
                    )}
                  </div>
                </div>
                <div className="text-xs text-[#6B6558]">{fmtDate(active.created_at)}</div>
              </div>

              <hr className="byrd-rule my-6" />

              <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                <div>
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Loan Type</dt>
                  <dd className="mt-1 font-semibold">{active.loan_type || "—"}</dd>
                </div>
                <div>
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Loan Amount</dt>
                  <dd className="mt-1 font-semibold">{active.loan_amount || "—"}</dd>
                </div>
                <div>
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Property Type</dt>
                  <dd className="mt-1 font-semibold">{active.property_type || "—"}</dd>
                </div>
              </dl>

              {active.message && (
                <>
                  <hr className="byrd-rule my-6" />
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Message</div>
                    <p className="mt-2 text-[#1A1A1A] whitespace-pre-wrap leading-relaxed">{active.message}</p>
                  </div>
                </>
              )}

              <div className="mt-8 flex gap-3">
                <a href={`mailto:${active.email}`} className="byrd-btn byrd-btn-primary" data-testid="quote-reply">
                  <Mail size={14} /> Reply
                </a>
                {active.phone && (
                  <a href={`tel:${active.phone}`} className="byrd-btn byrd-btn-outline">
                    <Phone size={14} /> Call
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
