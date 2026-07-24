import React, { useMemo, useRef, useState } from "react";
import { Upload, X, FileText, CheckCircle2, Loader2, Zap } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

// Simple heuristic to auto-match a filename to a doc-line label.
// Returns { docId, confidence } or null. Confidence 3=strong, 2=medium, 1=weak.
function autoMatchDoc(filename, docs) {
  const name = filename.toLowerCase();
  // Normalize: strip extension, replace underscores/dashes/dots with spaces so word-boundary regex works.
  const cleaned = name.replace(/\.[^.]+$/, "").replace(/[_\-.]+/g, " ").replace(/\s+/g, " ").trim();
  const yearMatch = cleaned.match(/20\d{2}/);
  const year = yearMatch ? parseInt(yearMatch[0], 10) : null;

  // Match rules (order = priority)
  const rules = [
    // Personal Financial Statement — very specific keywords first
    { pattern: /\b(pfs|personal financial statement)\b/i, label: /personal financial/i, confidence: 3 },
    // Tax returns
    { pattern: /\b(tax return|1040|schedule e|k ?1)\b/i, labels: /tax return/i, confidence: 3, useYear: true },
    // Bank statements
    { pattern: /\bbank statement/i, label: /bank statement/i, confidence: 3 },
    // Government ID
    { pattern: /\b(driver'?s? licen[cs]e|passport|state id|government id|photo id)\b/i, label: /(government|photo).*id/i, confidence: 3 },
    // Resume / Bio
    { pattern: /\b(resume|bio|cv|curriculum)\b/i, label: /(resume|bio)/i, confidence: 3 },
    // Entity docs
    { pattern: /\b(operating agreement|articles? of (organization|incorporation)|llc|ein|w ?9|entity docs?)\b/i, label: /(entity|operating|llc|ein)/i, confidence: 3 },
    // Rent roll
    { pattern: /\brent roll/i, label: /rent roll/i, confidence: 3 },
    // Property T12 / Financials
    { pattern: /\b(t ?12|trailing 12|operating (statements?|history))\b/i, label: /(t-?12|operating|financial)/i, confidence: 3 },
    // Purchase / Sale contract
    { pattern: /\b(purchase (and sale )?agreement|purchase contract|psa)\b/i, label: /(purchase|contract|psa)/i, confidence: 3 },
    // Insurance
    { pattern: /\binsurance/i, label: /insurance/i, confidence: 2 },
    // Appraisal
    { pattern: /\bappraisal/i, label: /appraisal/i, confidence: 2 },
    // Survey
    { pattern: /\bsurvey/i, label: /survey/i, confidence: 2 },
    // Photos
    { pattern: /\b(photos?|images?|pictures?)\b/i, label: /photo/i, confidence: 2 },
  ];

  // Try each rule
  for (const rule of rules) {
    if (!rule.pattern.test(cleaned)) continue;
    let candidates = docs.filter((d) => {
      const pattern = rule.label || rule.labels;
      return pattern && pattern.test(d.label || "");
    });
    if (candidates.length === 0) continue;

    // If tax return + year, try to pick "Year 1/2/3" by ordinal recency
    if (rule.useYear && year) {
      // Sort candidates by their label's "Year X" number
      const withYear = candidates.map((d) => {
        const m = (d.label || "").match(/year\s*(\d+)/i);
        return { d, yearIdx: m ? parseInt(m[1], 10) : null };
      });
      // Assume Year 1 = most recent completed year (last year), Year 2 = year-1, etc.
      // Pick candidate whose yearIdx corresponds to (currentYear - 1 - year)
      const now = new Date().getFullYear();
      const targetIdx = now - year; // 2023 -> 3 in 2026, but Year 1 = 2025's tax return typically
      // Prefer exact match
      let picked = withYear.find((c) => c.yearIdx === targetIdx);
      if (!picked) picked = withYear[0];
      return { docId: picked.d.id, confidence: rule.confidence, reason: `filename matched "${rule.pattern.source}"` };
    }

    // Otherwise take the first match — prefer one that doesn't already have files (spread across lines)
    const empty = candidates.find((d) => !((d.files && d.files.length) || d.file_id));
    const chosen = empty || candidates[0];
    return { docId: chosen.id, confidence: rule.confidence, reason: `filename matched "${rule.pattern.source}"` };
  }
  return null;
}

async function readAsB64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const s = r.result;
      resolve(s.substring(s.indexOf(",") + 1));
    };
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

const CREATE_NEW = "__create_new__";
const SKIP = "__skip__";

export default function BulkUploadZone({ scenarioId, docs, sponsors, sponsorFilter, onReload }) {
  const [dragActive, setDragActive] = useState(false);
  const [queue, setQueue] = useState([]); // {file, docId, status:'pending'|'uploading'|'done'|'error', error?, newLabel?, newCategory?, sponsorId?}
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef(null);
  const [expanded, setExpanded] = useState(false);

  const availableDocs = useMemo(
    () => docs.filter((d) => d.label !== "Signed Fee Agreement" && !d.system),
    [docs],
  );

  // A ref-array selector list, sorted with best matches at top
  const docOptions = useMemo(() => {
    return availableDocs.map((d) => ({
      id: d.id,
      label: `${d.label}${d.sponsor_id ? ` — ${(sponsors.find((s) => s.id === d.sponsor_id)?.name) || "Sponsor"}` : " (shared)"}${((d.files && d.files.length) || d.file_id) ? ` · ${(d.files?.length || 1)} file${(d.files?.length || 1) > 1 ? "s" : ""}` : ""}`,
    }));
  }, [availableDocs, sponsors]);

  const defaultSponsorId = sponsorFilter && sponsorFilter !== "all" && sponsorFilter !== "shared" ? sponsorFilter : "";

  const addFiles = (fileList) => {
    const items = Array.from(fileList).map((file) => {
      const match = autoMatchDoc(file.name, availableDocs);
      return {
        file,
        docId: match?.docId || "",
        matchConfidence: match?.confidence || 0,
        matchReason: match?.reason || "",
        status: "pending",
        newLabel: "",
        newCategory: "Other",
        sponsorId: defaultSponsorId,
      };
    });
    setQueue((prev) => [...prev, ...items]);
    setExpanded(true);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
  };

  const updateItem = (idx, patch) => setQueue((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  const removeItem = (idx) => setQueue((prev) => prev.filter((_, i) => i !== idx));
  const clearAll = () => setQueue([]);

  const applyAll = async () => {
    if (queue.length === 0) return;
    // Validate: every non-skipped item has a target
    const problems = queue.filter((q) => q.status !== "done" && q.docId !== SKIP && !q.docId);
    if (problems.length > 0) {
      toast.error(`${problems.length} file(s) need a target line selected`);
      return;
    }
    setUploading(true);
    let successCount = 0;
    let errorCount = 0;
    for (let i = 0; i < queue.length; i++) {
      const it = queue[i];
      if (it.status === "done" || it.docId === SKIP) continue;
      updateItem(i, { status: "uploading" });
      try {
        let targetDocId = it.docId;
        // Create new line first if needed
        if (targetDocId === CREATE_NEW) {
          const label = (it.newLabel || it.file.name.replace(/\.[^.]+$/, "")).trim();
          if (!label) throw new Error("Give the new line a label");
          const r = await api.post(`/admin/scenarios/${scenarioId}/docs`, {
            label,
            category: it.newCategory || "Other",
            required: false,
            sponsor_id: it.sponsorId || null,
          });
          targetDocId = r.data?.id;
          if (!targetDocId) throw new Error("Failed to create doc line");
        }
        const b64 = await readAsB64(it.file);
        await api.post(`/admin/scenarios/${scenarioId}/docs/${targetDocId}/upload`, {
          filename: it.file.name,
          content_type: it.file.type || "application/octet-stream",
          data_b64: b64,
        });
        updateItem(i, { status: "done" });
        successCount++;
      } catch (err) {
        updateItem(i, { status: "error", error: err?.response?.data?.detail || err?.message || "Upload failed" });
        errorCount++;
      }
    }
    setUploading(false);
    if (successCount > 0) {
      toast.success(`Uploaded ${successCount} file${successCount > 1 ? "s" : ""}${errorCount ? ` · ${errorCount} failed` : ""}`);
      onReload();
    } else if (errorCount > 0) {
      toast.error(`${errorCount} upload${errorCount > 1 ? "s" : ""} failed`);
    }
  };

  const pendingCount = queue.filter((q) => q.status === "pending" || q.status === "error").length;
  const doneCount = queue.filter((q) => q.status === "done").length;
  const autoMatched = queue.filter((q) => q.matchConfidence >= 2 && q.docId && q.docId !== CREATE_NEW && q.docId !== SKIP).length;

  return (
    <div
      className={`byrd-card border-2 ${dragActive ? "border-[#C89434] bg-[#FBEFD3]/30" : "border-dashed border-[#C89434]/40"} p-5 transition-colors`}
      onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
      onDragLeave={() => setDragActive(false)}
      onDrop={onDrop}
      data-testid="bulk-upload-zone"
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-md bg-[#FBEFD3] border border-[#C89434]/40 grid place-items-center text-[#C89434]">
            <Upload size={20} />
          </div>
          <div>
            <div className="font-serif text-lg font-bold">Bulk Upload</div>
            <div className="text-xs text-[#6B6558]">
              Drop many files here (or click to browse) — we&apos;ll auto-match each to the right doc line. Files upload on behalf of the borrower.
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="byrd-btn byrd-btn-outline"
            data-testid="bulk-browse-btn"
          >
            <Upload size={14} /> Browse files
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
            data-testid="bulk-file-input"
          />
        </div>
      </div>

      {queue.length > 0 && (
        <>
          <div className="mt-4 border-t border-[#E4DFD1] pt-3 flex items-center justify-between text-xs text-[#6B6558]">
            <div className="flex items-center gap-3 flex-wrap">
              <span data-testid="bulk-queue-count">{queue.length} file{queue.length > 1 ? "s" : ""} queued</span>
              {autoMatched > 0 && (
                <span className="text-[#245C25] inline-flex items-center gap-1">
                  <Zap size={11} /> {autoMatched} auto-matched
                </span>
              )}
              {doneCount > 0 && <span className="text-[#23446E]">{doneCount} uploaded</span>}
              {pendingCount > 0 && <span>{pendingCount} pending</span>}
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => setExpanded((v) => !v)} className="underline hover:text-[#1A1A1A]" data-testid="bulk-toggle-expanded">
                {expanded ? "Hide" : "Show"} list
              </button>
              <button type="button" onClick={clearAll} disabled={uploading} className="underline hover:text-[#8A1F1A] disabled:opacity-50" data-testid="bulk-clear-all">
                Clear
              </button>
            </div>
          </div>

          {expanded && (
            <div className="mt-3 space-y-2 max-h-[420px] overflow-y-auto" data-testid="bulk-queue-list">
              {queue.map((it, i) => (
                <div
                  key={`${it.file.name}-${i}`}
                  className={`flex flex-col md:flex-row md:items-center gap-2 border rounded-md p-2 ${
                    it.status === "done" ? "border-[#245C25]/30 bg-[#E5F0E5]/30" :
                    it.status === "error" ? "border-[#8A1F1A]/30 bg-[#FCE8E6]/30" :
                    "border-[#E4DFD1] bg-white"
                  }`}
                  data-testid={`bulk-row-${i}`}
                >
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {it.status === "done" ? (
                      <CheckCircle2 size={14} className="text-[#245C25] shrink-0" />
                    ) : it.status === "uploading" ? (
                      <Loader2 size={14} className="text-[#C89434] shrink-0 animate-spin" />
                    ) : it.status === "error" ? (
                      <X size={14} className="text-[#8A1F1A] shrink-0" />
                    ) : (
                      <FileText size={14} className="text-[#6B6558] shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-sm truncate" title={it.file.name}>{it.file.name}</div>
                      <div className="text-[10px] text-[#6B6558]">
                        {(it.file.size / 1024).toFixed(1)} KB
                        {it.matchConfidence >= 2 && it.status === "pending" && (
                          <span className="text-[#245C25] ml-2">
                            <Zap size={9} className="inline" /> auto-matched
                          </span>
                        )}
                        {it.error && <span className="text-[#8A1F1A] ml-2">— {it.error}</span>}
                      </div>
                    </div>
                  </div>
                  {it.status !== "done" && (
                    <div className="flex items-center gap-2 flex-wrap md:flex-nowrap">
                      <select
                        value={it.docId}
                        onChange={(e) => updateItem(i, { docId: e.target.value })}
                        disabled={uploading || it.status === "uploading"}
                        className="h-8 px-2 border border-[#E4DFD1] bg-white rounded-md text-xs min-w-[200px] max-w-[300px]"
                        data-testid={`bulk-target-${i}`}
                      >
                        <option value="">— Choose doc line —</option>
                        {docOptions.map((o) => (
                          <option key={o.id} value={o.id}>{o.label}</option>
                        ))}
                        <option value={CREATE_NEW}>+ Create new line…</option>
                        <option value={SKIP}>Skip this file</option>
                      </select>
                      {it.docId === CREATE_NEW && (
                        <input
                          value={it.newLabel}
                          onChange={(e) => updateItem(i, { newLabel: e.target.value })}
                          placeholder="Line label (e.g. Insurance Policy)"
                          className="h-8 px-2 border border-[#E4DFD1] bg-white rounded-md text-xs w-[180px]"
                          data-testid={`bulk-newlabel-${i}`}
                        />
                      )}
                      <button
                        type="button"
                        onClick={() => removeItem(i)}
                        disabled={uploading || it.status === "uploading"}
                        className="text-[#8A1F1A] hover:text-[#5A0F0A] disabled:opacity-40 p-1"
                        data-testid={`bulk-remove-${i}`}
                        title="Remove from queue"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={applyAll}
              disabled={uploading || pendingCount === 0}
              className="byrd-btn byrd-btn-dark disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="bulk-upload-all"
            >
              {uploading ? (
                <><Loader2 size={14} className="animate-spin" /> Uploading…</>
              ) : (
                <><Upload size={14} /> Upload {pendingCount} file{pendingCount !== 1 ? "s" : ""}</>
              )}
            </button>
          </div>
        </>
      )}

      {queue.length === 0 && (
        <div className="mt-4 text-center text-xs text-[#6B6558] py-3 border-t border-dashed border-[#E4DFD1]">
          Drop files anywhere in this box, or click <span className="font-semibold">Browse files</span>. Common filenames (tax returns, PFS, entity docs, bank statements, ID) auto-match. You can create new doc lines on-the-fly.
        </div>
      )}
    </div>
  );
}
