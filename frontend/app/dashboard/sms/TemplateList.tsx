"use client";

import { useState } from "react";
import useSWR from "swr";
import { FileSpreadsheet, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { formatIst, friendlyError, sendersFrom } from "./helpers";
import { AddTemplatePanel, ListToolbar, TEMPLATES_KEY, TemplateExcelPanel } from "./DltForms";
import { matchesQuery } from "./dltSetup";
import { SenderChips, TemplateCard } from "./TemplateCard";
import { Btn, Card, CardHeader, Empty, LoadError, Notice, Skeleton } from "./ui";
import { usePerm } from "./usePerm";

export function TemplateList() {
  const { canManage } = usePerm();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [sender, setSender] = useState("");
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
  const senders = sendersFrom(templates);
  const shown = templates.filter(
    (t) => (!sender || t.sender_id === sender) && (!status || t.status === status) && matchesQuery([t.message, t.sender_id, t.dlt_template_id, t.entity_name, t.entity_id], query),
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
        {senders.length > 1 && <SenderChips label="Filter by sender" senders={senders} value={sender} onChange={setSender} all={templates.length} />}
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
            hint={templates.length === 0 ? "Once a template is approved on your DLT portal, add it here or press Refresh." : "Try a different sender, search or status."}
          />
        ) : (
          <ul className="grid gap-3 lg:grid-cols-2">
            {shown.map((t) => (
              <TemplateCard key={t.id} t={t} variant="full" canSend={canManage} />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
