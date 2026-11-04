"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Copy, FileSpreadsheet, Plus, RefreshCw, Send } from "lucide-react";
import { toast } from "sonner";
import { api, type SmsTemplate } from "@/lib/api";
import { categoryLabel, countVars, formatIst, friendlyError, splitTemplate } from "./helpers";
import { AddTemplatePanel, ListToolbar, TEMPLATES_KEY, TemplateExcelPanel } from "./DltForms";
import { matchesQuery } from "./dltSetup";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Notice, Skeleton } from "./ui";
import { usePerm } from "./usePerm";

export function TemplateList() {
  const { canManage } = usePerm();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [excelOpen, setExcelOpen] = useState(false);
  // One form open at a time, in place under the toolbar.
  const openAdd = () => {
    setExcelOpen(false);
    setAddOpen(true);
  };
  const openExcel = () => {
    setAddOpen(false);
    setExcelOpen(true);
  };
  const [refreshing, setRefreshing] = useState(false);
  const { data, error, isLoading, mutate } = useSWR(TEMPLATES_KEY, () => api.sms.templates(), { revalidateOnFocus: false });

  const templates = data?.templates ?? [];
  const shown = templates.filter(
    (t) => (!status || t.status === status) && matchesQuery([t.message, t.sender_id, t.dlt_template_id, t.entity_name, t.entity_id], query),
  );

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

  return (
    <Card>
      <CardHeader
        title={`Content Template (${templates.length})`}
        hint={data?.last_synced_at ? `Last refreshed ${formatIst(data.last_synced_at)} IST` : "Not refreshed yet"}
      />
      <div className="space-y-3 p-4 sm:p-5">
        <ListToolbar
          query={query}
          onQuery={setQuery}
          placeholder="Search templates"
          status={status}
          onStatus={setStatus}
          options={[
            { value: "", label: "All" },
            { value: "ready", label: "Ready" },
            { value: "submitted", label: "Submitted" },
          ]}
        >
          {canManage && (
            <>
              <Btn variant="outline" busy={refreshing} onClick={() => void refresh()}>
                <RefreshCw size={14} /> Refresh
              </Btn>
              <Btn variant="outline" onClick={openExcel}>
                <FileSpreadsheet size={14} /> Import from DLT Excel
              </Btn>
              <Btn onClick={openAdd}>
                <Plus size={14} /> Add template
              </Btn>
            </>
          )}
        </ListToolbar>
        <AddTemplatePanel open={addOpen} onClose={() => setAddOpen(false)} />
        <TemplateExcelPanel open={excelOpen} onClose={() => setExcelOpen(false)} />
        {data?.error && <Notice tone="danger">{"Couldn't refresh from the operator, so this is the last saved list."} {data.error}</Notice>}
        {isLoading && !data ? (
          <Skeleton className="h-40" />
        ) : error && !data ? (
          <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
        ) : shown.length === 0 ? (
          <Empty
            title={templates.length === 0 ? "No templates yet." : "No templates match."}
            hint={templates.length === 0 ? "Once a template is approved on your DLT portal, add it here or press Refresh." : "Try a different search or status."}
          />
        ) : (
          <ul className="grid gap-3 lg:grid-cols-2">
            {shown.map((t) => (
              <TemplateCard key={t.id} t={t} canSend={canManage} />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied.`);
  } catch {
    toast.error("Couldn't copy. Select it and copy by hand.");
  }
}

/**
 * One template as the SMS people will get: a message bubble with the variables marked, then the few
 * facts that matter (sender, status, DLT category) and the IDs a developer needs, each one tap to copy.
 */
function TemplateCard({ t, canSend }: { t: SmsTemplate; canSend: boolean }) {
  const ready = t.status === "ready";
  const vars = Math.max(t.var_count, countVars(t.message));
  return (
    <li className="flex flex-col gap-3 rounded-xl border border-[#e2e8f0] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#e6f4f4] text-[11px] font-bold text-[#036b6e]" aria-hidden>
          {t.sender_id.slice(0, 2)}
        </span>
        <span className="text-sm font-bold text-[#0A1528]">{t.sender_id}</span>
        <Badge tone={ready ? "success" : "warn"}>{ready ? "Approved" : "Waiting for approval"}</Badge>
        <span className="ml-auto text-xs text-[#64748b]" title="The category DLT approved this template under">
          {categoryLabel(t.template_type)}
        </span>
      </div>
      <p className="whitespace-pre-wrap break-words rounded-2xl rounded-tl-sm bg-[#f1f5f9] px-3.5 py-2.5 text-sm leading-relaxed text-[#1e293b]">
        {splitTemplate(t.message).map((part, i) =>
          part.kind === "text" ? (
            <span key={i}>{part.text}</span>
          ) : (
            <span key={i} className="mx-0.5 rounded bg-[#d9f0f0] px-1.5 py-0.5 text-xs font-bold text-[#036b6e]">
              Variable {part.index + 1}
            </span>
          ),
        )}
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-[#64748b]">
        {t.message_id && (
          <button type="button" onClick={() => void copy(t.message_id!, "Message ID")} className="inline-flex items-center gap-1 hover:text-[#0A1528]" title="Copy the Message ID (used by the API)">
            Message ID <span className="font-bold text-[#0A1528]">{t.message_id}</span> <Copy size={12} />
          </button>
        )}
        {t.dlt_template_id && (
          <button type="button" onClick={() => void copy(t.dlt_template_id!, "DLT template ID")} className="inline-flex items-center gap-1 hover:text-[#0A1528]" title="Copy the DLT template ID">
            DLT ID <span className="font-bold text-[#0A1528]">{t.dlt_template_id}</span> <Copy size={12} />
          </button>
        )}
        <span>{vars === 0 ? "No variables" : `${vars} variable${vars === 1 ? "" : "s"}`}</span>
        {t.entity_name && <span>{t.entity_name}</span>}
      </div>
      {ready && canSend ? (
        <Link href={`/dashboard/sms/send?template=${encodeURIComponent(t.id)}`} className="inline-flex items-center gap-1.5 self-start text-sm font-bold text-primary hover:underline">
          <Send size={14} /> Use this template
        </Link>
      ) : !ready ? (
        <p className="text-xs text-[#64748b]">It can be used once DLT approves it.</p>
      ) : null}
    </li>
  );
}
