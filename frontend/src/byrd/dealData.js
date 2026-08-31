// Deal engine shared helpers
export const LOAN_TYPES = ["Purchase", "Refinance", "Cash-Out", "Construction", "Bridge", "Portfolio"];

export const PROPERTY_TYPES = [
  "Multifamily", "Hotel", "Office", "Retail", "Industrial", "Healthcare",
  "Special Use", "Mobile Home Park", "Self Storage",
  "Condo Project", "Single-Family Residence", "Condo Unit", "1-4 Unit",
  "Portfolio", "New Construction", "Other",
];

// Sub-type map for the Package screen. Keys must match PROPERTY_TYPES entries.
// Sourced from CommLoan property-type flyer + broker additions.
// Types not listed here (e.g. "Other", "1-4 Unit") intentionally have no sub-types.
export const PROPERTY_SUBTYPES = {
  Retail: [
    "Factory Outlet",
    "Mall Regional",
    "Mall Super Regional",
    "Neighborhood Center Grocery (Anchored)",
    "Power Center",
    "Retail Shadow Anchored",
    "Retail Single Tenant",
    "Unanchored Retail Strip",
  ],
  Multifamily: [
    "Apartment Building CO-OP",
    "Apartment Building Condo",
    "Apartment Building Garden",
    "Apartment Building Mid-High Rise",
    "Apartment Building Townhomes",
    "Mixed Use",
    "Senior Housing / 55+ Community",
    "Special Use — Military",
    "Special Use — Student",
  ],
  Industrial: [
    "Flex Space / R&D",
    "Manufacturing Heavy Industrial",
    "Manufacturing Light Industrial",
    "Warehouse Bulk District",
    "Warehouse Cold Storage",
  ],
  Office: [
    "CBD Central Business District",
    "Medical Office",
    "Mixed Use (Office / Retail)",
    "Office Single Tenant",
    "Suburban Garden Office",
    "Suburban High Rise",
  ],
  Healthcare: [
    "Assisted Living Facility",
    "Hospital",
    "Inpatient Facility",
    "Outpatient Facility",
    "Skilled Nursing (Memory Care)",
  ],
  "Special Use": [
    "Auto Body / Service and Repair",
    "Auto Dealership",
    "Bars / Nightclubs",
    "Bowling Alley",
    "C-Store",
    "Campground",
    "Car Wash",
    "Daycare Facility",
    "Franchise Restaurant",
    "Non-Franchise Restaurant",
    "Funeral Home",
    "Gas / Fuel Station",
    "Golf Course",
    "Marina",
    "Movie Theatre",
    "Single Family Home Portfolio",
  ],
  Hotel: [
    "Flagged / Unflagged Conversion",
    "Flagged / Unflagged Full Service",
    "Flagged / Unflagged Limited Service",
    "Flagged / Unflagged Suite / Extended Stay",
  ],
  "Mobile Home Park": [
    "1-Star",
    "2-Star",
    "3-Star",
    "4-Star",
    "5-Star",
  ],
};

export const RECOURSE_OPTIONS = ["recourse", "non-recourse", "partial"];

export const INSTITUTION_TYPES = [
  { v: "bank", label: "Bank" },
  { v: "credit_union", label: "Credit Union" },
  { v: "private", label: "Private / Debt Fund" },
  { v: "agency", label: "Agency (Fannie/Freddie/HUD)" },
  { v: "bridge", label: "Bridge Lender" },
  { v: "hard_money", label: "Hard Money" },
  { v: "other", label: "Other" },
];

export const SCENARIO_STATUSES = [
  { v: "draft", label: "Draft", chip: "byrd-chip" },
  { v: "shopping", label: "Shopping", chip: "byrd-chip byrd-chip-blue" },
  { v: "term_sheet", label: "Term Sheet", chip: "byrd-chip byrd-chip-gold" },
  { v: "closed", label: "Closed", chip: "byrd-chip byrd-chip-green" },
  { v: "lost", label: "Lost", chip: "byrd-chip byrd-chip-red" },
];

export const LENDER_STATUSES = [
  { v: "active", label: "Active", chip: "byrd-chip byrd-chip-green" },
  { v: "passive", label: "Passive", chip: "byrd-chip byrd-chip-gold" },
  { v: "dormant", label: "Dormant", chip: "byrd-chip" },
];

export const fmtMoney = (v) => {
  if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "—";
  return "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
};

export const fmtPct = (v, digits = 2) => {
  if (v === null || v === undefined || v === "") return "—";
  return `${Number(v).toFixed(digits)}%`;
};

export const fmtNum = (v) => (v === null || v === undefined || v === "" ? "—" : v);

export const scenarioStatusChip = (v) => {
  const found = SCENARIO_STATUSES.find((s) => s.v === v);
  return found || SCENARIO_STATUSES[0];
};
export const lenderStatusChip = (v) => {
  const found = LENDER_STATUSES.find((s) => s.v === v);
  return found || LENDER_STATUSES[0];
};
