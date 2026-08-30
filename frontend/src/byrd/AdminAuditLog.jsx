import React, { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  Shield, Filter, X, RefreshCcw, Download, ChevronLeft, ChevronRight, ExternalLink,
  User, Globe, Clock, FileText, Search, ArrowRight,
} from "lucide-react";

/**
 * Admin Audit Log — chain-of-custody view of every security-relevant event
 * (login, document upload/view/download/delete, term-sheet lifecycle,
 * scenario CRUD, admin invites, 2FA changes).
 */
export default function AdminAuditLog() {
  const [types, setTypes] = useState([]);
  const [filters, setFilters] = useState({
    event_type: "",
    q: "",
    user_email: "",
    ip: "",
    date_from: "",
    date_to: "",
  });
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const [data, setData] = useState(null); // { total, events }
  const [loading, setLoading] = useState(true);
  const [detailEvent, setDetailEvent] = useState(null);

  useEffect(() => {
    api.get("/admin/audit-log/event-types").then((r) => setTypes(r.data.types || []));
  }, []);

  const load = async (nextPage = page) => {
    setLoading(true);
    try {
      const params = { ...filters, page: nextPage, page_size: pageSize };
      Object.keys(params).forEach((k) => {
        if (params[k] === "" || params[k] === null || params[k] === undefined) delete params[k];
      });
      const res = await api.get("/admin/audit-log", { params });
      setData(res.data);
      setPage(res.data.page);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't load audit log");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(1); /* eslint-disable-next-line */ }, []);

  const applyFilters = () => load(1);
  const clearFilters = () => {
    setFilters({ event_type: "", q: "", user_email: "", ip: "", date_from: "", date_to: "" });
    setTimeout(() => load(1), 50);
  };

  const exportCsv = async () => {
    try {
      const params = { ...filters };
      Object.keys(params).forEach((k) => {
        if (params[k] === "" || params[k] === null) delete params[k];
      });
      const res = await api.get("/admin/audit-log/export.csv", { params, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `byrd-audit-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Export downloaded");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Export failed");
    }
  };

  const labelByType = useMemo(() => {
    const m = {};
    types.forEach((t) => (m[t.key] = t.label));
    return m;
  }, [types]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <div className="space-y-6" data-testid="audit-log-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Compliance</div>
          <h1 className="font-serif text-3xl font-bold mt-1">Audit Log</h1>
          <p className="text-sm text-[#6B6558] mt-2 max-w-2xl">
            Every login, document access, upload, deletion, and admin action is captured with the actor,
            timestamp, and IP address. Use this to prove chain of custody on any file.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => load(page)} disabled={loading} data-testid="audit-refresh-btn" className="byrd-btn byrd-btn-outline">
            <RefreshCcw size={14} /> Refresh
          </button>
          <button onClick={exportCsv} data-testid="audit-export-csv-btn" className="byrd-btn byrd-btn-dark">
            <Download size={14} /> Export CSV
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="byrd-card p-5" data-testid="audit-filters">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <label className="block">
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">Event type</div>
            <select
              value={filters.event_type}
              onChange={(e) => setFilters((f) => ({ ...f, event_type: e.target.value }))}
              data-testid="audit-filter-event-type"
              className="mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
            >
              <option value="">All events</option>
              {types.map((t) => (
                <option key={t.key} value={t.key}>{t.label}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">User email</div>
            <input
              type="email"
              value={filters.user_email}
              onChange={(e) => setFilters((f) => ({ ...f, user_email: e.target.value.toLowerCase() }))}
              data-testid="audit-filter-user-email"
              placeholder="wayne@byrd-co.com"
              className="mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
            />
          </label>
          <label className="block">
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">IP address</div>
            <input
              type="text"
              value={filters.ip}
              onChange={(e) => setFilters((f) => ({ ...f, ip: e.target.value }))}
              data-testid="audit-filter-ip"
              placeholder="e.g. 73.44.12.9"
              className="mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
            />
          </label>
          <label className="block">
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">Search</div>
            <input
              type="text"
              value={filters.q}
              onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
              data-testid="audit-filter-q"
              placeholder="filename, name, ID…"
              className="mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
            />
          </label>
          <label className="block">
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">From (UTC)</div>
            <input
              type="date"
              value={filters.date_from}
              onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))}
              data-testid="audit-filter-from"
              className="mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
            />
          </label>
          <label className="block">
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">To (UTC)</div>
            <input
              type="date"
              value={filters.date_to}
              onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
              data-testid="audit-filter-to"
              className="mt-1 w-full h-10 px-2 rounded-md border border-[#E4DFD1] bg-white text-sm"
            />
          </label>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={applyFilters} data-testid="audit-apply-filters" className="byrd-btn byrd-btn-dark">
            <Filter size={14} /> Apply
          </button>
          <button onClick={clearFilters} data-testid="audit-clear-filters" className="byrd-btn byrd-btn-outline">
            <X size={14} /> Clear
          </button>
        </div>
      </div>

      {/* Results */}
      <div className="byrd-card overflow-hidden" data-testid="audit-results">
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#E4DFD1]">
          <div className="text-xs text-[#6B6558]">
            {loading ? "Loading…" : `${(data?.total || 0).toLocaleString()} event${data?.total === 1 ? "" : "s"} matching filters`}
          </div>
          {data && data.total > pageSize && (
            <div className="flex items-center gap-2 text-xs">
              <button
                onClick={() => load(Math.max(1, page - 1))}
                disabled={page <= 1 || loading}
                data-testid="audit-prev-page"
                className="p-1 border border-[#E4DFD1] rounded disabled:opacity-30"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="text-[#6B6558]">Page {page} of {totalPages}</span>
              <button
                onClick={() => load(Math.min(totalPages, page + 1))}
                disabled={page >= totalPages || loading}
                data-testid="audit-next-page"
                className="p-1 border border-[#E4DFD1] rounded disabled:opacity-30"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>

        {data && data.events.length === 0 && !loading ? (
          <div className="p-10 text-center text-sm text-[#6B6558]">
            <Shield size={22} className="mx-auto text-[#C89434] mb-2" />
            No events match these filters. Try widening the date range.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="audit-table">
              <thead>
                <tr className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558] text-left bg-[#F3EEE0]/60">
                  <th className="py-2 px-3">When (UTC)</th>
                  <th className="py-2 px-3">Event</th>
                  <th className="py-2 px-3">Who</th>
                  <th className="py-2 px-3">Resource</th>
                  <th className="py-2 px-3">IP</th>
                  <th className="py-2 px-3"></th>
                </tr>
              </thead>
              <tbody>
                {(data?.events || []).map((e) => (
                  <tr key={e.id} className="border-t border-[#E4DFD1] hover:bg-[#F3EEE0]/30">
                    <td className="py-2 px-3 whitespace-nowrap text-[#2A2A2A]">
                      {e.timestamp ? e.timestamp.replace("T", " ").slice(0, 19) : "—"}
                    </td>
                    <td className="py-2 px-3">
                      <EventBadge type={e.event_type} label={labelByType[e.event_type] || e.event_type} result={e.result} />
                    </td>
                    <td className="py-2 px-3">
                      <div className="text-[#2A2A2A]">{e.user_email || "—"}</div>
                      <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">{e.user_role || ""}</div>
                    </td>
                    <td className="py-2 px-3">
                      <div className="text-[#2A2A2A] truncate max-w-[280px]" title={e.resource_name || e.resource_id || ""}>
                        {e.resource_name || e.resource_id || "—"}
                      </div>
                      <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
                        {e.resource_type || ""}
                      </div>
                    </td>
                    <td className="py-2 px-3 font-mono text-xs text-[#6B6558]">{e.ip || "—"}</td>
                    <td className="py-2 px-3 text-right">
                      <button
                        onClick={() => setDetailEvent(e)}
                        data-testid={`audit-row-details-${e.id}`}
                        className="text-xs text-[#C89434] hover:text-[#1A1A1A] inline-flex items-center gap-1"
                      >
                        Details <ExternalLink size={11} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {detailEvent && (
        <EventDetailModal event={detailEvent} label={labelByType[detailEvent.event_type]} onClose={() => setDetailEvent(null)} />
      )}
    </div>
  );
}

function EventBadge({ type, label, result }) {
  // Choose a color band per family
  const family = (type || "").split(".")[0];
  const palette = {
    auth:        result === "failure" ? "bg-[#FBE9E9] text-[#8B2A2A]" : "bg-[#E8F1E8] text-[#2A5D2A]",
    document:    type === "document.delete" ? "bg-[#FBE9E9] text-[#8B2A2A]" : "bg-[#F1EBDD] text-[#8A6A1F]",
    term_sheet:  "bg-[#EDE7F3] text-[#4B357A]",
    scenario:    "bg-[#DDEBEE] text-[#1F5560]",
    admin:       "bg-[#F1EBDD] text-[#8A6A1F]",
  }[family] || "bg-[#F3EEE0] text-[#2A2A2A]";
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-mono uppercase tracking-widest ${palette}`}>
      {label || type}
    </span>
  );
}

function EventDetailModal({ event, label, onClose }) {
  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-[#FBF8F1] max-w-2xl w-full rounded-md shadow-xl p-6 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        data-testid="audit-detail-modal"
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">Event #{event.id?.slice(0, 8)}</div>
            <h3 className="font-serif text-xl font-bold mt-1">{label || event.event_type}</h3>
          </div>
          <button onClick={onClose} className="text-[#6B6558] hover:text-[#1A1A1A]" data-testid="audit-detail-close">
            <X size={18} />
          </button>
        </div>

        <dl className="space-y-3 text-sm">
          <Row icon={<Clock size={14} />} label="Timestamp (UTC)" value={event.timestamp?.replace("T", " ").slice(0, 19) || "—"} />
          <Row icon={<Shield size={14} />} label="Result" value={event.result || "success"} mono />
          <Row icon={<User size={14} />} label="Who" value={
            <>
              {event.user_email || "—"} <span className="text-[#6B6558]">({event.user_role || "n/a"})</span>
              {event.user_name && <div className="text-xs text-[#6B6558]">{event.user_name}</div>}
              {event.user_id && <div className="text-[10px] font-mono text-[#6B6558]">id: {event.user_id}</div>}
            </>
          } />
          <Row icon={<Globe size={14} />} label="IP" value={event.ip || "—"} mono />
          {event.user_agent && <Row icon={<Search size={14} />} label="Browser" value={event.user_agent} mono />}
          {event.resource_type && (
            <Row icon={<FileText size={14} />} label="Resource" value={
              <>
                <div className="text-[#2A2A2A]">{event.resource_name || "—"}</div>
                <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
                  {event.resource_type} · id: <span className="normal-case">{event.resource_id || "—"}</span>
                </div>
              </>
            } />
          )}
          {event.metadata && Object.keys(event.metadata).length > 0 && (
            <div>
              <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558] mb-1">Metadata</div>
              <pre className="bg-[#1A1A1A] text-[#C89434] text-xs p-3 rounded-md overflow-x-auto whitespace-pre-wrap break-words" data-testid="audit-detail-metadata">
{JSON.stringify(event.metadata, null, 2)}
              </pre>
            </div>
          )}
        </dl>
      </div>
    </div>,
    document.body
  );
}

function Row({ icon, label, value, mono }) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-6 h-6 rounded bg-[#F3EEE0] text-[#6B6558] grid place-items-center shrink-0 mt-0.5">{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">{label}</div>
        <div className={mono ? "font-mono text-sm break-all" : "text-sm"}>{value}</div>
      </div>
    </div>
  );
}
