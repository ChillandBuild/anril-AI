// Pure helpers and response types for the per-client MCP switches on /operator/mcp.
// No React, no network: easy to test.

import { formatAllowedDate } from "./claude-access";

/* GET /api/v1/operator/mcp/clients */

export interface McpClientRow {
  tenant_id: string;
  name: string;
  status: string;
  on: boolean;
  connected: boolean;
  connected_at: string | null;
  last_used_at: string | null;
  sent_today: number;
  daily_cap: number;
}

export interface McpClientsResponse {
  enabled: boolean;
  mcp_url: string;
  default_daily_cap: number;
  clients: McpClientRow[];
}

/* PUT /api/v1/operator/mcp/clients/{tenant_id} */

export interface McpClientSwitchResponse {
  tenant_id: string;
  on: boolean;
}

/** The Connection column: Off / Not connected yet / Connected · Allowed <date>. */
export function connectionLabel(row: Pick<McpClientRow, "on" | "connected" | "connected_at">): string {
  if (!row.on) return "Off";
  if (!row.connected) return "Not connected yet";
  return row.connected_at ? `Connected · allowed ${formatAllowedDate(row.connected_at)}` : "Connected";
}

/** The Sent today column: "12 / 500". A dash when the client is off and nothing was sent. */
export function sentLabel(row: Pick<McpClientRow, "on" | "sent_today" | "daily_cap">): string {
  if (!row.on && row.sent_today === 0) return "—";
  return `${row.sent_today} / ${row.daily_cap}`;
}

/** A client's status tag: nothing for active clients, the status text for any other. */
export function statusTag(status: string): string | null {
  const s = status.trim();
  return !s || s.toLowerCase() === "active" ? null : s;
}

/** The list with one client's switch changed (other rows untouched). */
export function withSwitch(clients: McpClientRow[], tenantId: string, on: boolean): McpClientRow[] {
  return clients.map((c) => (c.tenant_id === tenantId ? { ...c, on } : c));
}
