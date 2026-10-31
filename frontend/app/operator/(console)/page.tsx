"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Plus, RefreshCw, PowerOff, Power, List, LayoutGrid, Copy, Check, Eye, EyeOff, X, AlertTriangle } from "lucide-react";
import { operatorFetch } from "@/lib/operator";
import { fleetWaitingByTenant, waitingColumnText, type FleetWaitingResponse } from "@/components/brain/operatorBrain";
import { OnboardingWizard } from "./components/onboarding-wizard";
import { ConfirmModal } from "@/components/ConfirmModal";
import { CheckTick } from "@/components/ui/controls";

type Client = {
  id: string;
  name: string;
  status: string;
  created_at: string;
};

const FLEET_REFRESH_MS = 5 * 60_000;

export default function OperatorPage() {
  const router = useRouter();
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tempPw, setTempPw] = useState<{ name: string; pw: string } | null>(null);
  const [pwRevealed, setPwRevealed] = useState(false);
  const [pwCopied, setPwCopied] = useState(false);
  const [resetTarget, setResetTarget] = useState<Client | null>(null);
  const [resetLoading, setResetLoading] = useState(false);
  const [statusTarget, setStatusTarget] = useState<Client | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [fleet, setFleet] = useState<FleetWaitingResponse | null>(null);
  const [fleetFailed, setFleetFailed] = useState(false);
  const waitingByTenant = fleetWaitingByTenant(fleet?.data ?? []);
  const waitingText = (id: string) => (fleet ? waitingColumnText(waitingByTenant.get(id)) : fleetFailed ? "Unavailable" : "…");

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState<"active" | "suspended" | null>(null);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);
  const [bulkSummary, setBulkSummary] = useState<{ succeeded: number; failed: number; failedNames: string[] } | null>(null);

  const [view, setView] = useState<"grid" | "table">(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("operator-clients-view") as "grid" | "table") || "grid";
    }
    return "grid";
  });

  useEffect(() => {
    localStorage.setItem("operator-clients-view", view);
  }, [view]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await operatorFetch<{ data: Client[] }>("/api/v1/operator/clients");
      setClients(res.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Waiting approvals per client plus the stuck-approval alerts. Bulk queries on the
  // server, so it refreshes more slowly than the client list itself.
  const loadFleet = useCallback(async () => {
    try {
      setFleet(await operatorFetch<FleetWaitingResponse>("/api/v1/operator/brain/waiting"));
      setFleetFailed(false);
    } catch {
      setFleetFailed(true);
    }
  }, []);

  useEffect(() => {
    loadFleet();
    const id = setInterval(loadFleet, FLEET_REFRESH_MS);
    return () => clearInterval(id);
  }, [loadFleet]);

  // Auto-refresh the client list every 60s.
  useEffect(() => {
    const id = setInterval(() => { load(); }, 60_000);
    return () => clearInterval(id);
  }, [load]);

  function handleToggleStatus(client: Client) {
    setStatusTarget(client);
  }

  async function confirmToggleStatus() {
    if (!statusTarget) return;
    setStatusLoading(true);
    const newStatus = statusTarget.status === "active" ? "suspended" : "active";
    try {
      await operatorFetch(`/api/v1/operator/clients/${statusTarget.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus }),
      });
      setStatusTarget(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update status");
    } finally {
      setStatusLoading(false);
    }
  }

  function toggleSelected(clientId: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(clientId)) next.delete(clientId);
      else next.add(clientId);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelectedIds(prev => {
      if (clients.length > 0 && prev.size === clients.length) return new Set();
      return new Set(clients.map(c => c.id));
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  function requestBulkAction(status: "active" | "suspended") {
    setBulkSummary(null);
    setBulkAction(status);
  }

  async function confirmBulkAction() {
    if (!bulkAction) return;
    const targets = clients.filter(c => selectedIds.has(c.id));
    if (targets.length === 0) {
      setBulkAction(null);
      return;
    }
    setBulkRunning(true);
    setBulkProgress({ done: 0, total: targets.length });
    let succeeded = 0;
    const failedNames: string[] = [];

    for (const client of targets) {
      try {
        await operatorFetch(`/api/v1/operator/clients/${client.id}/status`, {
          method: "PATCH",
          body: JSON.stringify({ status: bulkAction }),
        });
        succeeded++;
      } catch {
        failedNames.push(client.name);
      }
      setBulkProgress(prev => (prev ? { done: prev.done + 1, total: prev.total } : prev));
    }

    setBulkRunning(false);
    setBulkProgress(null);
    setBulkAction(null);
    setBulkSummary({ succeeded, failed: failedNames.length, failedNames });
    if (failedNames.length > 0) {
      setError(`Bulk update: ${succeeded} succeeded, ${failedNames.length} failed (${failedNames.join(", ")}).`);
    } else {
      setError(null);
    }
    clearSelection();
    await load();
  }

  function handleResetPassword(client: Client) {
    setResetTarget(client);
  }

  async function confirmResetPassword() {
    if (!resetTarget) return;
    setResetLoading(true);
    try {
      const res = await operatorFetch<{ temp_password: string }>(
        `/api/v1/operator/clients/${resetTarget.id}/reset-password`,
        { method: "POST" }
      );
      setPwRevealed(false);
      setPwCopied(false);
      setTempPw({ name: resetTarget.name, pw: res.temp_password });
      setResetTarget(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reset password");
    } finally {
      setResetLoading(false);
    }
  }

  function copyPw(pw: string) {
    navigator.clipboard.writeText(pw);
    setPwCopied(true);
    setTimeout(() => setPwCopied(false), 2000);
  }

  function copyId(id: string) {
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  function ActionButtons({ client }: { client: Client }) {
    return (
      <div className="flex items-center gap-2">
        <button
          onClick={(e) => { e.stopPropagation(); handleResetPassword(client); }}
          className="p-1.5 rounded-lg hover:bg-surface-mid text-ink-muted hover:text-ink transition-colors"
          title="Reset password"
        >
          <RefreshCw size={13} />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); handleToggleStatus(client); }}
          className={`p-1.5 rounded-lg hover:bg-surface-mid transition-colors ${
            client.status === "active" ? "text-ink-muted hover:text-danger" : "text-ink-muted hover:text-success"
          }`}
          title={client.status === "active" ? "Suspend" : "Activate"}
        >
          {client.status === "active" ? <PowerOff size={13} /> : <Power size={13} />}
        </button>
      </div>
    );
  }

  function goToClient(clientId: string) {
    router.push(`/operator/client/${clientId}`);
  }

  function handleRowKeyDown(e: React.KeyboardEvent, clientId: string) {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      goToClient(clientId);
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-8 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-ink">Clients</h1>
          <p className="text-sm text-ink-muted mt-1">Provision and manage tenant accounts.</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => load()}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-ink-secondary hover:text-ink border border-border rounded-lg hover:bg-surface-mid transition-colors disabled:opacity-60"
            title="Refresh"
            aria-label="Refresh clients"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
          </button>

          {/* View toggle */}
          <div className="flex bg-surface-mid rounded-lg p-0.5">
            <button
              onClick={() => setView("table")}
              className={`p-2 rounded-md transition-all ${
                view === "table" ? "bg-primary text-white shadow-sm" : "text-ink-secondary hover:text-ink"
              }`}
              title="Table view"
            >
              <List size={16} />
            </button>
            <button
              onClick={() => setView("grid")}
              className={`p-2 rounded-md transition-all ${
                view === "grid" ? "bg-primary text-white shadow-sm" : "text-ink-secondary hover:text-ink"
              }`}
              title="Grid view"
            >
              <LayoutGrid size={16} />
            </button>
          </div>

          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary-dark transition-colors"
          >
            <Plus size={14} /> New Client
          </button>
        </div>
      </div>


      {/* Error alert */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-danger/20 rounded-lg text-sm text-danger">
          {error}
        </div>
      )}

      {/* Temp password banner */}
      {tempPw && (
        <div className="mb-4 p-4 bg-green-50 border border-success/20 rounded-lg">
          <p className="text-sm font-medium text-success">Password reset for {tempPw.name}</p>
          <div className="flex items-center gap-2 mt-1">
            <p className="text-sm text-success">Temp password:</p>
            <code className="font-mono bg-green-100 px-2 py-0.5 rounded text-success tracking-wider">
              {pwRevealed ? tempPw.pw : "•".repeat(tempPw.pw.length)}
            </code>
            <button
              onClick={() => setPwRevealed(v => !v)}
              className="p-1 rounded hover:bg-green-100 text-success transition-colors"
              title={pwRevealed ? "Hide password" : "Reveal password"}
              aria-label={pwRevealed ? "Hide password" : "Reveal password"}
            >
              {pwRevealed ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
            <button
              onClick={() => copyPw(tempPw.pw)}
              className="p-1 rounded hover:bg-green-100 text-success transition-colors"
              title="Copy password"
              aria-label="Copy password"
            >
              {pwCopied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
          <button onClick={() => setTempPw(null)} className="text-xs text-success mt-2 underline">Dismiss</button>
        </div>
      )}

      {/* Reset password confirmation */}
      <ConfirmModal
        open={resetTarget !== null}
        onClose={() => setResetTarget(null)}
        onConfirm={confirmResetPassword}
        title="Reset password?"
        description={`This will generate a new temporary password for ${resetTarget?.name ?? "this client"}. Their current password will stop working immediately.`}
        confirmLabel="Reset"
        tone="primary"
        loading={resetLoading}
      />

      {/* Single client status toggle confirmation */}
      <ConfirmModal
        open={statusTarget !== null}
        onClose={() => setStatusTarget(null)}
        onConfirm={confirmToggleStatus}
        title={statusTarget?.status === "active" ? `Suspend ${statusTarget?.name ?? "client"}?` : `Activate ${statusTarget?.name ?? "client"}?`}
        description={
          statusTarget?.status === "active"
            ? `Suspended clients will lose access immediately. Are you sure you want to suspend ${statusTarget?.name}?`
            : `${statusTarget?.name} will regain access immediately. Are you sure you want to activate this client?`
        }
        confirmLabel={statusTarget?.status === "active" ? "Suspend" : "Activate"}
        tone={statusTarget?.status === "active" ? "danger" : "primary"}
        loading={statusLoading}
      />

      {/* Create modal */}
      {showCreate && (
        <OnboardingWizard open={showCreate} onClose={() => setShowCreate(false)} onComplete={load} />
      )}

      {/* Stuck approvals: sorted files a client has left unapproved for over a week */}
      {fleet && fleet.alerts.length > 0 && (
        <div role="alert" className="mb-4 rounded-xl border border-warning/30 bg-warning/10 p-3">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-warning">
            <AlertTriangle size={14} /> {fleet.alerts.length} client{fleet.alerts.length === 1 ? " has" : "s have"} approvals stuck for over {fleet.stuck_after_days} days
          </p>
          <ul className="mt-1.5 space-y-1">
            {fleet.alerts.map(alert => (
              <li key={alert.id} className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-ink">
                <span>{alert.detail}</span>
                {alert.href && (
                  <button type="button" onClick={() => router.push(alert.href as string)} className="font-semibold text-primary underline">
                    Open Anril Brain
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Content */}
      {loading && clients.length === 0 ? (
        <div className="p-8 text-center text-sm text-ink-muted">Loading…</div>
      ) : clients.length === 0 ? (
        <div className="p-12 text-center">
          <p className="text-ink font-semibold">No clients yet</p>
          <p className="text-sm text-ink-muted mt-1">Create your first client to get started.</p>
        </div>
      ) : view === "grid" ? (
        /* Grid view */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {clients.map(client => (
            <div
              key={client.id}
              role="button"
              tabIndex={0}
              aria-label={`Open client ${client.name}`}
              className="bg-white rounded-card border border-border shadow-card hover:shadow-card-hover transition-all duration-200 cursor-pointer p-5 focus:outline-none focus:ring-2 focus:ring-primary/40"
              onClick={() => goToClient(client.id)}
              onKeyDown={(e) => handleRowKeyDown(e, client.id)}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-start gap-2.5">
                  <CheckTick
                    checked={selectedIds.has(client.id)}
                    onChange={() => toggleSelected(client.id)}
                    aria-label={`Select ${client.name}`}
                    size="sm"
                    className="mt-0.5"
                  />
                  <div>
                    <h3 className="text-base font-semibold text-ink">{client.name}</h3>
                    <div className="flex items-center gap-1 mt-0.5">
                      <p className="text-xs text-ink-muted font-mono">{client.id.slice(0, 8)}&hellip;</p>
                      <button
                        onClick={(e) => { e.stopPropagation(); copyId(client.id); }}
                        className="p-0.5 rounded hover:bg-surface-mid text-ink-muted hover:text-ink transition-colors"
                        title="Copy tenant ID"
                      >
                        {copiedId === client.id ? <Check size={10} /> : <Copy size={10} />}
                      </button>
                    </div>
                  </div>
                </div>
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  client.status === "active" ? "bg-green-50 text-success" : "bg-red-50 text-danger"
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${client.status === "active" ? "bg-success" : "bg-danger"}`} />
                  {client.status}
                </span>
              </div>
              <p className="text-xs text-ink-muted mb-1">Created {new Date(client.created_at).toLocaleDateString("en-IN")}</p>
              <p className="text-xs text-ink-muted mb-3">Waiting approvals: {waitingText(client.id)}</p>
              <div className="border-t border-border-subtle pt-3">
                <ActionButtons client={client} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Table view */
        <div className="bg-white rounded-card border border-border overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-5 py-3 text-left bg-surface-mid w-10">
                  <CheckTick
                    checked={clients.length > 0 && selectedIds.size === clients.length}
                    indeterminate={selectedIds.size > 0 && selectedIds.size < clients.length}
                    onChange={() => toggleSelectAll()}
                    aria-label="Select all clients"
                    size="sm"
                  />
                </th>
                {["Company", "Status", "Waiting approvals", "Created", "Actions"].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-xs font-semibold text-ink-secondary uppercase tracking-wider bg-surface-mid">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {clients.map(client => (
                <tr
                  key={client.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Open client ${client.name}`}
                  className="hover:bg-surface-mid/50 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/40"
                  onClick={() => goToClient(client.id)}
                  onKeyDown={(e) => handleRowKeyDown(e, client.id)}
                >
                  <td className="px-5 py-4" onClick={(e) => e.stopPropagation()}>
                    <CheckTick
                      checked={selectedIds.has(client.id)}
                      onChange={() => toggleSelected(client.id)}
                      aria-label={`Select ${client.name}`}
                      size="sm"
                    />
                  </td>
                  <td className="px-5 py-4">
                    <p className="text-sm font-semibold text-ink">{client.name}</p>
                    <div className="flex items-center gap-1 mt-0.5">
                      <p className="text-xs text-ink-muted font-mono">{client.id.slice(0, 8)}&hellip;</p>
                      <button
                        onClick={(e) => { e.stopPropagation(); copyId(client.id); }}
                        className="p-0.5 rounded hover:bg-surface-mid text-ink-muted hover:text-ink transition-colors"
                        title="Copy tenant ID"
                      >
                        {copiedId === client.id ? <Check size={10} /> : <Copy size={10} />}
                      </button>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      client.status === "active" ? "bg-green-50 text-success" : "bg-red-50 text-danger"
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${client.status === "active" ? "bg-success" : "bg-danger"}`} />
                      {client.status}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-xs text-ink-muted">{waitingText(client.id)}</td>
                  <td className="px-5 py-4 text-xs text-ink-muted">
                    {new Date(client.created_at).toLocaleDateString("en-IN")}
                  </td>
                  <td className="px-5 py-4">
                    <ActionButtons client={client} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="fixed inset-x-0 bottom-6 z-40 flex justify-center px-4 motion-safe:animate-in motion-safe:slide-in-from-bottom-4 motion-safe:fade-in motion-safe:duration-200">
          <div className="flex items-center gap-4 bg-ink text-white rounded-full shadow-xl pl-5 pr-3 py-2.5">
            <span className="text-sm font-medium">
              {selectedIds.size} client{selectedIds.size === 1 ? "" : "s"} selected
            </span>
            <div className="h-4 w-px bg-white/20" />
            <div className="flex items-center gap-2">
              <button
                onClick={() => requestBulkAction("suspended")}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-full bg-white/10 hover:bg-white/20 transition-colors"
              >
                <PowerOff size={13} /> Suspend
              </button>
              <button
                onClick={() => requestBulkAction("active")}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-full bg-white/10 hover:bg-white/20 transition-colors"
              >
                <Power size={13} /> Activate
              </button>
              <button
                onClick={clearSelection}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-white/70 hover:text-white rounded-full hover:bg-white/10 transition-colors"
                aria-label="Clear selection"
              >
                <X size={13} /> Clear
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk action confirmation */}
      <ConfirmModal
        open={bulkAction !== null}
        onClose={() => { if (!bulkRunning) setBulkAction(null); }}
        onConfirm={confirmBulkAction}
        title={
          bulkAction === "suspended"
            ? `Suspend ${selectedIds.size} client${selectedIds.size === 1 ? "" : "s"}?`
            : `Activate ${selectedIds.size} client${selectedIds.size === 1 ? "" : "s"}?`
        }
        description={
          bulkProgress
            ? `Updating ${bulkProgress.done}/${bulkProgress.total}…`
            : bulkAction === "suspended"
              ? "Suspended clients will lose access immediately. This action is applied one at a time."
              : "These clients will regain access immediately. This action is applied one at a time."
        }
        confirmLabel={bulkAction === "suspended" ? "Suspend" : "Activate"}
        tone={bulkAction === "suspended" ? "danger" : "primary"}
        loading={bulkRunning}
      />

      {/* Bulk action result summary */}
      {bulkSummary && (
        <div className={`fixed inset-x-0 bottom-6 z-40 flex justify-center px-4 motion-safe:animate-in motion-safe:slide-in-from-bottom-4 motion-safe:fade-in motion-safe:duration-200`}>
          <div className={`flex items-center gap-3 rounded-full shadow-xl pl-5 pr-3 py-2.5 text-sm font-medium ${
            bulkSummary.failed > 0 ? "bg-red-50 border border-danger/20 text-danger" : "bg-green-50 border border-success/20 text-success"
          }`}>
            <span>
              {bulkSummary.failed > 0
                ? `${bulkSummary.succeeded} succeeded, ${bulkSummary.failed} failed`
                : `${bulkSummary.succeeded} client${bulkSummary.succeeded === 1 ? "" : "s"} updated`}
            </span>
            <button onClick={() => setBulkSummary(null)} aria-label="Dismiss" className="hover:opacity-70">
              <X size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
