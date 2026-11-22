"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Copy, Check, RefreshCw } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { operatorFetch, relTime } from "@/lib/operator";
import { ConfirmModal } from "@/components/ConfirmModal";
import {
  formatAllowedDate,
  formatCallArguments,
  type ClaudeAccessResponse,
  type ClaudeAccessRevokeResponse,
} from "@/lib/claude-access";
import {
  connectionLabel,
  sentLabel,
  statusTag,
  withSwitch,
  type McpClientRow,
  type McpClientSwitchResponse,
  type McpClientsResponse,
} from "@/lib/mcp-clients";

const BASE = "/api/v1/operator/claude-access";
const CLIENTS = "/api/v1/operator/mcp/clients";
const TH = "px-5 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wider";
const FOCUS = "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

function Skeleton() {
  return (
    <div className="animate-pulse" aria-busy="true" aria-label="Loading">
      <div className="bg-white rounded-card border border-border shadow-sm overflow-hidden">
        <div className="flex items-center gap-4 px-6 py-5">
          <div className="flex-1 space-y-2">
            <div className="h-4 bg-surface-mid rounded w-40" />
            <div className="h-3 bg-surface-mid rounded w-72 max-w-full" />
          </div>
          <div className="h-9 bg-surface-mid rounded-xl w-28" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 border-t border-border">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="px-6 py-4 space-y-2">
              <div className="h-5 bg-surface-mid rounded w-20" />
              <div className="h-3 bg-surface-mid rounded w-32" />
            </div>
          ))}
        </div>
      </div>
      <div className="bg-white rounded-card border border-border shadow-sm mt-6 h-40" />
    </div>
  );
}

function ClientsSkeleton() {
  return (
    <div className="animate-pulse bg-white rounded-card border border-border shadow-sm overflow-hidden" aria-busy="true" aria-label="Loading clients">
      <div className="h-10 bg-surface-mid" />
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex items-center gap-6 px-5 py-4 border-t border-border-subtle">
          <div className="h-4 bg-surface-mid rounded w-40" />
          <div className="h-5 bg-surface-mid rounded-full w-9" />
          <div className="h-3 bg-surface-mid rounded w-32" />
        </div>
      ))}
    </div>
  );
}

function SectionHead({ id, title, hint }: { id: string; title: string; hint?: string }) {
  return (
    <div className="mb-3">
      <h2 id={id} className="text-sm font-bold text-ink">{title}</h2>
      {hint && <p className="text-xs text-ink-muted mt-0.5">{hint}</p>}
    </div>
  );
}

