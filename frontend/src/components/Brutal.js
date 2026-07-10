import React from "react";

export const Metric = ({ label, value, unit, delta, testId }) => (
  <div className="border-2 border-black bg-white p-5" data-testid={testId}>
    <div className="font-mono text-[10px] uppercase text-[#555] tracking-widest">{label}</div>
    <div className="font-mono text-3xl font-bold mt-2 tracking-tight">
      {value}
      {unit && <span className="text-base text-[#555] ml-1">{unit}</span>}
    </div>
    {delta !== undefined && (
      <div className={`font-mono text-[11px] mt-2 ${delta >= 0 ? "text-[#00C853]" : "text-[#FF3B30]"}`}>
        {delta >= 0 ? "▲" : "▼"} {Math.abs(delta)}% vs prior period
      </div>
    )}
  </div>
);

export const SectionHeader = ({ eyebrow, title, action }) => (
  <div className="flex items-end justify-between mb-6 gap-4 flex-wrap">
    <div>
      {eyebrow && (
        <div className="font-mono text-[11px] uppercase text-[#555] tracking-widest mb-2">// {eyebrow}</div>
      )}
      <h1 className="font-display text-4xl font-bold tracking-tighter">{title}</h1>
    </div>
    {action}
  </div>
);

export const Chip = ({ children, color = "black" }) => {
  const styles = {
    black: "border-black bg-black text-white",
    green: "border-black bg-[#00C853] text-black",
    yellow: "border-black bg-[#FFCC00] text-black",
    red: "border-black bg-[#FF3B30] text-white",
    ghost: "border-black bg-white text-black",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 border-2 font-mono text-[10px] uppercase tracking-wider ${styles[color]}`}>
      {children}
    </span>
  );
};

export const fmtNum = (n) => new Intl.NumberFormat().format(n || 0);
export const fmtMoney = (n) =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n || 0);
