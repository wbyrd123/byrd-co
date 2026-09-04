import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import {
  ShieldCheck, ShieldAlert, Smartphone, Copy, Download, RefreshCcw, X, ArrowRight, Lock,
  DatabaseBackup, HardDrive, CheckCircle2, AlertCircle, Loader2, Mail, KeyRound, Send,
} from "lucide-react";

/**
 * SecuritySettings — enroll / manage Two-Factor Authentication for the current user.
 * Works for any authenticated role (admin, client, lender). The Database Backups
 * panel is admin-only (backend enforces this).
 */
export default function SecuritySettings() {
  const { user, refreshUser } = useAuth();
  const isAdmin = user?.role === "admin";

  const [status, setStatus] = useState(null); // { enabled, enrolled_at, backup_codes_remaining, method }
  const [loading, setLoading] = useState(true);

  // Enrollment state
  const [chooseMethod, setChooseMethod] = useState(false); // showing the "pick TOTP or Email" chooser
  const [setup, setSetup] = useState(null); // TOTP setup payload
  const [emailSetup, setEmailSetup] = useState(null); // { sent_to_masked, expires_in_minutes }
  const [enrollCode, setEnrollCode] = useState("");
  const [busy, setBusy] = useState(false);

  // Backup codes (shown once after enroll / regenerate)
  const [backupCodes, setBackupCodes] = useState(null);

  // Disable state
  const [disableOpen, setDisableOpen] = useState(false);
  const [disablePw, setDisablePw] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [disableEmailSent, setDisableEmailSent] = useState(null);

  // Regenerate state
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenCode, setRegenCode] = useState("");
  const [regenEmailSent, setRegenEmailSent] = useState(null);

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

  // ---- Enrollment flows ----

  const startTotpSetup = async () => {
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/setup");
      setSetup(res.data);
      setEmailSetup(null);
      setEnrollCode("");
      setChooseMethod(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't start 2FA setup");
    } finally {
      setBusy(false);
    }
  };

  const startEmailSetup = async () => {
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/email/setup");
      setEmailSetup(res.data);
      setSetup(null);
      setEnrollCode("");
      setChooseMethod(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't send email code");
    } finally {
      setBusy(false);
    }
  };

  const resendEmailSetup = async () => {
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/email/setup");
      setEmailSetup(res.data);
      toast.success(`New code sent to ${res.data.sent_to_masked}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't resend code");
    } finally {
      setBusy(false);
    }
  };

  const cancelSetup = () => {
    setSetup(null);
    setEmailSetup(null);
    setEnrollCode("");
    setChooseMethod(false);
  };

  const confirmTotpSetup = async () => {
    if (enrollCode.trim().length !== 6) return toast.error("Enter the 6-digit code from your authenticator app");
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/verify-setup", { code: enrollCode.trim() });
      setBackupCodes(res.data.backup_codes);
      cancelSetup();
      await refreshUser();
      await load();
      toast.success("2FA is now active (authenticator app)");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "That code didn't match. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const confirmEmailSetup = async () => {
    if (enrollCode.trim().length !== 6) return toast.error("Enter the 6-digit code from your email");
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/email/verify-setup", { code: enrollCode.trim() });
      setBackupCodes(res.data.backup_codes);
      cancelSetup();
      await refreshUser();
      await load();
      toast.success("2FA is now active (email codes)");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "That code didn't match. Try again.");
    } finally {
      setBusy(false);
    }
  };

  // ---- Sensitive-action helpers (for email-only users) ----

  const sendVerificationForDisable = async () => {
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/email/send-verification");
      setDisableEmailSent(res.data);
      toast.success(`Verification code sent to ${res.data.sent_to_masked}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't send code");
    } finally {
      setBusy(false);
    }
  };

  const sendVerificationForRegen = async () => {
    setBusy(true);
    try {
      const res = await api.post("/auth/2fa/email/send-verification");
      setRegenEmailSent(res.data);
      toast.success(`Verification code sent to ${res.data.sent_to_masked}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't send code");
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
      setDisableEmailSent(null);
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
      setRegenEmailSent(null);
      await load();
      toast.success("New backup codes generated");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't regenerate backup codes");
    } finally {
      setBusy(false);
    }
  };

  const method = status?.method; // "totp" | "email" | null

  return (
    <div className="space-y-6" data-testid="security-settings-page">
      <div>
        <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Security</div>
        <h1 className="font-serif text-3xl font-bold mt-1">Account Security</h1>
        <p className="text-sm text-[#6B6558] mt-2 max-w-2xl">
          Two-factor authentication (2FA) adds a second layer to your sign-in. After entering your password,
          you'll be asked for a 6-digit code — either from an authenticator app on your phone, or sent to your email.
          You can also use one of 10 backup codes if you lose access.
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
                      Method: <b>{method === "email" ? "Email codes" : "Authenticator app"}</b> ·{" "}
                      Enrolled {status.enrolled_at ? new Date(status.enrolled_at).toLocaleDateString() : "recently"} ·{" "}
                      <b>{status.backup_codes_remaining}</b> backup code{status.backup_codes_remaining === 1 ? "" : "s"} left
                    </>
                  ) : (
                    "Turn it on to require a second code every time you sign in."
                  )}
                </div>
              </div>
              {!status?.enabled && !setup && !emailSetup && !chooseMethod && (
                <button
                  onClick={() => setChooseMethod(true)}
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
                  onClick={() => { setRegenOpen(true); setRegenEmailSent(null); setRegenCode(""); }}
                  data-testid="two-fa-regen-btn"
                  className="byrd-btn byrd-btn-outline"
                >
                  <RefreshCcw size={14} /> Regenerate Backup Codes
                </button>
                <button
                  onClick={() => { setDisableOpen(true); setDisableEmailSent(null); setDisableCode(""); setDisablePw(""); }}
                  data-testid="two-fa-disable-btn"
                  className="byrd-btn byrd-btn-outline text-[#B23B3B] border-[#B23B3B]/40 hover:bg-[#B23B3B] hover:text-white"
                >
                  <Lock size={14} /> Disable 2FA
                </button>
              </div>
            )}
          </div>

          {/* Method chooser */}
          {chooseMethod && (
            <div className="byrd-card p-6" data-testid="two-fa-method-chooser">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Pick a method</div>
                  <h2 className="font-serif text-xl font-bold mt-1">How would you like to receive codes?</h2>
                </div>
                <button onClick={cancelSetup} className="text-[#6B6558] hover:text-[#1A1A1A]" data-testid="two-fa-cancel-chooser">
                  <X size={18} />
                </button>
              </div>
              <div className="grid sm:grid-cols-2 gap-3">
                <button
                  onClick={startTotpSetup}
                  disabled={busy}
                  data-testid="two-fa-choose-totp"
                  className="text-left p-4 border border-[#E4DFD1] rounded-md hover:border-[#C89434] hover:bg-[#F3EEE0]/40 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Smartphone size={18} className="text-[#C89434]" />
                    <div className="font-serif font-bold">Authenticator App</div>
                    <span className="ml-auto text-[10px] font-mono uppercase tracking-widest bg-[#C89434] text-[#1A1A1A] px-1.5 py-0.5 rounded">Recommended</span>
                  </div>
                  <p className="text-xs text-[#6B6558] leading-relaxed">
                    Codes come from an app like 1Password, Authy, Google Authenticator, or Microsoft Authenticator.
                    Strongest security — works offline, no reliance on email.
                  </p>
                </button>
                <button
                  onClick={startEmailSetup}
                  disabled={busy}
                  data-testid="two-fa-choose-email"
                  className="text-left p-4 border border-[#E4DFD1] rounded-md hover:border-[#C89434] hover:bg-[#F3EEE0]/40 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Mail size={18} className="text-[#C89434]" />
                    <div className="font-serif font-bold">Email Code</div>
                  </div>
                  <p className="text-xs text-[#6B6558] leading-relaxed">
                    We'll send a 6-digit code to your inbox each time you sign in. No app to install.
                    Slightly weaker than an authenticator (depends on your email security), but simpler.
                  </p>
                </button>
              </div>
            </div>
          )}

          {/* TOTP Enrollment Flow */}
          {setup && (
            <div className="byrd-card p-6 space-y-6" data-testid="two-fa-setup-card">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Step 1</div>
                  <h2 className="font-serif text-xl font-bold mt-1">Scan the QR code</h2>
                  <p className="text-sm text-[#6B6558] mt-1 max-w-lg">
                    Open your authenticator app (1Password, Google Authenticator, Authy, or Microsoft Authenticator)
                    and scan the code below. Or type the secret manually.
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
                  Your authenticator app will now show a rotating code for "Byrd & CO". Type it below to confirm.
                </p>
                <div className="mt-4 flex items-center gap-3 max-w-sm">
                  <input
                    type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                    value={enrollCode}
                    onChange={(e) => setEnrollCode(e.target.value.replace(/\D/g, ""))}
                    data-testid="two-fa-enroll-code"
                    className="flex-1 h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] font-mono tracking-widest text-center text-lg"
                    placeholder="123456"
                  />
                  <button
                    onClick={confirmTotpSetup}
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

          {/* Email Enrollment Flow */}
          {emailSetup && (
            <div className="byrd-card p-6 space-y-4" data-testid="two-fa-email-setup-card">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Confirm your email</div>
                  <h2 className="font-serif text-xl font-bold mt-1">Enter the code we just emailed you</h2>
                  <p className="text-sm text-[#6B6558] mt-2">
                    We sent a 6-digit code to <b>{emailSetup.sent_to_masked}</b>. It expires in <b>{emailSetup.expires_in_minutes} minutes</b>.
                    Check your inbox — and your spam folder if it doesn't arrive.
                  </p>
                </div>
                <button onClick={cancelSetup} className="text-[#6B6558] hover:text-[#1A1A1A]" data-testid="two-fa-cancel-email-setup">
                  <X size={18} />
                </button>
              </div>
              <div className="flex items-center gap-3 max-w-sm">
                <input
                  type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                  value={enrollCode}
                  onChange={(e) => setEnrollCode(e.target.value.replace(/\D/g, ""))}
                  data-testid="two-fa-email-enroll-code"
                  autoFocus
                  className="flex-1 h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] font-mono tracking-widest text-center text-lg"
                  placeholder="123456"
                />
                <button
                  onClick={confirmEmailSetup}
                  disabled={busy || enrollCode.length !== 6}
                  data-testid="two-fa-confirm-email-setup"
                  className="byrd-btn byrd-btn-dark"
                >
                  {busy ? "Verifying…" : "Verify"} <ArrowRight size={14} />
                </button>
              </div>
              <button
                onClick={resendEmailSetup}
                disabled={busy}
                data-testid="two-fa-resend-email-setup"
                className="text-xs text-[#C89434] hover:text-[#1A1A1A] inline-flex items-center gap-1"
              >
                <RefreshCcw size={11} /> Didn't get it? Resend the code
              </button>
            </div>
          )}

          {/* Backup Codes shown once */}
          {backupCodes && (
            <BackupCodesModal codes={backupCodes} onClose={() => setBackupCodes(null)} />
          )}

          {/* Disable modal (method-aware) */}
          {disableOpen && (
            <Modal title="Disable Two-Factor Authentication" onClose={() => setDisableOpen(false)}>
              <p className="text-sm text-[#6B6558] mb-4">
                To disable 2FA we need your password plus one verification code.
                {method === "email" ? " We'll email you a fresh code — click below." : " Enter a 6-digit code from your authenticator app (or a backup code)."}
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

                {method === "email" && !disableEmailSent && (
                  <button
                    type="button"
                    onClick={sendVerificationForDisable}
                    disabled={busy}
                    data-testid="two-fa-disable-send-email"
                    className="byrd-btn byrd-btn-outline w-full justify-center"
                  >
                    <Send size={14} /> {busy ? "Sending…" : "Email me a verification code"}
                  </button>
                )}
                {method === "email" && disableEmailSent && (
                  <div className="text-xs text-[#2A5D2A] bg-[#E8F1E8] rounded-md px-3 py-2">
                    Code sent to {disableEmailSent.sent_to_masked} · expires in {disableEmailSent.expires_in_minutes} min
                  </div>
                )}

                <label className="block">
                  <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
                    {method === "email" ? "Email code (or backup code)" : "6-digit code or backup code"}
                  </div>
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

          {/* Regenerate modal (method-aware) */}
          {regenOpen && (
            <Modal title="Regenerate Backup Codes" onClose={() => setRegenOpen(false)}>
              <p className="text-sm text-[#6B6558] mb-4">
                This creates 10 fresh backup codes. Your <b>old backup codes will stop working immediately.</b>
                Confirm with a {method === "email" ? "code sent to your email" : "6-digit code from your authenticator"}.
              </p>
              <form onSubmit={submitRegen} className="space-y-3">
                {method === "email" && !regenEmailSent && (
                  <button
                    type="button"
                    onClick={sendVerificationForRegen}
                    disabled={busy}
                    data-testid="two-fa-regen-send-email"
                    className="byrd-btn byrd-btn-outline w-full justify-center"
                  >
                    <Send size={14} /> {busy ? "Sending…" : "Email me a verification code"}
                  </button>
                )}
                {method === "email" && regenEmailSent && (
                  <div className="text-xs text-[#2A5D2A] bg-[#E8F1E8] rounded-md px-3 py-2">
                    Code sent to {regenEmailSent.sent_to_masked} · expires in {regenEmailSent.expires_in_minutes} min
                  </div>
                )}
                <label className="block">
                  <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
                    {method === "email" ? "Email code" : "6-digit code"}
                  </div>
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
              <KeyRound size={20} className="text-[#C89434] shrink-0 mt-0.5" />
              <div>
                <div className="font-serif font-bold">Not sure which method to pick?</div>
                <div className="text-sm text-[#6B6558] mt-1">
                  If you already use <b>1Password</b> to store passwords, choose the <b>Authenticator App</b> option —
                  the codes appear right next to your login for byrd-co.com. If you'd rather not install anything,
                  <b> Email Codes</b> work well: we send a fresh code to your inbox each time you sign in.
                </div>
              </div>
            </div>
          </div>

          {/* Admin-only: Backups Section */}
          {isAdmin && <BackupsPanel />}
        </>
      )}
    </div>
  );
}

function BackupsPanel() {
  const [backups, setBackups] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [running, setRunning] = React.useState(false);
  const [lastResult, setLastResult] = React.useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get("/admin/security/backup/list");
      setBackups(res.data.backups || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't load backup history");
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => { load(); }, []);

  const runNow = async () => {
    setRunning(true);
    setLastResult(null);
    try {
      const res = await api.post("/admin/security/backup/run");
      // The endpoint now returns immediately with { ok: true, queued: true, message }.
      // The actual dump / encrypt / upload runs on the server in the background so
      // Cloudflare's ~100s edge timeout can't kill it on a large database.
      if (res.data?.queued) {
        setLastResult({ ok: true, queued: true, message: res.data.message });
        toast.success("Backup started — refreshing shortly");
        // Poll the history a few times so the new row appears without user clicks.
        for (const delay of [8000, 20000, 45000, 90000]) {
          setTimeout(load, delay);
        }
      } else {
        setLastResult({ ok: true, ...res.data });
        toast.success("Backup complete");
        await load();
      }
    } catch (e) {
      setLastResult({ ok: false, error: e?.response?.data?.detail || "Backup failed" });
      toast.error(e?.response?.data?.detail || "Backup failed");
    } finally {
      setRunning(false);
    }
  };

  const fmtBytes = (n) => {
    if (!n && n !== 0) return "—";
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  };

  const fmtDate = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  const successful = (backups || []).filter((b) => b.status !== "error");
  const lastBackup = successful[0];

  return (
    <div className="byrd-card p-6" data-testid="backups-panel">
      <div className="flex items-start gap-4">
        <div className="w-11 h-11 rounded-md grid place-items-center shrink-0 bg-[#1A1A1A] text-[#C89434]">
          <DatabaseBackup size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-serif text-xl font-bold">Database Backups</div>
          <div className="text-sm text-[#6B6558] mt-1">
            Automated encrypted backups run every <b>6 hours</b> to Backblaze B2 with 30-day
            ransomware-proof Object Lock. You can also trigger one right now — for example, before a big change.
          </div>
        </div>
        <button
          onClick={runNow}
          disabled={running}
          data-testid="backup-run-now-btn"
          className="byrd-btn byrd-btn-dark shrink-0"
        >
          {running ? <><Loader2 size={14} className="animate-spin" /> Backing up…</> : <><HardDrive size={14} /> Backup Now</>}
        </button>
      </div>

      {lastResult && (
        <div
          className={`mt-4 rounded-md p-3 text-sm flex items-start gap-2 ${
            lastResult.ok ? "bg-[#E8F1E8] text-[#2A5D2A]" : "bg-[#FBE9E9] text-[#8B2A2A]"
          }`}
          data-testid="backup-last-result"
        >
          {lastResult.ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
          <div>
            {lastResult.ok && lastResult.queued ? (
              <>{lastResult.message || "Backup started in the background. Refresh shortly."}</>
            ) : lastResult.ok ? (
              <>
                Backup saved: <code className="font-mono text-xs">{lastResult.key}</code> · {fmtBytes(lastResult.encrypted_size)} · retained
                until {new Date(lastResult.retain_until).toLocaleDateString()}
              </>
            ) : (
              <>Backup failed: {lastResult.error}</>
            )}
          </div>
        </div>
      )}

      <div className="mt-6 pt-6 border-t border-[#E4DFD1]">
        <div className="flex items-center justify-between mb-3">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">// Recent Backups</div>
          <button
            onClick={load}
            data-testid="backup-refresh-btn"
            className="text-xs text-[#C89434] hover:text-[#1A1A1A] inline-flex items-center gap-1"
          >
            <RefreshCcw size={11} /> Refresh
          </button>
        </div>
        {loading ? (
          <div className="text-sm text-[#6B6558]">Loading history…</div>
        ) : !backups || backups.length === 0 ? (
          <div className="text-sm text-[#6B6558]">No backups yet. Click "Backup Now" to take the first one.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="backup-history-table">
              <thead>
                <tr className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558] text-left">
                  <th className="pb-2 pr-3">When</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2 pr-3">Size</th>
                  <th className="pb-2 pr-3">Retained Until</th>
                  <th className="pb-2">Key</th>
                </tr>
              </thead>
              <tbody>
                {backups.slice(0, 15).map((b, i) => (
                  <tr key={i} className="border-t border-[#E4DFD1]">
                    <td className="py-2 pr-3 whitespace-nowrap">{fmtDate(b.finished_at || b.started_at)}</td>
                    <td className="py-2 pr-3">
                      {b.status === "error" ? (
                        <span className="inline-flex items-center gap-1 text-[#8B2A2A]"><AlertCircle size={12} /> Error</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[#2A5D2A]"><CheckCircle2 size={12} /> OK</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap">{fmtBytes(b.encrypted_size)}</td>
                    <td className="py-2 pr-3 whitespace-nowrap">{b.retain_until ? new Date(b.retain_until).toLocaleDateString() : "—"}</td>
                    <td className="py-2 font-mono text-xs text-[#6B6558] truncate max-w-[280px]" title={b.key || b.error}>
                      {b.key || b.error || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {lastBackup && (
          <div className="text-xs text-[#6B6558] mt-3">
            Last successful backup: <b>{fmtDate(lastBackup.finished_at || lastBackup.started_at)}</b>
          </div>
        )}
      </div>
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
        These 10 codes are your lifeline if you lose access to your authenticator/email.
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
