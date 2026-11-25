"use client";
import { useState, useEffect } from "react";
import localFont from "next/font/local";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Eye, EyeOff, X } from "lucide-react";
import LoginShowcase from "@/components/auth/LoginShowcase";
import { LoginShaders } from "@/components/auth/LoginShaders";
import a from "@/components/auth/auth.module.css";
import L from "@/components/auth/login.module.css";
import {
  NO_TRIES,
  addWrongTry,
  formatCountdown,
  isWrongPasswordError,
  mustChangePassword,
  pauseSecondsLeft,
  readTries,
  writeTries,
  type LoginTries,
} from "@/components/first-setup/helpers";
import { requestPasswordHelp } from "@/lib/firstSetupApi";

// Off until Google is set up in Google Cloud and enabled as a Supabase provider.
// Calling signInWithOAuth before that lands people on a raw JSON error page.
const GOOGLE_ENABLED = process.env.NEXT_PUBLIC_GOOGLE_SIGNIN === "true";

// The public site's serif, for the two headlines. Same two static weights as components/site/SiteChrome.tsx.
const newsreader = localFont({
  src: [
    { path: "../../fonts/newsreader-latin-300.woff2", weight: "300", style: "normal" },
    { path: "../../fonts/newsreader-latin-400.woff2", weight: "400", style: "normal" },
  ],
  variable: "--font-newsreader",
  display: "swap",
});

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
  const [businessName, setBusinessName] = useState("");
  const [helpNote, setHelpNote] = useState("");
  const [phoneOrEmail, setPhoneOrEmail] = useState("");
  // After 5 wrong passwords in this browser the button waits 10 minutes. A courtesy only: the
  // real limit on sign-in attempts is Supabase's, on its server.
  const [tries, setTries] = useState<LoginTries>(NO_TRIES);
  const [now, setNow] = useState(() => Date.now());
  const [passkeyLoading, setPasskeyLoading] = useState(false);

  useEffect(() => {
    setTries(readTries());
  }, []);
  const secondsLeft = pauseSecondsLeft(tries, now);
  useEffect(() => {
    if (!secondsLeft) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [secondsLeft]);

  useEffect(() => {
    const reason = new URLSearchParams(window.location.search).get("reason");
    if (reason && Object.hasOwn(REASONS, reason)) setError(REASONS[reason]);
  }, []);

  function clearMessages() {
    setError(null);
    setNotice(null);
  }

  function switchView(next: "signin" | "forgot") {
    setView(next);
    clearMessages();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const stamp = Date.now();
    setNow(stamp);
    if (pauseSecondsLeft(readTries(), stamp) > 0) return;
    setLoading(true);
    setError(null);
    setNotice(null);
    const supabase = createClient();
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) {
      if (isWrongPasswordError(error)) {
        const next = addWrongTry(readTries(), Date.now());
        writeTries(next);
        setTries(next);
        setNow(Date.now());
      }
      setError(error.message);
      setLoading(false);
      return;
    }
    writeTries(NO_TRIES);
    // The Anril team made this login with a first password: the owner picks their own now.
    router.push(mustChangePassword(data.user) ? "/change-password" : "/dashboard");
    router.refresh();
  }

  // Forgot password is not automatic: the request goes to the Anril team, who check it is really
  // the owner and give the new password in person or on a call. Nothing is sent by email or SMS.
  async function handleHelpRequest(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const res = await requestPasswordHelp({
        identifier: phoneOrEmail.trim(),
        business_name: businessName.trim(),
        note: helpNote.trim(),
      });
      setNotice(res.message);
      setPhoneOrEmail("");
      setBusinessName("");
      setHelpNote("");
    } catch {
      setError("We couldn't send your request. Check your internet and try again.");
    }
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
    const { data, error } = await supabase.auth.signInWithPasskey();
    if (error) {
      setPasskeyLoading(false);
      // User cancelled the OS passkey prompt or it timed out — not a real error, stay quiet.
      if (error.name !== "NotAllowedError") {
        setError(error.message);
      }
      return;
    }
    router.push(mustChangePassword(data?.user) ? "/change-password" : "/dashboard");
    router.refresh();
  }

  return (
    <div className={`${newsreader.variable} ${L.page}`}>
      <LoginShowcase />
      <main className={L.side}>
        <LoginShaders variant="light" />
        <div className={L.card}>
            {(error || notice) && (
              <div
                role={error ? "alert" : "status"}
                className={`${error ? a.error : a.notice} ${a.banner}`}
              >
                <span>{error ?? notice}</span>
                <button
                  type="button"
                  className={a.bannerClose}
                  onClick={clearMessages}
                  aria-label="Dismiss"
                >
                  <X size={16} />
                </button>
              </div>
            )}
            {view === "signin" ? (
              <>
                <h1 className={L.heading}>
                  Welcome back
                </h1>
                <p className={L.lead}>
                  Sign in to your workspace
                </p>

                <form onSubmit={handleSubmit} className="space-y-4">
                  <div>
                    <label htmlFor="email" className={a.label}>
                      Email
                    </label>
                    <input
                      id="email"
                      type="email"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        clearMessages();
                      }}
                      required
                      inputMode="email"
                      autoCapitalize="none"
                      autoCorrect="off"
                      autoComplete="email"
                      className={L.field}
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
                        onClick={() => {
                          setPhoneOrEmail(email);
                          switchView("forgot");
                        }}
                      >
                        Forgot password?
                      </button>
                    </div>
                    <div className="relative">
                      <input
                        id="password"
                        type={showPassword ? "text" : "password"}
                        value={password}
                        onChange={(e) => {
                          setPassword(e.target.value);
                          clearMessages();
                        }}
                        required
                        autoComplete="current-password"
                        className={`${L.field} pr-12`}
                        placeholder="••••••••"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-1 top-1/2 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center text-ink-muted hover:text-ink transition-colors"
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
                    disabled={loading || secondsLeft > 0}
                    className={L.primary}
                  >
                    {secondsLeft > 0
                      ? `Too many tries. Wait ${formatCountdown(secondsLeft)}`
                      : loading
                        ? "Signing in…"
                        : "Sign in"}
                  </button>
                </form>

                <div className={L.or}>or</div>

                <button
                  type="button"
                  onClick={handleGoogle}
                  className={L.alt}
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
                <h1 className={`${L.heading} ${L.headingSmall}`}>
                  Forgot your password?
                </h1>
                <p className={L.lead}>
                  Send a request to the Anril team. They will check it is
                  really you and give you a new password in person or on a
                  call, Monday to Saturday, 10 to 6. We never send passwords
                  by email or SMS. Team members: ask your owner to set a new
                  password in Settings, Team &amp; roles.
                </p>

                <form onSubmit={handleHelpRequest} className="space-y-4">
                  <div>
                    <label htmlFor="help-who" className={a.label}>
                      Your login email and a phone number
                    </label>
                    <input
                      id="help-who"
                      type="text"
                      value={phoneOrEmail}
                      onChange={(e) => {
                        setPhoneOrEmail(e.target.value);
                        clearMessages();
                      }}
                      required
                      maxLength={120}
                      autoCapitalize="none"
                      autoCorrect="off"
                      className={L.field}
                      placeholder="you@shop.com, 98765 43210"
                    />
                  </div>
                  <div>
                    <label htmlFor="help-business" className={a.label}>
                      Business name (optional)
                    </label>
                    <input
                      id="help-business"
                      type="text"
                      value={businessName}
                      onChange={(e) => setBusinessName(e.target.value)}
                      maxLength={120}
                      className={L.field}
                    />
                  </div>
                  <div>
                    <label htmlFor="help-note" className={a.label}>
                      Anything we should know (optional)
                    </label>
                    <textarea
                      id="help-note"
                      value={helpNote}
                      onChange={(e) => setHelpNote(e.target.value)}
                      maxLength={300}
                      rows={2}
                      className={L.field}
                      placeholder="For example: best time to call you"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={loading || !phoneOrEmail.trim()}
                    className={L.primary}
                  >
                    {loading ? "Sending…" : "Send request to Anril team"}
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
      </main>
    </div>
  );
}
