"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { FileSpreadsheet, Plus } from "lucide-react";
import { api, type SmsDltEntity, type SmsDltSender } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AddEntityPanel } from "./AddEntityTab";
import { AddSenderPanel, DltStatusBadge, ListToolbar, SenderExcelPanel, TEMPLATES_KEY, useDltList } from "./DltForms";
import { matchesQuery, setupSubFor, type DltSub } from "./dltSetup";
import { formatIst, friendlyError } from "./helpers";
import { TemplatesTab } from "./TemplatesTab";
import { Btn, Card, CardHeader, Empty, LoadError, Notice, Skeleton, TableWrap, tdCls, thCls } from "./ui";
import { usePerm } from "./usePerm";

type Inner = "entity" | "sender" | "template";

const SUB_OF: Record<Inner, DltSub> = { entity: "entities", sender: "senders", template: "templates" };
const INNER_OF: Record<DltSub, Inner> = { entities: "entity", senders: "sender", templates: "template" };

const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "approved", label: "Approved" },
  { value: "submitted", label: "Submitted" },
];

function EntityTable({ rows }: { rows: SmsDltEntity[] }) {
  const { canManage } = usePerm();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const shown = rows.filter((r) => (!status || r.status === status) && matchesQuery([r.entity_id, r.entity_name], query));
  return (
    <div className="space-y-3 p-4 sm:p-5">
      <ListToolbar query={query} onQuery={setQuery} placeholder="Search entities" status={status} onStatus={setStatus} options={STATUS_OPTIONS}>
        {canManage && (
          <Btn onClick={() => setAddOpen(true)}>
            <Plus size={14} /> Add entity
          </Btn>
        )}
      </ListToolbar>
      <AddEntityPanel open={addOpen} onClose={() => setAddOpen(false)} />
      {shown.length === 0 ? (
        <Empty title={rows.length === 0 ? "No entities yet." : "No entities match."} hint={rows.length === 0 ? "Press Add entity to submit your DLT entity." : "Try a different search or status."} />
      ) : (
        <TableWrap>
          <table className="w-full min-w-[34rem]">
            <thead>
              <tr className="border-b border-[#e2e8f0]">
                <th className={thCls}>S.No</th>
                <th className={thCls}>Entity ID</th>
                <th className={thCls}>Name</th>
                <th className={thCls}>Status</th>
                <th className={thCls}>Date</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={r.entity_id} className="border-b border-[#f1f5f9] last:border-0">
                  <td className={tdCls}>{i + 1}</td>
                  <td className={cn(tdCls, "font-mono text-xs")}>{r.entity_id}</td>
                  <td className={tdCls}>{r.entity_name || "—"}</td>
                  <td className={tdCls}>
                    <DltStatusBadge status={r.status} />
                  </td>
                  <td className={cn(tdCls, "whitespace-nowrap")}>{formatIst(r.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </div>
  );
}

function SenderTable({ rows }: { rows: SmsDltSender[] }) {
  const { canManage } = usePerm();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [excelOpen, setExcelOpen] = useState(false);
  const shown = rows.filter((r) => (!status || r.status === status) && matchesQuery([r.sender_id, r.entity_id, r.entity_name], query));
  return (
    <div className="space-y-3 p-4 sm:p-5">
      <ListToolbar query={query} onQuery={setQuery} placeholder="Search sender IDs" status={status} onStatus={setStatus} options={STATUS_OPTIONS}>
        {canManage && (
          <>
            <Btn variant="outline" onClick={() => setExcelOpen(true)}>
              <FileSpreadsheet size={14} /> Import from DLT Excel
            </Btn>
            <Btn onClick={() => setAddOpen(true)}>
              <Plus size={14} /> Add sender ID
            </Btn>
          </>
        )}
      </ListToolbar>
      <AddSenderPanel open={addOpen} onClose={() => setAddOpen(false)} />
      <SenderExcelPanel open={excelOpen} onClose={() => setExcelOpen(false)} />
      {shown.length === 0 ? (
        <Empty title={rows.length === 0 ? "No sender IDs yet." : "No sender IDs match."} hint={rows.length === 0 ? "Add one, or import your DLT sender export." : "Try a different search or status."} />
      ) : (
        <TableWrap>
          <table className="w-full min-w-[30rem]">
            <thead>
              <tr className="border-b border-[#e2e8f0]">
                <th className={thCls}>Sender ID</th>
                <th className={thCls}>Entity</th>
                <th className={thCls}>Status</th>
                <th className={thCls}>Date</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.entity_id}-${r.sender_id}`} className="border-b border-[#f1f5f9] last:border-0">
                  <td className={cn(tdCls, "font-bold text-[#0A1528]")}>{r.sender_id}</td>
                  <td className={tdCls}>
                    {r.entity_name && <div>{r.entity_name}</div>}
                    <div className="font-mono text-xs text-[#64748b]">{r.entity_id}</div>
                  </td>
                  <td className={tdCls}>
                    <DltStatusBadge status={r.status} />
                  </td>
                  <td className={cn(tdCls, "whitespace-nowrap")}>{formatIst(r.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </div>
  );
}

export function DltManagerTab() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  // The sub-tab lives in the URL (?sub=senders) so dashboard links can open the right one. Old ?tab= links still work.
  const inner = INNER_OF[setupSubFor(params.get("tab"), params.get("sub"))];
  const setInner = (next: Inner) => router.replace(`${pathname}?sub=${SUB_OF[next]}`, { scroll: false });
  const { data, error, isLoading, mutate } = useDltList();
  const templates = useSWR(TEMPLATES_KEY, () => api.sms.templates(), { revalidateOnFocus: false });
  const entities = data?.entities ?? [];
  const senders = data?.senders ?? [];
  const tabs: { key: Inner; label: string; count: number | null }[] = [
    { key: "entity", label: "Entity ID", count: data ? entities.length : null },
    { key: "sender", label: "Sender ID", count: data ? senders.length : null },
    { key: "template", label: "Content Template", count: templates.data ? templates.data.templates.length : null },
  ];

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="DLT Manager" className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={inner === t.key}
            onClick={() => setInner(t.key)}
            className={cn(
              "h-9 rounded-xl border px-3.5 text-sm font-bold transition-colors",
              inner === t.key ? "border-primary bg-primary/5 text-primary" : "border-[#e2e8f0] bg-white text-[#64748b] hover:text-[#0A1528]",
            )}
          >
            {t.label}
            {t.count !== null ? ` (${t.count})` : ""}
          </button>
        ))}
      </div>

      {inner === "template" ? (
        <TemplatesTab />
      ) : (
        <Card>
          <CardHeader
            title={inner === "entity" ? "Entity IDs" : "Sender IDs"}
            hint={inner === "entity" ? "Submitted until it shows up on an approved sender or template, then Approved." : "Submitted until the operator lists it, then Approved."}
          />
          {data?.error && (
            <div className="px-4 pt-4 sm:px-5">
              <Notice tone="warn">{"Couldn't read the latest from the operator, so approved rows may be missing."} {data.error}</Notice>
            </div>
          )}
          {isLoading && !data ? (
            <div className="p-4 sm:p-5">
              <Skeleton className="h-40" />
            </div>
          ) : error && !data ? (
            <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
          ) : inner === "entity" ? (
            <EntityTable rows={entities} />
          ) : (
            <SenderTable rows={senders} />
          )}
        </Card>
      )}
    </div>
  );
}
