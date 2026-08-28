import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import {
  ShieldCheck, ShieldAlert, Smartphone, Copy, Download, RefreshCcw, X, ArrowRight, Lock,
} from "lucide-react";

/**
 * SecuritySettings — enroll / manage Two-Factor Authentication for the current user.
 * Works for any authenticated role (admin, client, lender).
 */
export default function SecuritySettings() {
  const { refreshUser } = useAuth();
  const [status, setStatus] = useState(null); // { enabled, enrolled_at, backup_codes_remaining }
  const [loading, setLoading] = useState(true);

  // Enrollment state
  const [setup, setSetup] = useState(null); // { secret, qr_data_url, otpauth_uri, ... }
  const [enrollCode, setEnrollCode] = useState("");
  const [busy, setBusy] = useState(false);

  // Backup codes state (shown once after enroll or regenerate)
  const [backupCodes, setBackupCodes] = useState(null);

  // Disable state
  const [disableOpen, setDisableOpen] = useState(false);
  const [disablePw, setDisablePw] = useState("");
  const [disableCode, setDisableCode] = useState("");

  // Regenerate state
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenCode, setRegenCode] = useState("");

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get("/auth/2fa/status");
      setStatus(res.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't load 2FA status");
    } finally {
      setLoading(false);
    }
  };

  const startSetup = async () => {
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/setup");
      setSetup(res.data);
      setEnrollCode("");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't start 2FA setup");
    } finally {
      setBusy(false);
    }
  };

  const cancelSetup = () => {
    setSetup(null);
    setEnrollCode("");
  };

  const confirmSetup = async () => {
    if (enrollCode.trim().length !== 6) {
      toast.error("Enter the 6-digit code from your authenticator app");
      return;
    }
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/verify-setup", { code: enrollCode.trim() });
      setBackupCodes(res.data.backup_codes);
      setSetup(null);
      setEnrollCode("");
      await refreshUser();
      await load();
      toast.success("2FA is now active on your account");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "That code didn't match. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const submitDisable = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/auth/2fa/disable", { password: disablePw, code: disableCode.trim() });
      setDisableOpen(false);
      setDisablePw("");
      setDisableCode("");
      await refreshUser();
      await load();
      toast.success("2FA has been disabled");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't disable 2FA");
    } finally {
      setBusy(false);
    }
  };

  const submitRegen = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/regenerate-backup-codes", { code: regenCode.trim() });
      setBackupCodes(res.data.backup_codes);
      setRegenOpen(false);
      setRegenCode("");
      await load();
      toast.success("New backup codes generated. Old ones no longer work.");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't regenerate backup codes");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="security-settings-page">
      <div>
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Security</div>
        <h1 className="font-serif text-3xl font-bold mt-1">Account Security</h1>
        <p className="text-sm text-[#6B6558] mt-2 max-w-2xl">
          Two-factor authentication (2FA) adds a second layer to your sign-in. After entering your
          password, you'll be asked for a 6-digit code from an authenticator app on your phone.
          If you lose your phone you can fall back to an email code or one of your backup codes.
        </p>
      </div>

      {loading ? (
        <div className="text-sm text-[#6B6558]">Loading…</div>
      ) : (
        <>
          {/* 2FA Status Card */}
          <div className="byrd-card p-6" data-testid="two-fa-status-card">
            <div className="flex items-start gap-4">
              <div className={`w-11 h-11 rounded-md grid place-items-center shrink-0 ${status?.enabled ? "bg-[#1A1A1A] text-[#C89434]" : "bg-[#F3EEE0] text-[#6B6558]"}`}>
                {status?.enabled ? <ShieldCheck size={20} /> : <ShieldAlert size={20} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-serif text-xl font-bold">
                  {status?.enabled ? "Two-factor authentication is ON" : "Two-factor authentication is OFF"}
                </div>
                <div className="text-sm text-[#6B6558] mt-1">
                  {status?.enabled ? (
                    <>
                      Enrolled {status.enrolled_at ? new Date(status.enrolled_at).toLocaleDateString() : "recently"}.
                      You have <b>{status.backup_codes_remaining}</b> backup code{status.backup_codes_remaining === 1 ? "" : "s"} left.
                    </>
                  ) : (
                    "Turn it on to require a code from your phone every time you sign in."
                  )}
                </div>
              </div>
              {!status?.enabled && !setup && (
                <button
                  onClick={startSetup}
                  disabled={busy}
                  data-testid="two-fa-enable-btn"
                  className="byrd-btn byrd-btn-dark"
                >
                  <ShieldCheck size={14} /> Enable 2FA
                </button>
              )}
            </div>

            {status?.enabled && (
              <div className="flex flex-wrap gap-2 mt-6 pt-6 border-t border-[#E4DFD1]">
                <button
                  onClick={() => setRegenOpen(true)}
                  data-testid="two-fa-regen-btn"
                  className="byrd-btn byrd-btn-outline"
                >
                  <RefreshCcw size={14} /> Regenerate Backup Codes
                </button>
                <button
                  onClick={() => setDisableOpen(true)}
                  data-testid="two-fa-disable-btn"
                  className="byrd-btn byrd-btn-outline text-[#B23B3B] border-[#B23B3B]/40 hover:bg-[#B23B3B] hover:text-white"
                >
                  <Lock size={14} /> Disable 2FA
                </button>
              </div>
            )}
          </div>

          {/* Enrollment Flow (QR code) */}
          {setup && (
            <div className="byrd-card p-6 space-y-6" data-testid="two-fa-setup-card">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Step 1</div>
                  <h2 className="font-serif text-xl font-bold mt-1">Scan the QR code</h2>
                  <p className="text-sm text-[#6B6558] mt-1 max-w-lg">
                    Open your authenticator app (1Password, Google Authenticator, Authy, or Microsoft
                    Authenticator) and scan the code below. Or tap "Enter secret manually" if you'd rather type it.
                  </p>
                </div>
                <button onClick={cancelSetup} className="text-[#6B6558] hover:text-[#1A1A1A]" data-testid="two-fa-cancel-setup">
                  <X size={18} />
                </button>
              </div>

              <div className="flex flex-col sm:flex-row items-start gap-6">
                <div className="bg-white border border-[#E4DFD1] rounded-md p-3">
                  <img src={setup.qr_data_url} alt="2FA QR code" className="w-48 h-48" data-testid="two-fa-qr-image" />
                </div>
                <div className="flex-1 min-w-0 space-y-3">
                  <div>
                    <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">Manual entry secret</div>
                    <div className="flex items-center gap-2 mt-1">
                      <code className="flex-1 bg-[#F3EEE0] px-3 py-2 rounded-md font-mono text-sm break-all" data-testid="two-fa-secret">
                        {setup.secret}
                      </code>
                      <button
                        onClick={() => { navigator.clipboard.writeText(setup.secret); toast.success("Secret copied"); }}
                        data-testid="two-fa-copy-secret"
                        className="p-2 border border-[#E4DFD1] rounded-md hover:bg-[#F3EEE0]"
                        title="Copy"
                      >
                        <Copy size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="text-xs text-[#6B6558]">
                    Account: <b>{setup.account}</b> · Issuer: <b>{setup.issuer}</b>
                  </div>
                </div>
              </div>

              <div className="pt-6 border-t border-[#E4DFD1]">
                <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Step 2</div>
                <h2 className="font-serif text-xl font-bold mt-1">Enter the 6-digit code</h2>
                <p className="text-sm text-[#6B6558] mt-1">
                  Your authenticator app will now show a rotating 6-digit code for "Byrd & CO". Type it below to confirm.
                </p>
                <div className="mt-4 flex items-center gap-3 max-w-sm">
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    value={enrollCode}
                    onChange={(e) => setEnrollCode(e.target.value.replace(/\D/g, ""))}
                    data-testid="two-fa-enroll-code"
                    className="flex-1 h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] font-mono tracking-widest text-center text-lg"
                    placeholder="123456"
                  />
                  <button
                    onClick={confirmSetup}
                    disabled={busy || enrollCode.length !== 6}
                    data-testid="two-fa-confirm-setup"
                    className="byrd-btn byrd-btn-dark"
                  >
                    {busy ? "Verifying…" : "Verify"} <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Backup Codes (shown once after enroll or regenerate) */}
          {backupCodes && (
            <BackupCodesModal codes={backupCodes} onClose={() => setBackupCodes(null)} />
          )}

          {/* Disable modal */}
          {disableOpen && (
            <Modal title="Disable Two-Factor Authentication" onClose={() => setDisableOpen(false)}>
              <p className="text-sm text-[#6B6558] mb-4">
                To disable 2FA we need your password plus one code from your authenticator app (or a backup code).
                After this, only your password will be needed to sign in.
              </p>
              <form onSubmit={submitDisable} className="space-y-3">
                <label className="block">
                  <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">Current password</div>
                  <input
                    type="password" required value={disablePw} onChange={(e) => setDisablePw(e.target.value)}
                    data-testid="two-fa-disable-password"
                    className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white"
                  />
                </label>
                <label className="block">
                  <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">6-digit code or backup code</div>
                  <input
                    type="text" required autoComplete="one-time-code" value={disableCode}
                    onChange={(e) => setDisableCode(e.target.value)}
                    data-testid="two-fa-disable-code"
                    className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white font-mono"
                  />
                </label>
                <div className="flex justify-end gap-2 pt-2">
                  <button type="button" onClick={() => setDisableOpen(false)} className="byrd-btn byrd-btn-outline">Cancel</button>
                  <button type="submit" disabled={busy} data-testid="two-fa-disable-confirm" className="byrd-btn byrd-btn-dark">
                    {busy ? "Disabling…" : "Disable 2FA"}
                  </button>
                </div>
              </form>
            </Modal>
          )}

          {/* Regenerate modal */}
          {regenOpen && (
            <Modal title="Regenerate Backup Codes" onClose={() => setRegenOpen(false)}>
              <p className="text-sm text-[#6B6558] mb-4">
                This creates 10 fresh backup codes. Your <b>old backup codes will stop working immediately.</b>
                Confirm with a 6-digit code from your authenticator.
              </p>
              <form onSubmit={submitRegen} className="space-y-3">
                <label className="block">
                  <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">6-digit code</div>
                  <input
                    type="text" required inputMode="numeric" maxLength={6} value={regenCode}
                    onChange={(e) => setRegenCode(e.target.value.replace(/\D/g, ""))}
                    data-testid="two-fa-regen-code"
                    className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white font-mono tracking-widest text-center"
                    placeholder="123456"
                  />
                </label>
                <div className="flex justify-end gap-2 pt-2">
                  <button type="button" onClick={() => setRegenOpen(false)} className="byrd-btn byrd-btn-outline">Cancel</button>
                  <button type="submit" disabled={busy || regenCode.length !== 6} data-testid="two-fa-regen-confirm" className="byrd-btn byrd-btn-dark">
                    {busy ? "Working…" : "Regenerate"}
                  </button>
                </div>
              </form>
            </Modal>
          )}

          {/* Recommended apps hint */}
          <div className="byrd-card p-6 bg-[#F3EEE0]/40">
            <div className="flex items-start gap-3">
              <Smartphone size={20} className="text-[#C89434] shrink-0 mt-0.5" />
              <div>
                <div className="font-serif font-bold">Which authenticator app should I use?</div>
                <div className="text-sm text-[#6B6558] mt-1">
                  Any of these work: <b>1Password</b>, <b>Google Authenticator</b>, <b>Authy</b>, or <b>Microsoft Authenticator</b>.
                  If you already use 1Password to store passwords, add it there — new codes appear right next to your login.
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function BackupCodesModal({ codes, onClose }) {
  const download = () => {
    const text =
      "BYRD & CO — Two-Factor Backup Codes\n" +
      "-------------------------------------\n" +
      "Each code works ONCE. Store them somewhere safe (1Password vault, printed copy).\n\n" +
      codes.join("\n") + "\n";
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "byrd-co-backup-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  const copy = () => {
    navigator.clipboard.writeText(codes.join("\n"));
    toast.success("Backup codes copied");
  };

  return (
    <Modal title="Save your backup codes" onClose={onClose}>
      <p className="text-sm text-[#6B6558] mb-4">
        These 10 codes are the only way in if you lose access to your phone AND email.
        Each works exactly once. <b>Save them now</b> — this is the only time we'll show them.
      </p>
      <div className="grid grid-cols-2 gap-2 bg-[#1A1A1A] text-[#C89434] font-mono p-4 rounded-md mb-4" data-testid="two-fa-backup-codes-list">
        {codes.map((c, i) => (
          <div key={i} className="text-sm tracking-widest text-center" data-testid={`two-fa-backup-code-${i}`}>{c}</div>
        ))}
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        <button onClick={copy} className="byrd-btn byrd-btn-outline" data-testid="two-fa-copy-backup-codes">
          <Copy size={14} /> Copy
        </button>
        <button onClick={download} className="byrd-btn byrd-btn-outline" data-testid="two-fa-download-backup-codes">
          <Download size={14} /> Download .txt
        </button>
        <button onClick={onClose} className="byrd-btn byrd-btn-dark" data-testid="two-fa-backup-codes-done">
          I've saved them
        </button>
      </div>
    </Modal>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-[#FBF8F1] max-w-md w-full rounded-md shadow-xl p-6"
        onClick={(e) => e.stopPropagation()}
        data-testid="two-fa-modal"
      >
        <div className="flex items-center justify-between mb-4">
          <div className="font-serif text-lg font-bold">{title}</div>
          <button onClick={onClose} className="text-[#6B6558] hover:text-[#1A1A1A]" data-testid="two-fa-modal-close">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
