import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, API_BASE } from "@/lib/api";
import { LOAN_TYPES_FLAT } from "@/byrd/data";
import { toast } from "sonner";
import { Copy, Plus, Users, X, Check } from "lucide-react";

const InviteDialog = ({ open, onClose, onCreated }) => {
  const [form, setForm] = useState({
    name: "", email: "", company: "", phone: "", loan_type: "",
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
      toast.success("Invite created — copy the link below");
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
            <h2 className="font-serif text-2xl font-bold mt-1">Create Invite</h2>
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
              <div className="sm:col-span-2">
                <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Loan Type (optional)</label>
                <select value={form.loan_type} onChange={(e) => set("loan_type", e.target.value)}
                  className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white"
                >
                  <option value="">Select…</option>
                  {LOAN_TYPES_FLAT.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>
            <div className="text-xs text-[#6B6558]">
              A default document checklist (personal + business 3-yr tax returns, resume, entity docs, etc.)
              will be attached. You can add/remove items after creating.
            </div>
            <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark w-full" data-testid="invite-submit">
              {busy ? "Creating…" : "Create Invite"}
            </button>
          </form>
        ) : (
          <div className="mt-6 space-y-4" data-testid="invite-result">
            <div className="byrd-chip byrd-chip-green"><Check size={12} /> Invite ready</div>
            <p className="text-sm text-[#2A2A2A]">
              Share this link with <span className="font-semibold">{result.user.name}</span>. They&apos;ll set a password and log in.
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
          <Plus size={14} /> Invite Client
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
            Create your first invite. A shareable link is generated — send it to your client to activate.
          </p>
          <button onClick={() => setOpen(true)} className="byrd-btn byrd-btn-primary mt-5">
            Create First Invite <Plus size={14} />
          </button>
        </div>
      ) : (
        <div className="byrd-card overflow-hidden">
          <div className="hidden md:grid grid-cols-[1.5fr_1fr_.9fr_.9fr_.9fr_.8fr] border-b border-[#E4DFD1] bg-[#FBF8F1]">
            {["Client", "Email", "Loan Type", "Pending", "Uploaded", "Reviewed"].map((h) => (
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
              <div className="px-4 py-4 text-sm">{c.loan_type || "—"}</div>
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
