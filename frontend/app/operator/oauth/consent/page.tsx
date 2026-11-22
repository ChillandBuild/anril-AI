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
  type ClientClaudeStatus,
  type ConsentDetails,
  type ConsentKind,
  type OperatorMe,
} from "@/lib/claude-access";

type Phase =
  | { name: "loading" }
  | { name: "missing" }
  | { name: "signed_out" }
  | { name: "not_admin"; email: string }
  | { name: "ready"; details: Extract<ConsentDetails, { kind: "pending" }>; email: string }
  | { name: "client_ready"; details: Extract<ConsentDetails, { kind: "pending" }>; email: string; business: string; dailyCap: number }
  | { name: "client_refused"; why: string }
  | { name: "continue"; redirectUrl: string; host: string }
  | { name: "already_consented"; admin: boolean }
  | { name: "cancelled" }
  | { name: "done" }
  | { name: "error"; message: string };

type Busy = "allow" | "deny" | null;

const OPERATOR_BASE = "/api/v1/operator";
// Anril AI, the connector a client's owner adds to their own Claude app.
const CLIENT_BASE = "/api/v1/claude";

/** Which connector is this app? A backend without the client connector yet (404) means the
 *  only connector that exists is the admin one. */
async function consentKind(clientId: string): Promise<ConsentKind> {
  try {
    return await operatorFetch<ConsentKind>(`${CLIENT_BASE}/consent?client_id=${encodeURIComponent(clientId)}`);
  } catch (e) {
    if ((e as { status?: number }).status === 404) return { kind: "admin" };
    throw e;
  }
}

/** Our own switch for this login: the admin connection for a system admin, else their client's. */
async function ourSwitch(): Promise<{ active: boolean; admin: boolean }> {
  let admin = false;
  try {
    const access = await operatorFetch<ClaudeAccessResponse>(`${OPERATOR_BASE}/claude-access`);
    admin = true;
    if (access.connection?.status === "active") return { active: true, admin };
  } catch {
    // not a system admin: fall through to the client check
  }
  try {
    const mine = await operatorFetch<ClientClaudeStatus>(CLIENT_BASE);
    return { active: mine.connections.some((c) => c.status === "active"), admin };
  } catch {
    return { active: false, admin };
  }
}

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

