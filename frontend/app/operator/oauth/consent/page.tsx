"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient, setLoginScope } from "@/lib/supabase/client";
import { API_URL } from "@/lib/api";
import { operatorFetch } from "@/lib/operator";
import { ConsentView, type Busy, type Connector, type Phase } from "@/components/claude-consent-views";
import {
  consentLoginHref,
  isSafeRedirectUrl,
  mapAuthorizationDetails,
  type ClaudeAccessAllowResponse,
  type ClaudeAccessResponse,
  type ClientClaudeStatus,
  type ConsentKind,
  type OperatorMe,
} from "@/lib/claude-access";

const OPERATOR_BASE = "/api/v1/operator";
// Anril AI, the connector a client's owner adds to their own Claude app.
const CLIENT_BASE = "/api/v1/claude";

type WhichApp = "admin" | "client" | "unknown" | null;

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

/**
 * Which connector is this request for? Asked BEFORE any login is used: Supabase stamps a request
 * with whichever login opens it first, and this page can hold two (the operator's and a client
 * owner's). Admin app -> operator login; client app -> dashboard login. null = could not tell.
 */
async function pickLogin(authorizationId: string): Promise<WhichApp> {
  try {
    const res = await fetch(`${API_URL}${CLIENT_BASE}/consent-app?authorization_id=${encodeURIComponent(authorizationId)}`);
    if (res.status === 404) return null; // a backend without the client connector: the admin app is the only one
    if (!res.ok) throw new Error(`consent-app ${res.status}`);
    const { kind } = (await res.json()) as { kind: "admin" | "client" | "unknown" };
    return kind;
  } catch {
    throw new Error("Could not check which Claude connector this is. Reload the page to try again.");
  }
}

/**
 * Our own switch for this login. With a known connector only that connector's switch is read;
 * with none, the admin one first, then the client's. Never throws: a failure means "off".
 */
async function ourSwitch(which: WhichApp): Promise<{ active: boolean; admin: boolean; clientId: string | null }> {
  let admin = false;
  if (which !== "client") {
    try {
      const access = await operatorFetch<ClaudeAccessResponse>(`${OPERATOR_BASE}/claude-access`);
      admin = true;
      if (access.connection?.status === "active") return { active: true, admin, clientId: null };
    } catch {
      // not a system admin: fall through to the client check
    }
    if (which === "admin") return { active: false, admin, clientId: null };
  }
  try {
    const mine = await operatorFetch<ClientClaudeStatus>(CLIENT_BASE);
    return { active: mine.connections.some((c) => c.status === "active"), admin, clientId: mine.oauth_client_id };
  } catch {
    return { active: false, admin, clientId: null };
  }
}

type MeResult = { ok: true; me: OperatorMe } | { ok: false; status?: number; error: unknown };

/** Never rejects, so it can start early and be read later without an unhandled rejection. */
async function fetchMe(): Promise<MeResult> {
  try {
    return { ok: true, me: await operatorFetch<OperatorMe>(`${OPERATOR_BASE}/me`) };
  } catch (e) {
    return { ok: false, status: (e as { status?: number }).status, error: e };
  }
}

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
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
      const which = await pickLogin(authorizationId);
      setLoginScope(which === "client" ? "dashboard" : which === "admin" ? "operator" : null);
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        // Signed out, so we cannot yet tell whether this is the admin app or a client's.
        setPhase({ name: "signed_out" });
        return;
      }
      const email = session.user.email ?? "";

      // These are independent reads, so they run together instead of one after another. The switch
      // and the admin check are only used on the paths that need them.
      const [{ data, error }, mine, adminCheck] = await Promise.all([
        supabase.auth.oauth.getAuthorizationDetails(authorizationId),
        ourSwitch(which),
        which === "admin" ? fetchMe() : Promise.resolve(null),
      ]);
      if (error || !data) throw new Error(error?.message || "Could not load this request");
      const details = mapAuthorizationDetails(data);

      if (details.kind === "already_consented") {
        // Supabase already holds this person's approval and only hands back a redirect. Never
        // follow it on our own: a link someone else started would sign THEIR Claude in as this
        // person with no click. Offer it only while our own switch is on, and make them press
        // Continue. If the switch is off, stop: the redirect carries no client id to turn it on.
        const connector: Connector = which === "admin" || (which !== "client" && mine.admin) ? "admin" : "client";
        if (isSafeRedirectUrl(details.redirectUrl) && mine.active) {
          let business: string | undefined;
          if (connector === "client" && mine.clientId) {
            try {
              const k = await consentKind(mine.clientId);
              if (k.kind === "client" && k.can_allow) business = k.business;
            } catch {
              // the card still works without the business name
            }
          }
          setPhase({
            name: "continue", redirectUrl: details.redirectUrl, host: new URL(details.redirectUrl).host,
            connector, email, business,
          });
          return;
        }
        setPhase({ name: "already_consented", admin: connector === "admin" });
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
      const result = adminCheck ?? (await fetchMe());
      if (!result.ok) {
        if (result.status === 401) {
          router.replace(consentLoginHref(authorizationId));
          return;
        }
        if (result.status === 403) {
          setPhase({ name: "not_admin", email });
          return;
        }
        throw result.error;
      }
      if (!result.me.is_system_admin) {
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
    return () => setLoginScope(null); // leaving this page: back to going by the address
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

  async function handleCancel() {
    // Reconnect card: nothing is pending at Supabase, so closing the offer is all there is to do.
    if (phase.name === "continue") {
      setPhase({ name: "cancelled" });
      return;
    }
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

  function handleContinue() {
    if (phase.name !== "continue") return;
    const { redirectUrl } = phase;
    setPhase({ name: "done" });
    window.location.assign(redirectUrl);
  }

  return (
    <ConsentView
      phase={phase}
      busy={busy}
      actionError={actionError}
      authorizationId={authorizationId}
      onAllow={handleAllow}
      onCancel={handleCancel}
      onContinue={handleContinue}
      onRetry={load}
    />
  );
}
