"use client";

import { useState } from "react";
import useSWR from "swr";
import { FileSpreadsheet, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { categoryLabel, countVars, formatIst, friendlyError } from "./helpers";
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
          <ul className="space-y-3">
            {shown.map((t) => (
              <li key={t.id} className="rounded-xl border border-[#e2e8f0] p-3.5">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge tone="info">Sender {t.sender_id}</Badge>
                  <Badge tone={t.status === "ready" ? "success" : "warn"}>{t.status === "ready" ? "Ready" : "Submitted"}</Badge>
                  <span className="text-xs text-[#64748b]">{Math.max(t.var_count, countVars(t.message))} variable(s)</span>
                  <span className="ml-auto text-xs text-[#64748b]" title="The category DLT approved this template under">
                    Category: <span className="font-bold text-[#334155]">{categoryLabel(t.template_type)}</span>
                  </span>
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
