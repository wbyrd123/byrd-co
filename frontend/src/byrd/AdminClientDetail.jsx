import React, { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { scenarioStatusChip, fmtMoney } from "@/byrd/dealData";
import {
  ArrowLeft, Plus, Copy, Trash2, Phone, Mail, Building2, Send,
  FileText, ExternalLink, AlertTriangle,
} from "lucide-react";
import NewScenarioDialog from "@/byrd/NewScenarioDialog";

export default function AdminClientDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [newScenarioOpen, setNewScenarioOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = () => api.get(`/admin/clients/${id}`).then((r) => setData(r.data));
  useEffect(() => { load(); }, [id]);

  const copyInvite = () => {
    if (!data?.invite?.token) return;
    const url = `${window.location.origin}/portal/invite/${data.invite.token}`;
    navigator.clipboard.writeText(url);
    toast.success("Invite link copied");
  };

  const deleteClient = async () => {
    const name = data?.client?.name || "this client";
    if (!window.confirm(`Delete ${name}? This can't be undone.`)) return;
    setDeleting(true);
    try {
      await api.delete(`/admin/clients/${id}`);
      toast.success(`${name} removed`);
      nav("/admin/clients");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  if (!data) return <div className="text-sm text-[#6B6558]">Loading…</div>;

  const { client, invite, scenarios = [] } = data;
  const inviteActivated = invite && invite.used_at;
  const canDelete = scenarios.length === 0;

  const toggleQuoteStudio = async () => {
    const next = !client.quote_studio_access;
    try {
      await api.patch(`/admin/clients/${id}/quote-studio-access`, { enabled: next });
      toast.success(next ? "Loan Quote Studio access granted" : "Loan Quote Studio access revoked");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't update access");
    }
  };

  return (
    <div className="space-y-8" data-testid="admin-client-detail">
      <button onClick={() => nav("/admin/clients")} className="text-sm text-[#6B6558] hover:text-[#1A1A1A] inline-flex items-center gap-2">
        <ArrowLeft size={14} /> All clients
      </button>

      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Client</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2 leading-tight">{client.name}</h1>
          <div className="mt-3 flex flex-wrap gap-4 text-sm text-[#6B6558]">
            <a href={`mailto:${client.email}`} className="inline-flex items-center gap-1 hover:text-[#C89434]"><Mail size={12} /> {client.email}</a>
            {client.phone && <a href={`tel:${client.phone}`} className="inline-flex items-center gap-1 hover:text-[#C89434]"><Phone size={12} /> {client.phone}</a>}
            {client.company && <span className="inline-flex items-center gap-1"><Building2 size={12} /> {client.company}</span>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          {invite && !inviteActivated && (
            <div className="flex gap-2">
              <button onClick={copyInvite} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid="copy-invite">
                <Copy size={12} /> Copy Link
              </button>
              <button
                onClick={async () => {
                  try {
                    await api.post(`/admin/users/${client.id}/send-invite`);
                    toast.success(`Portal invite emailed to ${client.email}`);
                  } catch (e) {
                    toast.error(e?.response?.data?.detail || "Failed to send");
                  }
                }}
                className="byrd-btn byrd-btn-dark h-9 px-3 text-xs"
                data-testid="send-invite-email"
              >
                <Send size={12} /> Send Portal Invite
              </button>
            </div>
          )}
          <div className="text-xs text-[#6B6558]">
            {inviteActivated ? (
              <span className="byrd-chip byrd-chip-green">Portal activated</span>
            ) : (
              <span className="byrd-chip byrd-chip-gold">Invite pending</span>
            )}
          </div>
          <button
            onClick={deleteClient}
            disabled={!canDelete || deleting}
            title={canDelete ? "" : "Delete or reassign this client's scenarios first"}
            className="text-[11px] mt-2 inline-flex items-center gap-1 text-[#6B6558] hover:text-[#8A1F1A] disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="delete-client"
          >
            <Trash2 size={12} /> {deleting ? "Deleting…" : "Delete client"}
          </button>
        </div>
      </div>

      {/* Scenarios — this is the client's whole world now */}
      <ScenariosStrip
        clientId={id}
        scenarios={scenarios}
        onCreate={() => setNewScenarioOpen(true)}
      />

      {/* Loan Quote Studio access toggle — for listing-agent-type clients */}
      <div className="byrd-card p-6" data-testid="quote-studio-access-card">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 shrink-0 rounded-md bg-[#F3EEE0] border border-[#E4DFD1] grid place-items-center text-[#C89434]">
              <FileText size={16} />
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Loan Quote Studio</div>
              <div className="font-serif text-lg font-bold mt-0.5">Give this client the Studio.</div>
              <p className="text-sm text-[#6B6558] mt-1 max-w-2xl">
                For listing agents &amp; RE brokers who want to build Byrd-branded quotes for their
                listings. They&apos;ll see the Studio in their portal, only their own quotes, and every
                PDF still carries our watermark + &quot;Request a Live Quote&quot; button.
              </p>
            </div>
          </div>
          <button
            onClick={toggleQuoteStudio}
            data-testid="toggle-quote-studio-access"
            className={`inline-flex items-center gap-2 h-9 px-4 rounded-full text-xs font-mono uppercase tracking-widest transition-colors ${
              client.quote_studio_access
                ? "bg-[#C89434] text-[#1A1A1A] hover:brightness-95"
                : "bg-white border border-[#E4DFD1] text-[#2A2A2A] hover:bg-[#F3EEE0]"
            }`}
          >
            <span className={`inline-block w-2 h-2 rounded-full ${client.quote_studio_access ? "bg-[#1A1A1A]" : "bg-[#C7C0AC]"}`} />
            {client.quote_studio_access ? "Access on" : "Enable access"}
          </button>
        </div>
      </div>

      {/* Explainer replacing the removed doc checklist */}
      <div className="byrd-card p-6" data-testid="docs-moved-notice">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 shrink-0 rounded-md bg-[#F3EEE0] border border-[#E4DFD1] grid place-items-center text-[#C89434]">
            <FileText size={16} />
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Documents</div>
            <div className="font-serif text-lg font-bold mt-0.5">Each loan has its own document folder.</div>
            <p className="text-sm text-[#6B6558] mt-1 max-w-2xl">
              Open a scenario above to manage its checklist. Docs that overlap (like Personal Tax Returns)
              can be <b>copied</b> from one scenario to another from inside the Documents tab.
            </p>
          </div>
        </div>
      </div>

      {newScenarioOpen && (
        <NewScenarioDialog
          clientId={id}
          onClose={() => setNewScenarioOpen(false)}
          onCreated={(sid) => {
            setNewScenarioOpen(false);
            nav(`/admin/scenarios/${sid}`);
          }}
        />
      )}
    </div>
  );
}

function ScenariosStrip({ clientId, scenarios, onCreate }) {
  return (
    <div className="byrd-card p-6" data-testid="client-scenarios-strip">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Loan Scenarios</div>
          <h3 className="font-serif text-xl font-bold mt-1">
            Deals in flight {scenarios.length > 0 && <span className="text-[#6B6558] font-normal">({scenarios.length})</span>}
          </h3>
        </div>
        <button onClick={onCreate} className="byrd-btn byrd-btn-dark" data-testid="new-scenario-for-client">
          <Plus size={14} /> New Scenario
        </button>
      </div>

      {scenarios.length === 0 ? (
        <div className="mt-4 text-sm text-[#6B6558] flex items-start gap-2">
          <AlertTriangle size={14} className="text-[#7A5410] mt-0.5 shrink-0" />
          <span>
            No scenarios yet. Start one and pick a checklist template (Purchase, Refi, Construction, Bridge, SBA, or blank).
            Each loan gets its own document folder.
          </span>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {scenarios.map((s) => {
            const chip = scenarioStatusChip(s.status);
            const dc = s.doc_counts || { total: 0, uploaded: 0, reviewed: 0 };
            const pct = dc.total ? Math.round((dc.reviewed / dc.total) * 100) : 0;
            return (
              <Link
                key={s.id}
                to={`/admin/scenarios/${s.id}`}
                data-testid={`client-scenario-${s.id}`}
                className="border border-[#E4DFD1] rounded-md p-3 flex items-start justify-between gap-3 hover:bg-[#FBF8F1] transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-sm truncate inline-flex items-center gap-1.5">
                    <FileText size={12} className="text-[#C89434] shrink-0" />
                    {s.name || "Untitled"}
                  </div>
                  <div className="text-xs text-[#6B6558] mt-1 flex flex-wrap items-center gap-2">
                    <span className={chip.chip}>{chip.label}</span>
                    {s.loan_type && <span className="byrd-chip byrd-chip-gold">{s.loan_type}</span>}
                    {s.loan_amount ? <span className="font-mono">{fmtMoney(s.loan_amount)}</span> : null}
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-[11px] text-[#6B6558]">
                    <span className="font-mono">{dc.total} doc{dc.total === 1 ? "" : "s"}</span>
                    {dc.total > 0 && (
                      <div className="flex-1 h-1 bg-[#F3EEE0] rounded-full overflow-hidden max-w-[100px]">
                        <div className="h-full bg-[#C89434]" style={{ width: `${pct}%` }} />
                      </div>
                    )}
                    {dc.reviewed > 0 && <span className="font-mono">{dc.reviewed} reviewed</span>}
                  </div>
                </div>
                <ExternalLink size={14} className="text-[#6B6558] shrink-0 mt-1" />
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
