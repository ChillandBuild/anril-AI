"use client";
import { useState } from "react";
import { Lock, Eye, EyeOff, Loader2, CheckCircle2, AlertCircle, ChevronDown } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";

const MIN_LENGTH = 8;

type State = "idle" | "saving" | "saved";

export default function ChangePasswordCard({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const [collapsed, setCollapsed] = useState(!defaultOpen);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setCurrent("");
    setNext("");
    setConfirm("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (next.length < MIN_LENGTH) {
      setError(`New password must be at least ${MIN_LENGTH} characters`);
      return;
    }
    if (next !== confirm) {
      setError("New password and confirmation do not match");
      return;
    }
    if (next === current) {
      setError("New password must be different from the current one");
      return;
    }

    setState("saving");
    const supabase = createClient();

    const { data: userData } = await supabase.auth.getUser();
    const email = userData.user?.email;
    if (!email) {
      setError("Session expired — please sign in again");
      setState("idle");
      return;
    }

    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password: current,
    });
    if (signInError) {
      setError("Current password is incorrect");
      setState("idle");
      return;
    }

    const { error: updateError } = await supabase.auth.updateUser({
      password: next,
      current_password: current,
    });
    if (updateError) {
      setError(updateError.message);
      setState("idle");
      return;
    }
    await api.rbac.markPasswordResetComplete().catch(() => {});

    reset();
    setState("saved");
    if (defaultOpen) {
      setTimeout(() => window.location.reload(), 700);
      return;
    }
    setTimeout(() => setState("idle"), 2500);
  }

  const eyeBtn = (
    <button
      type="button"
      onClick={() => setShow((s) => !s)}
      className="inline-flex h-10 w-10 items-center justify-center text-ink-muted hover:text-ink-secondary"
      tabIndex={-1}
      aria-label={show ? "Hide password" : "Show password"}
    >
      {show ? <EyeOff size={14} /> : <Eye size={14} />}
    </button>
  );

  return (
    <div className="card rounded-3xl">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center gap-3 text-left"
      >
        <div className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0" style={{ background: "#dbeafe" }}>
          <Lock size={18} style={{ color: "#2563eb" }} />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-display font-bold text-ink" style={{ fontSize: "1rem", letterSpacing: "-0.02em" }}>
            Account Security
          </h2>
          <p className="font-body text-sm text-ink-muted mt-0.5">Change the password for your login.</p>
        </div>
        <ChevronDown size={18} className={`text-ink-muted transition-transform flex-shrink-0 ${collapsed ? "" : "rotate-180"}`} />
      </button>

      {!collapsed && (
        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          {error && (
            <div className="flex items-center gap-2 p-3 rounded-xl bg-red-50 text-red-700 border border-red-100 font-body text-sm">
              <AlertCircle size={15} className="shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="font-label text-[11px] font-medium text-ink-muted block mb-1.5">Current password</label>
              <div className="relative">
                <input
                  type={show ? "text" : "password"}
                  value={current}
                  onChange={(e) => setCurrent(e.target.value)}
                  required
                  autoComplete="current-password"
                  className="w-full px-4 py-2.5 pr-10 rounded-xl bg-white border border-border text-sm font-body text-ink focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition"
                />
                <div className="absolute right-0.5 top-1/2 -translate-y-1/2">{eyeBtn}</div>
              </div>
            </div>
            <div>
              <label className="font-label text-[11px] font-medium text-ink-muted block mb-1.5">New password</label>
              <div className="relative">
                <input
                  type={show ? "text" : "password"}
                  value={next}
                  onChange={(e) => setNext(e.target.value)}
                  required
                  autoComplete="new-password"
                  className="w-full px-4 py-2.5 pr-10 rounded-xl bg-white border border-border text-sm font-body text-ink focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition"
                />
                <div className="absolute right-0.5 top-1/2 -translate-y-1/2">{eyeBtn}</div>
              </div>
            </div>
            <div>
              <label className="font-label text-[11px] font-medium text-ink-muted block mb-1.5">Confirm new password</label>
              <div className="relative">
                <input
                  type={show ? "text" : "password"}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  autoComplete="new-password"
                  className="w-full px-4 py-2.5 pr-10 rounded-xl bg-white border border-border text-sm font-body text-ink focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition"
                />
                <div className="absolute right-0.5 top-1/2 -translate-y-1/2">{eyeBtn}</div>
              </div>
            </div>
          </div>

          <p className="font-body text-[11px] text-ink-muted pl-1">Minimum {MIN_LENGTH} characters. You stay signed in after changing it.</p>

          <div className="flex items-center justify-between border-t border-border-subtle pt-5 gap-3 flex-wrap">
            <div className="min-h-[20px]">
              {state === "saved" && (
                <span className="inline-flex items-center gap-1.5 text-emerald-600 font-body text-sm font-medium">
                  <CheckCircle2 size={15} /> Password updated
                </span>
              )}
            </div>
            <button
              type="submit"
              disabled={state === "saving" || state === "saved"}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl font-label text-sm font-semibold transition-all ${
                state === "saved"
                  ? "bg-emerald-100 text-emerald-700 cursor-default"
                  : "bg-primary text-white hover:bg-primary/90 disabled:opacity-60"
              }`}
            >
              {state === "saving" ? (
                <><Loader2 size={14} className="animate-spin" />Updating…</>
              ) : state === "saved" ? (
                <><CheckCircle2 size={14} />Updated</>
              ) : (
                <><Lock size={14} />Update Password</>
              )}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
