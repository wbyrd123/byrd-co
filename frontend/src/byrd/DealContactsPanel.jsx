import React, { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Users, Plus, Mail, Phone, PenLine, Trash2, X, Building2, Home, Landmark, ShieldCheck, HelpCircle } from "lucide-react";

/**
 * DealContactsPanel — per-scenario rolodex of outside parties on the deal
 * (title, real estate broker, mortgage company, insurance, plus any custom "other").
 *
 * Props:
 *   scenarioId (required unless `fetchUrl` given)
 *   readOnly   (default false)   — hides add/edit/delete controls (lender / share views)
 *   compact    (default false)   — tighter card styling for portal sidebars
 *   fetchUrl   (optional)        — override endpoint (e.g., token-gated `/lender-view/{token}/deal-contacts`)
 */
export default function DealContactsPanel({ scenarioId, readOnly = false, compact = false, fetchUrl = null }) {
  const [state, setState] = useState({ contacts: [], editable: false, loading: true });
  const [editingContact, setEditingContact] = useState(null); // { ...contact } or "new" template
  const [busy, setBusy] = useState(false);

  const canEdit = !readOnly && state.editable;

  const listUrl = fetchUrl || `/scenarios/${scenarioId}/deal-contacts`;

  useEffect(() => {
    if (!scenarioId && !fetchUrl) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get(listUrl);
        if (!cancelled) setState({
          contacts: res.data.contacts,
          editable: !!res.data.editable && !readOnly && !fetchUrl,
          loading: false,
        });
      } catch (e) {
        if (!cancelled) setState({ contacts: [], editable: false, loading: false });
        toast.error(e?.response?.data?.detail || "Couldn't load deal contacts");
      }
    })();
    return () => { cancelled = true; };
  }, [scenarioId, fetchUrl]);

  const reload = async () => {
    try {
      const res = await api.get(listUrl);
      setState((s) => ({
        ...s,
        contacts: res.data.contacts,
        editable: !!res.data.editable && !readOnly && !fetchUrl,
      }));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't refresh deal contacts");
    }
  };

  const save = async (draft) => {
    setBusy(true);
    try {
      const body = {
        type: draft.type,
        custom_type: draft.type === "custom" ? draft.custom_type : null,
        company_name: draft.company_name || "",
        contact_person: draft.contact_person || "",
        email: draft.email || "",
        phone: draft.phone || "",
        loan_number: draft.type === "mortgage" ? (draft.loan_number || "") : "",
        notes: draft.notes || "",
      };
      if (draft.id && draft.id !== "new") {
        await api.patch(`/scenarios/${scenarioId}/deal-contacts/${draft.id}`, body);
      } else {
        await api.post(`/scenarios/${scenarioId}/deal-contacts`, body);
      }
      await reload();
      setEditingContact(null);
      toast.success(draft.id === "new" ? "Contact added" : "Contact updated");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't save contact");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (contact) => {
    if (!window.confirm(`Remove ${labelFor(contact)} from this deal?`)) return;
    try {
      await api.delete(`/scenarios/${scenarioId}/deal-contacts/${contact.id}`);
      await reload();
      toast.success("Contact removed");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't remove contact");
    }
  };

  const newContactDraft = () => ({
    id: "new", type: "title", custom_type: "",
    company_name: "", contact_person: "", email: "", phone: "",
    loan_number: "", notes: "",
  });

  const contactsByType = useMemo(() => {
    const preset = ["title", "re_broker", "mortgage", "insurance"];
    const groups = { preset: [], custom: [] };
    (state.contacts || []).forEach((c) => {
      if (preset.includes(c.type)) groups.preset.push(c);
      else groups.custom.push(c);
    });
    return groups;
  }, [state.contacts]);

  if (state.loading) {
    return (
      <div className="byrd-card p-5 text-sm text-[#6B6558]" data-testid="deal-contacts-loading">
        Loading deal contacts…
      </div>
    );
  }

  return (
    <div className={`byrd-card ${compact ? "p-4" : "p-5"}`} data-testid="deal-contacts-panel">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-md grid place-items-center bg-[#1A1A1A] text-[#C89434] shrink-0">
            <Users size={16} />
          </div>
          <div>
            <div className="font-serif font-bold leading-tight">Deal Contacts</div>
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
              // Title · Broker · Mortgage · Insurance
            </div>
          </div>
        </div>
        {canEdit && (
          <button
            onClick={() => setEditingContact(newContactDraft())}
            data-testid="deal-contact-add-btn"
            className="byrd-btn byrd-btn-outline text-xs"
          >
            <Plus size={12} /> Add
          </button>
        )}
      </div>

      {state.contacts.length === 0 ? (
        <div className="text-xs text-[#6B6558] italic py-2">
          {canEdit
            ? "No contacts yet — click Add to enter the title company, RE broker, or anyone else on this deal."
            : "No contacts entered yet."}
        </div>
      ) : (
        <div className="space-y-2">
          {[...contactsByType.preset, ...contactsByType.custom].map((c) => (
            <ContactCard
              key={c.id}
              contact={c}
              canEdit={canEdit}
              onEdit={() => setEditingContact({ ...c })}
              onDelete={() => remove(c)}
            />
          ))}
        </div>
      )}

      {editingContact && (
        <ContactEditModal
          contact={editingContact}
          busy={busy}
          onCancel={() => setEditingContact(null)}
          onSave={save}
        />
      )}
    </div>
  );
}

// ---------------- Presentation helpers ----------------

const TYPE_META = {
  title:      { label: "Title Company",       icon: Building2 },
  re_broker:  { label: "Real Estate Broker",  icon: Home },
  mortgage:   { label: "Mortgage Company",    icon: Landmark },
  insurance:  { label: "Insurance",           icon: ShieldCheck },
  custom:     { label: "Other",               icon: HelpCircle },
};

function labelFor(contact) {
  if (contact.type === "custom" && contact.custom_type) return contact.custom_type;
  return TYPE_META[contact.type]?.label || contact.type;
}

function ContactCard({ contact, canEdit, onEdit, onDelete }) {
  const meta = TYPE_META[contact.type] || TYPE_META.custom;
  const Icon = meta.icon;
  return (
    <div
      className="border border-[#E4DFD1] rounded-md p-3 bg-white hover:bg-[#FBF8F1]/60 transition-colors"
      data-testid={`deal-contact-${contact.id}`}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={13} className="text-[#C89434] shrink-0" />
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558] truncate">
            {labelFor(contact)}
          </div>
        </div>
        {canEdit && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={onEdit}
              data-testid={`deal-contact-edit-${contact.id}`}
              className="p-1 text-[#6B6558] hover:text-[#1A1A1A]"
              title="Edit"
            >
              <PenLine size={12} />
            </button>
            <button
              onClick={onDelete}
              data-testid={`deal-contact-delete-${contact.id}`}
              className="p-1 text-[#6B6558] hover:text-[#B23B3B]"
              title="Remove"
            >
              <Trash2 size={12} />
            </button>
          </div>
        )}
      </div>
      <div className="text-sm font-serif font-semibold text-[#1A1A1A]">
        {contact.company_name || <span className="text-[#6B6558] italic">No company name</span>}
      </div>
      {contact.contact_person && (
        <div className="text-xs text-[#2A2A2A] mt-0.5">{contact.contact_person}</div>
      )}
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
        {contact.email && (
          <a href={`mailto:${contact.email}`} className="text-[#C89434] hover:text-[#1A1A1A] inline-flex items-center gap-1">
            <Mail size={11} /> {contact.email}
          </a>
        )}
        {contact.phone && (
          <a href={`tel:${contact.phone}`} className="text-[#C89434] hover:text-[#1A1A1A] inline-flex items-center gap-1">
            <Phone size={11} /> {contact.phone}
          </a>
        )}
      </div>
      {contact.type === "mortgage" && contact.loan_number && (
        <div className="mt-1 text-[11px] text-[#6B6558]">
          <span className="font-mono uppercase tracking-widest text-[10px] mr-1">Loan #</span>
          <span className="font-mono">{contact.loan_number}</span>
        </div>
      )}
      {contact.notes && (
        <div className="mt-1 text-[11px] text-[#6B6558] italic leading-snug">{contact.notes}</div>
      )}
    </div>
  );
}

