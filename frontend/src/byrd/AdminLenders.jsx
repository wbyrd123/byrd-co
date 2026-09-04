import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  INSTITUTION_TYPES, PROPERTY_TYPES, LENDER_STATUSES, lenderStatusChip, fmtMoney, fmtPct,
} from "@/byrd/dealData";
import { Plus, Trash2, X, Save, Building2, Phone, Mail, Check, XCircle, Inbox } from "lucide-react";
import LenderSubtypePicker from "@/byrd/LenderSubtypePicker";

const emptyLender = () => ({
  name: "",
  institution_type: "bank",
  contacts: [{ name: "", title: "", phone: "", email: "" }],
  property_types: [],
  property_subtypes: [],
  min_loan: null, max_loan: null,
  max_ltv: null, max_ltc: null, min_dscr: null, min_debt_yield: null,
  geography: [],
  rate_min: null, rate_max: null,
  typical_term_months: null,
  recourse_preference: "",
  decision_speed_days: null,
  typical_fees: "",
  notes: "",
  deposit_relationship_required: null,
  borrower_in_state_required: null,
  status: "active",
});

const Field = ({ label, children, className = "" }) => (
  <div className={className}>
    <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</label>
    <div className="mt-1">{children}</div>
  </div>
);

const Inp = (props) => (
  <input {...props} className={`w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] ${props.className || ""}`} />
);
const Sel = ({ children, ...props }) => (
  <select {...props} className={`w-full h-10 px-3 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] ${props.className || ""}`}>{children}</select>
);
const TA = (props) => (
  <textarea {...props} className={`w-full px-3 py-2 rounded-md border border-[#E4DFD1] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] ${props.className || ""}`} />
);

// Compact tri-state Yes / No toggle for the admin lender editor. Matches the
// public apply form's YesNoField but sized to fit the two-column grid layout.
function AdminYesNo({ label, value, onChange, testId }) {
  const pill = (active) =>
    `h-9 px-4 rounded-md border text-xs font-medium transition-colors ${
      active
        ? "bg-[#1A1A1A] text-white border-[#1A1A1A]"
        : "bg-white text-[#1A1A1A] border-[#E4DFD1] hover:bg-[#F3EEE0]"
    }`;
  return (
    <div data-testid={testId}>
      <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">{label}</label>
      <div className="mt-1 flex gap-2 items-center">
        <button type="button" onClick={() => onChange(value === true ? null : true)}
          className={pill(value === true)} data-testid={`${testId}-yes`}>Yes</button>
        <button type="button" onClick={() => onChange(value === false ? null : false)}
          className={pill(value === false)} data-testid={`${testId}-no`}>No</button>
        {value !== null && value !== undefined && (
          <button type="button" onClick={() => onChange(null)}
            className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] hover:text-[#1A1A1A]"
            data-testid={`${testId}-clear`}>Clear</button>
        )}
      </div>
    </div>
  );
}

