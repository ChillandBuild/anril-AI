"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Eye, EyeOff } from "lucide-react";
import { AnrilLogo } from "@/components/logo";
import LoginShowcase from "@/components/auth/LoginShowcase";
import a from "@/components/auth/auth.module.css";

// Off until Google is set up in Google Cloud and enabled as a Supabase provider.
// Calling signInWithOAuth before that lands people on a raw JSON error page.
const GOOGLE_ENABLED = process.env.NEXT_PUBLIC_GOOGLE_SIGNIN === "true";

const REASONS: Record<string, string> = {
  removed:
    "Your access to this workspace was removed. Contact your admin if this is unexpected.",
  link: "That link has expired or was opened in a different browser. Request a new one.",
};

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"
      />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [view, setView] = useState<"signin" | "forgot">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const [peek, setPeek] = useState(false);
  const [wide, setWide] = useState(false);

  useEffect(() => {
    const reason = new URLSearchParams(window.location.search).get("reason");
    if (reason && Object.hasOwn(REASONS, reason)) setError(REASONS[reason]);
  }, []);

  // The showcase only mounts on wide screens, so phones skip its videos entirely.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1280px)");
    const sync = () => setWide(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  function switchView(next: "signin" | "forgot") {
    setView(next);
    setError(null);
    setNotice(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setNotice(null);
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) {
      setError(error.message);
      setLoading(false);
      return;
    }
    router.push("/dashboard");
    router.refresh();
  }

  async function handleReset(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const supabase = createClient();
    await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/callback?next=/reset-password`,
    });
    // Same message whether or not the email has an account, so this form can't be
    // used to find out who is a customer. Rate-limit errors land here too.
    setNotice(
      "If that email has an account, a reset link is on its way. Open it in this browser.",
    );
    setLoading(false);
  }

  async function handleGoogle() {
    setError(null);
    if (!GOOGLE_ENABLED) {
      setNotice(
        "Google sign-in is coming soon. Use your email and password for now.",
      );
      return;
    }
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    if (error) setError(error.message);
  }

  async function handlePasskeyLogin() {
    setPasskeyLoading(true);
    setError(null);
    setNotice(null);
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPasskey();
    if (error) {
      setPasskeyLoading(false);
      // User cancelled the OS passkey prompt or it timed out — not a real error, stay quiet.
      if (error.name !== "NotAllowedError") {
        setError(error.message);
      }
      return;
    }
    router.push("/dashboard");
    router.refresh();
  }

  return (
    <div className={`${a.page} flex flex-col`}>
      <AnrilLogo height={32} className={`${a.logo} text-ink hidden xl:block`} />

      {/* Below 1280px: soft colour behind the compact header */}
      <div
        className={`${a.blob} xl:hidden`}
        style={{
          left: -80,
          top: -60,
          width: 320,
          height: 260,
          background: "rgba(63,188,191,.4)",
        }}
        aria-hidden="true"
      />
      <div
        className={`${a.blob} xl:hidden`}
        style={{
          right: -80,
          top: 120,
          width: 280,
          height: 220,
          background: "rgba(217,150,107,.28)",
        }}
        aria-hidden="true"
      />

      <main className="flex-1 flex items-center justify-center px-4 py-8 sm:px-8 xl:py-16">
        <div className="flex w-full max-w-[420px] flex-col gap-5 xl:max-w-none xl:w-auto xl:flex-row xl:items-center xl:gap-12">
          {wide ? (
            <div className="hidden xl:block relative w-[680px] h-[600px] shrink-0">
              <LoginShowcase
                peek={peek}
                flying={loading && view === "signin"}
              />
            </div>
          ) : (
            <div className="xl:hidden flex flex-col gap-5">
              <AnrilLogo height={30} className="text-ink" />
              <div className={a.glassHeader}>
                <h2>Every lead, answered in seconds.</h2>
                <p>
                  WhatsApp · Instagram · Facebook, in Tamil, Tanglish and
                  English.
                </p>
              </div>
            </div>
          )}

          <div className="xl:w-[420px] xl:shrink-0">
            <div className={a.card}>
              {view === "signin" ? (
                <>
                  <h1 className="text-[26px] font-extrabold tracking-tight">
                    Welcome back
                  </h1>
                  <p className="mt-1 mb-6 text-[15px] text-ink-muted">
                    Sign in to your workspace
                  </p>

                  {error && (
                    <div role="alert" className={`${a.error} mb-4`}>
                      {error}
                    </div>
                  )}
                  {notice && (
                    <div role="status" className={`${a.notice} mb-4`}>
                      {notice}
                    </div>
                  )}

                  <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                      <label htmlFor="email" className={a.label}>
                        Email
                      </label>
                      <input
                        id="email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        inputMode="email"
                        autoCapitalize="none"
                        autoCorrect="off"
                        autoComplete="email"
                        className={a.field}
                        placeholder="you@company.com"
                      />
                    </div>
                    <div>
                      <div className="flex items-center justify-between">
                        <label htmlFor="password" className={a.label}>
                          Password
                        </label>
                        <button
                          type="button"
                          className={`${a.link} mb-2`}
                          onClick={() => switchView("forgot")}
                        >
                          Reset password
                        </button>
                      </div>
                      <div className="relative">
                        <input
                          id="password"
                          type={showPassword ? "text" : "password"}
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          onFocus={() => setPeek(true)}
                          onBlur={() => setPeek(false)}
                          required
                          autoComplete="current-password"
                          className={`${a.field} pr-12`}
                          placeholder="••••••••"
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink transition-colors"
                          aria-label={
                            showPassword ? "Hide password" : "Show password"
                          }
                        >
                          {showPassword ? (
                            <EyeOff size={18} />
                          ) : (
                            <Eye size={18} />
                          )}
                        </button>
                      </div>
                    </div>
                    <button
                      type="submit"
                      disabled={loading}
                      className={a.primary}
                    >
                      {loading ? "Signing in…" : "Sign in"}
                    </button>
                  </form>

                  <div className="flex items-center gap-3 my-5">
                    <div className="h-px flex-1 bg-[#E4DFD3]" />
                    <span className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                      or
                    </span>
                    <div className="h-px flex-1 bg-[#E4DFD3]" />
                  </div>

                  <button
                    type="button"
                    onClick={handleGoogle}
                    className={a.alt}
                  >
                    <GoogleIcon />
                    Continue with Google
                  </button>

                  <div className="mt-5 text-center">
                    <button
                      type="button"
                      onClick={handlePasskeyLogin}
                      disabled={passkeyLoading}
                      className={a.link}
                    >
                      {passkeyLoading ? "Verifying…" : "Use a passkey instead"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <h1 className="text-[26px] font-extrabold tracking-tight">
                    Reset your password
                  </h1>
                  <p className="mt-1 mb-6 text-[15px] text-ink-muted">
                    We&apos;ll email you a link to choose a new one.
                  </p>

                  {error && (
                    <div role="alert" className={`${a.error} mb-4`}>
                      {error}
                    </div>
                  )}
                  {notice && (
                    <div role="status" className={`${a.notice} mb-4`}>
                      {notice}
                    </div>
                  )}

                  <form onSubmit={handleReset} className="space-y-4">
                    <div>
                      <label htmlFor="reset-email" className={a.label}>
                        Email
                      </label>
                      <input
                        id="reset-email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        inputMode="email"
                        autoCapitalize="none"
                        autoCorrect="off"
                        autoComplete="email"
                        className={a.field}
                        placeholder="you@company.com"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={loading}
                      className={a.primary}
                    >
                      {loading ? "Sending…" : "Email me a reset link"}
                    </button>
                  </form>

                  <div className="mt-5 text-center">
                    <button
                      type="button"
                      className={a.link}
                      onClick={() => switchView("signin")}
                    >
                      Back to sign in
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
