import React, { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { api, API_BASE } from "@/lib/api";
import { toast } from "sonner";
import { StatusChip, fmtSize, STATUS_OPTIONS } from "@/byrd/docHelpers";
import {
  ArrowLeft, Plus, Copy, Trash2, Download, Phone, Mail, Building2, Save,
} from "lucide-react";

const AddDocForm = ({ onAdd }) => {
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("Other");
  const [required, setRequired] = useState(true);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!label) { toast.error("Give it a name"); return; }
    setBusy(true);
    await onAdd({ label, category, required });
    setLabel(""); setCategory("Other"); setRequired(true);
    setBusy(false);
  };

  return (
    <form onSubmit={submit} className="byrd-card p-4 flex flex-col md:flex-row gap-3 md:items-end" data-testid="add-doc-form">
      <div className="flex-1">
        <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Document label</label>
        <input value={label} onChange={(e) => setLabel(e.target.value)}
          data-testid="add-doc-label"
          className="mt-1 w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm"
          placeholder="e.g. Construction Budget"
        />
      </div>
      <div>
        <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Category</label>
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          data-testid="add-doc-category"
          className="mt-1 w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm">
          <option>Personal</option>
          <option>Business</option>
          <option>Financial</option>
          <option>Property</option>
          <option>Other</option>
        </select>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
        Required
      </label>
      <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark" data-testid="add-doc-submit">
        <Plus size={14} /> Add Line
      </button>
    </form>
  );
};

