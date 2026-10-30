"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { api, type SmsTemplateType } from "@/lib/api";
import { formatIst, friendlyError, humanizeKind } from "./helpers";
import type { Tone } from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, Field, LoadError, Skeleton, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

function requestTone(status: string): Tone {
  if (status === "ready") return "success";
  if (status === "rejected") return "danger";
  if (status === "in_progress") return "info";
  return "warn";
}

export function TemplateRequests() {
  const { canManage } = usePerm();
  const [wording, setWording] = useState("");
  const [type, setType] = useState<SmsTemplateType>("service");
  const [busy, setBusy] = useState(false);
  const { data, error, isLoading, mutate } = useSWR("sms:template-requests", () => api.sms.templateRequests(), { revalidateOnFocus: false });
  const requests = data?.requests ?? [];

  async function submit() {
    if (busy) return;
    setBusy(true);
    try {
      await api.sms.requestTemplate({ wording: wording.trim(), template_type: type });
      toast.success("Request sent. We'll get it approved for you.");
      setWording("");
      await mutate();
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't send the request"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Request a template" hint="Describe the message you want. Our team registers it with DLT for you." />
      <div className="space-y-4 p-4 sm:p-5">
        {canManage && (
          <div className="space-y-3">
            <Field label="Wording" hint="Use {#var#} where a value changes, e.g. Hi {#var#}, your visit is on {#var#}.">
              <textarea className={textareaCls} rows={3} maxLength={1000} value={wording} onChange={(e) => setWording(e.target.value)} />
            </Field>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Type" className="w-48">
                <select className={inputCls} value={type} onChange={(e) => setType(e.target.value as SmsTemplateType)}>
                  <option value="service">Service</option>
                  <option value="promotional">Promotional</option>
                </select>
              </Field>
              <Btn busy={busy} disabled={wording.trim().length < 5} onClick={() => void submit()}>
                Send request
              </Btn>
            </div>
          </div>
        )}
        <div>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-[#64748b]">My requests</h3>
          {isLoading && !data ? (
            <Skeleton className="h-24" />
          ) : error && !data ? (
            <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
          ) : requests.length === 0 ? (
            <Empty title="No requests yet." />
          ) : (
            <ul className="space-y-2">
              {requests.map((r) => (
                <li key={r.id} className="rounded-xl border border-[#e2e8f0] p-3">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <Badge tone={requestTone(r.status)}>{humanizeKind(r.status)}</Badge>
                    <Badge>{r.template_type === "promotional" ? "Promotional" : "Service"}</Badge>
                    <span className="text-xs text-[#64748b]">{formatIst(r.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-sm text-[#334155]">{r.wording}</p>
                  {r.reason && <p className="mt-1.5 text-xs font-semibold text-[#be123c]">Reason: {r.reason}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  );
}
