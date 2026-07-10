import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ArrowRight, Sparkles } from "lucide-react";

const HERO_IMG =
  "https://images.unsplash.com/photo-1738844153732-a485f0e78382?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1MDZ8MHwxfHNlYXJjaHwyfHxtaW5pbWFsaXN0JTIwZ2VvbWV0cmljJTIwYXJ0JTIwYXJjaGl0ZWN0dXJlfGVufDB8fHx8MTc4MzY4ODU5MHww&ixlib=rb-4.1.0&q=85";

export default function Auth() {
  const nav = useNavigate();
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, pw);
      } else {
        await register(name || email.split("@")[0], email, pw);
      }
      toast.success(mode === "login" ? "Logged in" : "Account created");
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2 bg-[#F4F4F0]">
      {/* Left visual */}
      <div className="relative hidden lg:block border-r-2 border-black">
        <img src={HERO_IMG} alt="" className="absolute inset-0 w-full h-full object-cover grayscale" />
        <div className="absolute inset-0 bg-black/25" />
        <div className="relative z-10 h-full flex flex-col justify-between p-10 text-white">
          <div className="flex items-center gap-3 font-display text-xl font-bold">
            <div className="w-8 h-8 bg-white text-black grid place-items-center hard-shadow-sm">
              <Sparkles size={16} />
            </div>
            AdsCopilot
          </div>
          <div className="max-w-md">
            <div className="font-mono text-xs uppercase mb-3 opacity-80">/ operators only</div>
            <h1 className="font-display text-5xl xl:text-6xl font-bold tracking-tighter leading-[0.95]">
              Run Google Ads<br />like an operator.
            </h1>
            <p className="mt-6 text-base opacity-90 max-w-sm">
              An AI copilot for advertisers. Draft campaigns, generate compliant ad copy,
              research keywords, and read the numbers — in one terminal.
            </p>
          </div>
          <div className="font-mono text-[11px] uppercase opacity-80 flex gap-6">
            <span>v1.0</span>
            <span>demo mode</span>
            <span>claude sonnet 4.5</span>
          </div>
        </div>
      </div>

      {/* Right form */}
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md" data-testid="auth-panel">
          <div className="flex items-center gap-3 lg:hidden mb-8 font-display text-xl font-bold">
            <div className="w-8 h-8 bg-black text-white grid place-items-center hard-shadow-sm">
              <Sparkles size={16} />
            </div>
            AdsCopilot
          </div>
          <div className="font-mono text-xs uppercase mb-2">// {mode === "login" ? "sign in" : "create account"}</div>
          <h2 className="font-display text-4xl font-bold tracking-tighter mb-8">
            {mode === "login" ? "Welcome back." : "Get building."}
          </h2>

          <form onSubmit={submit} className="space-y-5">
            {mode === "register" && (
              <div>
                <Label htmlFor="name" className="font-mono text-xs uppercase">Name</Label>
                <Input
                  id="name"
                  data-testid="auth-name-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Alex Kim"
                  className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
                />
              </div>
            )}
            <div>
              <Label htmlFor="email" className="font-mono text-xs uppercase">Email</Label>
              <Input
                id="email"
                data-testid="auth-email-input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
            <div>
              <Label htmlFor="pw" className="font-mono text-xs uppercase">Password</Label>
              <Input
                id="pw"
                data-testid="auth-password-input"
                type="password"
                required
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                placeholder="•••••••"
                className="mt-1 rounded-none border-2 border-black h-11 font-mono focus-visible:ring-0 focus-visible:ring-offset-0"
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              data-testid="auth-submit-btn"
              className="w-full h-12 bg-black text-white font-mono uppercase text-sm hard-shadow press-effect flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {busy ? "..." : mode === "login" ? "Sign in" : "Create account"}
              <ArrowRight size={16} />
            </button>
          </form>

          <div className="mt-6 font-mono text-xs">
            {mode === "login" ? (
              <>
                No account?{" "}
                <button
                  data-testid="auth-toggle-register"
                  onClick={() => setMode("register")}
                  className="underline underline-offset-4 font-semibold"
                >
                  Create one →
                </button>
              </>
            ) : (
              <>
                Already have one?{" "}
                <button
                  data-testid="auth-toggle-login"
                  onClick={() => setMode("login")}
                  className="underline underline-offset-4 font-semibold"
                >
                  Sign in →
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
