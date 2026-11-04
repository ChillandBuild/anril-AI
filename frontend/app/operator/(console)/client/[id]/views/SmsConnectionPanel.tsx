"use client";

import { useState } from "react";
import useSWR from "swr";
import { Loader2, MessageSquareText } from "lucide-react";
import { toast } from "sonner";
import { getOperatorSms, putOperatorSmsBatch, putOperatorSmsKey, registerOperatorSmsWebhook } from "@/lib/operator";
import { OperatorToggle } from "../../../components/operator-toggle";

const buttonClass = "inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-border px-3 text-xs font-semibold text-ink hover:bg-surface-low disabled:opacity-50";
const inputClass = "w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none focus:border-primary disabled:opacity-50";

export function SmsConnectionPanel({ tenantId, enabled, featureSaving, onToggle }: {
  tenantId: string; enabled: boolean; featureSaving: boolean; onToggle: (enabled: boolean) => void;
}) {
  const connection = useSWR(["operator:sms", tenantId], () => getOperatorSms(tenantId));
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<"key" | "webhook" | "batch" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function connect(action: "key" | "webhook") {
    if (busy) return;
    setBusy(action);
    setError(null);
    try {
      const data = action === "key" ? await putOperatorSmsKey(tenantId, key.trim()) : await registerOperatorSmsWebhook(tenantId);
      await connection.mutate(data, { revalidate: false });
      if (action === "key") setKey("");
      if (data.webhook_error) toast.warning(action === "key" ? "Key saved. Delivery setup needs a retry." : "Delivery setup needs a retry.");
      else toast.success(action === "key" ? "SMS key tested and saved." : "Delivery updates registered.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the SMS connection.");
      void connection.mutate();
    } finally {
      setBusy(null);
    }
  }

  async function setBatch(next: boolean) {
    if (busy) return;
    setBusy("batch");
    setError(null);
    try {
      await connection.mutate(await putOperatorSmsBatch(tenantId, next), { revalidate: false });
      toast.success(next ? "Batch sending on: up to 50 SMS per call." : "Batch sending off: one SMS per call.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change batch sending.");
      void connection.mutate();
    } finally {
      setBusy(null);
    }
  }

  const data = connection.data;
  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-ink"><MessageSquareText size={16} className="text-ink-muted" /> SMS connection</h3>
        <OperatorToggle checked={enabled} onChange={onToggle} loading={featureSaving} aria-label="Enable SMS for client" />
      </div>
      <div className="space-y-4 rounded-card border border-border bg-white p-4 shadow-sm">
        {connection.isLoading && !data && <p className="text-sm text-ink-muted">Loading SMS connection…</p>}
        {connection.error && !data && <div role="alert" className="text-sm text-danger">{connection.error instanceof Error ? connection.error.message : "Couldn't load SMS connection."} <button className="font-semibold underline" onClick={() => void connection.mutate()}>Retry</button></div>}
        {data && <div className="space-y-1 text-xs text-ink-muted">
          <p>Connection: <span className="font-semibold text-ink">{data.connected ? "Connected" : "Not connected"}</span>{data.key_masked && <span className="ml-2 font-mono">{data.key_masked}</span>}</p>
          <p>Delivery updates: <span className="font-semibold text-ink">{data.webhook_registered ? "Registered" : "Not registered"}</span></p>
          {data.webhook_error && <p role="alert" className="break-words text-danger">{data.webhook_error}</p>}
          {data.sms_count != null && <p>{data.sms_count.toLocaleString("en-IN")} SMS left</p>}
        </div>}
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-48 flex-1 text-xs font-medium text-ink-muted">Bulk9 client API key
            <input type="password" autoComplete="new-password" className={`${inputClass} mt-1`} value={key} onChange={(event) => setKey(event.target.value)} placeholder="Enter key to connect or replace" disabled={!!busy} />
          </label>
          <button className={`${buttonClass} border-primary bg-primary text-white hover:bg-primary/90`} disabled={!!busy || !key.trim()} onClick={() => void connect("key")}>{busy === "key" && <Loader2 size={14} className="animate-spin" />}Test &amp; save</button>
          <button className={buttonClass} disabled={!!busy || !data?.connected} onClick={() => void connect("webhook")}>{busy === "webhook" && <Loader2 size={14} className="animate-spin" />}{data?.webhook_registered ? "Retry delivery setup" : "Register delivery updates"}</button>
        </div>
        {data?.connected && (
          <div className="flex items-start justify-between gap-3 border-t border-border pt-3">
            <div className="text-xs text-ink-muted">
              <p className="font-semibold text-ink">Send in batches</p>
              <p>Up to 50 SMS per Bulk9 call instead of one. Each SMS still gets its own delivery status. Test with 2 of your own numbers before leaving it on.</p>
            </div>
            <OperatorToggle checked={!!data.batch_send} onChange={(next) => void setBatch(next)} loading={busy === "batch"} disabled={!!busy && busy !== "batch"} aria-label="Send SMS in batches" />
          </div>
        )}
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      </div>
    </section>
  );
}
