"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { LifeBuoy } from "lucide-react";
import { toast } from "sonner";
import { finishOperatorSetupHelpRequest, getOperatorSetupHelpRequests, type OperatorSetupHelpRequest } from "@/lib/setupHelpApi";

const buttonClass = "inline-flex h-8 items-center justify-center rounded-lg border border-border px-3 text-xs font-semibold text-ink hover:bg-surface-low disabled:opacity-50";

const KIND_LABEL: Record<string, string> = { catalogue: "Add their catalogue" };

// Open "Let the Anril team do it" asks from first setup. The team WhatsApps the client, does the work, then marks it here.
export function SetupHelpRequestsCard() {
  const requests = useSWR("operator:setup-help-requests", getOperatorSetupHelpRequests);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function finish(request: OperatorSetupHelpRequest, status: "done" | "cancelled") {
    if (busyId) return;
    if (status === "cancelled" && !confirm(`Cancel the setup request from ${request.tenant_name ?? "this client"}?`)) return;
    setBusyId(request.id);
    try {
      await finishOperatorSetupHelpRequest(request.id, status);
      await requests.mutate();
      toast.success(status === "done" ? "Setup request marked done." : "Setup request cancelled.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't update the setup request.");
    } finally {
      setBusyId(null);
    }
  }

  const items = requests.data?.items ?? [];
  return (
    <section className="mb-6 rounded-card border border-border bg-white p-4 shadow-sm">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink"><LifeBuoy size={16} className="text-ink-muted" /> Setup help requests{requests.data ? ` (${items.length})` : ""}</h2>
      {requests.error && !requests.data ? <p role="alert" className="text-sm text-danger">Couldn&apos;t load setup requests. <button className="font-semibold underline" onClick={() => void requests.mutate()}>Retry</button></p>
        : requests.isLoading && !requests.data ? <p className="text-xs text-ink-muted">Loading requests…</p>
        : !items.length ? <p className="text-xs text-ink-muted">No open requests.</p>
        : <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="text-xs text-ink-muted"><tr><th className="py-1.5 pr-3 font-medium">Client</th><th className="py-1.5 pr-3 font-medium">Asked for</th><th className="py-1.5 pr-3 font-medium">Requested</th><th className="py-1.5 font-medium"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{items.map((request) => <tr key={request.id} className="border-t border-border align-top">
            <td className="py-2 pr-3 text-ink">{request.tenant_name ? <Link href={`/operator/client/${request.tenant_id}`} className="font-semibold text-primary underline">{request.tenant_name}</Link> : <Link href={`/operator/client/${request.tenant_id}`} className="text-ink-muted underline">Unnamed client</Link>}</td>
            <td className="py-2 pr-3 text-ink">{KIND_LABEL[request.kind] ?? request.kind}</td>
            <td className="whitespace-nowrap py-2 pr-3 text-ink-muted">{new Date(request.created_at).toLocaleDateString("en-IN")}</td>
            <td className="py-2"><div className="flex gap-2">
              <button className={`${buttonClass} border-primary bg-primary text-white hover:bg-primary/90`} disabled={!!busyId} onClick={() => void finish(request, "done")}>{busyId === request.id ? "Saving…" : "Done"}</button>
              <button className={buttonClass} disabled={!!busyId} onClick={() => void finish(request, "cancelled")}>Cancel</button>
            </div></td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  );
}
