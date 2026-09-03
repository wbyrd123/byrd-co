import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  Sparkles, Search, Plus, Upload, Trash2, Send, Check, X, Mail, RefreshCw, ShieldOff,
} from "lucide-react";

const STATES = ["TX", "LA", "OK", "AR", "MS", "AL", "TN", "FL", "GA", "NC"];
const STATUSES = [
  { v: "sourced", label: "Sourced", color: "bg-[#F3EEE0] text-[#6B6558]" },
  { v: "queued", label: "Queued", color: "bg-[#E5F1E5] text-[#245C25]" },
  { v: "drafted", label: "Drafted", color: "bg-[#FBEFD3] text-[#7A5410]" },
  { v: "approved", label: "Approved", color: "bg-[#C89434] text-[#1A1A1A]" },
  { v: "sent", label: "Sent", color: "bg-[#1A1A1A] text-white" },
  { v: "replied", label: "Replied", color: "bg-[#245C25] text-white" },
  { v: "converted", label: "Converted", color: "bg-[#7A5410] text-white" },
  { v: "opted_out", label: "Opted Out", color: "bg-[#FADCDA] text-[#8A1F1A]" },
  { v: "bounced", label: "Bounced", color: "bg-[#FADCDA] text-[#8A1F1A]" },
];
const chipFor = (v) => STATUSES.find((s) => s.v === v) || STATUSES[0];