function ContactEditModal({ contact, busy, onCancel, onSave }) {
  const [draft, setDraft] = useState(contact);
  const isNew = draft.id === "new";
  const isCustom = draft.type === "custom";
  const isMortgage = draft.type === "mortgage";

  const submit = (e) => {
    e.preventDefault();
    if (isCustom && !(draft.custom_type || "").trim()) {
      toast.error("Give the custom contact a label (e.g., 'Contractor', 'Escrow Officer')");
      return;
    }
    onSave(draft);
  };

  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onCancel}>
      <div
        className="bg-[#FBF8F1] w-full max-w-lg rounded-md shadow-xl p-6 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        data-testid="deal-contact-edit-modal"
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
              {isNew ? "// Add Deal Contact" : "// Edit Deal Contact"}
            </div>
            <h3 className="font-serif text-xl font-bold mt-1">
              {isNew ? "Who else is on this deal?" : "Update contact"}
            </h3>
          </div>
          <button onClick={onCancel} className="text-[#6B6558] hover:text-[#1A1A1A]" data-testid="deal-contact-modal-close">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={submit} className="space-y-3 text-sm">
          <div>
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">Contact type</div>
            <select
              value={draft.type}
              onChange={(e) => setDraft((d) => ({ ...d, type: e.target.value }))}
              data-testid="deal-contact-type-select"
              className="mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white"
            >
              <option value="title">Title Company</option>
              <option value="re_broker">Real Estate Broker</option>
              <option value="mortgage">Mortgage Company</option>
              <option value="insurance">Insurance</option>
              <option value="custom">Other (custom)</option>
            </select>
          </div>

          {isCustom && (
            <Field
              label="Contact type label"
              placeholder="e.g., Contractor, Escrow Officer, Environmental"
              value={draft.custom_type || ""}
              onChange={(v) => setDraft((d) => ({ ...d, custom_type: v }))}
              testid="deal-contact-custom-type"
              hint="Required — this is how the contact will be labeled on the deal."
            />
          )}

          <Field
            label="Company name"
            placeholder="Chicago Title, First American, State Farm…"
            value={draft.company_name || ""}
            onChange={(v) => setDraft((d) => ({ ...d, company_name: v }))}
            testid="deal-contact-company"
          />
          <Field
            label="Contact person"
            placeholder="Full name"
            value={draft.contact_person || ""}
            onChange={(v) => setDraft((d) => ({ ...d, contact_person: v }))}
            testid="deal-contact-person"
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field
              label="Email"
              type="email"
              placeholder="name@company.com"
              value={draft.email || ""}
              onChange={(v) => setDraft((d) => ({ ...d, email: v }))}
              testid="deal-contact-email"
            />
            <Field
              label="Phone"
              type="tel"
              placeholder="(713) 555-1234"
              value={draft.phone || ""}
              onChange={(v) => setDraft((d) => ({ ...d, phone: v }))}
              testid="deal-contact-phone"
            />
          </div>
          {isMortgage && (
            <Field
              label="Loan number"
              placeholder="e.g., 1234567890"
              value={draft.loan_number || ""}
              onChange={(v) => setDraft((d) => ({ ...d, loan_number: v }))}
              testid="deal-contact-loan-number"
              mono
            />
          )}
          <Field
            label="Notes"
            placeholder="e.g., 'Handling both title + escrow, primary point of contact for closing.'"
            value={draft.notes || ""}
            onChange={(v) => setDraft((d) => ({ ...d, notes: v }))}
            testid="deal-contact-notes"
            multiline
          />

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onCancel} className="byrd-btn byrd-btn-outline">Cancel</button>
            <button type="submit" disabled={busy} data-testid="deal-contact-save-btn" className="byrd-btn byrd-btn-dark">
              {busy ? "Saving…" : (isNew ? "Add Contact" : "Save Changes")}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}

function Field({ label, value, onChange, type = "text", placeholder, testid, required, multiline, mono, hint }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
        {label}{required && " *"}
      </div>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={2}
          placeholder={placeholder}
          data-testid={testid}
          className="mt-1 w-full px-2 py-2 rounded-md border border-[#E4DFD1] bg-white text-sm resize-y"
        />
      ) : (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          required={required}
          data-testid={testid}
          className={`mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white text-sm ${mono ? "font-mono" : ""}`}
        />
      )}
      {hint && <div className="text-[10px] text-[#6B6558] mt-1 italic">{hint}</div>}
    </label>
  );
}