export default function AdminClientDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);

  const load = () => api.get(`/admin/clients/${id}`).then((r) => setData(r.data));
  useEffect(() => { load(); }, [id]);

  const update = async (docId, patch) => {
    await api.patch(`/admin/clients/${id}/docs/${docId}`, patch);
    load();
  };

  const remove = async (docId, label) => {
    if (!window.confirm(`Remove "${label}" from the checklist? Any uploaded file will be deleted.`)) return;
    await api.delete(`/admin/clients/${id}/docs/${docId}`);
    toast.success("Removed");
    load();
  };

  const add = async (item) => {
    await api.post(`/admin/clients/${id}/docs`, item);
    toast.success("Added");
    load();
  };

  const copyInvite = () => {
    if (!data?.invite?.token) return;
    const url = `${window.location.origin}/portal/invite/${data.invite.token}`;
    navigator.clipboard.writeText(url);
    toast.success("Invite link copied");
  };

  const downloadFile = async (fileId) => {
    const res = await api.get(`/files/${fileId}`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    window.open(url, "_blank");
  };

  if (!data) return <div className="text-sm text-[#6B6558]">Loading…</div>;

  const { client, docs, invite } = data;
  const inviteActivated = invite && invite.used_at;

  return (
    <div className="space-y-8" data-testid="admin-client-detail">
      <button onClick={() => nav("/admin/clients")} className="text-sm text-[#6B6558] hover:text-[#1A1A1A] inline-flex items-center gap-2">
        <ArrowLeft size={14} /> All clients
      </button>

      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Client</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2 leading-tight">{client.name}</h1>
          <div className="mt-3 flex flex-wrap gap-4 text-sm text-[#6B6558]">
            <a href={`mailto:${client.email}`} className="inline-flex items-center gap-1 hover:text-[#C89434]"><Mail size={12} /> {client.email}</a>
            {client.phone && <a href={`tel:${client.phone}`} className="inline-flex items-center gap-1 hover:text-[#C89434]"><Phone size={12} /> {client.phone}</a>}
            {client.company && <span className="inline-flex items-center gap-1"><Building2 size={12} /> {client.company}</span>}
            {client.loan_type && <span className="byrd-chip byrd-chip-gold">{client.loan_type}</span>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          {invite && !inviteActivated && (
            <button onClick={copyInvite} className="byrd-btn byrd-btn-primary" data-testid="copy-invite">
              <Copy size={14} /> Copy Invite Link
            </button>
          )}
          <div className="text-xs text-[#6B6558]">
            {inviteActivated ? (
              <span className="byrd-chip byrd-chip-green">Portal activated</span>
            ) : (
              <span className="byrd-chip byrd-chip-gold">Invite pending</span>
            )}
          </div>
        </div>
      </div>

      {/* Add doc line */}
      <AddDocForm onAdd={add} />

      {/* Doc table */}
      <div className="byrd-card overflow-hidden">
        <div className="hidden md:grid grid-cols-[2fr_.9fr_1.2fr_1.4fr_1fr] border-b border-[#E4DFD1] bg-[#FBF8F1]">
          {["Document", "Category", "Status", "File / Notes", "Actions"].map((h) => (
            <div key={h} className="px-4 py-3 text-[11px] uppercase font-mono tracking-widest text-[#6B6558]">{h}</div>
          ))}
        </div>
        {docs.length === 0 && (
          <div className="p-8 text-center text-sm text-[#6B6558]">No documents on this client&apos;s checklist yet.</div>
        )}
        {docs.map((d) => (
          <DocRow
            key={d.id}
            doc={d}
            onUpdate={update}
            onRemove={() => remove(d.id, d.label)}
            onDownload={downloadFile}
          />
        ))}
      </div>
    </div>
  );
}

function DocRow({ doc, onUpdate, onRemove, onDownload }) {
  const [notes, setNotes] = useState(doc.notes || "");
  const [status, setStatus] = useState(doc.status);
  const [dirty, setDirty] = useState(false);

  useEffect(() => { setNotes(doc.notes || ""); setStatus(doc.status); setDirty(false); }, [doc.id, doc.status, doc.notes]);

  const save = async () => {
    await onUpdate(doc.id, { status, notes });
    setDirty(false);
  };

  const quickStatus = async (s) => {
    setStatus(s);
    await onUpdate(doc.id, { status: s, notes });
    setDirty(false);
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-[2fr_.9fr_1.2fr_1.4fr_1fr] border-b border-[#E4DFD1] last:border-b-0 items-center" data-testid={`admin-doc-${doc.id}`}>
      <div className="px-4 py-3">
        <div className="font-semibold">{doc.label}</div>
        {doc.required && <div className="text-[10px] font-mono uppercase text-[#C89434] tracking-widest mt-0.5">Required</div>}
      </div>
      <div className="px-4 py-3 text-sm text-[#6B6558]">{doc.category}</div>
      <div className="px-4 py-3">
        <select
          value={status}
          onChange={(e) => quickStatus(e.target.value)}
          data-testid={`doc-status-${doc.id}`}
          className="h-9 w-full px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
        >
          {STATUS_OPTIONS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
        </select>
      </div>
      <div className="px-4 py-3">
        {doc.file ? (
          <div className="text-sm">
            <button onClick={() => onDownload(doc.file.id)} className="inline-flex items-center gap-1 text-[#1A1A1A] hover:text-[#C89434]" data-testid={`doc-download-${doc.id}`}>
              <Download size={12} /> {doc.file.filename}
            </button>
            <div className="text-[11px] text-[#6B6558] mt-0.5">{fmtSize(doc.file.size)}</div>
          </div>
        ) : (
          <div className="text-xs text-[#6B6558]">Not uploaded</div>
        )}
        <input
          value={notes}
          onChange={(e) => { setNotes(e.target.value); setDirty(true); }}
          onBlur={() => dirty && save()}
          placeholder="Note (visible to client)"
          data-testid={`doc-notes-${doc.id}`}
          className="mt-2 w-full h-8 px-2 rounded-md border border-[#E4DFD1] bg-white text-xs"
        />
      </div>
      <div className="px-4 py-3 flex items-center gap-2">
        {dirty && (
          <button onClick={save} className="byrd-btn byrd-btn-dark h-9 px-3 text-xs" data-testid={`doc-save-${doc.id}`}>
            <Save size={12} /> Save
          </button>
        )}
        <button
          onClick={onRemove}
          data-testid={`doc-remove-${doc.id}`}
          className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1] hover:bg-[#FADCDA] hover:border-[#E38380] hover:text-[#8A1F1A] transition-colors"
          title="Delete line"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}
