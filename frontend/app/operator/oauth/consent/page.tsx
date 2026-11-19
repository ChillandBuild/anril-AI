"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { operatorFetch } from "@/lib/operator";
import { AnrilLogo } from "@/components/logo";
import {
  consentLoginHref,
  isSafeRedirectUrl,
  mapAuthorizationDetails,
  type ClaudeAccessAllowResponse,
  type ClaudeAccessResponse,
  type ConsentDetails,
  type OperatorMe,
} from "@/lib/claude-access";

type Phase =
  | { name: "loading" }
  | { name: "missing" }
  | { name: "not_admin"; email: string }
  | { name: "ready"; details: Extract<ConsentDetails, { kind: "pending" }>; email: string }
  | { name: "already_consented" }
  | { name: "cancelled" }
  | { name: "done" }
  | { name: "error"; message: string };

type Busy = "allow" | "deny" | null;

const OPERATOR_BASE = "/api/v1/operator";

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

function Shell({ children }: { children: React.ReactNode }) {
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
        <div className="bg-white rounded-card shadow-card border border-border p-8">{children}</div>
      </div>
    </div>
  );
}

export default function OAuthConsentPage({
  searchParams,
}: {
  searchParams: { authorization_id?: string };
}) {
  const router = useRouter();
  const authorizationId = searchParams.authorization_id?.trim() || "";
  const [phase, setPhase] = useState<Phase>({ name: "loading" });
  const [busy, setBusy] = useState<Busy>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!authorizationId) {
      setPhase({ name: "missing" });
      return;
    }
    setPhase({ name: "loading" });
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        router.replace(consentLoginHref(authorizationId));
        return;
      }
      const email = session.user.email ?? "";

      let me: OperatorMe;
      try {
        me = await operatorFetch<OperatorMe>(`${OPERATOR_BASE}/me`);
      } catch (e) {
        const status = (e as { status?: number }).status;
        if (status === 401) {
          router.replace(consentLoginHref(authorizationId));
          return;
        }
        if (status === 403) {
          setPhase({ name: "not_admin", email });
          return;
        }
        throw e;
      }
      if (!me.is_system_admin) {
        setPhase({ name: "not_admin", email });
        return;
      }

      const { data, error } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId);
      if (error || !data) throw new Error(error?.message || "Could not load this request");
      const details = mapAuthorizationDetails(data);
      if (details.kind === "already_consented") {
        // Supabase already holds this admin's approval and only hands back a redirect. Follow
        // it only while our own switch is on (Claude is just signing in again). If the switch
        // is off, stop here: the redirect carries no client id we could use to turn it back on.
        const access = await operatorFetch<ClaudeAccessResponse>(`${OPERATOR_BASE}/claude-access`);
        if (access.connection?.status === "active" && isSafeRedirectUrl(details.redirectUrl)) {
          setPhase({ name: "done" });
          window.location.assign(details.redirectUrl);
          return;
        }
        setPhase({ name: "already_consented" });
        return;
      }
      setPhase({ name: "ready", details, email: details.email || email });
    } catch (e) {
      setPhase({ name: "error", message: errorMessage(e, "Could not load this request") });
    }
  }, [authorizationId, router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAllow() {
    if (phase.name !== "ready" || busy) return;
    const { details } = phase;
    setBusy("allow");
    setActionError(null);
    try {
      // 1. Switch our own side on first. If this fails, nothing is approved at Supabase.
      await operatorFetch<ClaudeAccessAllowResponse>(`${OPERATOR_BASE}/claude-access/allow`, {
        method: "POST",
        body: JSON.stringify({ client_id: details.clientId, label: details.clientName }),
      });
      // 2. Then approve at Supabase and send the browser back to the client.
      const supabase = createClient();
      const { data, error } = await supabase.auth.oauth.approveAuthorization(details.authorizationId, {
        skipBrowserRedirect: true,
      });
      if (error || !data) throw new Error(error?.message || "Supabase did not approve the request");
      if (!isSafeRedirectUrl(data.redirect_url)) throw new Error("Supabase returned an unusable redirect address");
      setPhase({ name: "done" });
      window.location.assign(data.redirect_url);
    } catch (e) {
      setActionError(errorMessage(e, "Could not allow access"));
      setBusy(null);
    }
  }

  async function handleDeny() {
    if (phase.name !== "ready" || busy) return;
    setBusy("deny");
    setActionError(null);
    try {
      const supabase = createClient();
      const { data, error } = await supabase.auth.oauth.denyAuthorization(phase.details.authorizationId, {
        skipBrowserRedirect: true,
      });
      if (error || !data) throw new Error(error?.message || "Supabase did not cancel the request");
      setPhase({ name: "cancelled" });
      if (isSafeRedirectUrl(data.redirect_url)) window.location.assign(data.redirect_url);
    } catch (e) {
      setActionError(errorMessage(e, "Could not cancel"));
      setBusy(null);
    }
  }

  if (phase.name === "loading") {
    return (
      <Shell>
        <div className="animate-pulse space-y-3" aria-busy="true" aria-label="Loading">
          <div className="h-5 bg-surface-mid rounded w-4/5" />
          <div className="h-3 bg-surface-mid rounded w-3/5" />
          <div className="h-3 bg-surface-mid rounded w-full mt-6" />
          <div className="h-3 bg-surface-mid rounded w-full" />
          <div className="h-3 bg-surface-mid rounded w-5/6" />
          <div className="flex gap-3 pt-4">
            <div className="h-10 bg-surface-mid rounded-xl flex-1" />
            <div className="h-10 bg-surface-mid rounded-xl flex-1" />
          </div>
        </div>
      </Shell>
    );
  }

  if (phase.name === "missing") {
    return (
      <Shell>
        <h1 className="text-base font-bold text-ink font-display">Nothing to approve</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">
          This page opens from the Claude app when you connect it. Start from the Claude app, or go to{" "}
          <Link href="/operator/claude-access" className="text-primary hover:underline">
            Operator Console → Claude Access
          </Link>
          .
        </p>
      </Shell>
    );
  }

  if (phase.name === "not_admin") {
    return (
      <Shell>
        <h1 className="text-base font-bold text-ink font-display">Only an Anril system admin can allow this</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">
          {phase.email ? `You are signed in as ${phase.email}, which is not a system admin.` : "You are not signed in as a system admin."}{" "}
          Ask a system admin to connect Claude.
        </p>
      </Shell>
    );
  }

  if (phase.name === "already_consented") {
    return (
      <Shell>
        <h1 className="text-base font-bold text-ink font-display">Claude is already approved</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">
          Open{" "}
          <Link href="/operator/claude-access" className="text-primary hover:underline">
            Operator Console → Claude Access
          </Link>
          . The connection is switched off there. Press Reset sign-in on that page, then connect again from the
          Claude app to see the Allow screen.
        </p>
      </Shell>
    );
  }

  if (phase.name === "cancelled") {
    return (
      <Shell>
        <h1 className="text-base font-bold text-ink font-display">Cancelled</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">Nothing was connected.</p>
      </Shell>
    );
  }

  if (phase.name === "done") {
    return (
      <Shell>
        <p role="status" className="text-sm font-semibold text-success text-center font-body">
          Connected. You can go back to Claude.
        </p>
      </Shell>
    );
  }

  if (phase.name === "error") {
    return (
      <Shell>
        <div role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-body">
          {phase.message}
        </div>
        <button
          type="button"
          onClick={load}
          className="mt-4 w-full border border-border rounded-xl py-2 text-sm font-medium text-ink-secondary hover:bg-surface-mid transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 font-display"
        >
          Try again
        </button>
      </Shell>
    );
  }

  const { details, email } = phase;
  return (
    <Shell>
      <h1 className="text-base font-bold text-ink font-display">{details.clientName} wants to read Anril Operator data</h1>
      <p className="text-xs text-ink-muted mt-1 font-body">Signed in as {email} · system admin</p>
      <ul className="list-disc pl-[18px] my-4 space-y-1.5 text-sm text-ink-secondary font-body">
        <li>Read every client&apos;s leads, phone numbers and chats</li>
        <li>Read health, usage, AI spend and audit log</li>
        <li className="text-danger">Cannot send, change or delete anything</li>
      </ul>
      {actionError && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-body">
          {actionError}
        </div>
      )}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={handleDeny}
          disabled={busy !== null}
          className="flex-1 border border-border rounded-xl py-2.5 text-sm font-medium text-ink-secondary hover:bg-surface-mid transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 font-display"
        >
          {busy === "deny" ? "Cancelling..." : "Cancel"}
        </button>
        <button
          type="button"
          onClick={handleAllow}
          disabled={busy !== null}
          className="flex-1 bg-primary hover:bg-primary-dark text-white font-medium py-2.5 rounded-xl text-sm transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 font-display"
        >
          {busy === "allow" ? "Allowing..." : "Allow"}
        </button>
      </div>
      <p className="text-xs text-ink-muted mt-4 font-body">
        You can switch this off any time in Operator Console → Claude Access.
      </p>
    </Shell>
  );
}
