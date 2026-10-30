"use client";

import { useState } from "react";
import useSWR from "swr";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, type SmsTemplate, type SmsTemplateType } from "@/lib/api";
import { countVars, formatIst, friendlyError } from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Notice, Skeleton, inputCls } from "./ui";
import { usePerm } from "./usePerm";

export function TemplateList() {
  const { canManage } = usePerm();
  const [sender, setSender] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const { data, error, isLoading, mutate } = useSWR("sms:templates", () => api.sms.templates(), { revalidateOnFocus: false });

  const templates = data?.templates ?? [];
  const senders = Array.from(new Set(templates.map((t) => t.sender_id))).sort();
  const shown = sender ? templates.filter((t) => t.sender_id === sender) : templates;

  async function refresh() {
    setRefreshing(true);
    try {
      // On a Bulk9 failure the server keeps the cached rows and sets `error`, so we always replace the cache with the reply.
      const res = await api.sms.refreshTemplates();
      await mutate(res, { revalidate: false });
      if (res.error) toast.error("Couldn't refresh from the operator. Showing the last saved list.");
      else toast.success("Templates refreshed.");
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't refresh templates"));
    } finally {
      setRefreshing(false);
    }
  }

  async function changeType(t: SmsTemplate, next: SmsTemplateType) {
    if (next === t.template_type) return;
    setSavingId(t.id);
    try {
      const updated = await api.sms.setTemplateType(t.id, next);
      await mutate(
        (cur) => (cur ? { ...cur, templates: cur.templates.map((x) => (x.id === t.id ? { ...x, ...updated } : x)) } : cur),
        { revalidate: false },
      );
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't change the type"));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Your templates"
        hint={data?.last_synced_at ? `Last refreshed ${formatIst(data.last_synced_at)} IST` : "Not refreshed yet"}
        action={
          <div className="flex flex-wrap items-center gap-2">
            {senders.length > 1 && (
              <select aria-label="Filter by sender" className={`${inputCls} w-auto`} value={sender} onChange={(e) => setSender(e.target.value)}>
                <option value="">All senders</option>
                {senders.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            )}
            {canManage && (
              <Btn variant="outline" busy={refreshing} onClick={() => void refresh()}>
                <RefreshCw size={14} /> Refresh
              </Btn>
            )}
          </div>
        }
      />
      <div className="space-y-3 p-4 sm:p-5">
        {data?.error && <Notice tone="danger">{"Couldn't refresh from the operator, so this is the last saved list."} {data.error}</Notice>}
        {isLoading && !data ? (
          <Skeleton className="h-40" />
        ) : error && !data ? (
          <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
        ) : shown.length === 0 ? (
          <Empty title="No templates yet." hint="Once a template is approved on your DLT portal, add it below or press Refresh." />
        ) : (
          <ul className="space-y-3">
            {shown.map((t) => (
              <li key={t.id} className="rounded-xl border border-[#e2e8f0] p-3.5">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge tone="info">Sender {t.sender_id}</Badge>
                  <Badge tone={t.status === "ready" ? "success" : "warn"}>{t.status === "ready" ? "Ready" : "Submitted"}</Badge>
                  <span className="text-xs text-[#64748b]">{Math.max(t.var_count, countVars(t.message))} variable(s)</span>
                  <div className="ml-auto">
                    {canManage ? (
                      <select
                        aria-label="Template type"
                        className="h-8 rounded-lg border border-[#e2e8f0] bg-white px-2 text-xs font-bold text-[#334155] disabled:opacity-50"
                        value={t.template_type}
                        disabled={savingId === t.id}
                        onChange={(e) => void changeType(t, e.target.value as SmsTemplateType)}
                      >
                        <option value="service">Service</option>
                        <option value="promotional">Promotional</option>
                      </select>
                    ) : (
                      <Badge>{t.template_type === "promotional" ? "Promotional" : "Service"}</Badge>
                    )}
                  </div>
                </div>
                <p className="whitespace-pre-wrap break-words text-sm text-[#334155]">{t.message}</p>
                {t.status === "submitted" && <p className="mt-2 text-xs text-[#64748b]">Waiting for approval. It can be used once it shows as Ready.</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
