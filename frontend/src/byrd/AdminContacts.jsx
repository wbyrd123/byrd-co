import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  Contact as ContactIcon, Plus, Upload, Send, Trash2, Edit3, X, Mail, Phone,
  MessageSquare, Tag, Search, Check, AlertCircle, FileText, Sparkles, ArrowRight,
} from "lucide-react";
import { Link } from "react-router-dom";

const fmtRelative = (iso) => {
  if (!iso) return "Never";
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 90) return `${Math.floor(days / 7)}w ago`;
  return d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
};
const staleColor = (iso) => {
  if (!iso) return "text-[#6B6558]";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days < 30) return "text-[#245C25]";
  if (days < 90) return "text-[#7A5410]";
  return "text-[#8A1F1A]";
};

export default function AdminContacts() {
  const [contacts, setContacts] = useState([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [dialog, setDialog] = useState(null); // null | "new" | "import" | "compose" | contact-id
  const [loading, setLoading] = useState(true);
  const [prefill, setPrefill] = useState(null); // { subject, body, target_tags, suggestion_id }
  const location = useLocation();
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    const r = await api.get("/admin/contacts");
    setContacts(r.data);
    setLoading(false);
    return r.data;
  };
  useEffect(() => { load(); }, []);

  // Handle inbound prefill from Assistant marketing suggestions.
  // sessionStorage carries the draft; ?compose=1 in the URL is the signal to open.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("compose") !== "1") return;
    const raw = sessionStorage.getItem("byrd_mkt_prefill");
    if (!raw) return;
    let draft;
    try { draft = JSON.parse(raw); } catch { return; }
    sessionStorage.removeItem("byrd_mkt_prefill");
    // Wait for contacts to load, then pre-select by target tags
    (async () => {
      const list = contacts.length ? contacts : await load();
      const targets = new Set((draft.target_tags || []).map((t) => t.toLowerCase()));
      if (targets.size > 0) {
        const matched = list.filter((c) =>
          c.email && !c.unsubscribed && (c.tags || []).some((t) => targets.has(t.toLowerCase()))
        );
        setSelected(new Set(matched.map((c) => c.id)));
      } else {
        // Empty target_tags → everyone with a valid, subscribed email
        const matched = list.filter((c) => c.email && !c.unsubscribed);
        setSelected(new Set(matched.map((c) => c.id)));
      }
      setPrefill(draft);
      setDialog("compose");
      // Strip the compose param so a refresh doesn't re-trigger
      navigate("/admin/contacts", { replace: true });
    })();
  }, [location.search]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return contacts;
    return contacts.filter((c) =>
      [c.name, c.email, c.phone, c.company, c.state, (c.tags || []).join(" ")].join(" ").toLowerCase().includes(term)
    );
  }, [contacts, q]);

  const toggleSel = (id) =>
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = () =>
    setSelected(selected.size === filtered.length ? new Set() : new Set(filtered.map((c) => c.id)));

  const remove = async (c) => {
    if (!window.confirm(`Delete ${c.name}?`)) return;
    await api.delete(`/admin/contacts/${c.id}`);
    toast.success("Removed");
    load();
  };

  return (
    <div className="space-y-6" data-testid="admin-contacts">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// CRM · Shared Rolodex</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Contacts.</h1>
          <p className="text-sm text-[#6B6558] mt-2 max-w-xl">
            Referral sources, past sponsors, warm leads. Select multiple and send a marketing email
            with a template. Loan-specific emails to clients still go through the Personal Assistant.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => setDialog("import")} className="byrd-btn byrd-btn-outline" data-testid="import-csv-btn"><Upload size={14} /> Import CSV</button>
          <button onClick={() => setDialog("new")} className="byrd-btn byrd-btn-dark" data-testid="new-contact-btn"><Plus size={14} /> New Contact</button>
        </div>
      </div>

      <div className="byrd-card p-4 space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[240px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6B6558]" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by name, email, phone, tag…"
              className="w-full h-10 pl-9 pr-3 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
              data-testid="contact-search"
            />
          </div>
          <div className="text-xs text-[#6B6558]">
            {selected.size > 0 ? `${selected.size} selected` : `${filtered.length} contact${filtered.length === 1 ? "" : "s"}`}
          </div>
          <button
            onClick={() => setDialog("compose")}
            disabled={selected.size === 0}
            className="byrd-btn byrd-btn-dark h-10 disabled:opacity-40"
            data-testid="bulk-email-btn"
          >
            <Send size={14} /> Send Marketing Email ({selected.size})
          </button>
        </div>

        {loading ? (
          <div className="text-sm text-[#6B6558] py-6 text-center">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="py-12 text-center">
            <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]"><ContactIcon size={20} /></div>
            <div className="mt-3 font-serif text-lg font-bold">No contacts yet</div>
            <div className="text-xs text-[#6B6558] mt-1">Add manually or import from CSV to get started.</div>
          </div>
        ) : (
          <div className="border border-[#E4DFD1] rounded-md overflow-hidden">
            <div className="hidden md:grid grid-cols-[24px_1.3fr_1.3fr_0.9fr_0.9fr_60px_0.9fr_115px_50px] gap-2 px-3 py-2 bg-[#FBF8F1] border-b border-[#E4DFD1] text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
              <input type="checkbox" checked={selected.size === filtered.length && filtered.length > 0} onChange={toggleAll} data-testid="select-all" />
              <div>Name</div><div>Email</div><div>Phone</div><div>Company</div><div>State</div><div>Tags</div><div>Last Contact</div><div></div>
            </div>
            {filtered.map((c) => (
              <div key={c.id} className="grid grid-cols-[24px_1.3fr_1.3fr_0.9fr_0.9fr_60px_0.9fr_115px_50px] gap-2 px-3 py-2 border-b border-[#E4DFD1] last:border-b-0 items-center hover:bg-[#FBF8F1]" data-testid={`contact-row-${c.id}`}>
                <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggleSel(c.id)} data-testid={`contact-select-${c.id}`} />
                <div className="min-w-0">
                  <div className="font-semibold text-sm truncate">{c.name}</div>
                  <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                    {(c.contact_type || []).includes("email") && <Mail size={10} className="text-[#6B6558]" />}
                    {(c.contact_type || []).includes("phone") && <Phone size={10} className="text-[#6B6558]" />}
                    {(c.contact_type || []).includes("text") && <MessageSquare size={10} className="text-[#6B6558]" />}
                    {c.unsubscribed && <span className="byrd-chip byrd-chip-red text-[9px]">Unsubscribed</span>}
                    {c.client_user_id && (
                      <Link
                        to={`/admin/clients/${c.client_user_id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="byrd-chip byrd-chip-green text-[9px] inline-flex items-center gap-1 hover:brightness-95"
                        data-testid={`contact-client-chip-${c.id}`}
                        title="This contact is now a client. Open their client page."
                      >
                        <ArrowRight size={8} /> CLIENT
                      </Link>
                    )}
                  </div>
                </div>
                <div className="text-xs text-[#2A2A2A] truncate">{c.email || "—"}</div>
                <div className="text-xs text-[#2A2A2A] truncate">{c.phone || "—"}</div>
                <div className="text-xs text-[#2A2A2A] truncate" title={c.company || ""}>{c.company || "—"}</div>
                <div className="text-xs text-[#2A2A2A] font-mono uppercase">{c.state || "—"}</div>
                <div className="flex flex-wrap gap-1">
                  {(c.tags || []).slice(0, 3).map((t) => (
                    <span key={t} className="byrd-chip"><Tag size={9} /> {t}</span>
                  ))}
                </div>
                <div className={`text-xs font-mono ${staleColor(c.last_contact_at)}`}>{fmtRelative(c.last_contact_at)}</div>
                <div className="flex items-center gap-1">
                  <button onClick={() => setDialog(c.id)} className="w-7 h-7 grid place-items-center rounded-md border border-[#E4DFD1] hover:bg-[#F3EEE0]" data-testid={`edit-contact-${c.id}`}><Edit3 size={11} /></button>
                  <button onClick={() => remove(c)} className="w-7 h-7 grid place-items-center rounded-md border border-[#E4DFD1] hover:bg-[#FADCDA] hover:border-[#E38380] hover:text-[#8A1F1A]" data-testid={`delete-contact-${c.id}`}><Trash2 size={11} /></button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {(dialog === "new" || contacts.find((c) => c.id === dialog)) && (
        <ContactDialog
          initial={contacts.find((c) => c.id === dialog) || null}
          onClose={() => setDialog(null)}
          onSaved={() => { setDialog(null); load(); }}
        />
      )}
      {dialog === "import" && (
        <ImportDialog onClose={() => setDialog(null)} onDone={() => { setDialog(null); load(); }} />
      )}
      {dialog === "compose" && (
        <ComposeDialog
          contacts={contacts.filter((c) => selected.has(c.id))}
          prefill={prefill}
          onClose={() => { setDialog(null); setPrefill(null); }}
          onSent={() => { setDialog(null); setPrefill(null); setSelected(new Set()); load(); }}
        />
      )}
    </div>
  );
}

function ContactDialog({ initial, onClose, onSaved }) {
  const isNew = !initial;
  // Legacy / auto-created contacts (e.g., from Loan Quote saves) can be missing
  // `contact_type` or `tags`. Normalize on hydration so nothing calls `.includes`
  // or `.map` on undefined and blanks the screen.
  const [f, setF] = useState(() => {
    const seed = initial || {};
    return {
      name: seed.name || "",
      email: seed.email || "",
      phone: seed.phone || "",
      company: seed.company || "",
      state: seed.state || "",
      contact_type: Array.isArray(seed.contact_type) ? seed.contact_type : (isNew ? ["email"] : []),
      notes: seed.notes || "",
      tags: Array.isArray(seed.tags) ? seed.tags : [],
    };
  });
  const [tagInput, setTagInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Studio-access state — only meaningful when editing an existing contact.
  const [studioOn, setStudioOn] = useState(false);
  const [studioBusy, setStudioBusy] = useState(false);
  const [clientUserId, setClientUserId] = useState(initial?.client_user_id || null);

  useEffect(() => {
    if (!clientUserId) return;
    api.get(`/admin/clients/${clientUserId}`)
      .then((r) => setStudioOn(!!r.data?.client?.quote_studio_access))
      .catch(() => {});
  }, [clientUserId]);

  const toggleType = (t) => setF({ ...f, contact_type: f.contact_type.includes(t) ? f.contact_type.filter((x) => x !== t) : [...f.contact_type, t] });
  const addTag = () => { const t = tagInput.trim(); if (t && !f.tags.includes(t)) setF({ ...f, tags: [...f.tags, t] }); setTagInput(""); };

  const toggleStudio = async () => {
    if (!f.email && !clientUserId) {
      toast.error("Add an email first — required to create the client account.");
      return;
    }
    setStudioBusy(true);
    try {
      let uid = clientUserId;
      // Promote first if this contact isn't yet a client.
      if (!uid) {
        const p = await api.post(`/admin/contacts/${initial.id}/promote-to-client`);
        uid = p.data?.user?.id;
        setClientUserId(uid);
      }
      const next = !studioOn;
      await api.patch(`/admin/clients/${uid}/quote-studio-access`, { enabled: next });
      setStudioOn(next);
      toast.success(
        next
          ? (clientUserId
              ? "Studio access granted."
              : `${initial.name} is now a client with Studio access.`)
          : "Studio access revoked."
      );
      onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't update Studio access");
    } finally { setStudioBusy(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!f.name.trim()) { toast.error("Name required"); return; }
    setBusy(true);
    try {
      const payload = { ...f, email: f.email || null };
      if (isNew) await api.post("/admin/contacts", payload);
      else await api.patch(`/admin/contacts/${initial.id}`, payload);
      toast.success(isNew ? "Contact added" : "Updated");
      onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose} data-testid="contact-dialog">
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-lg">
        <div className="px-6 py-4 border-b border-[#E4DFD1] flex items-center justify-between">
          <div><div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// {isNew ? "New Contact" : "Edit Contact"}</div><h2 className="font-serif text-2xl font-bold mt-1">{isNew ? "Add Contact" : "Update Contact"}</h2></div>
          <button type="button" onClick={onClose} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]"><X size={16} /></button>
        </div>
        <div className="px-6 py-4 space-y-3">
          <div><label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Name *</label><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1]" data-testid="c-name" /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Email</label><input type="email" value={f.email || ""} onChange={(e) => setF({ ...f, email: e.target.value })} className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1]" data-testid="c-email" /></div>
            <div><label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Phone</label><input value={f.phone || ""} onChange={(e) => setF({ ...f, phone: e.target.value })} className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1]" data-testid="c-phone" /></div>
          </div>
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Company</label>
              <input
                value={f.company || ""}
                onChange={(e) => setF({ ...f, company: e.target.value })}
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1]"
                placeholder="Frost Bank · Marcus & Millichap · Byrd Rep Agency"
                data-testid="c-company"
              />
            </div>
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">State</label>
              <input
                value={f.state || ""}
                onChange={(e) => setF({ ...f, state: e.target.value.length === 2 ? e.target.value.toUpperCase() : e.target.value })}
                maxLength={20}
                className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] font-mono uppercase"
                placeholder="TX"
                data-testid="c-state"
              />
            </div>
          </div>
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Preferred Contact</label>
            <div className="mt-1 flex items-center gap-2">
              {[{ k: "email", i: Mail }, { k: "phone", i: Phone }, { k: "text", i: MessageSquare }].map(({ k, i: I }) => (
                <button key={k} type="button" onClick={() => toggleType(k)} className={`h-9 px-3 rounded-md border text-xs inline-flex items-center gap-1 ${f.contact_type.includes(k) ? "bg-[#1A1A1A] text-white border-[#1A1A1A]" : "bg-white border-[#E4DFD1]"}`} data-testid={`c-type-${k}`}>
                  <I size={11} /> {k}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Tags</label>
            <div className="mt-1 flex flex-wrap gap-1 mb-1">
              {f.tags.map((t) => (
                <span key={t} className="byrd-chip inline-flex items-center gap-1">{t} <button type="button" onClick={() => setF({ ...f, tags: f.tags.filter((x) => x !== t) })}><X size={10} /></button></span>
              ))}
            </div>
            <div className="flex gap-2">
              <input value={tagInput} onChange={(e) => setTagInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }} placeholder="e.g. referral source" className="flex-1 h-9 px-3 rounded-md border border-[#E4DFD1] text-sm" data-testid="c-tag-input" />
              <button type="button" onClick={addTag} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs">Add</button>
            </div>
          </div>
          <div><label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Notes</label><textarea rows={2} value={f.notes || ""} onChange={(e) => setF({ ...f, notes: e.target.value })} className="mt-1 w-full px-3 py-2 rounded-md border border-[#E4DFD1] text-sm resize-y" /></div>
          {!isNew && (
            <div className="border-t border-[#E4DFD1] pt-3">
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Loan Quote Studio Access</label>
              <div className="mt-1.5 flex items-start justify-between gap-3">
                <div className="text-[11px] text-[#6B6558] leading-relaxed flex-1">
                  For listing agents &amp; RE brokers who need to build Byrd-branded quotes for their own listings.
                  {clientUserId ? (
                    <div className="mt-1 text-[10px]">
                      Linked to client <Link
                        to={`/admin/clients/${clientUserId}`}
                        onClick={onClose}
                        className="text-[#C89434] hover:underline"
                        data-testid="contact-open-client"
                      >open profile →</Link>
                    </div>
                  ) : (
                    <div className="mt-1 text-[10px]">
                      Enabling promotes this contact to a client user in one tap. No invite email is sent — you send it manually when the doc list is ready.
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={toggleStudio}
                  disabled={studioBusy || (!f.email && !clientUserId)}
                  data-testid="contact-studio-toggle"
                  className={`inline-flex items-center gap-2 h-9 px-4 rounded-full text-xs font-mono uppercase tracking-widest whitespace-nowrap transition-colors disabled:opacity-50 ${
                    studioOn
                      ? "bg-[#C89434] text-[#1A1A1A] hover:brightness-95"
                      : "bg-white border border-[#E4DFD1] text-[#2A2A2A] hover:bg-[#F3EEE0]"
                  }`}
                >
                  <span className={`inline-block w-2 h-2 rounded-full ${studioOn ? "bg-[#1A1A1A]" : "bg-[#C7C0AC]"}`} />
                  {studioBusy ? "…" : (studioOn ? "Access on" : (clientUserId ? "Enable" : "Convert & enable"))}
                </button>
              </div>
            </div>
          )}
        </div>
        <div className="px-6 py-4 border-t border-[#E4DFD1] flex items-center gap-2"><button type="button" onClick={onClose} className="byrd-btn byrd-btn-outline flex-1">Cancel</button><button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark flex-1" data-testid="c-save">{busy ? "Saving…" : (isNew ? "Add" : "Save")}</button></div>
      </form>
    </div>
  );
}

function ImportDialog({ onClose, onDone }) {
  const [text, setText] = useState("name,email,phone,contact_type,tags\n");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post("/admin/contacts/import-csv", { csv_text: text });
      setResult(r.data);
      toast.success(`Imported ${r.data.created} contact${r.data.created === 1 ? "" : "s"}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Import failed");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose} data-testid="import-dialog">
      <div onClick={(e) => e.stopPropagation()} className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-2xl">
        <div className="px-6 py-4 border-b border-[#E4DFD1] flex items-center justify-between"><div><div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Import CSV</div><h2 className="font-serif text-2xl font-bold mt-1">Paste your rolodex</h2></div><button onClick={onClose} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]"><X size={16} /></button></div>
        <div className="px-6 py-4 space-y-3">
          <div className="text-xs text-[#6B6558]">Expected headers (any subset, any order): <code className="font-mono bg-[#F3EEE0] px-1 rounded">name, email, phone, contact_type, tags, notes</code>. Separate multi-values in <code className="font-mono bg-[#F3EEE0] px-1 rounded">contact_type</code> or <code className="font-mono bg-[#F3EEE0] px-1 rounded">tags</code> with commas or pipes.</div>
          <textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} className="w-full px-3 py-2 rounded-md border border-[#E4DFD1] text-xs font-mono resize-y" data-testid="import-text" />
          {result && <div className="text-xs bg-[#E4F4E4] border border-[#8DBE8F] text-[#245C25] rounded-md p-2"><Check size={11} className="inline mr-1" /> Imported {result.created} · Skipped {result.skipped}</div>}
        </div>
        <div className="px-6 py-4 border-t border-[#E4DFD1] flex items-center gap-2"><button onClick={onClose} className="byrd-btn byrd-btn-outline flex-1">{result ? "Close" : "Cancel"}</button><button onClick={result ? onDone : submit} disabled={busy} className="byrd-btn byrd-btn-dark flex-1" data-testid="import-submit">{result ? "Done" : (busy ? "Importing…" : "Import")}</button></div>
      </div>
    </div>
  );
}

function ComposeDialog({ contacts, prefill, onClose, onSent }) {
  const [templates, setTemplates] = useState([]);
  const [subject, setSubject] = useState(prefill?.subject || "");
  const [body, setBody] = useState(prefill?.body || "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  useEffect(() => { api.get("/admin/email-templates").then((r) => setTemplates(r.data)); }, []);
  const pickTemplate = (t) => { setSubject(t.subject); setBody(t.body); };
  const validEmails = contacts.filter((c) => c.email && !c.unsubscribed);
  const submit = async () => {
    if (!subject.trim() || !body.trim()) { toast.error("Subject and body required"); return; }
    setBusy(true);
    try {
      const r = await api.post("/admin/contacts/bulk-email", {
        contact_ids: contacts.map((c) => c.id), subject, body,
      });
      setResult(r.data);
      if (r.data.failed === 0 && r.data.sent > 0) toast.success(`Sent to ${r.data.sent}`);
      else if (r.data.sent === 0) toast.error("No emails went out — check errors");
      else toast.warning(`Sent ${r.data.sent}, failed ${r.data.failed}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose} data-testid="compose-dialog">
      <div onClick={(e) => e.stopPropagation()} className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col">
        <div className="px-6 py-4 border-b border-[#E4DFD1] flex items-center justify-between"><div><div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Marketing Email · {contacts.length} recipient{contacts.length === 1 ? "" : "s"}</div><h2 className="font-serif text-2xl font-bold mt-1">Compose</h2></div><button onClick={onClose} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]"><X size={16} /></button></div>
        <div className="px-6 py-4 space-y-3 overflow-y-auto">
          {prefill && (
            <div className="rounded-md border border-[#C89434] bg-[#FBEFD3]/60 text-[#7A5410] text-xs px-3 py-2 inline-flex items-center gap-2" data-testid="prefill-banner">
              <Sparkles size={12} /> Draft from your Assistant — review, edit, then send when it feels right.
            </div>
          )}
          <div className="text-xs text-[#6B6558]">
            {contacts.length} selected · {validEmails.length} will receive · {contacts.filter((c) => c.unsubscribed).length} unsubscribed · {contacts.filter((c) => !c.email).length} missing email
          </div>
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Template</label>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {templates.map((t) => (
                <button key={t.id} onClick={() => pickTemplate(t)} className="px-2.5 h-8 rounded-md border border-[#E4DFD1] bg-white hover:bg-[#F3EEE0] text-xs inline-flex items-center gap-1" data-testid={`template-${t.id}`}>
                  <FileText size={11} /> {t.name}
                </button>
              ))}
            </div>
          </div>
          <div><label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Subject</label><input value={subject} onChange={(e) => setSubject(e.target.value)} className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1]" data-testid="compose-subject" /></div>
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Body</label>
            <textarea rows={10} value={body} onChange={(e) => setBody(e.target.value)} className="mt-1 w-full px-3 py-2 rounded-md border border-[#E4DFD1] text-sm font-mono resize-y" data-testid="compose-body" />
            <div className="text-[10px] text-[#6B6558] mt-1">Variables: <code className="font-mono bg-[#F3EEE0] px-1 rounded">{"{{first_name}}"}</code> · <code className="font-mono bg-[#F3EEE0] px-1 rounded">{"{{admin_first_name}}"}</code>. An unsubscribe footer is added automatically.</div>
          </div>
          {result && (
            <div className={`text-xs rounded-md p-3 border ${result.failed === 0 ? "bg-[#E4F4E4] border-[#8DBE8F] text-[#245C25]" : "bg-[#FBEFD3] border-[#C89434] text-[#7A5410]"}`}>
              <div className="font-semibold inline-flex items-center gap-1">{result.failed === 0 ? <><Check size={12} /> All sent</> : <><AlertCircle size={12} /> Partial</>}</div>
              <div className="mt-1">Sent: {result.sent} · Failed: {result.failed} · Skipped (no email): {result.skipped_no_email} · Skipped (unsubscribed): {result.skipped_unsubscribed}</div>
              {result.errors && result.errors.length > 0 && (<div className="mt-1"><div className="font-semibold">Errors:</div><ul className="list-disc pl-4">{result.errors.map((e, i) => <li key={i} className="text-[10px] break-all">{e}</li>)}</ul></div>)}
            </div>
          )}
        </div>
        <div className="px-6 py-4 border-t border-[#E4DFD1] flex items-center gap-2"><button onClick={onClose} className="byrd-btn byrd-btn-outline flex-1">{result ? "Close" : "Cancel"}</button><button onClick={result ? onSent : submit} disabled={busy || (!result && validEmails.length === 0)} className="byrd-btn byrd-btn-dark flex-1" data-testid="compose-send">{result ? "Done" : (busy ? "Sending…" : <><Send size={13} /> Send to {validEmails.length}</>)}</button></div>
      </div>
    </div>
  );
}
