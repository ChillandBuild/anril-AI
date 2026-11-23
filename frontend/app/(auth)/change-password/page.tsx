"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import { AnrilLogo } from "@/components/logo";
import { checkNewPassword, mustChangePassword } from "@/components/first-setup/helpers";
import a from "@/components/auth/auth.module.css";

// First sign-in after the Anril team made the login: the owner picks their own password.
// A helper for the owner, not a security wall (see MustChangePasswordGate).
export default function ChangePasswordPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function check() {
      try {
        const { data } = await createClient().auth.getUser();
        if (!data.user) router.replace("/login");
        // Someone who already chose a password has nothing to do here.
        else if (!mustChangePassword(data.user)) router.replace("/dashboard");
        else setReady(true);
      } catch {
        router.replace("/login");
      }
    }
    void check();
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const problem = checkNewPassword({ current, next, again });
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({
      password: next,
      current_password: current,
      data: { must_change_password: false },
    });
    if (updateError) {
      setError(/same|different/i.test(updateError.message) ? "The new password must be different from the old one" : updateError.message);
      setSaving(false);
      return;
    }
    // A team member whose owner set a temporary password has a second flag on the server; clear it too.
    await api.rbac.markPasswordResetComplete().catch(() => {});
    router.push("/dashboard");
    router.refresh();
  }

  const eye = (
    <button
      type="button"
      onClick={() => setShow((s) => !s)}
      className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink transition-colors"
      aria-label={show ? "Hide passwords" : "Show passwords"}
    >
      {show ? <EyeOff size={18} /> : <Eye size={18} />}
    </button>
  );

  return (
    <div className={`${a.page} flex flex-col`}>
      <main className="flex-1 flex items-center justify-center px-4 py-8 sm:px-8">
        <div className="w-full max-w-[420px]">
          <div className={a.card}>
            <AnrilLogo height={30} className="text-ink mb-7" />
            <h1 className="text-[26px] font-extrabold tracking-tight">Choose your own password</h1>
            <p className="mt-1 mb-6 text-[15px] text-ink-muted">
              The Anril team gave you a first password. Pick one only you know, at least 8 characters.
            </p>
            {error && (
              <div role="alert" className={`${a.error} mb-4`}>
                {error}
              </div>
            )}
            {ready ? (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="current" className={a.label}>
                    Password you were given
                  </label>
                  <div className="relative">
                    <input
                      id="current"
                      type={show ? "text" : "password"}
                      value={current}
                      onChange={(e) => setCurrent(e.target.value)}
                      autoComplete="current-password"
                      required
                      className={`${a.field} pr-12`}
                    />
                    {eye}
                  </div>
                </div>
                <div>
                  <label htmlFor="next" className={a.label}>
                    New password
                  </label>
                  <input
                    id="next"
                    type={show ? "text" : "password"}
                    value={next}
                    onChange={(e) => setNext(e.target.value)}
                    autoComplete="new-password"
                    minLength={8}
                    required
                    className={a.field}
                  />
                </div>
                <div>
                  <label htmlFor="again" className={a.label}>
                    New password again
                  </label>
                  <input
                    id="again"
                    type={show ? "text" : "password"}
                    value={again}
                    onChange={(e) => setAgain(e.target.value)}
                    autoComplete="new-password"
                    required
                    className={a.field}
                  />
                </div>
                <button type="submit" disabled={saving} className={a.primary}>
                  {saving ? "Saving…" : "Save and continue"}
                </button>
              </form>
            ) : (
              <p className="text-[15px] text-ink-muted">Checking your sign-in…</p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