function LenderEditor({ open, initial, onClose, onSaved }) {
  const [form, setForm] = useState(initial || emptyLender());
  useEffect(() => { setForm(initial || emptyLender()); }, [initial]);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const num = (v) => (v === "" || v === null ? null : Number(v));
  const int = (v) => (v === "" || v === null ? null : parseInt(v));

  const toggleArr = (k, val) => {
    const cur = new Set(form[k] || []);
    if (cur.has(val)) cur.delete(val); else cur.add(val);
    set(k, Array.from(cur));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name) { toast.error("Name is required"); return; }
    try {
      let saved;
      if (form.id) {
        const res = await api.patch(`/admin/lenders/${form.id}`, form);
        saved = res.data;
      } else {
        const res = await api.post("/admin/lenders", form);
        saved = res.data;
      }
      toast.success("Saved");
      onSaved?.(saved);
      onClose();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed");
    }
  };

  const addContact = () => set("contacts", [...(form.contacts || []), { name: "", title: "", phone: "", email: "" }]);
  const rmContact = (i) => {
    const list = [...(form.contacts || [])]; list.splice(i, 1); set("contacts", list);
  };
  const setContact = (i, k, v) => {
    const list = [...(form.contacts || [])]; list[i] = { ...list[i], [k]: v }; set("contacts", list);
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-[#1A1A1A]/50 overflow-y-auto py-8 px-4" onClick={onClose}>
      <div className="max-w-3xl mx-auto byrd-card p-6 md:p-8" onClick={(e) => e.stopPropagation()} data-testid="lender-editor">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Lender</div>
            <h2 className="font-serif text-2xl font-bold mt-1">{form.id ? "Edit" : "Add"} Lender</h2>
          </div>
          <button onClick={onClose} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]"><X size={16} /></button>
        </div>

        <form onSubmit={submit} className="space-y-6">
          <section>
            <h3 className="font-serif text-lg font-semibold mb-3">Basics</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Field label="Institution Name *" className="md:col-span-2">
                <Inp value={form.name} onChange={(e) => set("name", e.target.value)} required data-testid="l-name" />
              </Field>
              <Field label="Type">
                <Sel value={form.institution_type || "bank"} onChange={(e) => set("institution_type", e.target.value)}>
                  {INSTITUTION_TYPES.map((t) => <option key={t.v} value={t.v}>{t.label}</option>)}
                </Sel>
              </Field>
              <Field label="Status">
                <Sel value={form.status || "active"} onChange={(e) => set("status", e.target.value)}>
                  {LENDER_STATUSES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
                </Sel>
              </Field>
              <Field label="Recourse Preference">
                <Sel value={form.recourse_preference || ""} onChange={(e) => set("recourse_preference", e.target.value)}>
                  <option value="">—</option>
                  <option value="recourse">Recourse</option>
                  <option value="non-recourse">Non-Recourse</option>
                  <option value="either">Either</option>
                </Sel>
              </Field>
              <Field label="Decision Speed (days to TS)">
                <Inp type="number" value={form.decision_speed_days ?? ""} onChange={(e) => set("decision_speed_days", int(e.target.value))} />
              </Field>
            </div>
          </section>

          <section>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-serif text-lg font-semibold">Contacts</h3>
              <button type="button" onClick={addContact} className="byrd-btn byrd-btn-outline h-8 px-3 text-xs"><Plus size={12} /> Add</button>
            </div>
            <div className="space-y-2">
              {(form.contacts || []).map((c, i) => (
                <div key={i} className="grid grid-cols-1 md:grid-cols-[1fr_1fr_1fr_1fr_auto] gap-2">
                  <Inp placeholder="Name" value={c.name} onChange={(e) => setContact(i, "name", e.target.value)} data-testid={`l-contact-name-${i}`} />
                  <Inp placeholder="Title" value={c.title} onChange={(e) => setContact(i, "title", e.target.value)} />
                  <Inp placeholder="Phone" value={c.phone} onChange={(e) => setContact(i, "phone", e.target.value)} />
                  <Inp placeholder="Email" type="email" value={c.email} onChange={(e) => setContact(i, "email", e.target.value)} />
                  <button type="button" onClick={() => rmContact(i)} className="w-10 h-10 grid place-items-center rounded-md border border-[#E4DFD1] hover:bg-[#FADCDA] hover:text-[#8A1F1A]"><Trash2 size={12} /></button>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="font-serif text-lg font-semibold mb-3">Credit Box</h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <Field label="Min Loan ($)"><Inp type="number" value={form.min_loan ?? ""} onChange={(e) => set("min_loan", num(e.target.value))} /></Field>
              <Field label="Max Loan ($)"><Inp type="number" value={form.max_loan ?? ""} onChange={(e) => set("max_loan", num(e.target.value))} /></Field>
              <Field label="Max LTV (%)"><Inp type="number" step="0.1" value={form.max_ltv ?? ""} onChange={(e) => set("max_ltv", num(e.target.value))} /></Field>
              <Field label="Max LTC (%)"><Inp type="number" step="0.1" value={form.max_ltc ?? ""} onChange={(e) => set("max_ltc", num(e.target.value))} /></Field>
              <Field label="Min DSCR"><Inp type="number" step="0.01" value={form.min_dscr ?? ""} onChange={(e) => set("min_dscr", num(e.target.value))} /></Field>
              <Field label="Min Debt Yield (%)"><Inp type="number" step="0.1" value={form.min_debt_yield ?? ""} onChange={(e) => set("min_debt_yield", num(e.target.value))} /></Field>
              <Field label="Rate Min (%)"><Inp type="number" step="0.01" value={form.rate_min ?? ""} onChange={(e) => set("rate_min", num(e.target.value))} /></Field>
              <Field label="Rate Max (%)"><Inp type="number" step="0.01" value={form.rate_max ?? ""} onChange={(e) => set("rate_max", num(e.target.value))} /></Field>
              <Field label="Typical Term (months)"><Inp type="number" value={form.typical_term_months ?? ""} onChange={(e) => set("typical_term_months", int(e.target.value))} /></Field>
            </div>
          </section>

          <section>
            <h3 className="font-serif text-lg font-semibold mb-3">Property Types</h3>
            <div className="flex flex-wrap gap-2">
              {PROPERTY_TYPES.map((p) => {
                const on = (form.property_types || []).includes(p);
                return (
                  <button key={p} type="button" onClick={() => toggleArr("property_types", p)}
                    className={`px-3 py-1.5 rounded-md border text-xs ${on ? "bg-[#1A1A1A] text-white border-[#1A1A1A]" : "bg-white border-[#E4DFD1] hover:bg-[#F3EEE0]"}`}
                    data-testid={`l-pt-${p}`}
                  >
                    {p}
                  </button>
                );
              })}
            </div>
            <div className="mt-4">
              <h4 className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-2">Sub-Type Specialties (optional)</h4>
              <LenderSubtypePicker
                propertyTypes={form.property_types || []}
                value={form.property_subtypes || []}
                onChange={(v) => set("property_subtypes", v)}
                testIdPrefix="l-subtype"
              />
            </div>
          </section>

          <section>
            <h3 className="font-serif text-lg font-semibold mb-3">Geography</h3>
            <Field label="States (comma-separated) or 'Nationwide'">
              <Inp
                value={(form.geography || []).join(", ")}
                onChange={(e) => set("geography", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                placeholder="TX, LA, OK — or Nationwide"
                data-testid="l-geo"
              />
            </Field>
          </section>

          <section>
            <h3 className="font-serif text-lg font-semibold mb-3">Notes &amp; Fees</h3>
            <div className="space-y-3">
              <Field label="Typical Fees"><Inp value={form.typical_fees || ""} onChange={(e) => set("typical_fees", e.target.value)} placeholder="1% origination + $x processing" /></Field>
              <div className="grid sm:grid-cols-2 gap-3">
                <AdminYesNo
                  label="Deposit relationship required?"
                  value={form.deposit_relationship_required}
                  onChange={(v) => set("deposit_relationship_required", v)}
                  testId="l-deposit-required"
                />
                <AdminYesNo
                  label="Borrower must be in bank state?"
                  value={form.borrower_in_state_required}
                  onChange={(v) => set("borrower_in_state_required", v)}
                  testId="l-borrower-in-state"
                />
              </div>
              <Field label="Notes"><TA rows={3} value={form.notes || ""} onChange={(e) => set("notes", e.target.value)} placeholder="Prefers stabilized deals · hates hotels in Q4 · fast on refis" /></Field>
            </div>
          </section>

          <div className="flex justify-end gap-3">
            <button type="button" onClick={onClose} className="byrd-btn byrd-btn-outline">Cancel</button>
            <button type="submit" className="byrd-btn byrd-btn-dark" data-testid="l-save"><Save size={14} /> Save</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function AdminLenders() {
  const [lenders, setLenders] = useState([]);
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null = closed, {} = new, {...} = edit

  const load = () => Promise.all([
    api.get("/admin/lenders").then((r) => setLenders(r.data)),
    api.get("/admin/marketplace/pending-lenders").then((r) => setPending(r.data)).catch(() => setPending([])),
  ]).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const approve = async (l) => {
    try {
      await api.post(`/admin/marketplace/lenders/${l.id}/approve`);
      toast.success(`${l.name} approved — activation email sent`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Approve failed");
    }
  };
  const reject = async (l) => {
    if (!window.confirm(`Reject "${l.name}"?`)) return;
    try {
      await api.post(`/admin/marketplace/lenders/${l.id}/reject`);
      toast.success("Rejected");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Reject failed");
    }
  };

  const remove = async (l) => {
    if (!window.confirm(`Delete "${l.name}"? This cannot be undone.`)) return;
    await api.delete(`/admin/lenders/${l.id}`);
    toast.success("Deleted");
    load();
  };

  return (
    <div className="space-y-6" data-testid="admin-lenders">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Directory</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Lenders.</h1>
          <p className="text-sm text-[#6B6558] mt-2">Your private directory. Not visible to clients or lenders themselves.</p>
        </div>
        <button onClick={() => setEditing({})} className="byrd-btn byrd-btn-dark" data-testid="new-lender-btn"><Plus size={14} /> Add Lender</button>
      </div>

      {/* Marketplace pending applications — always visible so the broker knows where new ones will appear */}
      <div
        className={`byrd-card p-6 border-l-4 ${pending.length > 0 ? "border-[#C89434]" : "border-[#E4DFD1]"}`}
        data-testid="pending-applications-card"
      >
        <div className="flex items-center gap-2 mb-3">
          <Inbox size={16} className={pending.length > 0 ? "text-[#C89434]" : "text-[#6B6558]"} />
          <h2 className="font-serif text-xl font-bold">
            Marketplace applications
            {pending.length > 0 ? ` (${pending.length})` : ""}
          </h2>
        </div>
        {pending.length === 0 ? (
          <p className="text-sm text-[#6B6558]" data-testid="pending-applications-empty">
            No pending applications. New submissions from{" "}
            <code className="bg-[#F3EEE0] px-1">/lenders/apply</code> will show up here — you'll
            also get an email in your inbox.
          </p>
        ) : (
          <>
            <p className="text-xs text-[#6B6558] mb-4">
              Lenders who applied through <code className="bg-[#F3EEE0] px-1">/lenders/apply</code>. Approve to send them
              an activation email; the activated portal lets them update their credit box and submit term sheets.
            </p>
            <div className="space-y-3">
            {pending.map((l) => (
              <div key={l.id} className="border border-[#E4DFD1] rounded-md p-4 bg-white" data-testid={`pending-${l.id}`}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <div className="font-serif text-lg font-bold">{l.name}</div>
                    <div className="text-xs text-[#6B6558] mt-0.5 capitalize">{l.institution_type?.replace("_", " ")}</div>
                    <div className="text-xs mt-2">
                      <b>{l.contacts?.[0]?.name}</b>
                      {l.contacts?.[0]?.title ? ` · ${l.contacts[0].title}` : ""}
                      {" · "}<a href={`mailto:${l.contacts?.[0]?.email}`} className="text-[#C89434]">{l.contacts?.[0]?.email}</a>
                    </div>
                    <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-y-1 text-xs text-[#2A2A2A]">
                      <div><span className="text-[#6B6558]">Size:</span> {fmtMoney(l.min_loan)} – {fmtMoney(l.max_loan)}</div>
                      <div><span className="text-[#6B6558]">Max LTV:</span> {fmtPct(l.max_ltv, 1)}</div>
                      <div><span className="text-[#6B6558]">Min DSCR:</span> {l.min_dscr ?? "—"}</div>
                      <div><span className="text-[#6B6558]">Geo:</span> {(l.geography || []).slice(0, 3).join(", ") || "—"}</div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {(l.property_types || []).slice(0, 6).map((p) => <span key={p} className="byrd-chip">{p}</span>)}
                    </div>
                    {l.notes && <div className="mt-2 text-xs italic text-[#6B6558]">"{l.notes}"</div>}
                  </div>
                  <div className="flex flex-col gap-2 shrink-0">
                    <button onClick={() => approve(l)} className="byrd-btn byrd-btn-dark h-9 px-3 text-xs" data-testid={`pending-${l.id}-approve`}>
                      <Check size={12} /> Approve
                    </button>
                    <button onClick={() => reject(l)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs text-[#8A1F1A] border-[#E38380]" data-testid={`pending-${l.id}-reject`}>
                      <XCircle size={12} /> Reject
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
          </>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-[#6B6558]">Loading…</div>
      ) : lenders.length === 0 ? (
        <div className="byrd-card p-10 text-center">
          <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]"><Building2 size={22} /></div>
          <h3 className="font-serif text-2xl font-bold mt-4">No lenders yet.</h3>
          <p className="text-[#6B6558] mt-2 max-w-md mx-auto">Add lenders you regularly place with. Their credit box drives the auto-match on each scenario.</p>
          <button onClick={() => setEditing({})} className="byrd-btn byrd-btn-primary mt-5"><Plus size={14} /> Add First Lender</button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {lenders.map((l) => {
            const status = lenderStatusChip(l.status);
            return (
              <div key={l.id} className="byrd-card p-5" data-testid={`lender-card-${l.id}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="font-serif text-xl font-bold truncate">{l.name}</div>
                      <span className={status.chip}>{status.label}</span>
                    </div>
                    <div className="text-xs text-[#6B6558] mt-1 capitalize">{l.institution_type?.replace("_", " ")}</div>
                    <div className="mt-3 flex flex-wrap gap-1">
                      {(l.property_types || []).slice(0, 5).map((p) => <span key={p} className="byrd-chip">{p}</span>)}
                      {l.property_types?.length > 5 && <span className="byrd-chip">+{l.property_types.length - 5}</span>}
                    </div>
                    {l.property_subtypes?.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1" data-testid={`lender-subtypes-${l.id}`}>
                        {l.property_subtypes.slice(0, 4).map((s) => (
                          <span key={s} className="byrd-chip byrd-chip-gold text-[10px]">{s}</span>
                        ))}
                        {l.property_subtypes.length > 4 && <span className="byrd-chip text-[10px]">+{l.property_subtypes.length - 4}</span>}
                      </div>
                    )}
                    <div className="mt-3 grid grid-cols-2 gap-y-1 text-xs text-[#2A2A2A]">
                      <div><span className="text-[#6B6558]">Size:</span> {fmtMoney(l.min_loan)} – {fmtMoney(l.max_loan)}</div>
                      <div><span className="text-[#6B6558]">Max LTV:</span> {fmtPct(l.max_ltv, 1)}</div>
                      <div><span className="text-[#6B6558]">Min DSCR:</span> {l.min_dscr ?? "—"}</div>
                      <div><span className="text-[#6B6558]">Geo:</span> {(l.geography || []).slice(0, 3).join(", ") || "—"}</div>
                    </div>
                    {l.contacts?.[0]?.name && (
                      <div className="mt-3 pt-3 border-t border-[#E4DFD1] text-xs text-[#6B6558]">
                        <div className="font-semibold text-[#1A1A1A]">{l.contacts[0].name}{l.contacts[0].title ? ` · ${l.contacts[0].title}` : ""}</div>
                        <div className="flex gap-3 mt-1">
                          {l.contacts[0].phone && <span className="inline-flex items-center gap-1"><Phone size={10} /> {l.contacts[0].phone}</span>}
                          {l.contacts[0].email && <span className="inline-flex items-center gap-1"><Mail size={10} /> {l.contacts[0].email}</span>}
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col gap-2 shrink-0">
                    <button onClick={() => setEditing(l)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`edit-lender-${l.id}`}>Edit</button>
                    <button onClick={() => remove(l)} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs text-[#8A1F1A] border-[#E38380]" data-testid={`del-lender-${l.id}`}><Trash2 size={12} /></button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <LenderEditor
        open={!!editing}
        initial={editing && editing.id ? editing : null}
        onClose={() => setEditing(null)}
        onSaved={load}
      />
    </div>
  );
}