export default function AdminLenderProspects() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ total: 0, by_status: {} });
  const [filterState, setFilterState] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [discoverState, setDiscoverState] = useState("TX");
  const [discovering, setDiscovering] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [addOpen, setAddOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    const [r, s] = await Promise.all([
      api.get("/admin/marketplace/prospects", {
        params: { state: filterState || undefined, status: filterStatus || undefined },
      }),
      api.get("/admin/marketplace/prospects/stats"),
    ]);
    setRows(r.data || []);
    setStats(s.data || { total: 0, by_status: {} });
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filterState, filterStatus]);

  const discover = async () => {
    setDiscovering(true);
    try {
      const r = await api.post("/admin/marketplace/prospects/discover",
                                { state: discoverState });
      toast.success(`Discovered ${r.data.discovered} banks · ${r.data.added} new · ${r.data.skipped_dupes} dupes skipped`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Discovery failed");
    } finally { setDiscovering(false); }
  };

  const enrich = async (p) => {
    setBusyId(p.id);
    try {
      const r = await api.post(`/admin/marketplace/prospects/${p.id}/enrich`);
      toast[r.data.found_contact ? "success" : "message"](
        r.data.found_contact
          ? `Found ${r.data.contact_name} · ${r.data.contact_email}`
          : `No contact published for ${p.institution} — enrich manually.`
      );
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enrichment failed");
    } finally { setBusyId(null); }
  };

  const draft = async (p) => {
    setBusyId(p.id);
    try {
      await api.post(`/admin/marketplace/prospects/${p.id}/draft`, {});
      toast.success("Ada drafted the email — review below and approve.");
      setExpanded((s) => ({ ...s, [p.id]: true }));
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Draft failed");
    } finally { setBusyId(null); }
  };

  const approve = async (p) => {
    setBusyId(p.id);
    try {
      await api.post(`/admin/marketplace/prospects/${p.id}/approve`);
      toast.success(`Approved — will send once Instantly.ai is wired.`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Approve failed");
    } finally { setBusyId(null); }
  };

  const remove = async (p) => {
    if (!window.confirm(`Delete prospect for ${p.institution}?`)) return;
    setBusyId(p.id);
    try {
      await api.delete(`/admin/marketplace/prospects/${p.id}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    } finally { setBusyId(null); }
  };

  const suppress = async (p) => {
    if (!p.contact_email) return;
    if (!window.confirm(`Permanently suppress ${p.contact_email}?`)) return;
    try {
      await api.post("/admin/marketplace/suppressions",
                      { email: p.contact_email, reason: "manual",
                        note: `Manually suppressed from ${p.institution}` });
      toast.success("Added to suppression list");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Suppress failed");
    }
  };

  const counts = useMemo(() => ({
    total: stats.total || 0,
    sourced: stats.by_status?.sourced || 0,
    queued: stats.by_status?.queued || 0,
    drafted: stats.by_status?.drafted || 0,
    approved: stats.by_status?.approved || 0,
    replied: stats.by_status?.replied || 0,
    converted: stats.by_status?.converted || 0,
  }), [stats]);

  return (
    <div className="space-y-6" data-testid="admin-prospects">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Marketplace · Outreach</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Lender Prospects.</h1>
          <p className="text-sm text-[#6B6558] mt-2 max-w-2xl">
            Ada sources regional/community banks by state, tries to find each LO's email, then drafts a personalized invite to your marketplace. Draft &amp; Approve mode — nothing ships until you tap Approve <b>and</b> Instantly.ai is wired.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setAddOpen(true)} className="byrd-btn byrd-btn-outline" data-testid="prospect-add-btn">
            <Plus size={14} /> Add manually
          </button>
        </div>
      </div>

      {/* Stat strip */}
      <div className="grid grid-cols-2 md:grid-cols-7 gap-3">
        {[
          ["Total", counts.total, "text-[#1A1A1A]"],
          ["Sourced", counts.sourced, "text-[#6B6558]"],
          ["Queued", counts.queued, "text-[#245C25]"],
          ["Drafted", counts.drafted, "text-[#7A5410]"],
          ["Approved", counts.approved, "text-[#C89434]"],
          ["Replied", counts.replied, "text-[#245C25]"],
          ["Converted", counts.converted, "text-[#7A5410]"],
        ].map(([l, v, c]) => (
          <div key={l} className="byrd-card p-3">
            <div className="font-mono text-[9px] uppercase tracking-widest text-[#6B6558]">{l}</div>
            <div className={`font-serif text-2xl font-bold mt-1 ${c}`}>{v}</div>
          </div>
        ))}
      </div>

      {/* Discover */}
      <div className="byrd-card p-6 border-l-4 border-[#C89434]" data-testid="discover-card">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Ada Sourcing</div>
            <h3 className="font-serif text-xl font-bold mt-0.5">Discover banks in a state.</h3>
            <p className="text-xs text-[#6B6558] mt-1 max-w-md">
              Ada queries Perplexity for regional/community banks + credit unions in the state that fund non-owner-occupied CRE, then adds them here as <code>sourced</code>. Enrich each to try to find an LO email.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select value={discoverState} onChange={(e) => setDiscoverState(e.target.value)}
                    data-testid="discover-state"
                    className="h-10 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm">
              {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button onClick={discover} disabled={discovering}
                    data-testid="discover-btn"
                    className="byrd-btn byrd-btn-dark disabled:opacity-60">
              <Sparkles size={14} /> {discovering ? "Ada is searching…" : "Discover"}
            </button>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Filter:</div>
        <select value={filterState} onChange={(e) => setFilterState(e.target.value)}
                data-testid="filter-state"
                className="h-8 px-2 border border-[#E4DFD1] bg-white rounded-md text-xs">
          <option value="">All states</option>
          {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
                data-testid="filter-status"
                className="h-8 px-2 border border-[#E4DFD1] bg-white rounded-md text-xs">
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
        </select>
        <button onClick={load} className="byrd-btn byrd-btn-outline h-8 px-2 text-xs" data-testid="reload-btn">
          <RefreshCw size={11} /> Refresh
        </button>
      </div>

      {/* Prospect table */}
      <div className="byrd-card overflow-hidden">
        {loading ? (
          <div className="p-6 text-sm text-[#6B6558]">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#6B6558]">
            No prospects yet. Tap <b>Discover</b> above to seed a state, or add one manually.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-[#FBF8F1] text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">
              <tr className="text-left">
                <th className="p-3">Bank</th>
                <th className="p-3">Contact</th>
                <th className="p-3">State</th>
                <th className="p-3">Status</th>
                <th className="p-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E4DFD1]">
              {rows.map((p) => {
                const chip = chipFor(p.status);
                return (
                  <React.Fragment key={p.id}>
                    <tr className="hover:bg-[#FBF8F1]/60" data-testid={`prospect-row-${p.id}`}>
                      <td className="p-3 align-top">
                        <div className="font-semibold">{p.institution}</div>
                        {p.hq_city && <div className="text-[11px] text-[#6B6558]">{p.hq_city}</div>}
                        {p.website && (
                          <a href={p.website} target="_blank" rel="noreferrer" className="text-[11px] text-[#C89434] hover:underline">
                            {p.website.replace(/^https?:\/\//, "").split("/")[0]}
                          </a>
                        )}
                      </td>
                      <td className="p-3 align-top">
                        {p.contact_name ? (
                          <>
                            <div className="font-medium">{p.contact_name}</div>
                            <div className="text-[11px] text-[#6B6558]">{p.contact_title}</div>
                            {p.contact_email && <div className="text-[11px] text-[#1A1A1A]">{p.contact_email}</div>}
                          </>
                        ) : (
                          <span className="text-[11px] text-[#6B6558] italic">Not enriched</span>
                        )}
                      </td>
                      <td className="p-3 align-top text-xs font-mono">{p.state}</td>
                      <td className="p-3 align-top">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-widest ${chip.color}`}
                              data-testid={`prospect-status-${p.id}`}>
                          {chip.label}
                        </span>
                      </td>
                      <td className="p-3 align-top text-right whitespace-nowrap">
                        {!p.contact_email && (
                          <button onClick={() => enrich(p)} disabled={busyId === p.id}
                                  className="byrd-btn byrd-btn-outline h-8 px-2 text-xs disabled:opacity-60"
                                  data-testid={`enrich-${p.id}`} title="Ada finds the LO">
                            <Search size={11} /> Enrich
                          </button>
                        )}
                        {p.contact_email && !p.draft_body && (
                          <button onClick={() => draft(p)} disabled={busyId === p.id}
                                  className="byrd-btn byrd-btn-outline h-8 px-2 text-xs disabled:opacity-60"
                                  data-testid={`draft-${p.id}`} title="Ada writes the email">
                            <Sparkles size={11} /> Draft
                          </button>
                        )}
                        {p.draft_body && p.status !== "approved" && p.status !== "sent" && (
                          <button onClick={() => approve(p)} disabled={busyId === p.id}
                                  className="byrd-btn byrd-btn-dark h-8 px-2 text-xs disabled:opacity-60"
                                  data-testid={`approve-${p.id}`} title="Approve for send">
                            <Check size={11} /> Approve
                          </button>
                        )}
                        {p.draft_body && (
                          <button onClick={() => setExpanded((s) => ({ ...s, [p.id]: !s[p.id] }))}
                                  className="byrd-btn byrd-btn-outline h-8 px-2 text-xs ml-1"
                                  data-testid={`toggle-${p.id}`}>
                            {expanded[p.id] ? <X size={11} /> : <Mail size={11} />}
                          </button>
                        )}
                        {p.contact_email && (
                          <button onClick={() => suppress(p)}
                                  className="byrd-btn byrd-btn-outline h-8 px-2 text-xs ml-1"
                                  data-testid={`suppress-${p.id}`} title="Never contact this email again">
                            <ShieldOff size={11} />
                          </button>
                        )}
                        <button onClick={() => remove(p)}
                                className="byrd-btn byrd-btn-outline h-8 px-2 text-xs ml-1 hover:bg-[#FADCDA]"
                                data-testid={`delete-${p.id}`}>
                          <Trash2 size={11} />
                        </button>
                      </td>
                    </tr>
                    {expanded[p.id] && p.draft_body && (
                      <tr className="bg-[#FBF8F1]">
                        <td colSpan={5} className="p-4">
                          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] mb-1">// Ada's draft</div>
                          <div className="text-sm font-semibold mb-1">Subject: {p.draft_subject}</div>
                          <pre className="text-sm text-[#2A2A2A] whitespace-pre-wrap font-sans border-l-2 border-[#C89434] pl-3">{p.draft_body}</pre>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {addOpen && <AddDialog onClose={() => setAddOpen(false)} onSaved={() => { setAddOpen(false); load(); }} />}
    </div>
  );
}

function AddDialog({ onClose, onSaved }) {
  const [f, setF] = useState({
    institution: "", state: "TX", hq_city: "", website: "",
    contact_name: "", contact_title: "", contact_email: "", contact_phone: "", notes: "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    if (!f.institution.trim()) return toast.error("Institution required");
    setBusy(true);
    try {
      await api.post("/admin/marketplace/prospects", f);
      toast.success("Prospect added");
      onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Add failed");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 bg-[#1A1A1A]/50 grid place-items-center p-4" onClick={onClose}>
      <div className="byrd-card w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}
           data-testid="add-prospect-dialog">
        <h2 className="font-serif text-2xl font-bold">Add prospect</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
          <Fld label="Institution *"><Inp value={f.institution} onChange={set("institution")} data-testid="ap-institution" /></Fld>
          <Fld label="State *">
            <select value={f.state} onChange={set("state")} data-testid="ap-state"
                    className="w-full h-10 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm">
              {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Fld>
          <Fld label="HQ City"><Inp value={f.hq_city} onChange={set("hq_city")} /></Fld>
          <Fld label="Website"><Inp value={f.website} onChange={set("website")} placeholder="https://…" /></Fld>
          <Fld label="Contact Name"><Inp value={f.contact_name} onChange={set("contact_name")} /></Fld>
          <Fld label="Title"><Inp value={f.contact_title} onChange={set("contact_title")} /></Fld>
          <Fld label="Email"><Inp value={f.contact_email} onChange={set("contact_email")} data-testid="ap-email" /></Fld>
          <Fld label="Phone"><Inp value={f.contact_phone} onChange={set("contact_phone")} /></Fld>
        </div>
        <Fld label="Notes" className="mt-3">
          <textarea value={f.notes} onChange={set("notes")} rows={2}
                    className="w-full px-3 py-2 border border-[#E4DFD1] bg-white rounded-md text-sm" />
        </Fld>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="byrd-btn byrd-btn-outline">Cancel</button>
          <button onClick={save} disabled={busy} className="byrd-btn byrd-btn-dark disabled:opacity-60" data-testid="ap-save">
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

const Fld = ({ label, children, className = "" }) => (
  <label className={`block ${className}`}>
    <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-1">{label}</div>
    {children}
  </label>
);
const Inp = (p) => (
  <input {...p} className="w-full h-10 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm focus:outline-none focus:border-[#C89434]" />
);
