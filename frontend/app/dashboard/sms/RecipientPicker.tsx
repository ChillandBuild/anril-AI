"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { FileSpreadsheet } from "lucide-react";
import { CheckTick } from "@/components/ui/controls";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LeadPicker } from "./LeadPicker";
import {
  MAX_LIST_GROUPS,
  MAX_PASTED_NUMBERS,
  NUMBERS_MODE_LABELS,
  excelSummary,
  errorText,
  formatCount,
  friendlyError,
  parseNumbers,
  skippedRowsCsv,
  type NumbersMode,
  type NumbersState,
} from "./helpers";
import { Btn, ConsentCheck, Field, LoadError, Notice, Skeleton, inputCls, saveCsv, textareaCls } from "./ui";

/** Whether this client has any Anril leads (the Leads mode is hidden when they have none). */
export function useHasLeads(): boolean {
  const probe = useSWR("sms:has-leads", () => api.leads.listPage({ page: 1, limit: 1 }), { revalidateOnFocus: false, shouldRetryOnError: false });
  return (probe.data?.total ?? 0) > 0;
}

/** The four ways to say who gets an SMS: Contact (typed), List (Address Book groups), Excel (upload), Leads. */
export function NumbersPicker({
  value,
  onChange,
  promotional,
  showLeads,
}: {
  value: NumbersState;
  onChange: (update: (prev: NumbersState) => NumbersState) => void;
  promotional: boolean;
  showLeads: boolean;
}) {
  const set = (patch: Partial<NumbersState>) => onChange((prev) => ({ ...prev, ...patch }));
  const modes: NumbersMode[] = showLeads ? ["contact", "list", "excel", "leads"] : ["contact", "list", "excel"];
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Where the numbers come from" className="flex flex-wrap border-b border-[#e9edf2]">
        {modes.map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={value.mode === m}
            onClick={() => set({ mode: m })}
            className={cn(
              "-mb-px h-10 border-b-2 px-4 text-sm",
              value.mode === m ? "border-primary font-extrabold text-[#0A1528]" : "border-transparent font-semibold text-[#64748b] hover:text-[#0A1528]",
            )}
          >
            {NUMBERS_MODE_LABELS[m]}
          </button>
        ))}
      </div>

      {value.mode === "contact" && <NumbersBox value={value.numbersText} onChange={(numbersText) => set({ numbersText })} />}
      {value.mode === "list" && <GroupPicker selected={new Set(value.groupIds)} onChange={(ids) => set({ groupIds: Array.from(ids) })} />}
      {value.mode === "excel" && <ExcelUpload value={value} onChange={onChange} />}
      {value.mode === "leads" && <LeadPicker selected={new Set(value.leadIds)} onChange={(ids) => set({ leadIds: Array.from(ids) })} />}

      {promotional && (value.mode === "contact" || value.mode === "excel") && (
        <div className="space-y-2">
          <Notice tone="warn">This is a promotional SMS. These numbers need your confirmation before you can send.</Notice>
          <ConsentCheck checked={value.consent} onChange={(consent) => set({ consent })} />
        </div>
      )}
    </div>
  );
}

