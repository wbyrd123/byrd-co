import React, { useMemo } from "react";
import { subtypesForLenderTypes } from "@/byrd/dealData";

/**
 * Chip picker for lender specialties. Given the lender's selected top-level
 * `property_types`, renders the flat, grouped list of possible sub-types. When
 * the lender has selected no top-level types (or none with defined sub-types),
 * renders a subtle hint and no chips.
 *
 * Value is a plain string[] (subset of the eligible subtypes). Any values that
 * are no longer eligible (because the lender un-checked their parent top-level)
 * are still shown as "orphan" chips with a strikethrough so the lender knows to
 * clean them up.
 */
export default function LenderSubtypePicker({ propertyTypes = [], value = [], onChange, testIdPrefix = "cb-subtype" }) {
  const eligible = useMemo(() => subtypesForLenderTypes(propertyTypes), [propertyTypes]);
  const eligibleSet = useMemo(() => new Set(eligible.map((x) => x.subtype)), [eligible]);
  const orphans = value.filter((v) => !eligibleSet.has(v));
  const toggle = (s) => {
    if (value.includes(s)) onChange(value.filter((x) => x !== s));
    else onChange([...value, s]);
  };
  if (eligible.length === 0 && orphans.length === 0) {
    return (
      <p className="text-[11px] text-[#6B6558] mt-1">
        Pick a property type above with sub-types (e.g. Industrial, Retail, Office) to specify specialties.
      </p>
    );
  }
  // Group by parent for readability.
  const byParent = {};
  for (const { subtype, parent } of eligible) {
    if (!byParent[parent]) byParent[parent] = [];
    byParent[parent].push(subtype);
  }
  return (
    <div className="space-y-3 mt-1" data-testid={`${testIdPrefix}-wrap`}>
      {Object.entries(byParent).map(([parent, subs]) => (
        <div key={parent}>
          <div className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558] mb-1.5">// {parent}</div>
          <div className="flex flex-wrap gap-1.5">
            {subs.map((s) => {
              const active = value.includes(s);
              return (
                <button
                  type="button"
                  key={s}
                  onClick={() => toggle(s)}
                  data-testid={`${testIdPrefix}-${s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`}
                  className={`px-2.5 py-1 rounded-full text-[11px] border transition-colors ${active
                    ? "bg-[#C89434] text-white border-[#C89434]"
                    : "border-[#E4DFD1] text-[#2A2A2A] hover:bg-[#F3EEE0]"}`}
                >
                  {s}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {orphans.length > 0 && (
        <div>
          <div className="text-[10px] font-mono uppercase tracking-widest text-[#B23B3B] mb-1.5">
            // No longer covered — un-check to clean up
          </div>
          <div className="flex flex-wrap gap-1.5">
            {orphans.map((s) => (
              <button
                type="button"
                key={s}
                onClick={() => toggle(s)}
                data-testid={`${testIdPrefix}-orphan-${s.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
                className="px-2.5 py-1 rounded-full text-[11px] border border-[#E38380] text-[#8A1F1A] line-through hover:bg-[#FADCDA]"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
