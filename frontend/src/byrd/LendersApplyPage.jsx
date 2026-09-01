import React, { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Building2, Check } from "lucide-react";
import LenderSubtypePicker from "@/byrd/LenderSubtypePicker";

const INSTITUTION_TYPES = [
  { value: "bank", label: "Bank" },
  { value: "credit_union", label: "Credit Union" },
  { value: "private", label: "Private Lender" },
  { value: "agency", label: "Agency (Fannie/Freddie/HUD)" },
  { value: "bridge", label: "Bridge / Debt Fund" },
  { value: "hard_money", label: "Hard Money" },
  { value: "cmbs", label: "CMBS" },
  { value: "life_co", label: "Life Insurance Co." },
  { value: "other", label: "Other" },
];

const PROPERTY_TYPES = [
  "Multifamily", "Office", "Retail", "Industrial", "Hospitality",
  "Self-storage", "Mixed-use", "Medical Office", "Mobile Home Park", "Land",
  "New Construction",
];

function Field({ label, hint, children, testId }) {
  return (
    <label className="block" data-testid={testId}>
      <div className="text-xs font-mono uppercase tracking-widest text-[#6B6558] mb-1">{label}</div>
      {children}
      {hint && <div className="text-[11px] text-[#6B6558] mt-1">{hint}</div>}
    </label>
  );
}

const Input = (p) => (
  <input {...p} className={`w-full h-11 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm focus:outline-none focus:border-[#C89434] ${p.className || ""}`} />
);
const Textarea = (p) => (
  <textarea {...p} className={`w-full min-h-[80px] px-3 py-2 border border-[#E4DFD1] bg-white rounded-md text-sm focus:outline-none focus:border-[#C89434] ${p.className || ""}`} />
);

