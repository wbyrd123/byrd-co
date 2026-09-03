import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CheckCircle2, AlertTriangle, RefreshCw, Link2, ExternalLink } from "lucide-react";

/**
 * Live Google Ads API connection panel for the AdsCopilot Overview page.
 *
 * Renders one of three states:
 *  - "not configured" (missing env vars)  → muted card with instructions
 *  - "connected"                          → green chip, MCC ID, list of accounts
 *  - "error"                              → red chip + error message
 *
 * All routes are admin-only. Data returned here comes straight from the live
 * Google Ads API, so a green chip means the OAuth refresh token, developer
 * token, MCC, and API scope are all working end-to-end.
 */
export default function GoogleAdsStatusPanel() {
  const [status, setStatus] = useState(null);
  const [accounts, setAccounts] = useState(null);
  const [loading, setLoading] = useState(false);
  const [accountsLoading, setAccountsLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.get("/admin/google-ads/status");
      setStatus(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "Request failed");
    } finally {
      setLoading(false);
    }
  };

  const loadAccounts = async () => {
    setAccountsLoading(true);
    try {
      const r = await api.get("/admin/google-ads/accounts");
      setAccounts(r.data.accounts || []);
    } catch (e) {
      setAccounts([]);
    } finally {
      setAccountsLoading(false);
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (status?.configured && status?.ok) loadAccounts();
  }, [status?.configured, status?.ok]);

  const configured = !!status?.configured;
  const ok = !!status?.ok;
  const bannerColor = ok ? "bg-[#E7F5E5] border-[#245C25]" :
                      configured ? "bg-[#FADCDA] border-[#8A1F1A]" :
                      "bg-[#F3EEE0] border-[#6B6558]";

  return (
    <div className={`border-2 border-black bg-white p-5`} data-testid="google-ads-status">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#555]">// integration / google ads api</div>
          <h3 className="font-display text-xl font-bold tracking-tight mt-0.5">Google Ads Connection</h3>
        </div>
        <button
          onClick={() => { load(); if (status?.ok) loadAccounts(); }}
          disabled={loading}
          className="h-8 px-3 border-2 border-black font-mono text-[11px] uppercase inline-flex items-center gap-1 hover:bg-[#F3EEE0] disabled:opacity-40"
          data-testid="gads-refresh"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className={`border-2 ${bannerColor} p-3 flex items-start gap-3`}>
        {ok ? (
          <CheckCircle2 size={18} className="text-[#245C25] flex-shrink-0 mt-0.5" />
        ) : (
          <AlertTriangle size={18} className={configured ? "text-[#8A1F1A]" : "text-[#6B6558]"} />
        )}
        <div className="flex-1 text-sm">
          {loading && !status && <span className="font-mono text-xs text-[#555]">Checking…</span>}
          {!loading && !configured && (
            <>
              <div className="font-semibold">API credentials not configured</div>
              <div className="text-xs mt-1 text-[#555]">
                Set GOOGLE_ADS_DEVELOPER_TOKEN, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, and MCC_CUSTOMER_ID in the backend .env, then refresh.
              </div>
            </>
          )}
          {!loading && configured && ok && (
            <>
              <div className="font-semibold text-[#1A4A1B]">
                Connected — MCC <span className="font-mono">{status.mcc}</span>
              </div>
              <div className="text-xs mt-1 text-[#555]">
                {(status.accessible_customers || []).length} account
                {(status.accessible_customers || []).length === 1 ? "" : "s"} accessible via this OAuth login.
              </div>
            </>
          )}
          {!loading && configured && !ok && (
            <>
              <div className="font-semibold text-[#8A1F1A]">Connection failed</div>
              <div className="text-xs mt-1 font-mono break-all">
                {(status.error?.errors || []).map((e, i) => (
                  <div key={i}>{e.code}: {e.message}</div>
                ))}
                {!status.error?.errors && status.error?.message}
                {!status.error && error}
              </div>
            </>
          )}
        </div>
      </div>

      {ok && (
        <div className="mt-4">
          <div className="font-mono text-[10px] uppercase text-[#555] mb-2 flex items-center gap-1">
            <Link2 size={10} /> accounts under this mcc
            {accountsLoading && <span className="text-[#888]">· loading…</span>}
          </div>
          {accounts && accounts.length > 0 ? (
            <div className="border-2 border-black divide-y-2 divide-black" data-testid="gads-accounts">
              {accounts.map((a) => (
                <div key={a.id} className="flex items-center justify-between px-3 py-2 text-sm">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs text-[#555]">{a.id}</span>
                    <span className="font-semibold">{a.name}</span>
                    {a.is_manager && (
                      <span className="text-[10px] font-mono uppercase bg-black text-white px-1.5 py-0.5">Manager</span>
                    )}
                    {a.is_test_account && (
                      <span className="text-[10px] font-mono uppercase bg-[#F3EEE0] border border-[#C89434] text-[#8A6821] px-1.5 py-0.5">Test</span>
                    )}
                  </div>
                  <div className="font-mono text-xs text-[#555]">
                    {a.currency} · L{a.level}
                  </div>
                </div>
              ))}
            </div>
          ) : accounts && accounts.length === 0 ? (
            <div className="text-xs text-[#555] font-mono">
              No sub-accounts under this MCC yet. Reports will appear here once campaigns run.
            </div>
          ) : null}

          {status?.mcc && (
            <div className="mt-3 flex items-center gap-3 text-[11px] font-mono text-[#555]">
              <a
                href={`https://ads.google.com/aw/overview?ocid=${status.mcc}`}
                target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 hover:text-black"
              >
                Open in Google Ads <ExternalLink size={10} />
              </a>
              <span>·</span>
              <span>
                {(status.accessible_customers || []).length} accessible OAuth accounts
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
