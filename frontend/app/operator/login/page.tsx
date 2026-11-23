"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { API_URL } from "@/lib/api";
import { safeOperatorNext } from "@/lib/claude-access";
import { AnrilLogo } from "@/components/logo";

export default function OperatorLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const supabase = createClient();

    try {
      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });

      if (signInError) throw new Error("Invalid email or password");

      const token = data.session?.access_token;
      if (!token) throw new Error("No session returned");

      const res = await fetch(`${API_URL}/api/v1/operator/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        await supabase.auth.signOut({ scope: "local" });
        setError("Access denied. This console is for Anril AI operators only.");
        return;
      }

      const me = await res.json();

      if (!me.is_system_admin) {
        await supabase.auth.signOut({ scope: "local" });
        setError("Access denied. This console is for Anril AI operators only.");
        return;
      }

      // Coming from the Claude consent screen? Go back there. Anything else is ignored.
      const next = safeOperatorNext(new URLSearchParams(window.location.search).get("next"));
      router.push(next ?? "/operator");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-2">
            <AnrilLogo className="h-7 w-auto text-ink" />
          </div>
          <p className="text-xs text-ink-muted mt-1.5 uppercase tracking-widest font-semibold font-label">
            Operator Console
          </p>
        </div>

        <div className="bg-white rounded-card shadow-card border border-border p-8">
          <form onSubmit={handleLogin} className="space-y-4">
            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-body">
                {error}
              </div>
            )}
            <div>
              <label className="text-sm font-medium text-ink block mb-1.5 font-label">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoFocus
                className="w-full px-3 py-2 border border-border rounded-xl text-ink placeholder-ink-muted focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary font-body"
                placeholder="you@airaai.com"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-ink block mb-1.5 font-label">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                className="w-full px-3 py-2 border border-border rounded-xl text-ink placeholder-ink-muted focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary font-body"
                placeholder="••••••••"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-primary-dark text-white font-medium py-2 rounded-xl transition-colors disabled:opacity-50 font-display"
            >
              {loading ? "Verifying..." : "Sign in"}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-ink-muted mt-6 font-body">
          Client dashboard?{" "}
          <Link href="/login" className="text-primary hover:underline">Login here</Link>
        </p>
      </div>
    </div>
  );
}