export default function LendersApplyPage() {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [f, setF] = useState({
    lender_name: "", institution_type: "bank",
    contact_name: "", contact_title: "", contact_email: "", contact_phone: "",
    website: "",
    property_types: [], property_subtypes: [], geography: [],
    min_loan: "", max_loan: "", max_ltv: "", max_ltc: "",
    min_dscr: "", min_debt_yield: "", rate_min: "", rate_max: "",
    typical_term_months: "", recourse_preference: "",
    decision_speed_days: "", typical_fees: "", notes: "",
  });

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggle = (arr, val) => (arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);

  const submit = async (e) => {
    e.preventDefault();
    if (!f.lender_name || !f.contact_name || !f.contact_email) {
      toast.error("Lender name, contact name, and contact email are required");
      return;
    }
    setBusy(true);
    try {
      const num = (v) => (v === "" || v == null ? null : Number(v));
      const geo = (f.geography.join(",") + "," + (typeof f._geo_input === "string" ? f._geo_input : ""))
        .split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
      const payload = {
        lender_name: f.lender_name.trim(),
        institution_type: f.institution_type,
        contact_name: f.contact_name.trim(),
        contact_title: f.contact_title.trim(),
        contact_email: f.contact_email.trim().toLowerCase(),
        contact_phone: f.contact_phone.trim(),
        website: f.website.trim(),
        property_types: f.property_types,
        property_subtypes: f.property_subtypes,
        geography: [...new Set(geo)],
        min_loan: num(f.min_loan), max_loan: num(f.max_loan),
        max_ltv: num(f.max_ltv), max_ltc: num(f.max_ltc),
        min_dscr: num(f.min_dscr), min_debt_yield: num(f.min_debt_yield),
        rate_min: num(f.rate_min), rate_max: num(f.rate_max),
        typical_term_months: num(f.typical_term_months),
        recourse_preference: f.recourse_preference,
        decision_speed_days: num(f.decision_speed_days),
        typical_fees: f.typical_fees, notes: f.notes,
      };
      await api.post("/public/lender/apply", payload);
      setDone(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Application failed");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="min-h-screen bg-[#FBF8F1] flex items-center justify-center px-4" data-testid="apply-success">
        <div className="max-w-lg w-full bg-white border border-[#E4DFD1] rounded-md p-8 text-center">
          <div className="w-14 h-14 mx-auto rounded-full bg-[#E5F0E5] text-[#245C25] grid place-items-center mb-4">
            <Check size={28} />
          </div>
          <h1 className="font-serif text-2xl font-bold">Application received</h1>
          <p className="text-sm text-[#6B6558] mt-3">
            Thanks for applying to become a Byrd &amp; CO lending partner. One of the brokers will
            review your application shortly. You&apos;ll get an email with activation instructions once
            you&apos;re approved.
          </p>
          <Link to="/" className="byrd-btn byrd-btn-dark mt-6 inline-flex" data-testid="apply-back-home">
            Back to Byrd &amp; CO
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FBF8F1]" data-testid="lender-apply-page">
      <div className="max-w-3xl mx-auto px-4 py-10">
        <Link to="/" className="text-xs font-mono uppercase tracking-widest text-[#6B6558] hover:text-[#C89434]">
          ← Byrd &amp; CO
        </Link>
        <div className="mt-4 flex items-start gap-4">
          <div className="w-12 h-12 rounded-full bg-[#1A1A1A] text-[#C89434] grid place-items-center">
            <Building2 size={22} />
          </div>
          <div>
            <div className="font-mono text-[11px] uppercase tracking-widest text-[#6B6558]">// Lender Marketplace</div>
            <h1 className="font-serif text-3xl sm:text-4xl font-bold mt-1">Become a Byrd &amp; CO lending partner</h1>
            <p className="text-sm text-[#6B6558] mt-2 max-w-2xl">
              Tell us about your credit box. Once approved, you&apos;ll get a lender portal where we&apos;ll
              route deals that match your parameters — with structured term-sheet submission and
              a clean way to track everything.
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="mt-8 bg-white border border-[#E4DFD1] rounded-md p-6 sm:p-8 space-y-6" data-testid="apply-form">
          {/* Institution */}
          <section>
            <h2 className="font-serif text-lg font-bold border-b border-[#E4DFD1] pb-2 mb-4">Institution</h2>
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Lender / Institution Name *" testId="field-lender-name">
                <Input value={f.lender_name} onChange={set("lender_name")} required data-testid="input-lender-name" />
              </Field>
              <Field label="Institution Type" testId="field-institution-type">
                <select value={f.institution_type} onChange={set("institution_type")} className="w-full h-11 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm" data-testid="input-institution-type">
                  {INSTITUTION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </Field>
              <Field label="Website" testId="field-website">
                <Input value={f.website} onChange={set("website")} placeholder="https://" data-testid="input-website" />
              </Field>
            </div>
          </section>

          {/* Primary contact */}
          <section>
            <h2 className="font-serif text-lg font-bold border-b border-[#E4DFD1] pb-2 mb-4">Primary Contact</h2>
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Contact Name *" testId="field-contact-name">
                <Input value={f.contact_name} onChange={set("contact_name")} required data-testid="input-contact-name" />
              </Field>
              <Field label="Title" testId="field-contact-title">
                <Input value={f.contact_title} onChange={set("contact_title")} placeholder="e.g. VP, Commercial Real Estate" data-testid="input-contact-title" />
              </Field>
              <Field label="Email *" hint="Where we'll send your activation link" testId="field-contact-email">
                <Input type="email" value={f.contact_email} onChange={set("contact_email")} required data-testid="input-contact-email" />
              </Field>
              <Field label="Phone" testId="field-contact-phone">
                <Input value={f.contact_phone} onChange={set("contact_phone")} data-testid="input-contact-phone" />
              </Field>
            </div>
          </section>

          {/* Credit box */}
          <section>
            <h2 className="font-serif text-lg font-bold border-b border-[#E4DFD1] pb-2 mb-4">Credit Box</h2>
            <Field label="Property Types" hint="Pick every asset type you'll consider">
              <div className="flex flex-wrap gap-2 mt-1">
                {PROPERTY_TYPES.map((p) => {
                  const active = f.property_types.includes(p);
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setF({ ...f, property_types: toggle(f.property_types, p) })}
                      className={`px-3 py-1.5 rounded-full text-xs border ${active ? "bg-[#1A1A1A] text-white border-[#1A1A1A]" : "border-[#E4DFD1] text-[#2A2A2A] hover:bg-[#F3EEE0]"}`}
                      data-testid={`ptype-${p.toLowerCase().replace(/[^a-z0-9]/g,"-")}`}
                    >
                      {p}
                    </button>
                  );
                })}
              </div>
            </Field>
            <div className="mt-4">
              <Field label="Sub-Type Specialties (optional)" hint="Narrow the property types above with the specific sub-types you specialize in. Leave empty if you're open to all sub-types.">
                <LenderSubtypePicker
                  propertyTypes={f.property_types}
                  value={f.property_subtypes}
                  onChange={(v) => setF({ ...f, property_subtypes: v })}
                  testIdPrefix="apply-subtype"
                />
              </Field>
            </div>
            <div className="mt-4">
              <Field label="Geography" hint="Comma-separated 2-letter states (e.g. TX, LA, OK). Use 'NATIONWIDE' for national coverage.">
                <Input
                  value={f._geo_input || f.geography.join(", ")}
                  onChange={(e) => setF({ ...f, _geo_input: e.target.value, geography: e.target.value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) })}
                  placeholder="TX, LA, OK"
                  data-testid="input-geography"
                />
              </Field>
            </div>
            <div className="grid sm:grid-cols-2 gap-4 mt-4">
              <Field label="Min Loan Amount ($)"><Input type="number" value={f.min_loan} onChange={set("min_loan")} data-testid="input-min-loan" /></Field>
              <Field label="Max Loan Amount ($)"><Input type="number" value={f.max_loan} onChange={set("max_loan")} data-testid="input-max-loan" /></Field>
              <Field label="Max LTV (%)"><Input type="number" step="0.1" value={f.max_ltv} onChange={set("max_ltv")} data-testid="input-max-ltv" /></Field>
              <Field label="Max LTC (%)"><Input type="number" step="0.1" value={f.max_ltc} onChange={set("max_ltc")} data-testid="input-max-ltc" /></Field>
              <Field label="Min DSCR (x)"><Input type="number" step="0.01" value={f.min_dscr} onChange={set("min_dscr")} data-testid="input-min-dscr" /></Field>
              <Field label="Min Debt Yield (%)"><Input type="number" step="0.1" value={f.min_debt_yield} onChange={set("min_debt_yield")} data-testid="input-min-dy" /></Field>
              <Field label="Rate Range: Min (%)"><Input type="number" step="0.01" value={f.rate_min} onChange={set("rate_min")} /></Field>
              <Field label="Rate Range: Max (%)"><Input type="number" step="0.01" value={f.rate_max} onChange={set("rate_max")} /></Field>
              <Field label="Typical Term (months)"><Input type="number" value={f.typical_term_months} onChange={set("typical_term_months")} /></Field>
              <Field label="Decision Speed (days)"><Input type="number" value={f.decision_speed_days} onChange={set("decision_speed_days")} /></Field>
              <Field label="Recourse Preference">
                <select value={f.recourse_preference} onChange={set("recourse_preference")} className="w-full h-11 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm">
                  <option value="">—</option>
                  <option value="recourse">Recourse</option>
                  <option value="non-recourse">Non-Recourse</option>
                  <option value="either">Either</option>
                </select>
              </Field>
            </div>
            <div className="mt-4">
              <Field label="Typical Fees"><Input value={f.typical_fees} onChange={set("typical_fees")} placeholder="e.g. 1% origination, $2,500 processing" /></Field>
            </div>
            <div className="mt-4">
              <Field label="Anything else we should know?">
                <Textarea value={f.notes} onChange={set("notes")} placeholder="Sweet spots, deals you love, deal-breakers…" />
              </Field>
            </div>
          </section>

          <div className="flex justify-end pt-2">
            <button type="submit" disabled={busy} className="byrd-btn byrd-btn-dark" data-testid="apply-submit-btn">
              {busy ? "Submitting…" : "Submit application"}
            </button>
          </div>
          <p className="text-[11px] text-[#6B6558]">
            You&apos;ll get a confirmation email now, and a second email with activation instructions
            once a broker approves your application.
          </p>
        </form>
      </div>
    </div>
  );
}
