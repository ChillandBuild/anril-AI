"use client";

import { useState } from "react";
import useSWR from "swr";
import { Loader2, MessageSquareText } from "lucide-react";
import { toast } from "sonner";
import {
  getOperatorSms, getOperatorSmsTemplateRequests, putOperatorSmsChecklist, putOperatorSmsKey,
  registerOperatorSmsWebhook, updateOperatorSmsTemplateRequest,
  type OperatorSmsChecklist, type OperatorSmsTemplateRequest,
} from "@/lib/operator";
import { OperatorToggle } from "../../../components/operator-toggle";

const buttonClass = "inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-border px-3 text-xs font-semibold text-ink hover:bg-surface-low disabled:opacity-50";
const inputClass = "w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none focus:border-primary disabled:opacity-50";

const CHECKLIST_ITEMS: { key: keyof OperatorSmsChecklist; label: string }[] = [
  { key: "dlt", label: "DLT registered" },
  { key: "pe_tm", label: "PE–TM binding" },
  { key: "sender", label: "Sender ID" },
];

export function SmsConnectionPanel({ tenantId, enabled, featureSaving, onToggle }: {
  tenantId: string; enabled: boolean; featureSaving: boolean; onToggle: (enabled: boolean) => void;
}) {
  const connection = useSWR(["operator:sms", tenantId], () => getOperatorSms(tenantId));
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<"key" | "webhook" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checklistBusy, setChecklistBusy] = useState(false);
  const [checklistError, setChecklistError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const requests = useSWR(["operator:sms-requests", tenantId, page], () => getOperatorSmsTemplateRequests(tenantId, page, 10));

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

  async function toggleChecklist(item: keyof OperatorSmsChecklist, value: boolean) {
    const current = connection.data?.checklist ?? { dlt: false, pe_tm: false, sender: false };
    if (checklistBusy) return;
    setChecklistBusy(true);
    setChecklistError(null);
    try {
      await connection.mutate(await putOperatorSmsChecklist(tenantId, { ...current, [item]: value }), { revalidate: false });
    } catch (err) {
      setChecklistError(err instanceof Error ? err.message : "Couldn't save the setup checklist.");
      void connection.mutate();
    } finally {
      setChecklistBusy(false);
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
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        {data && <div className="space-y-2 border-t border-border pt-3">
          <h4 className="text-sm font-semibold text-ink">Client setup checklist</h4>
          {CHECKLIST_ITEMS.map((item) => <div key={item.key} className="flex items-center justify-between gap-3">
            <span className="text-sm text-ink">{item.label}</span>
            <OperatorToggle checked={data.checklist?.[item.key] === true} onChange={(next) => void toggleChecklist(item.key, next)} disabled={checklistBusy} aria-label={item.label} size="sm" />
          </div>)}
          <p className="text-xs text-ink-muted">PE–TM must be ticked before this client can send SMS.</p>
          {checklistError && <p role="alert" className="text-sm text-danger">{checklistError}</p>}
        </div>}
        <details className="border-t border-border pt-3">
          <summary className="cursor-pointer text-sm font-semibold text-ink">Template requests{requests.data ? ` (${requests.data.total})` : ""}</summary>
          <div className="mt-3 space-y-3">
            {requests.error ? <p role="alert" className="text-sm text-danger">Couldn&apos;t load template requests. <button className="font-semibold underline" onClick={() => void requests.mutate()}>Retry</button></p> : requests.isLoading ? <p className="text-xs text-ink-muted">Loading requests…</p> : !requests.data?.items.length ? <p className="text-xs text-ink-muted">No template requests.</p> : requests.data.items.map((request) => <TemplateRequest key={request.id} request={request} tenantId={tenantId} onSaved={() => void requests.mutate()} />)}
            {(requests.data?.total ?? 0) > 10 && <div className="flex items-center justify-between gap-2 text-xs text-ink-muted"><span>Page {page}</span><div className="flex gap-2"><button className={buttonClass} disabled={page === 1} onClick={() => setPage((current) => current - 1)}>Previous</button><button className={buttonClass} disabled={page * 10 >= (requests.data?.total ?? 0)} onClick={() => setPage((current) => current + 1)}>Next</button></div></div>}
          </div>
        </details>
      </div>
    </section>
  );
}

function TemplateRequest({ request, tenantId, onSaved }: { request: OperatorSmsTemplateRequest; tenantId: string; onSaved: () => void }) {
  const [status, setStatus] = useState(request.status);
  const [reason, setReason] = useState(request.reason ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    if (!["in_progress", "ready", "rejected"].includes(status)) return;
    setBusy(true);
    setError(null);
    try {
      await updateOperatorSmsTemplateRequest(tenantId, request.id, { status: status as "in_progress" | "ready" | "rejected", reason: reason.trim() });
      onSaved();
      toast.success("Template request updated.");
    } catch (err) { setError(err instanceof Error ? err.message : "Couldn't update template request."); }
    finally { setBusy(false); }
  }
  return <div className="space-y-2 rounded-xl border border-border p-3">
    <p className="whitespace-pre-wrap break-words text-sm text-ink">{request.wording}</p>
    <p className="text-xs text-ink-muted">{request.template_type} · {request.status.replace(/_/g, " ")}</p>
    <div className="flex flex-wrap gap-2">
      <label className="text-xs text-ink-muted">Status<select className={`${inputClass} mt-1`} value={status} disabled={busy} onChange={(event) => setStatus(event.target.value)}><option value="requested" disabled>Requested</option><option value="in_progress">In progress</option><option value="ready">Ready</option><option value="rejected">Rejected</option></select></label>
      <label className="min-w-48 flex-1 text-xs text-ink-muted">Client update<input className={`${inputClass} mt-1`} value={reason} onChange={(event) => setReason(event.target.value)} disabled={busy} placeholder="Approval details or next steps" /></label>
      <button className={`${buttonClass} self-end`} disabled={busy || status === "requested"} onClick={() => void save()}>{busy ? "Saving…" : "Save update"}</button>
    </div>
    {error && <p role="alert" className="text-xs text-danger">{error}</p>}
  </div>;
}
