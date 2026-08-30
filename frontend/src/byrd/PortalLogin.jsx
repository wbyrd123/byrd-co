import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LOGO_URL } from "@/byrd/data";
import { toast } from "sonner";
import { ArrowRight, ArrowLeft, ShieldCheck, Mail, KeyRound } from "lucide-react";

export default function PortalLogin() {
  const nav = useNavigate();
  const { login, complete2FA, send2FAEmail } = useAuth();

  // Stage: "password" | "2fa"
  const [stage, setStage] = useState("password");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  // 2FA state
  const [challengeToken, setChallengeToken] = useState("");
  const [twoFACode, setTwoFACode] = useState("");
  const [twoFAMethod, setTwoFAMethod] = useState("totp"); // "totp" | "email" | "backup"
  const [emailStatus, setEmailStatus] = useState(null); // {sent_to_masked, expires_in_minutes}
  const [primaryMethod, setPrimaryMethod] = useState("totp"); // user's enrolled primary method
  const [totpAvailable, setTotpAvailable] = useState(true);

  const routeUser = (user) => {
    const dest =
      user.role === "admin" ? "/admin" : user.role === "lender" ? "/lender/portal" : "/portal";
    nav(dest);
  };

  const submitPassword = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await login(email, pw);
      if (result.requires_2fa) {
        setChallengeToken(result.challenge_token);
        setStage("2fa");
        setPrimaryMethod(result.primary_method || "totp");
        setTotpAvailable(!!result.totp_available);
        setTwoFACode("");
        setEmailStatus(null);
        if (result.primary_method === "email") {
          // Email-primary users: auto-send the code right away
          setTwoFAMethod("email");
          try {
            const emailRes = await send2FAEmail(result.challenge_token);
            setEmailStatus(emailRes);
            toast.success(`Check your email — we sent a code to ${emailRes.sent_to_masked}`);
          } catch (err) {
            toast.error(err?.response?.data?.detail || "Couldn't send email code");
          }
        } else {
          setTwoFAMethod("totp");
          toast.success("Password accepted. Enter your 6-digit code.");
        }
      } else {
        toast.success(`Welcome back, ${result.user.name}`);
        routeUser(result.user);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Invalid credentials");
    } finally {
      setBusy(false);
    }
  };

  const submit2FA = async (e) => {
    e.preventDefault();
    if (!twoFACode.trim()) {
      toast.error("Enter a verification code");
      return;
    }
    setBusy(true);
    try {
      const user = await complete2FA(challengeToken, twoFACode.trim(), twoFAMethod);
      toast.success(`Welcome back, ${user.name}`);
      routeUser(user);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Code is invalid or expired");
    } finally {
      setBusy(false);
    }
  };

  const requestEmailCode = async () => {
    setBusy(true);
    try {
      const res = await send2FAEmail(challengeToken);
      setEmailStatus(res);
      setTwoFAMethod("email");
      setTwoFACode("");
      toast.success(`Code sent to ${res.sent_to_masked}`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Couldn't send email code");
    } finally {
      setBusy(false);
    }
  };

  const restartLogin = () => {
    setStage("password");
    setChallengeToken("");
    setTwoFACode("");
    setEmailStatus(null);
  };

  return (
    <div className="min-h-screen bg-[#FBF8F1] flex flex-col">
      <div className="max-w-6xl w-full mx-auto px-5 sm:px-8 py-6">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-[#6B6558] hover:text-[#1A1A1A]" data-testid="back-home">
          <ArrowLeft size={14} /> Back to home
        </Link>
      </div>

      <div className="flex-1 flex items-center justify-center px-5 pb-16">
        <div className="w-full max-w-md byrd-card p-8 md:p-10" data-testid="login-card">
          <div className="flex items-center gap-3 mb-8">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-12 w-auto" />
            <div>
              <div className="font-serif text-xl font-bold">Byrd &amp; CO</div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Client Portal</div>
            </div>
          </div>

          {stage === "password" && (
            <>
              <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Sign In</div>
              <h1 className="font-serif text-3xl font-bold mt-2">Welcome back.</h1>
              <p className="text-sm text-[#6B6558] mt-2">
                Enter the credentials you set up when you accepted your invite.
              </p>

              <form onSubmit={submitPassword} className="mt-6 space-y-4">
                <div>
                  <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Email</label>
                  <input
                    type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                    data-testid="login-email"
                    className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <div className="flex items-baseline justify-between">
                    <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">Password</label>
                    <Link to="/portal/forgot-password" className="text-xs text-[#C89434] hover:text-[#1A1A1A]" data-testid="forgot-password-link">
                      Forgot password?
                    </Link>
                  </div>
                  <input
                    type="password" required value={pw} onChange={(e) => setPw(e.target.value)}
                    data-testid="login-password"
                    className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
                    placeholder="•••••••"
                  />
                </div>
                <button type="submit" disabled={busy} data-testid="login-submit" className="byrd-btn byrd-btn-dark w-full">
                  {busy ? "Signing in…" : "Sign In"} <ArrowRight size={16} />
                </button>
              </form>

              <div className="text-xs text-[#6B6558] mt-6 leading-relaxed">
                Don&apos;t have an account? Byrd &amp; CO invites clients directly — reach out to your loan officer to
                get a portal invite link.
              </div>
            </>
          )}

          {stage === "2fa" && (
            <>
              <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest flex items-center gap-2">
                <ShieldCheck size={12} /> // Two-Factor Verification
              </div>
              <h1 className="font-serif text-3xl font-bold mt-2">One more step.</h1>
              <p className="text-sm text-[#6B6558] mt-2">
                {twoFAMethod === "totp" && "Open your authenticator app (1Password, Google Authenticator, etc.) and enter the 6-digit code."}
                {twoFAMethod === "email" && emailStatus && (
                  <>We sent a 6-digit code to <b>{emailStatus.sent_to_masked}</b>. It expires in {emailStatus.expires_in_minutes} minutes.</>
                )}
                {twoFAMethod === "backup" && "Enter one of your 10 backup codes (format: xxxx-xxxx). Each works only once."}
              </p>

              <form onSubmit={submit2FA} className="mt-6 space-y-4">
                <div>
                  <label className="text-xs uppercase font-mono tracking-widest text-[#6B6558]">
                    {twoFAMethod === "backup" ? "Backup Code" : "Verification Code"}
                  </label>
                  <input
                    type="text"
                    inputMode={twoFAMethod === "backup" ? "text" : "numeric"}
                    autoComplete="one-time-code"
                    required
                    value={twoFACode}
                    onChange={(e) => setTwoFACode(e.target.value)}
                    data-testid="two-fa-code-input"
                    autoFocus
                    className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] font-mono tracking-widest text-center text-lg"
                    placeholder={twoFAMethod === "backup" ? "xxxx-xxxx" : "123456"}
                    maxLength={twoFAMethod === "backup" ? 9 : 6}
                  />
                </div>
                <button type="submit" disabled={busy} data-testid="two-fa-submit" className="byrd-btn byrd-btn-dark w-full">
                  {busy ? "Verifying…" : "Verify & Sign In"} <ArrowRight size={16} />
                </button>
              </form>

              <div className="mt-6 pt-6 border-t border-[#E4DFD1] space-y-2">
                <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558] mb-1">Trouble?</div>
                {twoFAMethod !== "email" && (
                  <button
                    type="button"
                    onClick={requestEmailCode}
                    disabled={busy}
                    data-testid="two-fa-use-email"
                    className="text-xs text-[#C89434] hover:text-[#1A1A1A] flex items-center gap-1 w-fit"
                  >
                    <Mail size={12} /> Email me a code instead
                  </button>
                )}
                {twoFAMethod !== "totp" && totpAvailable && (
                  <button
                    type="button"
                    onClick={() => { setTwoFAMethod("totp"); setTwoFACode(""); }}
                    data-testid="two-fa-use-totp"
                    className="text-xs text-[#C89434] hover:text-[#1A1A1A] flex items-center gap-1 w-fit"
                  >
                    <ShieldCheck size={12} /> Use my authenticator app
                  </button>
                )}
                {twoFAMethod !== "backup" && (
                  <button
                    type="button"
                    onClick={() => { setTwoFAMethod("backup"); setTwoFACode(""); }}
                    data-testid="two-fa-use-backup"
                    className="text-xs text-[#C89434] hover:text-[#1A1A1A] flex items-center gap-1 w-fit"
                  >
                    <KeyRound size={12} /> Use a backup code
                  </button>
                )}
                <button
                  type="button"
                  onClick={restartLogin}
                  data-testid="two-fa-restart"
                  className="text-xs text-[#6B6558] hover:text-[#1A1A1A] flex items-center gap-1 w-fit mt-2"
                >
                  <ArrowLeft size={12} /> Start over
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
