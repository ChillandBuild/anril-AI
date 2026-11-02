"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import a from "@/components/auth/auth.module.css";
import { clearRecoveryCookie } from "./actions";

const MIN_LENGTH = 8;

export default function ResetPasswordForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_LENGTH) {
      setError(`Password must be at least ${MIN_LENGTH} characters`);
      return;
    }
    if (password !== confirm) {
      setError("The two passwords don't match");
      return;
    }
    setSaving(true);
    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) {
      setError(updateError.message);
      setSaving(false);
      return;
    }
    // Anyone else still signed in as this user (a stolen session, an old laptop) is
    // signed out; this browser stays in.
    await supabase.auth.signOut({ scope: "others" }).catch(() => {});
    // Clears an admin-issued "must change password" flag, if there was one.
    await api.rbac.markPasswordResetComplete().catch(() => {});
    await clearRecoveryCookie().catch(() => {});
    router.push("/dashboard");
    router.refresh();
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div role="alert" className={a.error}>
          {error}
        </div>
      )}
      <div>
        <label htmlFor="new-password" className={a.label}>
          New password
        </label>
        <div className="relative">
          <input
            id="new-password"
            type={show ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={MIN_LENGTH}
            autoComplete="new-password"
            className={`${a.field} pr-12`}
          />
          <button
            type="button"
            onClick={() => setShow(!show)}
            className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink transition-colors"
            aria-label={show ? "Hide password" : "Show password"}
          >
            {show ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </div>
      <div>
        <label htmlFor="confirm-password" className={a.label}>
          Confirm new password
        </label>
        <input
          id="confirm-password"
          type={show ? "text" : "password"}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          autoComplete="new-password"
          className={a.field}
        />
      </div>
      <button type="submit" disabled={saving} className={a.primary}>
        {saving ? "Saving…" : "Save and sign in"}
      </button>
    </form>
  );
}
