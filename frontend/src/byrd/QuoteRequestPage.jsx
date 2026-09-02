import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Building2, Check, ArrowRight } from "lucide-react";

export default function QuoteRequestPage() {
  const { qid } = useParams();
  const [meta, setMeta] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [f, setF] = useState({ name: "", email: "", phone: "", best_time: "", message: "" });

  useEffect(() => {
    api.get(`/public/quote/${qid}`)
      .then((r) => setMeta(r.data))
      .catch(() => setNotFound(true));
  }, [qid]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (!f.name || !f.email) {
      toast.error("Please share your name and email so we can follow up.");
      return;
    }
    setBusy(true);
    try {
      await api.post(`/public/quote/${qid}/request-callback`, f);
      setDone(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Couldn't send request — please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (notFound) {
    return (
      <div className="min-h-screen bg-[#FBF8F1] grid place-items-center px-4">
        <div className="byrd-card p-10 max-w-lg text-center">
          <h1 className="font-serif text-3xl font-bold">Quote not found.</h1>
          <p className="text-[#6B6558] mt-3">The link in the PDF may be expired or malformed. Reach us directly at <a href="mailto:wayne@byrd-co.com" className="underline">wayne@byrd-co.com</a>.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FBF8F1] flex flex-col">
      <header className="border-b border-[#E4DFD1] bg-white">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center gap-3">
          <Building2 size={22} className="text-[#C89434]" />
          <div>
            <div className="font-serif text-lg font-bold">Byrd &amp; CO</div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Commercial Real Estate Lending</div>
          </div>
        </div>
      </header>
      <main className="flex-1 max-w-3xl w-full mx-auto px-6 py-10">
        {done ? (
          <div className="byrd-card p-10 text-center" data-testid="quote-request-done">
            <div className="w-14 h-14 mx-auto rounded-full bg-[#E5F1E5] grid place-items-center text-[#2F6B3A]"><Check size={22} /></div>
            <h1 className="font-serif text-3xl font-bold mt-4">We've got it.</h1>
            <p className="text-[#6B6558] mt-3 max-w-md mx-auto">
              Wayne or Caleb will reach out shortly with live terms. If you need us
              faster, call <b>832-813-9802</b> — that goes to Wayne directly.
            </p>
            <Link to="/" className="byrd-btn byrd-btn-outline mt-6 inline-flex" data-testid="quote-request-home">
              Byrd &amp; CO home <ArrowRight size={13} />
            </Link>
          </div>
        ) : (
          <div className="byrd-card p-8 md:p-10" data-testid="quote-request-form">
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Live Quote Request</div>
            <h1 className="font-serif text-3xl md:text-4xl font-bold mt-2">Talk to a Byrd broker.</h1>
            {meta?.property_name || meta?.address ? (
              <p className="text-sm text-[#6B6558] mt-3">
                Regarding: <b className="text-[#1A1A1A]">{meta.property_name || `${meta.address || ""}, ${meta.city || ""} ${meta.state || ""}`.trim()}</b>
                {meta.property_type ? ` · ${meta.property_type}` : ""}
              </p>
            ) : (
              <p className="text-sm text-[#6B6558] mt-3">Share a few details and we'll follow up with live terms and next steps.</p>
            )}

            <form onSubmit={submit} className="mt-6 space-y-4" data-testid="quote-request-form-el">
              <FieldRow>
                <Field label="Name">
                  <Input value={f.name} onChange={set("name")} data-testid="qr-name" required />
                </Field>
                <Field label="Email">
                  <Input type="email" value={f.email} onChange={set("email")} data-testid="qr-email" required />
                </Field>
              </FieldRow>
              <FieldRow>
                <Field label="Phone">
                  <Input value={f.phone} onChange={set("phone")} data-testid="qr-phone" placeholder="(832) 555-0100" />
                </Field>
                <Field label="Best time to reach you">
                  <Input value={f.best_time} onChange={set("best_time")} data-testid="qr-best-time" placeholder="Weekday mornings, CT" />
                </Field>
              </FieldRow>
              <Field label="Anything we should know?">
                <Textarea value={f.message} onChange={set("message")} data-testid="qr-message"
                          rows={4}
                          placeholder="Rate priority, closing timeline, questions on the quote you saw…" />
              </Field>
              <div className="pt-2">
                <button type="submit" disabled={busy}
                        data-testid="qr-submit"
                        className="byrd-btn byrd-btn-primary h-11 px-6 disabled:opacity-60">
                  {busy ? "Sending…" : "Send Request"} <ArrowRight size={13} />
                </button>
                <p className="text-[11px] text-[#6B6558] mt-3">
                  Your info goes directly to Wayne &amp; Caleb Byrd — never shared, sold, or added to a list.
                </p>
              </div>
            </form>
          </div>
        )}
      </main>
    </div>
  );
}

const FieldRow = ({ children }) => (
  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">{children}</div>
);
const Field = ({ label, children }) => (
  <label className="block">
    <div className="text-[11px] font-mono uppercase tracking-widest text-[#6B6558] mb-1">{label}</div>
    {children}
  </label>
);
const Input = (p) => (
  <input {...p} className={`w-full h-11 px-3 border border-[#E4DFD1] bg-white rounded-md text-sm focus:outline-none focus:border-[#C89434] ${p.className || ""}`} />
);
const Textarea = (p) => (
  <textarea {...p} className={`w-full px-3 py-2 border border-[#E4DFD1] bg-white rounded-md text-sm focus:outline-none focus:border-[#C89434] ${p.className || ""}`} />
);