function Shell({ children, label = "Operator Console" }: { children: React.ReactNode; label?: string }) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-2">
            <AnrilLogo className="h-7 w-auto text-ink" />
          </div>
          <p className="text-xs text-ink-muted mt-1.5 uppercase tracking-widest font-semibold font-label">
            {label}
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
        // Signed out, so we cannot yet tell whether this is the admin app or a client's.
        setPhase({ name: "signed_out" });
        return;
      }
      const email = session.user.email ?? "";

      const { data, error } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId);
      if (error || !data) throw new Error(error?.message || "Could not load this request");
      const details = mapAuthorizationDetails(data);
      if (details.kind === "already_consented") {
        // Supabase already holds this person's approval and only hands back a redirect. Never
        // follow it on our own: a link someone else started would sign THEIR Claude in as this
        // person with no click. Offer it only while our own switch is on, and make them press
        // Continue. If the switch is off, stop: the redirect carries no client id to turn it on.
        const mine = await ourSwitch();
        if (isSafeRedirectUrl(details.redirectUrl) && mine.active) {
          setPhase({ name: "continue", redirectUrl: details.redirectUrl, host: new URL(details.redirectUrl).host });
          return;
        }
        setPhase({ name: "already_consented", admin: mine.admin });
        return;
      }

      const kind = await consentKind(details.clientId);
      if (kind.kind === "unknown") {
        setPhase({ name: "error", message: "This app is not an approved Anril connector." });
        return;
      }
      if (kind.kind === "client") {
        if (!kind.can_allow) {
          setPhase({ name: "client_refused", why: kind.why });
          return;
        }
        setPhase({
          name: "client_ready", details, email: details.email || email,
          business: kind.business, dailyCap: kind.daily_cap,
        });
        return;
      }

      // The admin app: only an Anril system admin may allow it.
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
      setPhase({ name: "ready", details, email: details.email || email });
    } catch (e) {
      setPhase({ name: "error", message: errorMessage(e, "Could not load this request") });
    }
  }, [authorizationId, router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAllow() {
    if ((phase.name !== "ready" && phase.name !== "client_ready") || busy) return;
    const { details } = phase;
    const allowPath = phase.name === "client_ready" ? `${CLIENT_BASE}/allow` : `${OPERATOR_BASE}/claude-access/allow`;
    setBusy("allow");
    setActionError(null);
    try {
      // 1. Switch our own side on first. If this fails, nothing is approved at Supabase.
      await operatorFetch<ClaudeAccessAllowResponse>(allowPath, {
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
    if ((phase.name !== "ready" && phase.name !== "client_ready") || busy) return;
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
          <Link href="/operator/mcp" className="text-primary hover:underline">
            Operator Console → MCP
          </Link>
          .
        </p>
      </Shell>
    );
  }

  if (phase.name === "signed_out") {
    return (
      <Shell label="Connect to Claude">
        <h1 className="text-base font-bold text-ink font-display">Sign in to Anril first</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">
          Sign in to Anril in a new tab, then come back here and continue.
        </p>
        <a
          href="/login"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 block w-full text-center bg-primary hover:bg-primary-dark text-white font-medium py-2.5 rounded-xl text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 font-display"
        >
          Sign in to Anril
        </a>
        <button
          type="button"
          onClick={load}
          className="mt-3 w-full border border-border rounded-xl py-2.5 text-sm font-medium text-ink-secondary hover:bg-surface-mid transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 font-display"
        >
          I have signed in, continue
        </button>
        <p className="text-xs text-ink-muted mt-4 font-body">
          Anril operator?{" "}
          <Link href={consentLoginHref(authorizationId)} className="text-primary hover:underline">
            Sign in to the Operator Console
          </Link>
          .
        </p>
      </Shell>
    );
  }

  if (phase.name === "client_refused") {
    return (
      <Shell label="Anril AI">
        <h1 className="text-base font-bold text-ink font-display">This account cannot connect Claude</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">{phase.why}</p>
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

  if (phase.name === "continue") {
    const { redirectUrl } = phase;
    return (
      <Shell label="Connect to Claude">
        <h1 className="text-base font-bold text-ink font-display">Sign Claude in to Anril again?</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">
          You allowed Claude before, and it is asking to sign in again. Continue only if you started this yourself,
          just now, in your own Claude app.
        </p>
        <p className="text-sm text-danger mt-2 font-body">
          If someone sent you this link, close this page. Continuing would connect their Claude to your account.
        </p>
        <button
          type="button"
          onClick={() => {
            setPhase({ name: "done" });
            window.location.assign(redirectUrl);
          }}
          className="mt-4 w-full bg-primary hover:bg-primary-dark text-white font-medium py-2.5 rounded-xl text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 font-display"
        >
          Continue to Claude
        </button>
        <p className="text-xs text-ink-muted mt-3 text-center font-body">You will go back to {phase.host}</p>
      </Shell>
    );
  }

  if (phase.name === "already_consented" && !phase.admin) {
    return (
      <Shell label="Anril AI">
        <h1 className="text-base font-bold text-ink font-display">Claude is switched off for your account</h1>
        <p className="text-sm text-ink-secondary mt-2 font-body">
          You allowed Claude before and then disconnected it. To connect again, open Anril → Settings → Anril AI
          for Claude, press Clear old approval, then connect from the Claude app. If that does not work, ask your
          Anril account manager.
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
          <Link href="/operator/mcp" className="text-primary hover:underline">
            Operator Console → MCP
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

  if (phase.name === "client_ready") {
    return (
      <Shell label="Anril AI">
        <h1 className="text-base font-bold text-ink font-display">
          {phase.details.clientName} wants to use your Anril account
        </h1>
        <p className="text-xs text-ink-muted mt-1 font-body">
          Signed in as {phase.email} · owner of {phase.business}
        </p>
        <ul className="list-disc pl-[18px] my-4 space-y-1.5 text-sm text-ink-secondary font-body">
          <li>Read your leads, phone numbers, chats, calls and broadcasts</li>
          <li>Assign leads and add notes to them</li>
          <li className="text-danger">
            Send WhatsApp messages and template broadcasts to your customers, up to {phase.dailyCap.toLocaleString("en-IN")} a day
          </li>
        </ul>
        <p className="text-xs text-ink-muted mb-4 font-body">
          What Claude reads here (lead names, phone numbers and chats) is sent to Claude, which is run by Anthropic.
          It cannot touch payments, your team, settings or any other business.
        </p>
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
          You can switch this off, or change the daily limit, any time in Anril → Settings.
        </p>
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
        You can switch this off any time in Operator Console → MCP.
      </p>
    </Shell>
  );
}
