import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import BrandNav from "@/byrd/BrandNav";
import BrandFooter from "@/byrd/BrandFooter";
import {
  LOAN_PROGRAMS,
  PROPERTY_TYPES,
  PROCESS_STEPS,
  CONTACT,
  HERO_IMAGE,
  LOAN_TYPES_FLAT,
  PROPERTY_TYPES_FLAT,
  PRINCIPAL_PHOTOS,
} from "@/byrd/data";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  ArrowRight,
  Building2,
  Hotel,
  Home as HomeIcon,
  Layers,
  LandPlot,
  Warehouse,
  Building,
  Boxes,
  Phone,
  Mail,
  Star,
  ChevronRight,
  Check,
} from "lucide-react";

const propertyIcons = {
  multifamily: Building2,
  hotels: Hotel,
  office: Building,
  "condo-projects": Boxes,
  sfr: HomeIcon,
  "condo-units": Layers,
  "1-4": Warehouse,
  portfolio: LandPlot,
};

const QuoteForm = () => {
  const [form, setForm] = useState({
    name: "", email: "", phone: "", loan_type: "", loan_amount: "", property_type: "", message: "",
  });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name || !form.email) {
      toast.error("Name and email are required");
      return;
    }
    setBusy(true);
    try {
      await api.post("/public/quote", form);
      setDone(true);
      toast.success("Request sent — we'll be in touch shortly.");
    } catch (err) {
      toast.error("Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="byrd-card p-8 md:p-10 text-center" data-testid="quote-success">
        <div className="w-14 h-14 mx-auto rounded-full bg-[#FBEFD3] border border-[#E5B968] grid place-items-center">
          <Check size={22} className="text-[#7A5410]" />
        </div>
        <h3 className="font-serif text-3xl font-bold mt-5">Request received.</h3>
        <p className="text-[#6B6558] mt-3 max-w-md mx-auto">
          Wayne and Caleb have been notified. Expect a call within one business day.
          If it&apos;s urgent, ring us directly — numbers below.
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-4 font-mono text-sm">
          <a href={`tel:${CONTACT.wayne.phone}`} className="byrd-btn byrd-btn-outline">
            <Phone size={14} /> {CONTACT.wayne.phone}
          </a>
          <a href={`tel:${CONTACT.caleb.phone}`} className="byrd-btn byrd-btn-outline">
            <Phone size={14} /> {CONTACT.caleb.phone}
          </a>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="byrd-card p-6 md:p-8 grid grid-cols-1 md:grid-cols-2 gap-4"
      data-testid="quote-form"
    >
      <div className="md:col-span-2">
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Request a Quote</div>
        <h3 className="font-serif text-3xl md:text-4xl font-bold mt-2 leading-tight">
          Tell us about the deal.
        </h3>
        <p className="text-[#6B6558] mt-2">
          Fastest path is a five-minute conversation. We&apos;ll follow up personally.
        </p>
      </div>

      <div>
        <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Full Name *</label>
        <input
          value={form.name} onChange={(e) => set("name", e.target.value)}
          data-testid="q-name" required
          className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
          placeholder="Your name"
        />
      </div>
      <div>
        <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Email *</label>
        <input
          type="email" value={form.email} onChange={(e) => set("email", e.target.value)}
          data-testid="q-email" required
          className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
          placeholder="you@example.com"
        />
      </div>
      <div>
        <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Phone</label>
        <input
          value={form.phone} onChange={(e) => set("phone", e.target.value)}
          data-testid="q-phone"
          className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
          placeholder="(555) 555-5555"
        />
      </div>
      <div>
        <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Loan Amount</label>
        <input
          value={form.loan_amount} onChange={(e) => set("loan_amount", e.target.value)}
          data-testid="q-amount"
          className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
          placeholder="$500,000"
        />
      </div>
      <div>
        <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Loan Type</label>
        <select
          value={form.loan_type} onChange={(e) => set("loan_type", e.target.value)}
          data-testid="q-loan-type"
          className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
        >
          <option value="">Select…</option>
          {LOAN_TYPES_FLAT.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div>
        <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Property Type</label>
        <select
          value={form.property_type} onChange={(e) => set("property_type", e.target.value)}
          data-testid="q-property-type"
          className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
        >
          <option value="">Select…</option>
          {PROPERTY_TYPES_FLAT.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div className="md:col-span-2">
        <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Tell us about the deal</label>
        <textarea
          value={form.message} onChange={(e) => set("message", e.target.value)}
          data-testid="q-message" rows={4}
          className="mt-1 w-full px-3 py-2 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
          placeholder="Sponsor, asset, timing, and anything a lender should know."
        />
      </div>
      <div className="md:col-span-2 flex flex-col sm:flex-row items-center justify-between gap-3 pt-2">
        <p className="text-xs text-[#6B6558]">
          By submitting you agree to be contacted about your inquiry. No spam, ever.
        </p>
        <button type="submit" disabled={busy} data-testid="q-submit" className="byrd-btn byrd-btn-dark w-full sm:w-auto">
          {busy ? "Sending…" : "Send Request"}
          <ArrowRight size={16} />
        </button>
      </div>
    </form>
  );
};

const Testimonials = () => {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.get("/public/testimonials").then((r) => setItems(r.data));
  }, []);
  return (
    <section id="testimonials" className="py-20 md:py-28 bg-[#F3EEE0]">
      <div className="max-w-7xl mx-auto px-5 sm:px-8">
        <div className="max-w-2xl">
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Reviews</div>
          <h2 className="font-serif text-4xl md:text-5xl font-bold mt-3 leading-tight">What clients say.</h2>
          <p className="text-[#6B6558] mt-4">
            A few operators who chose Byrd &amp; CO for their last closing.
          </p>
        </div>
        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-6">
          {items.map((t) => (
            <div key={t.id} className="byrd-card p-7 md:p-8 flex flex-col" data-testid={`testimonial-${t.id}`}>
              <div className="flex gap-1 text-[#C89434]">
                {Array.from({ length: t.rating || 5 }).map((_, i) => (
                  <Star key={i} size={16} fill="currentColor" strokeWidth={0} />
                ))}
              </div>
              <blockquote className="font-serif text-xl md:text-2xl mt-4 leading-snug text-[#1A1A1A]">
                “{t.quote}”
              </blockquote>
              <div className="mt-6 flex items-center gap-3">
                <img src={t.avatar} alt={t.name} className="w-11 h-11 rounded-full object-cover border border-[#E4DFD1]" />
                <div>
                  <div className="font-semibold text-sm">{t.name}</div>
                  <div className="text-xs text-[#6B6558]">{t.title}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default function Home() {
  return (
    <div>
      <BrandNav />

      {/* HERO */}
      <section className="byrd-hero border-b border-[#E4DFD1]">
        <div className="max-w-7xl mx-auto px-5 sm:px-8 py-16 md:py-24 lg:py-28 grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          <div className="fade-up">
            <div className="byrd-chip byrd-chip-gold">Commercial Real Estate Lending</div>
            <h1 className="font-serif text-5xl sm:text-6xl lg:text-7xl font-bold mt-6 leading-[0.95] tracking-tight">
              Capital, placed<br /><span className="text-[#C89434]">with intention.</span>
            </h1>
            <p className="mt-6 text-lg text-[#2A2A2A] max-w-xl leading-relaxed">
              Byrd &amp; CO structures commercial and residential debt for owners, operators and developers —
              multifamily, hotels, office, condo, and 1–4 units. Purchases, refinances, cash-outs, and new construction.
            </p>
            <div className="mt-8 flex flex-col sm:flex-row gap-3">
              <a href="#contact" className="byrd-btn byrd-btn-primary" data-testid="hero-cta-primary">
                Request a Quote <ArrowRight size={16} />
              </a>
              <a href="#programs" className="byrd-btn byrd-btn-outline" data-testid="hero-cta-secondary">
                Explore Programs
              </a>
            </div>
            <div className="mt-10 flex flex-wrap gap-x-8 gap-y-3 text-sm text-[#6B6558]">
              <div><span className="font-serif text-2xl text-[#1A1A1A] font-semibold">20+</span> years combined</div>
              <div><span className="font-serif text-2xl text-[#1A1A1A] font-semibold">8</span> property verticals</div>
              <div><span className="font-serif text-2xl text-[#1A1A1A] font-semibold">Same-day</span> callbacks</div>
            </div>
          </div>
          <div className="relative fade-up-2">
            <div className="absolute -top-6 -right-6 w-40 h-40 bg-[#C89434] rounded-lg -z-0 hidden md:block" />
            <div className="relative border border-[#1A1A1A] rounded-lg overflow-hidden shadow-[0_20px_50px_-15px_rgba(26,26,26,0.35)]">
              <img
                src={HERO_IMAGE}
                alt="City skyline"
                className="w-full h-[420px] lg:h-[560px] object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-[#1A1A1A]/50 to-transparent" />
              <div className="absolute bottom-6 left-6 right-6 flex items-end justify-between text-white">
                <div>
                  <div className="font-mono text-[10px] uppercase tracking-widest opacity-80">Currently Placing</div>
                  <div className="font-serif text-2xl font-semibold mt-1">Debt from $250K to $50M+</div>
                </div>
                <a
                  href={`tel:${CONTACT.wayne.phone}`}
                  className="hidden sm:inline-flex items-center gap-2 bg-white/95 text-[#1A1A1A] px-3 py-2 rounded-md text-sm font-semibold hover:bg-[#C89434]"
                  data-testid="hero-call"
                >
                  <Phone size={14} /> Call Byrd &amp; CO
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* PROGRAMS */}
      <section id="programs" className="py-20 md:py-28">
        <div className="max-w-7xl mx-auto px-5 sm:px-8">
          <div className="flex items-end justify-between flex-wrap gap-6 mb-12">
            <div className="max-w-xl">
              <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Programs</div>
              <h2 className="font-serif text-4xl md:text-5xl font-bold mt-3 leading-tight">
                Four ways to move.
              </h2>
              <p className="text-[#6B6558] mt-4">
                Whether you&apos;re acquiring, unlocking equity, refinancing to term, or breaking ground —
                we place the debt that fits.
              </p>
            </div>
            <a href="#contact" className="byrd-btn byrd-btn-dark">
              Get Terms <ArrowRight size={16} />
            </a>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {LOAN_PROGRAMS.map((p, i) => (
              <div
                key={p.key}
                className="byrd-card byrd-card-hover p-7 md:p-9 flex flex-col"
                data-testid={`program-${p.key}`}
              >
                <div className="font-mono text-[11px] tracking-widest text-[#C89434]">
                  {String(i + 1).padStart(2, "0")}
                </div>
                <h3 className="font-serif text-2xl md:text-3xl font-bold mt-2">{p.title}</h3>
                <p className="text-[#1A1A1A] mt-3 text-base font-medium">{p.lead}</p>
                <p className="text-[#6B6558] mt-3 text-sm leading-relaxed">{p.body}</p>
                <div className="mt-6">
                  <a href="#contact" className="text-sm font-semibold text-[#1A1A1A] hover:text-[#C89434] inline-flex items-center gap-1">
                    Start this program <ChevronRight size={14} />
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PROPERTIES */}
      <section id="properties" className="py-20 md:py-28 bg-[#1A1A1A] text-[#FBF8F1]">
        <div className="max-w-7xl mx-auto px-5 sm:px-8">
          <div className="max-w-2xl">
            <div className="font-mono text-[11px] uppercase text-[#E5B968] tracking-widest">// Property Types</div>
            <h2 className="font-serif text-4xl md:text-5xl font-bold mt-3 leading-tight">
              We lend across the map.
            </h2>
            <p className="text-[#C9C1AF] mt-4">
              Eight property verticals, one relationship. Portfolio and leasehold structures welcome.
            </p>
          </div>
          <div className="mt-12 grid grid-cols-2 md:grid-cols-4 gap-4">
            {PROPERTY_TYPES.map((p) => {
              const Icon = propertyIcons[p.key] || Building2;
              return (
                <div
                  key={p.key}
                  className="border border-[#3A3A3A] p-5 md:p-6 rounded-lg hover:border-[#C89434] transition-colors group"
                  data-testid={`property-${p.key}`}
                >
                  <div className="w-10 h-10 rounded-md bg-[#2A2A2A] grid place-items-center text-[#C89434] group-hover:bg-[#C89434] group-hover:text-[#1A1A1A] transition-colors">
                    <Icon size={18} />
                  </div>
                  <div className="font-serif text-lg font-semibold mt-4">{p.title}</div>
                  <div className="text-xs text-[#8F8877] mt-1">{p.note}</div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* PROCESS */}
      <section id="process" className="py-20 md:py-28">
        <div className="max-w-7xl mx-auto px-5 sm:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-[.55fr_1fr] gap-12 lg:gap-16">
            <div>
              <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Process</div>
              <h2 className="font-serif text-4xl md:text-5xl font-bold mt-3 leading-tight">
                From call to close, orchestrated.
              </h2>
              <p className="text-[#6B6558] mt-4 max-w-md">
                Every deal has moments where it can stall. Our job is to see them coming and route around them.
              </p>
              <a href="#contact" className="byrd-btn byrd-btn-primary mt-8 inline-flex">
                Start a Deal <ArrowRight size={16} />
              </a>
            </div>
            <ol className="relative border-l-2 border-[#E4DFD1] pl-8 space-y-10">
              {PROCESS_STEPS.map((s) => (
                <li key={s.n} className="relative" data-testid={`process-${s.n}`}>
                  <span className="absolute -left-[41px] top-0 w-8 h-8 rounded-full bg-[#C89434] text-[#1A1A1A] grid place-items-center font-mono text-xs font-bold">
                    {s.n}
                  </span>
                  <h3 className="font-serif text-2xl font-bold">{s.title}</h3>
                  <p className="text-[#6B6558] mt-2 max-w-lg leading-relaxed">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* PRINCIPALS */}
      <section id="principals" className="py-20 md:py-28 bg-[#F3EEE0]">
        <div className="max-w-7xl mx-auto px-5 sm:px-8">
          <div className="max-w-2xl">
            <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Team</div>
            <h2 className="font-serif text-4xl md:text-5xl font-bold mt-3 leading-tight">
              The people behind the placements.
            </h2>
          </div>
          <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-8">
            {[
              { key: "wayne", ...CONTACT.wayne, bio: "Two decades structuring commercial real estate debt across multifamily, hospitality and mixed-use." },
              { key: "caleb", ...CONTACT.caleb, bio: "Focuses on portfolio, construction and value-add loans for owner-operators and developers." },
            ].map((p) => (
              <div key={p.key} className="byrd-card overflow-hidden" data-testid={`principal-${p.key}`}>
                <div className="aspect-[5/3] overflow-hidden">
                  <img src={PRINCIPAL_PHOTOS[p.key]} alt={p.name} className="w-full h-full object-cover" />
                </div>
                <div className="p-7">
                  <div className="font-serif text-3xl font-bold">{p.name}</div>
                  <div className="text-xs uppercase font-mono tracking-widest text-[#C89434] mt-1">Principal</div>
                  <p className="text-[#6B6558] mt-3 leading-relaxed">{p.bio}</p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    <a href={`tel:${p.phone}`} className="byrd-btn byrd-btn-outline">
                      <Phone size={14} /> {p.phone}
                    </a>
                    <a href={`mailto:${p.email}`} className="byrd-btn byrd-btn-outline">
                      <Mail size={14} /> Email
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TESTIMONIALS */}
      <Testimonials />

      {/* CONTACT / QUOTE */}
      <section id="contact" className="py-20 md:py-28">
        <div className="max-w-6xl mx-auto px-5 sm:px-8">
          <QuoteForm />
        </div>
      </section>

      <BrandFooter />
    </div>
  );
}
