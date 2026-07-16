// Shared Byrd & CO data — logos, services, property types, testimonials fallback

export const LOGO_URL =
  "https://customer-assets-7cd3h4nn.emergentagent.net/job_google-ads-auto-2/artifacts/b2zezk1u_Byrd%20%26%20Co%20Logo.jpg";

export const CONTACT = {
  wayne: { name: "Wayne Byrd", phone: "832-813-9802", email: "wayne@byrd-co.com" },
  caleb: { name: "Caleb Byrd", phone: "832-661-4390", email: "caleb@byrd-co.com" },
};

export const LOAN_PROGRAMS = [
  {
    key: "purchase",
    title: "Purchase Financing",
    lead: "Acquire commercial and residential income properties with speed and certainty.",
    body: "Competitive terms structured around your business plan — bridge, permanent, or agency debt.",
  },
  {
    key: "refi",
    title: "Refinance",
    lead: "Lower rate, extend term, restructure — with a lender who reads the deal, not the form.",
    body: "Rate-and-term refi options for stabilized assets across every property type we lend on.",
  },
  {
    key: "cashout",
    title: "Cash-Out",
    lead: "Unlock equity to reinvest, renovate, or expand.",
    body: "Cash-out programs sized to your DSCR and asset value — with a straight-talk broker in your corner.",
  },
  {
    key: "construction",
    title: "New Construction",
    lead: "Ground-up and value-add construction lending for developers who ship.",
    body: "Draw schedules, contingency planning, and takeout debt lined up before you break ground.",
  },
];

export const PROPERTY_TYPES = [
  { key: "multifamily", title: "Multifamily", note: "5+ units, market-rate & workforce" },
  { key: "hotels", title: "Hotels", note: "Flagged and independent, incl. SBA" },
  { key: "office", title: "Office", note: "Class A/B, medical, flex" },
  { key: "condo-projects", title: "Condo Projects", note: "Ground-up and conversions" },
  { key: "sfr", title: "Single-Family Residences", note: "SFR investors and portfolios" },
  { key: "condo-units", title: "Condo Units", note: "Incl. leaseholds" },
  { key: "1-4", title: "1–4 Unit Properties", note: "DSCR + agency programs" },
  { key: "portfolio", title: "Portfolio Loans", note: "Blanket across 5–100+ units" },
];

export const LOAN_TYPES_FLAT = [
  "Purchase",
  "Refinance",
  "Cash-Out",
  "New Construction",
  "Portfolio",
  "Bridge",
];

export const PROPERTY_TYPES_FLAT = [
  "Multifamily",
  "Hotel",
  "Office",
  "Condo Project",
  "Single-Family Residence",
  "Condo Unit",
  "1–4 Unit Property",
  "Portfolio",
  "Other",
];

export const PROCESS_STEPS = [
  { n: "01", title: "Talk", body: "A 15-minute call to understand the deal — sponsor, asset, and outcome." },
  { n: "02", title: "Terms", body: "Written term sheet within days. No mystery, no bait-and-switch." },
  { n: "03", title: "Docs", body: "Upload to your private portal. We tell you exactly what's outstanding." },
  { n: "04", title: "Close", body: "Underwriting, appraisal, and closing — orchestrated so nothing stalls." },
];

export const PRINCIPAL_PHOTOS = {
  wayne:
    "https://images.unsplash.com/photo-1560250097-0b93528c311a?w=600&h=700&fit=crop",
  caleb:
    "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=600&h=700&fit=crop",
};

export const HERO_IMAGE =
  "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=1600&h=1000&fit=crop";
