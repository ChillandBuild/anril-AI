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
 * Anril AI, the client connector (GET/POST /api/v1/claude...)
 * ------------------------------------------------------------------ */

/** What the consent screen is told about the app asking for access. */
export type ConsentKind =
  | { kind: "admin" }
  | { kind: "unknown" }
  | { kind: "client"; can_allow: false; why: string }
  | { kind: "client"; can_allow: true; business: string; daily_cap: number; connected: boolean };

export interface ClientConnection extends McpConnection {
  tenant_id: string;
}

export interface ClientClaudeStatus {
  available: boolean;
  mcp_url: string;
  oauth_client_id: string | null;
  connections: ClientConnection[];
  daily_cap: number;
  max_daily_cap: number;
  sent_today: number;
  recent: { id: string; created_at: string | null; action: string; tool: string | null; ok: boolean | null; arguments: Record<string, unknown> }[];
}

export type ClientRecent = ClientClaudeStatus["recent"][number];

/** What kind of thing a row in "What Claude did recently" was. */
export type ClientActionKind = "ask" | "edit" | "send" | "setting";

const ACTION_KINDS: Record<string, ClientActionKind> = {
  "claude.read": "ask",
  "claude.edit": "edit",
  "claude.send": "send",
};

const TOOL_PHRASES: Record<string, string> = {
  my_business: "Looked at your business summary",
  dashboard_summary: "Looked at the dashboard numbers",
  leads_overview: "Looked at the leads overview",
  lead_details: "Opened a lead and its chat",
  conversations: "Looked at the inbox",
  messaging_stats: "Looked at messaging numbers",
  calling_stats: "Looked at calling numbers",
  broadcasts: "Looked at broadcasts",
  templates: "Looked at templates",
  team: "Looked at the team",
  plan_and_usage: "Looked at the plan and usage",
  reply_options: "Checked what can be sent to a lead",
  add_lead_note: "Added a note to a lead",
};

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function shorten(value: string, max = 60): string {
  return value.length > max ? `${value.slice(0, max).trimEnd()}…` : value;
}

/**
 * One row of "What Claude did recently" in plain words. The arguments are the audit log's
 * cut-down copy, so a phone typed into a search already reads "phone ending 4471".
 */
export function describeClientAction(row: Pick<ClientRecent, "action" | "tool" | "ok" | "arguments">): {
  kind: ClientActionKind;
  text: string;
} {
  const args = row.arguments ?? {};
  if (row.action === "claude.connection.allow") return { kind: "setting", text: "Claude was connected" };
  if (row.action === "claude.connection.revoke") return { kind: "setting", text: "Claude was disconnected" };
  if (row.action === "claude.cap.change") return { kind: "setting", text: "The daily sending limit was changed" };

  const kind = ACTION_KINDS[row.action] ?? "ask";
  const tool = row.tool ?? "";
  let what: string;
  if (tool === "find_leads") {
    const filters = ["search", "segment", "source", "created_from", "created_to"]
      .map((key) => text(args[key]))
      .filter(Boolean);
    what = filters.length ? `Searched leads: ${shorten(filters.join(", "))}` : "Listed leads";
  } else if (tool === "assign_lead") {
    const member = text(args.team_member);
    what = member ? `Assigned a lead to ${shorten(member, 40)}` : "Unassigned a lead";
  } else if (tool === "send_reply") {
    const body = text(args.text);
    what = body ? `Reply to a lead: "${shorten(body)}"` : "Template message to a lead";
  } else if (tool === "preview_broadcast" || tool === "send_broadcast") {
    const template = text(args.template_name);
    const verb = tool === "send_broadcast" ? "Broadcast" : "Previewed a broadcast";
    what = template ? `${verb}: ${shorten(template, 40)}` : verb;
  } else {
    what = TOOL_PHRASES[tool] ?? (tool ? tool.replace(/_/g, " ") : "Used Anril AI");
  }
  return { kind, text: row.ok === false ? `Not done: ${what}` : what };
}

/** The daily limit the owner typed, as a whole number inside 0..max. Null when it is not a number. */
export function parseDailyCap(input: string, max: number): number | null {
  const trimmed = input.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value > max ? null : value;
}

/** How full today's sending limit is, for the meter (a limit of 0 reads as full). */
export function capUsage(sent: number, cap: number): { percent: number; left: number } {
  const left = Math.max(cap - sent, 0);
  if (cap <= 0) return { percent: 100, left: 0 };
  return { percent: Math.min(100, Math.round((sent / cap) * 1000) / 10), left };
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
