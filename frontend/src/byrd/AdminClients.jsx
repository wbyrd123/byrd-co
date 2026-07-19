import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, API_BASE } from "@/lib/api";
import { toast } from "sonner";
import { Copy, Plus, Users, X, Check } from "lucide-react";

const InviteDialog = ({ open, onClose, onCreated }) => {
  const [form, setForm] = useState({
    name: "", email: "", company: "", phone: "",
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  if (!open) return null;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name || !form.email) { toast.error("Name and email required"); return; }
    setBusy(true);
    try {
      const res = await api.post("/admin/invites", form);
      setResult(res.data);
      onCreated?.();
      toast.success("Client added — invite link ready to copy");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed");
    } finally {
      setBusy(false);
    }
  };

  const url = result ? `${window.location.origin}${result.invite_url_path}` : "";

  const copy = () => {
    navigator.clipboard.writeText(url);
    toast.success("Copied to clipboard");
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#1A1A1A]/50 grid place-items-center p-4" onClick={onClose}>
      <div
        className="byrd-card w-full max-w-lg p-6 md:p-8"
        onClick={(e) => e.stopPropagation()}
        data-testid="invite-dialog"
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// New Client</div>
            <h2 className="font-serif text-2xl font-bold mt-1">Add Client</h2>
          </div>
          <button onClick={onClose} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]" data-testid="invite-close">
            <X size={16} />
          </button>
        </div>

        {!result ? (
          <form onSubmit={submit} className="mt-6 space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Full name *</label>
                <input required value={form.name} onChange={(e) => set("name", e.target.value)}
                  data-testid="invite-name"
                  className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                />
              </div>
              <div>
                <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Email *</label>
                <input required type="email" value={form.email} onChange={(e) => set("email", e.target.value)}
                  data-testid="invite-email"
                  className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                />
              </div>
              <div>
                <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Company</label>
                <input value={form.company} onChange={(e) => set("company", e.target.value)}
                  className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                />
              </div>
              <div>
                <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Phone</label>
                <input value={form.phone} onChange={(e) => set("phone", e.target.value)}
                  className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                />
              </div>
            </div>
            <div className="text-xs text-[#6B6558]">
              This adds the client to your roster and generates a portal invite link.
              A default document checklist (personal + business 3-yr tax returns, resume, entity docs, etc.)
              is attached automatically — you can edit it after. <b>Loan details</b> live on scenarios, so one
              client can have multiple deals in flight. Send the invite link now or later from the client&apos;s page.
            </div>
            <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark w-full" data-testid="invite-submit">
              {busy ? "Adding…" : "Add Client"}
            </button>
          </form>
        ) : (
          <div className="mt-6 space-y-4" data-testid="invite-result">
            <div className="byrd-chip byrd-chip-green"><Check size={12} /> Client added</div>
            <p className="text-sm text-[#2A2A2A]">
              <span className="font-semibold">{result.user.name}</span> is now in your roster. Share this
              invite link whenever you&apos;re ready — they&apos;ll set a password and land in their portal.
              You can also copy this link later from their client page.
            </p>
            <div className="flex items-center gap-2">
              <input readOnly value={url} className="flex-1 h-11 px-3 rounded-md border border-[#E4DFD1] bg-[#FBF8F1] font-mono text-xs"
                data-testid="invite-link" />
              <button onClick={copy} className="byrd-btn byrd-btn-dark h-11 px-3" data-testid="invite-copy">
                <Copy size={14} /> Copy
              </button>
            </div>
            <div className="flex gap-3 pt-2">
              <Link to={`/admin/clients/${result.user.id}`} className="byrd-btn byrd-btn-primary flex-1" data-testid="invite-open-client">
                Open client
              </Link>
              <button onClick={onClose} className="byrd-btn byrd-btn-outline flex-1">
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default function AdminClients() {
  const [clients, setClients] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = () => api.get("/admin/clients").then((r) => setClients(r.data)).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-6" data-testid="admin-clients">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Clients</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Client Roster.</h1>
        </div>
        <button onClick={() => setOpen(true)} className="byrd-btn byrd-btn-dark" data-testid="new-invite-btn">
          <Plus size={14} /> Add Client
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-[#6B6558]">Loading…</div>
      ) : clients.length === 0 ? (
        <div className="byrd-card p-10 text-center">
          <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]">
            <Users size={22} />
          </div>
          <h3 className="font-serif text-2xl font-bold mt-4">No clients yet.</h3>
          <p className="text-[#6B6558] mt-2 max-w-md mx-auto">
            Add your first client. You&apos;ll get a shareable portal invite link you can send now or later.
          </p>
          <button onClick={() => setOpen(true)} className="byrd-btn byrd-btn-primary mt-5">
            Add First Client <Plus size={14} />
          </button>
        </div>
      ) : (
        <div className="byrd-card overflow-hidden">
          <div className="hidden md:grid grid-cols-[1.5fr_1fr_.9fr_.9fr_.9fr_.8fr] border-b border-[#E4DFD1] bg-[#FBF8F1]">
            {["Client", "Email", "Scenarios", "Pending", "Uploaded", "Reviewed"].map((h) => (
              <div key={h} className="px-4 py-3 text-[11px] uppercase font-mono tracking-widest text-[#6B6558]">{h}</div>
            ))}
          </div>
          {clients.map((c) => (
            <Link
              key={c.id}
              to={`/admin/clients/${c.id}`}
              data-testid={`client-row-${c.id}`}
              className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr_.9fr_.9fr_.9fr_.8fr] border-b border-[#E4DFD1] last:border-b-0 hover:bg-[#FBF8F1] transition-colors"
            >
              <div className="px-4 py-4">
                <div className="font-semibold">{c.name}</div>
                <div className="text-xs text-[#6B6558]">{c.company || "—"}</div>
              </div>
              <div className="px-4 py-4 text-sm text-[#2A2A2A] truncate">{c.email}</div>
              <div className="px-4 py-4 text-sm">
                {c.scenario_count > 0 ? (
                  <div>
                    <div className="font-mono text-sm">{c.scenario_count}</div>
                    {c.latest_scenario?.loan_type && (
                      <div className="text-[11px] text-[#6B6558] truncate">Latest: {c.latest_scenario.loan_type}</div>
                    )}
                  </div>
                ) : (
                  <span className="text-[#6B6558]">—</span>
                )}
              </div>
              <div className="px-4 py-4 font-mono text-sm">{c.doc_summary.pending}</div>
              <div className="px-4 py-4 font-mono text-sm">{c.doc_summary.uploaded}</div>
              <div className="px-4 py-4 font-mono text-sm">
                <span className="byrd-chip byrd-chip-green">{c.doc_summary.reviewed}</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      <InviteDialog open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
  );
}
