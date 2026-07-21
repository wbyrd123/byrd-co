import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { api, API_BASE } from "@/lib/api";
import { LOGO_URL, CONTACT } from "@/byrd/data";
import { StatusChip, readFileAsBase64, fmtSize } from "@/byrd/docHelpers";
import { toast } from "sonner";
import AdaChatPanel from "@/byrd/AdaChatPanel";
import {
  LogOut, Upload, FileText, Download, Phone, Mail, CheckCircle2, Circle, CircleAlert,
  ChevronDown, ChevronRight, PenLine,
} from "lucide-react";

const groupByCategory = (docs) => {
  const map = {};
  docs.forEach((d) => {
    const k = d.category || "Other";
    map[k] = map[k] || [];
    map[k].push(d);
  });
  return map;
};

export default function ClientPortal() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [uploading, setUploading] = useState(null);
  // Track which scenario cards are collapsed (default: open)
  const [collapsed, setCollapsed] = useState({});

  const load = () => api.get("/client/me").then((r) => setData(r.data));

  useEffect(() => { load(); }, []);

  const handleUpload = async (docId, file) => {
    if (!file) return;
    if (file.size > 15 * 1024 * 1024) {
      toast.error("File exceeds 15 MB limit");
      return;
    }
    setUploading(docId);
    try {
      const data_b64 = await readFileAsBase64(file);
      await api.post(`/client/docs/${docId}/upload`, {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        data_b64,
      });
      toast.success("Uploaded");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(null);
    }
  };

  if (!data) {
    return <div className="min-h-screen bg-[#FBF8F1] grid place-items-center text-sm text-[#6B6558]">Loading portal…</div>;
  }

  const scenarios = data.scenarios || [];
  // Aggregate totals across scenarios for the header progress
  const allDocs = scenarios.flatMap((s) => s.docs || []);
  const totalAll = allDocs.length;
  const reviewedAll = allDocs.filter((d) => d.status === "reviewed").length;
  const rejectedAll = allDocs.filter((d) => d.status === "rejected").length;
  const uploadedAll = allDocs.filter((d) => ["uploaded", "reviewed"].includes(d.status)).length;
  const pctAll = totalAll ? Math.round((reviewedAll / totalAll) * 100) : 0;

  const toggle = (sid) => setCollapsed((c) => ({ ...c, [sid]: !c[sid] }));

  return (
    <div className="min-h-screen bg-[#FBF8F1]">
      {/* Header */}
      <header className="border-b border-[#E4DFD1] bg-white/80 backdrop-blur sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-10 w-auto" />
            <div className="leading-tight hidden sm:block">
              <div className="font-serif text-lg font-bold">Byrd &amp; CO</div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Client Portal</div>
            </div>
          </Link>
          <div className="flex items-center gap-3">
            <div className="hidden sm:block text-right">
              <div className="text-sm font-semibold">{user?.name}</div>
              <div className="text-xs text-[#6B6558]">{user?.email}</div>
            </div>
            <button
              onClick={() => { logout(); nav("/"); }}
              data-testid="client-logout"
              className="byrd-btn byrd-btn-outline h-10 px-3"
              title="Log out"
            >
              <LogOut size={14} /> Log out
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-5 sm:px-8 py-10 md:py-14">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-8">
          <div>
            <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Your Document Portal</div>
            <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2 leading-tight">
              Hi, {user?.name?.split(" ")[0]}.
            </h1>
            <p className="text-[#6B6558] mt-3 max-w-xl">
              Each of your loans has its own checklist below. Upload each item on the deal it belongs to —
              we&apos;ll mark items reviewed as they clear our desk.
            </p>

            {/* Ada — borrower AI document concierge */}
            <div className="mt-8">
              <AdaChatPanel user={user} scenarios={scenarios} onUploaded={load} />
            </div>

            {/* Overall progress card (visible when 2+ scenarios) */}
            {scenarios.length > 1 && totalAll > 0 && (
              <div className="byrd-card p-6 md:p-7 mt-8" data-testid="client-progress-total">
                <div className="flex items-center justify-between flex-wrap gap-3">
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Across all deals</div>
                    <div className="font-serif text-2xl font-bold mt-1">
                      {reviewedAll}/{totalAll} reviewed
                    </div>
                  </div>
                  <div className="flex gap-2 text-xs">
                    <span className="byrd-chip">{allDocs.filter(d => d.status === "pending").length} pending</span>
                    <span className="byrd-chip byrd-chip-blue">{uploadedAll} uploaded</span>
                    {rejectedAll > 0 && <span className="byrd-chip byrd-chip-red">{rejectedAll} rejected</span>}
                  </div>
                </div>
                <div className="mt-4 h-2 bg-[#F3EEE0] rounded-full overflow-hidden">
                  <div className="h-full bg-[#C89434] transition-[width] duration-500" style={{ width: `${pctAll}%` }} />
                </div>
              </div>
            )}

            {/* Empty state */}
            {scenarios.length === 0 && (
              <div className="byrd-card p-10 text-center mt-8" data-testid="client-no-scenarios">
                <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]">
                  <FileText size={22} />
                </div>
                <h3 className="font-serif text-2xl font-bold mt-4">You&apos;re all set up.</h3>
                <p className="text-[#6B6558] mt-2 max-w-md mx-auto">
                  When Wayne or Caleb starts a loan scenario for you, it&apos;ll show up here with its own
                  document checklist to complete.
                </p>
              </div>
            )}

            {/* Per-scenario checklists */}
            <div className="mt-8 space-y-8">
              {scenarios.map((s) => {
                const docs = s.docs || [];
                const total = docs.length;
                const reviewed = docs.filter((d) => d.status === "reviewed").length;
                const uploaded = docs.filter((d) => ["uploaded", "reviewed"].includes(d.status)).length;
                const rejected = docs.filter((d) => d.status === "rejected").length;
                const pct = total ? Math.round((reviewed / total) * 100) : 0;
                const isCollapsed = !!collapsed[s.id];
                const grouped = groupByCategory(docs);

                return (
                  <section key={s.id} className="byrd-card p-5 md:p-6" data-testid={`client-scenario-${s.id}`}>
                    <button
                      onClick={() => toggle(s.id)}
                      className="w-full flex items-start justify-between gap-3 text-left"
                      data-testid={`client-scenario-toggle-${s.id}`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <div className="w-8 h-8 rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1] shrink-0">
                            <FileText size={14} />
                          </div>
                          <div>
                            <div className="font-serif text-xl md:text-2xl font-bold leading-tight">{s.name}</div>
                            <div className="text-[11px] text-[#6B6558] mt-0.5 flex flex-wrap gap-2 items-center">
                              {s.loan_type && <span className="byrd-chip byrd-chip-gold">{s.loan_type}</span>}
                              {s.property_type && <span>{s.property_type}</span>}
                              {s.location && <span>· {s.location}</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 shrink-0 pt-1">
                        <div className="text-right">
                          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Progress</div>
                          <div className="font-semibold text-sm">{reviewed}/{total} reviewed</div>
                        </div>
                        {isCollapsed ? <ChevronRight size={18} className="text-[#6B6558]" /> : <ChevronDown size={18} className="text-[#6B6558]" />}
                      </div>
                    </button>

                    <div className="mt-4 flex items-center gap-2 text-xs">
                      <div className="flex-1 h-1.5 bg-[#F3EEE0] rounded-full overflow-hidden">
                        <div className="h-full bg-[#C89434] transition-[width] duration-500" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="byrd-chip">{docs.filter((d) => d.status === "pending").length} pending</span>
                      <span className="byrd-chip byrd-chip-blue">{uploaded} uploaded</span>
                      {rejected > 0 && <span className="byrd-chip byrd-chip-red">{rejected} rejected</span>}
                    </div>

                    {!isCollapsed && (
                      <div className="mt-6 space-y-6">
                        {total === 0 ? (
                          <div className="text-sm text-[#6B6558] py-6 text-center">
                            Nothing on this deal&apos;s checklist yet — your broker will add items shortly.
                          </div>
                        ) : (
                          Object.entries(grouped).map(([cat, list]) => (
                            <div key={cat} data-testid={`client-cat-${s.id}-${cat}`}>
                              <div className="flex items-baseline justify-between mb-2">
                                <h4 className="font-serif text-lg font-bold">{cat}</h4>
                                <div className="font-mono text-[10px] text-[#6B6558]">{list.length} items</div>
                              </div>
                              <div className="space-y-2">
                                {list.map((d) => {
                                  const hasFile = !!d.file;
                                  const isFeeAgreement = d.label === "Signed Fee Agreement";
                                  const pendingSignToken = d.pending_sign_token;
                                  const iconMap = {
                                    pending: <Circle size={16} className="text-[#6B6558]" />,
                                    uploaded: <FileText size={16} className="text-[#23446E]" />,
                                    reviewed: <CheckCircle2 size={16} className="text-[#245C25]" />,
                                    rejected: <CircleAlert size={16} className="text-[#8A1F1A]" />,
                                  };
                                  return (
                                    <div
                                      key={d.id}
                                      data-testid={`client-doc-${d.id}`}
                                      className={`border ${isFeeAgreement ? "border-[#C89434] bg-[#FBEFD3]/40" : "border-[#E4DFD1] bg-white"} rounded-md p-3 md:p-4 flex flex-col md:flex-row md:items-center gap-3`}
                                    >
                                      <div className="w-9 h-9 shrink-0 rounded-md bg-[#F3EEE0] border border-[#E4DFD1] grid place-items-center">
                                        {iconMap[d.status]}
                                      </div>
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                          <div className="font-semibold">{d.label}</div>
                                          {d.required && <span className="text-[10px] font-mono uppercase text-[#C89434] tracking-widest">Required</span>}
                                          {isFeeAgreement && (
                                            <span className="text-[10px] font-mono uppercase text-[#7A5410] tracking-widest">Managed by Byrd &amp; CO</span>
                                          )}
                                        </div>
                                        {hasFile && (
                                          <div className="text-xs text-[#6B6558] mt-1 truncate">
                                            {d.file.filename} · {fmtSize(d.file.size)}
                                          </div>
                                        )}
                                        {d.notes && (
                                          <div className={`text-xs mt-1 ${isFeeAgreement ? "text-[#6B6558]" : "text-[#8A1F1A]"}`}>
                                            {isFeeAgreement ? "" : "Note from broker: "}{d.notes}
                                          </div>
                                        )}
                                      </div>
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <StatusChip status={d.status} />
                                        {hasFile && (
                                          <a
                                            href={`${API_BASE}/files/${d.file.id}?tok=${localStorage.getItem("ac_token")}`}
                                            target="_blank" rel="noopener noreferrer"
                                            onClick={async (e) => {
                                              e.preventDefault();
                                              const res = await api.get(`/files/${d.file.id}`, { responseType: "blob" });
                                              const url = URL.createObjectURL(res.data);
                                              window.open(url, "_blank");
                                            }}
                                            className="byrd-btn byrd-btn-ghost h-9 px-3 text-xs"
                                            data-testid={`view-${d.id}`}
                                          >
                                            <Download size={12} /> View
                                          </a>
                                        )}
                                        {isFeeAgreement && pendingSignToken && (
                                          <a
                                            href={`/fee-agreement/${pendingSignToken}`}
                                            target="_blank" rel="noopener noreferrer"
                                            className="byrd-btn byrd-btn-primary h-9 px-3 text-xs"
                                            data-testid={`sign-now-${d.id}`}
                                          >
                                            <PenLine size={12} /> Sign Now
                                          </a>
                                        )}
                                        {!isFeeAgreement && (
                                          <label
                                            className={`byrd-btn h-9 px-3 text-xs cursor-pointer ${
                                              hasFile ? "byrd-btn-outline" : "byrd-btn-primary"
                                            }`}
                                            data-testid={`upload-${d.id}`}
                                          >
                                            <Upload size={12} />
                                            {uploading === d.id ? "Uploading…" : hasFile ? "Replace" : "Upload"}
                                            <input
                                              type="file" className="hidden"
                                              onChange={(e) => {
                                                const f = e.target.files?.[0];
                                                if (f) handleUpload(d.id, f);
                                                e.target.value = "";
                                              }}
                                              disabled={uploading === d.id}
                                            />
                                          </label>
                                        )}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          </div>

          {/* Sidebar */}
          <aside className="space-y-6">
            <div className="byrd-card p-6" data-testid="client-help">
              <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Your Loan Officers</div>
              <div className="mt-4 space-y-4">
                {[CONTACT.wayne, CONTACT.caleb].map((p) => (
                  <div key={p.email}>
                    <div className="font-serif text-lg font-semibold">{p.name}</div>
                    <div className="mt-1 flex flex-col gap-1 text-sm">
                      <a href={`tel:${p.phone}`} className="text-[#6B6558] hover:text-[#C89434] inline-flex items-center gap-2">
                        <Phone size={12} /> {p.phone}
                      </a>
                      <a href={`mailto:${p.email}`} className="text-[#6B6558] hover:text-[#C89434] inline-flex items-center gap-2 break-all">
                        <Mail size={12} /> {p.email}
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="byrd-card p-6 bg-[#1A1A1A] text-[#FBF8F1]">
              <div className="font-mono text-[11px] uppercase tracking-widest text-[#E5B968]">// Quick Tips</div>
              <ul className="mt-3 text-sm space-y-2 list-disc list-inside text-[#C9C1AF]">
                <li>Each loan has its own list — upload each doc to the right deal.</li>
                <li>PDFs are ideal — up to 15 MB per file.</li>
                <li>Replacing an upload overwrites the previous version.</li>
                <li>Rejected? Check the broker note and re-upload.</li>
              </ul>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
