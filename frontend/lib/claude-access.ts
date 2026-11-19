// Pure helpers and response types for "Claude Access" (the read-only connection that lets the
// owner's Claude app read Operator Console data). No React, no network: easy to test.

import type { OAuthAuthorizationDetails, OAuthRedirect } from "@supabase/supabase-js";

/* ------------------------------------------------------------------ *
 * Backend response types (GET/POST /api/v1/operator/claude-access...)
 * ------------------------------------------------------------------ */

export interface McpConnection {
  id: string;
  user_id: string;
  client_id: string;
  label: string | null;
  status: "active" | "revoked";
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface McpRecentCall {
  id: string;
  created_at: string | null;
  tool: string | null;
  tenant_id: string | null;
  tenant_name: string | null;
  arguments: Record<string, unknown> | null;
}

export interface ClaudeAccessResponse {
  enabled: boolean;
  mcp_url: string;
  connection: McpConnection | null;
  calls_today: number;
  top_tool_week: string | null;
  top_client_week: string | null;
  recent_calls: McpRecentCall[];
}

export interface ClaudeAccessAllowResponse {
  connection: McpConnection;
}

export interface ClaudeAccessRevokeResponse {
  revoked: number;
  connection: McpConnection | null;
}

export interface OperatorMe {
  is_system_admin: boolean;
}

/* ------------------------------------------------------------------ *
 * Login "come back here" path
 * ------------------------------------------------------------------ */

const CONSENT_PREFIX = "/operator/oauth/consent?";

/**
 * The `next` value the operator login page may honour. Only the consent screen (with its
 * query string) is allowed: anything else returns null, so the login page can never be used
 * as an open redirect.
 */
export function safeOperatorNext(next: string | null | undefined): string | null {
  if (typeof next !== "string" || next.length > 2000) return null;
  if (!next.startsWith(CONSENT_PREFIX)) return null;
  // Same-origin path only: no backslashes, whitespace or control characters anywhere.
  if (/[\\\s\u0000-\u001f\u007f]/.test(next)) return null;
  return next;
}

/** Where to send a signed-out visitor so they land back on the consent screen after login. */
export function consentLoginHref(authorizationId: string): string {
  const back = `${CONSENT_PREFIX}authorization_id=${encodeURIComponent(authorizationId)}`;
  return `/operator/login?next=${encodeURIComponent(back)}`;
}

/* ------------------------------------------------------------------ *
 * Mapping Supabase's getAuthorizationDetails() answer
 * ------------------------------------------------------------------ */

export type ConsentDetails =
  | {
      kind: "pending";
      authorizationId: string;
      clientId: string;
      clientName: string;
      email: string;
    }
  | {
      // The user already consented at Supabase. The answer carries only a redirect URL: no
      // client id, so we cannot re-register the connection on our side from here.
      kind: "already_consented";
      redirectUrl: string;
    };

export function mapAuthorizationDetails(data: OAuthAuthorizationDetails | OAuthRedirect): ConsentDetails {
  if ("authorization_id" in data) {
    return {
      kind: "pending",
      authorizationId: data.authorization_id,
      clientId: data.client.id,
      clientName: data.client.name?.trim() || "Claude",
      email: data.user.email,
    };
  }
  return { kind: "already_consented", redirectUrl: data.redirect_url };
}

/** Claude's own sites. The sign-in always returns to https://claude.ai/api/mcp/auth_callback. */
const CLAUDE_HOSTS = ["claude.ai", "claude.com"];

/**
 * A redirect we are willing to send the browser to after consent: an https address on one of
 * Claude's own sites, nothing else. An allowlist on purpose: the address comes back from
 * Supabase, and a look-alike app must not be able to steer the admin's browser elsewhere.
 */
export function isSafeRedirectUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return false;
    return CLAUDE_HOSTS.some((host) => parsed.hostname === host || parsed.hostname.endsWith(`.${host}`));
  } catch {
    return false;
  }
}

/* ------------------------------------------------------------------ *
 * Display helpers
 * ------------------------------------------------------------------ */

/** "lead Ravi K · page 1" style summary of a tool call's arguments. */
export function formatCallArguments(args: Record<string, unknown> | null | undefined): string {
  if (!args) return "";
  return Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k} ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

export function formatAllowedDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
