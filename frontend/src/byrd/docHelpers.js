import React from "react";

const STATUS_STYLES = {
  pending: { chip: "byrd-chip", label: "Pending" },
  uploaded: { chip: "byrd-chip byrd-chip-blue", label: "Uploaded" },
  reviewed: { chip: "byrd-chip byrd-chip-green", label: "Reviewed" },
  rejected: { chip: "byrd-chip byrd-chip-red", label: "Rejected" },
};

export function StatusChip({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.pending;
  return <span className={s.chip} data-testid={`status-chip-${status}`}>{s.label}</span>;
}

export function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const result = r.result;
      // result: data:mime;base64,XXXXXX
      const idx = result.indexOf(",");
      resolve(result.substring(idx + 1));
    };
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

export function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

export const STATUS_OPTIONS = [
  { v: "pending", label: "Pending" },
  { v: "uploaded", label: "Uploaded" },
  { v: "reviewed", label: "Reviewed" },
  { v: "rejected", label: "Rejected" },
];
