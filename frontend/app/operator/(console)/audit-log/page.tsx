"use client";
import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ChevronLeft, ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { relTime } from "@/lib/operator";

interface AuditEntry {
  id: string;
  tenant_id: string | null;
  tenant_name: string;
  actor_user_id: string | null;
  actor_role: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

interface AuditResponse {
  data: AuditEntry[];
  total: number;
  page: number;
  limit: number;
}

const ACTION_COLORS: Record<string, string> = {
  "operator.data_cleared": "bg-danger/10 text-danger",
  "operator.client_created": "bg-success/10 text-success",
  "operator.status_changed": "bg-warning/10 text-warning",
  "operator.password_reset": "bg-primary-light text-primary",
  "operator.features_updated": "bg-primary-light text-primary",
};

function actionColor(action: string): string {
  for (const [prefix, cls] of Object.entries(ACTION_COLORS)) {
    if (action.startsWith(prefix)) return cls;
  }
  return "bg-surface-mid text-ink-secondary";
}

function formatMeta(meta: Record<string, unknown> | null): string {
  if (!meta || Object.keys(meta).length === 0) return "";
  return Object.entries(meta)
    .filter(([, v]) => v !== null && v !== undefined && v !== "********")
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

export default function AuditLogPage({ searchParams }: { searchParams?: { claude?: string } }) {
  const [logs, setLogs] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [includeMcp, setIncludeMcp] = useState(searchParams?.claude === "1");
  const limit = 30;

  // Debounce the search input ~300ms before it drives a request.
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(id);
  }, [searchInput]);

  // Reset to page 1 whenever the (debounced) search term changes.
  useEffect(() => { setPage(1); }, [search]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const auth = await getAuthHeaders();
      const params = new URLSearchParams({ page: String(page), limit: String(limit) });
      if (search) params.set("action", search);
      if (includeMcp) params.set("include_mcp", "true");
      const res = await fetch(`${API_URL}/api/v1/operator/audit-logs?${params}`, {
        headers: { ...auth },
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data: AuditResponse = await res.json();
      setLogs(data.data);
      setTotal(data.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [page, search, includeMcp]);

  useEffect(() => { load(); }, [load]);

  const totalPages = Math.ceil(total / limit) || 1;

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-8 py-8">
      <div className="flex items-center justify-between gap-4 flex-wrap mb-6">
        <div>
          <h1 className="text-2xl font-bold text-ink">Audit Log</h1>
          <p className="text-sm text-ink-muted mt-1">Track all operator actions across clients.</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <button
              id="show-claude-reads"
              type="button"
              role="switch"
              aria-checked={includeMcp}
              onClick={() => { setIncludeMcp((v) => !v); setPage(1); }}
              className={`relative w-9 h-5 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 ${
                includeMcp ? "bg-primary" : "bg-slate-300"
              }`}
            >
              <span
                aria-hidden="true"
                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                  includeMcp ? "translate-x-4" : ""
                }`}
              />
            </button>
            <label htmlFor="show-claude-reads" className="text-sm text-ink-secondary cursor-pointer select-none">
              Show Claude reads
            </label>
          </div>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Filter by action..."
              className="pl-9 pr-3 py-2 border border-border rounded-xl text-sm w-56 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
            />
          </div>
          <button
            onClick={load}
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-ink-secondary hover:text-ink border border-border rounded-xl hover:bg-surface-mid transition-colors"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger">
          {error}
        </div>
      )}

      <div className="bg-white rounded-card border border-border overflow-x-auto shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-mid text-left">
              <th className="px-5 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wider">Time</th>
              <th className="px-5 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wider">Action</th>
              <th className="px-5 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wider">Client</th>
              <th className="px-5 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wider">Target</th>
              <th className="px-5 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wider">Details</th>
              <th className="px-5 py-2.5 text-xs font-semibold text-ink-muted uppercase tracking-wider">Actor</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {loading && logs.length === 0 ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="animate-pulse">
                  <td className="px-5 py-3"><div className="h-3 bg-surface-mid rounded w-16" /></td>
                  <td className="px-5 py-3"><div className="h-3 bg-surface-mid rounded w-32" /></td>
                  <td className="px-5 py-3"><div className="h-3 bg-surface-mid rounded w-20" /></td>
                  <td className="px-5 py-3"><div className="h-3 bg-surface-mid rounded w-16" /></td>
                  <td className="px-5 py-3"><div className="h-3 bg-surface-mid rounded w-40" /></td>
                  <td className="px-5 py-3"><div className="h-3 bg-surface-mid rounded w-24" /></td>
                </tr>
              ))
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-12 text-center text-ink-muted">
                  No audit log entries found.
                </td>
              </tr>
            ) : (
              logs.map((log) => (
                <tr key={log.id} className="hover:bg-surface-mid/50 transition-colors">
                  <td className="px-5 py-3 text-ink-muted text-xs whitespace-nowrap" title={new Date(log.created_at).toLocaleString("en-IN")}>
                    {relTime(log.created_at)}
                  </td>
                  <td className="px-5 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${actionColor(log.action)}`}>
                      {log.action}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-ink text-xs">
                    {log.tenant_id ? (
                      <Link href={`/operator/client/${log.tenant_id}`} className="font-medium text-primary hover:text-primary-dark">
                        {log.tenant_name}
                      </Link>
                    ) : (
                      log.tenant_name
                    )}
                  </td>
                  <td className="px-5 py-3 text-ink-muted text-xs font-mono">
                    {log.target_type}{log.target_id ? `:${log.action === "mcp.tool_call" ? log.target_id : log.target_id.slice(0, 8)}` : ""}
                  </td>
                  <td className="px-5 py-3 text-ink-muted text-xs max-w-[300px] truncate" title={formatMeta(log.metadata)}>
                    {formatMeta(log.metadata) || "—"}
                  </td>
                  <td className="px-5 py-3 text-xs">
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                      log.actor_role === "system_admin" ? "bg-primary-50 text-primary-700" : "bg-surface-mid text-ink-muted"
                    }`}>
                      {log.actor_role || "system"}{log.action === "mcp.tool_call" ? " · Claude" : ""}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {!includeMcp && (
        <p className="text-xs text-ink-muted mt-3">
          Claude reads are hidden by default so they do not bury real operator actions.
        </p>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-xs text-ink-muted">{total} entries · page {page} of {totalPages}</p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-2 rounded-lg border border-border hover:bg-surface-mid disabled:opacity-30 transition-colors"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-2 rounded-lg border border-border hover:bg-surface-mid disabled:opacity-30 transition-colors"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