function ClientSwitch({
  name,
  on,
  busy,
  onToggle,
}: {
  name: string;
  on: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={`MCP for ${name}`}
      disabled={busy}
      onClick={onToggle}
      className={`relative w-9 h-5 rounded-full transition-colors shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-wait ${
        on ? "bg-primary" : "bg-slate-300"
      }`}
    >
      <span
        aria-hidden="true"
        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${on ? "translate-x-4" : ""}`}
      />
    </button>
  );
}

export default function McpPage() {
  const [data, setData] = useState<ClaudeAccessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Client connectors: loaded on their own, so one failing never blanks the other.
  const [clientsData, setClientsData] = useState<McpClientsResponse | null>(null);
  const [clientsLoading, setClientsLoading] = useState(true);
  const [clientsError, setClientsError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [offTarget, setOffTarget] = useState<McpClientRow | null>(null);

  const loadAdmin = useCallback(async () => {
    setLoading(true);
    try {
      setData(await operatorFetch<ClaudeAccessResponse>(BASE));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadClients = useCallback(async () => {
    setClientsLoading(true);
    try {
      setClientsData(await operatorFetch<McpClientsResponse>(CLIENTS));
      setClientsError(null);
      setRowErrors({});
    } catch (e) {
      setClientsError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setClientsLoading(false);
    }
  }, []);

  const load = useCallback(() => {
    loadAdmin();
    loadClients();
  }, [loadAdmin, loadClients]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => () => { if (copyTimer.current) clearTimeout(copyTimer.current); }, []);

  // For a connection that is already off: remove Claude's saved approval at Supabase again. Needed
  // when that step failed during Switch off, because the Allow screen only shows without it.
  async function resetSignIn() {
    const clientId = data?.connection?.client_id;
    if (!clientId) return;
    setSwitching(true);
    setSwitchError(null);
    setWarning(null);
    try {
      const { error: grantError } = await createClient().auth.oauth.revokeGrant({ clientId });
      if (grantError) throw new Error(grantError.message);
      setWarning("Sign-in reset. Connect again from the Claude app to see the Allow screen.");
    } catch (e) {
      setSwitchError(e instanceof Error && e.message ? e.message : "Could not reset the sign-in");
    } finally {
      setSwitching(false);
    }
  }

  async function switchOff() {
    const clientId = data?.connection?.client_id;
    setSwitching(true);
    setSwitchError(null);
    setWarning(null);
    try {
      const res = await operatorFetch<ClaudeAccessRevokeResponse>(`${BASE}/revoke`, { method: "POST" });
      setData((prev) => (prev ? { ...prev, connection: res.connection } : prev));
      setConfirmOpen(false);
      // Also kill Claude's sign-in at Supabase so its refresh token stops working.
      if (clientId) {
        try {
          const { error: grantError } = await createClient().auth.oauth.revokeGrant({ clientId });
          if (grantError) throw new Error(grantError.message);
        } catch (e) {
          const why = e instanceof Error && e.message ? ` (${e.message})` : "";
          setWarning(
            `Switched off here, but Anril could not also remove Claude's sign-in at Supabase${why}. ` +
              "Tool calls are still refused. Try Switch off again if Claude later asks to reconnect without a prompt.",
          );
        }
      }
      loadAdmin();
    } catch (e) {
      setSwitchError(e instanceof Error ? e.message : "Could not switch off");
      setConfirmOpen(false);
    } finally {
      setSwitching(false);
    }
  }

  // Optimistic: the row flips at once, and flips back with an inline error if the request fails.
  async function setClientOn(row: McpClientRow, on: boolean) {
    const id = row.tenant_id;
    setPending((p) => ({ ...p, [id]: true }));
    setRowErrors((errs) => {
      const rest = { ...errs };
      delete rest[id];
      return rest;
    });
    setClientsData((prev) => (prev ? { ...prev, clients: withSwitch(prev.clients, id, on) } : prev));
    try {
      await operatorFetch<McpClientSwitchResponse>(`${CLIENTS}/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify({ on }),
      });
    } catch (e) {
      setClientsData((prev) => (prev ? { ...prev, clients: withSwitch(prev.clients, id, !on) } : prev));
      const why = e instanceof Error && e.message ? e.message : "Request failed";
      setRowErrors((errs) => ({
        ...errs,
        [id]: `Could not switch ${on ? "on" : "off"} MCP for ${row.name}: ${why}`,
      }));
    } finally {
      setPending((p) => {
        const rest = { ...p };
        delete rest[id];
        return rest;
      });
    }
  }

  function toggleClient(row: McpClientRow) {
    if (row.on) setOffTarget(row);
    else setClientOn(row, true);
  }

  async function confirmClientOff() {
    const target = offTarget;
    if (!target) return;
    setOffTarget(null);
    await setClientOn(target, false);
  }

  async function copyUrl() {
    if (!data?.mcp_url) return;
    try {
      await navigator.clipboard.writeText(data.mcp_url);
      setCopied(true);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  const connection = data?.connection ?? null;
  const active = connection?.status === "active";
  const calls = (data?.recent_calls ?? []).slice(0, 3);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-8 py-8">
      <div className="flex items-end justify-between gap-4 flex-wrap mb-6">
        <div>
          <h1 className="text-2xl font-bold text-ink">MCP</h1>
          <p className="text-sm text-ink-muted mt-1">
            Lets AI apps like Claude work with Anril. Your own connector on top, one switch per client below.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className={`flex items-center gap-1.5 px-3 py-2 text-sm text-ink-secondary hover:text-ink border border-border rounded-xl hover:bg-surface-mid transition-colors ${FOCUS}`}
        >
          <RefreshCw size={14} className={loading || clientsLoading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <section aria-labelledby="admin-connector" className="mb-10">
      <SectionHead id="admin-connector" title="Admin connector" hint="Read-only. One connection." />

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger flex items-center justify-between gap-3 flex-wrap">
          <span>{error}</span>
          <button
            type="button"
            onClick={loadAdmin}
            className={`px-3 py-1 text-xs font-semibold border border-danger/30 rounded-lg hover:bg-danger/5 transition-colors ${FOCUS}`}
          >
            Retry
          </button>
        </div>
      )}
      {switchError && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger">
          {switchError}
        </div>
      )}
      {warning && (
        <div role="status" className="mb-4 p-3 bg-warning/10 border border-warning/30 rounded-xl text-sm text-ink-secondary">
          {warning}
        </div>
      )}

      {loading && !data ? (
        <Skeleton />
      ) : data ? (
        <>
          {!data.enabled && (
            <div role="status" className="mb-4 p-3 bg-warning/10 border border-warning/30 rounded-xl text-sm text-ink-secondary">
              The admin connector is switched off on the server (MCP_ENABLED). Nothing can connect until it is turned on.
            </div>
          )}

          <div className="bg-white rounded-card border border-border overflow-hidden shadow-sm">
            <div className="flex items-center gap-4 flex-wrap px-6 py-5">
              <div className="flex-1 min-w-[220px]">
                {connection ? (
                  <>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-ink">{connection.label || "Claude app"}</span>
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${
                          active ? "bg-success/10 text-success" : "bg-surface-mid text-ink-muted"
                        }`}
                      >
                        {active ? "Connected" : "Switched off"}
                      </span>
                    </div>
                    <p className="text-xs text-ink-muted mt-1">
                      {active
                        ? `Allowed on ${formatAllowedDate(connection.created_at)} · last used ${
                            connection.last_used_at ? relTime(connection.last_used_at) : "never"
                          }`
                        : "Switched off · every tool call is refused until you connect again from the Claude app"}
                    </p>
                  </>
                ) : (
                  <>
                    <span className="font-semibold text-ink">Not connected yet</span>
                    <p className="text-xs text-ink-muted mt-1">Follow the steps under How to connect.</p>
                  </>
                )}
              </div>
              {active && (
                <button
                  type="button"
                  onClick={() => setConfirmOpen(true)}
                  disabled={switching}
                  className={`px-4 py-2 text-sm font-medium text-danger border border-danger/30 rounded-xl hover:bg-danger/5 transition-colors disabled:opacity-50 ${FOCUS}`}
                >
                  Switch off
                </button>
              )}
              {!active && connection && (
                <button
                  type="button"
                  onClick={resetSignIn}
                  disabled={switching}
                  title="Removes Claude's saved sign-in at Supabase, so the next connect shows the Allow screen again"
                  className={`px-4 py-2 text-sm font-medium text-ink-secondary border border-border rounded-xl hover:bg-surface-mid transition-colors disabled:opacity-50 ${FOCUS}`}
                >
                  Reset sign-in
                </button>
              )}
            </div>
            {connection && (
              <div className="grid grid-cols-1 sm:grid-cols-3 border-t border-border">
                {[
                  { value: String(data.calls_today), label: "calls today" },
                  { value: data.top_tool_week || "—", label: "most used tool this week" },
                  { value: data.top_client_week || "—", label: "most read client this week" },
                ].map((s, i) => (
                  <div
                    key={s.label}
                    className={`px-6 py-4 border-border ${i > 0 ? "border-t sm:border-t-0 sm:border-l" : ""}`}
                  >
                    <p className="text-xl font-bold text-ink truncate" title={s.value}>{s.value}</p>
                    <p className="text-xs text-ink-muted">{s.label}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {connection && (
            <div className="bg-white rounded-card border border-border overflow-hidden shadow-sm mt-6">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-mid text-left">
                      <th className={TH}>Time</th>
                      <th className={TH}>Tool</th>
                      <th className={TH}>Client</th>
                      <th className={TH}>Asked for</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    {calls.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-5 py-8 text-center text-ink-muted">
                          Claude has not read anything yet.
                        </td>
                      </tr>
                    ) : (
                      calls.map((c) => (
                        <tr key={c.id}>
                          <td
                            className="px-5 py-3 text-ink-muted text-xs whitespace-nowrap"
                            title={c.created_at ? new Date(c.created_at).toLocaleString("en-IN") : undefined}
                          >
                            {relTime(c.created_at)}
                          </td>
                          <td className="px-5 py-3">
                            <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-primary-light text-primary-dark">
                              {c.tool || "unknown"}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-ink text-xs">{c.tenant_name || "All clients"}</td>
                          <td className="px-5 py-3 text-ink-muted text-xs font-mono max-w-[300px] truncate" title={formatCallArguments(c.arguments)}>
                            {formatCallArguments(c.arguments) || "—"}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center gap-2 px-5 py-3 border-t border-border text-xs">
                <span className="text-ink-muted">Last 3 calls ·</span>
                <Link
                  href="/operator/audit-log?claude=1"
                  className={`font-semibold text-primary hover:text-primary-dark rounded ${FOCUS}`}
                >
                  See all in Audit Log →
                </Link>
              </div>
            </div>
          )}

          <section className="bg-surface-mid rounded-2xl px-5 py-4 mt-6 text-sm text-ink-secondary leading-relaxed" aria-labelledby="how-to-connect">
            <h2 id="how-to-connect" className="font-bold text-ink">How to connect</h2>
            <ol className="mt-1 space-y-1">
              <li>1. In the Claude app: Customize → Connectors → Add custom connector.</li>
              <li className="flex items-center gap-2 flex-wrap">
                <span>2. Paste this address:</span>
                <code className="bg-white border border-border rounded-md px-2 py-0.5 text-xs font-mono break-all">{data.mcp_url}</code>
                <button
                  type="button"
                  onClick={copyUrl}
                  className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-ink-secondary bg-white border border-border rounded-lg hover:bg-white/60 transition-colors ${FOCUS}`}
                >
                  {copied ? <Check size={12} aria-hidden="true" /> : <Copy size={12} aria-hidden="true" />}
                  {copied ? "Copied" : "Copy"}
                </button>
                <span className="sr-only" role="status">{copied ? "Address copied" : ""}</span>
              </li>
              <li>3. Sign in to Anril and click Allow.</li>
            </ol>
          </section>
        </>
      ) : null}
      </section>

      <section aria-labelledby="client-connectors">
        <SectionHead id="client-connectors" title="Client connectors" />

        {clientsError && (
          <div role="alert" className="mb-4 p-3 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger flex items-center justify-between gap-3 flex-wrap">
            <span>{clientsError}</span>
            <button
              type="button"
              onClick={loadClients}
              className={`px-3 py-1 text-xs font-semibold border border-danger/30 rounded-lg hover:bg-danger/5 transition-colors ${FOCUS}`}
            >
              Retry
            </button>
          </div>
        )}

        {clientsLoading && !clientsData ? (
          <ClientsSkeleton />
        ) : clientsData ? (
          <>
            {!clientsData.enabled && (
              <div role="status" className="mb-4 p-3 bg-warning/10 border border-warning/30 rounded-xl text-sm text-ink-secondary">
                The client connector is switched off on the server (MCP_CLIENT_ENABLED). Switches are saved but nothing can connect until it is on.
              </div>
            )}
            <div className="bg-white rounded-card border border-border overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-mid text-left">
                      <th className={TH}>Client</th>
                      <th className={TH}>MCP</th>
                      <th className={TH}>Connection</th>
                      <th className={TH}>Sent today</th>
                      <th className={TH}>Last used</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    {clientsData.clients.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-5 py-8 text-center text-ink-muted">
                          No clients yet
                        </td>
                      </tr>
                    ) : (
                      clientsData.clients.map((c) => {
                        const tag = statusTag(c.status);
                        const rowError = rowErrors[c.tenant_id];
                        return (
                          <tr key={c.tenant_id}>
                            <td className="px-5 py-3 text-ink">
                              <span className="font-medium">{c.name}</span>
                              {tag && <span className="ml-2 text-[11px] text-ink-muted">{tag}</span>}
                              {rowError && (
                                <p role="alert" className="mt-1 text-xs text-danger">{rowError}</p>
                              )}
                            </td>
                            <td className="px-5 py-3">
                              <ClientSwitch
                                name={c.name}
                                on={c.on}
                                busy={!!pending[c.tenant_id]}
                                onToggle={() => toggleClient(c)}
                              />
                            </td>
                            <td className="px-5 py-3 text-ink-secondary text-xs whitespace-nowrap">{connectionLabel(c)}</td>
                            <td className="px-5 py-3 text-ink-muted text-xs whitespace-nowrap">{sentLabel(c)}</td>
                            <td
                              className="px-5 py-3 text-ink-muted text-xs whitespace-nowrap"
                              title={c.last_used_at ? new Date(c.last_used_at).toLocaleString("en-IN") : undefined}
                            >
                              {c.last_used_at ? relTime(c.last_used_at) : "—"}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
            <p className="text-xs text-ink-muted mt-3">
              Each client&apos;s owner finds the address and the client ID in their own Settings → Anril AI for Claude.
            </p>
          </>
        ) : null}
      </section>

      <ConfirmModal
        open={offTarget !== null}
        onClose={() => setOffTarget(null)}
        onConfirm={confirmClientOff}
        title={`Switch off MCP for ${offTarget?.name ?? "this client"}?`}
        description="Claude stops working for this client on its next request. The owner does not need to connect again when you switch it back on."
        tone="danger"
        confirmLabel="Switch off"
      />

      <ConfirmModal
        open={confirmOpen}
        onClose={() => { if (!switching) setConfirmOpen(false); }}
        onConfirm={switchOff}
        title="Switch off the admin connector"
        description="Claude will stop being able to read Operator data. Every tool call is refused until you connect again from the Claude app."
        tone="danger"
        confirmLabel="Switch off"
        loading={switching}
        loadingLabel="Switching off…"
      />
    </div>
  );
}