function GroupPicker({ selected, onChange }: { selected: Set<string>; onChange: (next: Set<string>) => void }) {
  const groups = useSWR("sms:contact-groups", () => api.sms.contactGroups(), { revalidateOnFocus: false });
  const list = groups.data?.groups ?? [];
  const picked = list.filter((g) => selected.has(g.id));
  const upTo = picked.reduce((sum, g) => sum + g.contacts, 0);

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else if (next.size < MAX_LIST_GROUPS) next.add(id);
    onChange(next);
  }

  if (groups.isLoading && !groups.data) return <Skeleton className="h-32" />;
  if (groups.error && !groups.data) return <LoadError message={friendlyError(groups.error, "Check your connection.")} onRetry={() => void groups.mutate()} />;
  if (list.length === 0)
    return (
      <div className="rounded-xl border border-dashed border-[#e2e8f0] px-4 py-6 text-center">
        <p className="text-sm font-semibold text-[#0A1528]">Your Address Book has no groups yet.</p>
        <p className="mt-1 text-xs text-[#64748b]">Save contacts there and put them in a group, then pick the group here.</p>
        <Link href="/dashboard/sms/contacts" className="mt-2 inline-block text-sm font-bold text-primary hover:underline">
          Open Address Book →
        </Link>
      </div>
    );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="text-sm font-bold text-[#0A1528]">
        {formatCount(picked.length)} group{picked.length === 1 ? "" : "s"} picked
        {picked.length > 0 && <span className="font-normal text-[#64748b]"> · up to {formatCount(upTo)} contacts (someone in two groups gets one SMS)</span>}
      </p>
        <Link href="/dashboard/sms/contacts" className="text-xs font-bold text-primary hover:underline">
          Manage Address Book →
        </Link>
      </div>
      <ul className="divide-y divide-[#f1f5f9] overflow-hidden rounded-xl border border-[#e2e8f0]">
        {list.map((g) => (
          <li key={g.id} className="flex items-center gap-3 px-3 py-2.5">
            <CheckTick checked={selected.has(g.id)} onChange={() => toggle(g.id)} aria-label={`Pick group ${g.name}`} />
            <span className="min-w-0 flex-1 truncate text-sm font-semibold text-[#0A1528]">{g.name}</span>
            <span className="text-xs text-[#64748b]">
              {formatCount(g.contacts)} contact{g.contacts === 1 ? "" : "s"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NumbersBox({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  const count = parseNumbers(value).length;
  const over = count > MAX_PASTED_NUMBERS;
  return (
    <Field label="Mobile numbers" hint={`One per line (commas work too). Up to ${formatCount(MAX_PASTED_NUMBERS)}.`}>
      <textarea className={cn(textareaCls, "resize-y")} rows={4} value={value} placeholder={"9876543210\n9123456780"} onChange={(e) => onChange(e.target.value)} />
      <span className={cn("mt-1 block text-xs", over ? "font-semibold text-danger" : "text-[#64748b]")}>
        {formatCount(count)} number{count === 1 ? "" : "s"}
        {over ? `, too many. Remove ${formatCount(count - MAX_PASTED_NUMBERS)}.` : ""}
      </span>
    </Field>
  );
}

/** Upload a .csv/.xlsx; the server reads the phone column and hands back the numbers. */
function ExcelUpload({ value, onChange }: { value: NumbersState; onChange: (update: (prev: NumbersState) => NumbersState) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [column, setColumn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);

  async function read(f: File, phoneColumn: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.sms.parseNumbers(f, phoneColumn.trim() || undefined);
      onChange((prev) => ({
        ...prev,
        excelNumbers: r.numbers,
        excel: { fileName: f.name, total: r.total, skipped_total: r.skipped_total, phone_column: r.phone_column, skipped: r.skipped },
      }));
    } catch (err) {
      // The server's own message (for example "save it to the Address Book as a group first") is shown as sent.
      setError(errorText(err, "Couldn't read that file."));
      onChange((prev) => ({ ...prev, excelNumbers: [], excel: null }));
    } finally {
      setBusy(false);
    }
  }

  const info = value.excel;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Excel or CSV file" hint={`.csv or .xlsx, up to ${formatCount(MAX_PASTED_NUMBERS)} numbers`}>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx"
            className="block text-sm text-[#334155] file:mr-3 file:rounded-lg file:border file:border-[#e2e8f0] file:bg-white file:px-3 file:py-2 file:text-sm file:font-bold"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f) void read(f, column);
            }}
          />
        </Field>
        <Field label="Phone column (optional)" hint="Only if it wasn't found">
          <input className={`${inputCls} w-44`} value={column} placeholder="e.g. Mobile" onChange={(e) => setColumn(e.target.value)} />
        </Field>
        {file && (
          <Btn variant="outline" busy={busy} onClick={() => void read(file, column)}>
            Read again
          </Btn>
        )}
      </div>
      {error && <Notice tone="danger">{error}</Notice>}
      {info && !error && (
        <div className="space-y-1 rounded-xl bg-[#f8fafc] p-3.5">
          <p className="flex items-center gap-2 text-sm font-bold text-[#0A1528]">
            <FileSpreadsheet size={15} className="text-primary" /> {excelSummary(info)}
          </p>
          <p className="text-xs text-[#64748b]">
            {info.fileName}
            {info.phone_column ? ` · phone column "${info.phone_column}"` : ""}
          </p>
          {info.skipped.length > 0 && (
            <Btn variant="link" className="text-xs" onClick={() => saveCsv(skippedRowsCsv(info.skipped), "skipped-rows.csv")}>
              Download skipped rows
            </Btn>
          )}
        </div>
      )}
    </div>
  );
}
