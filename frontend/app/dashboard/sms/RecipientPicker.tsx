"use client";

import type { ClipboardEvent } from "react";
import Link from "next/link";
import useSWR from "swr";
import { X } from "lucide-react";
import { CheckTick } from "@/components/ui/controls";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LeadPicker } from "./LeadPicker";
import {
  MAX_LIST_GROUPS,
  MAX_PASTED_NUMBERS,
  MAX_TYPED_ROWS,
  NUMBERS_MODE_LABELS,
  formatCount,
  friendlyError,
  parseNumbers,
  pasteIntoRows,
  type NumbersMode,
  type NumbersState,
  type TypedRow,
} from "./helpers";
import { ConsentCheck, Field, LoadError, Notice, Skeleton, inputCls, textareaCls } from "./ui";

/** Whether this client has any Anril leads (the Leads mode is hidden when they have none). */
export function useHasLeads(): boolean {
  const probe = useSWR("sms:has-leads", () => api.leads.listPage({ page: 1, limit: 1 }), { revalidateOnFocus: false, shouldRetryOnError: false });
  return (probe.data?.total ?? 0) > 0;
}

/**
 * The ways to say who gets an SMS: Contact (typed), List (Address Book groups), Leads. With a
 * variable typed per number (`typedVars`), Contact becomes a table with a value column per variable.
 */
export function NumbersPicker({
  value,
  onChange,
  promotional,
  showLeads,
  typedVars,
}: {
  value: NumbersState;
  onChange: (update: (prev: NumbersState) => NumbersState) => void;
  promotional: boolean;
  showLeads: boolean;
  /** Variable positions typed per number (empty when none). */
  typedVars: number[];
}) {
  const set = (patch: Partial<NumbersState>) => onChange((prev) => ({ ...prev, ...patch }));
  const modes: NumbersMode[] = showLeads ? ["contact", "list", "leads"] : ["contact", "list"];
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

      {value.mode === "contact" &&
        (typedVars.length > 0 ? (
          <TypedNumbersTable rows={value.rows} typedVars={typedVars} onChange={(rows) => set({ rows })} />
        ) : (
          <NumbersBox value={value.numbersText} onChange={(numbersText) => set({ numbersText })} />
        ))}
      {value.mode === "list" && <GroupPicker selected={new Set(value.groupIds)} onChange={(ids) => set({ groupIds: Array.from(ids) })} />}
      {value.mode === "leads" && <LeadPicker selected={new Set(value.leadIds)} onChange={(ids) => set({ leadIds: Array.from(ids) })} />}

      {promotional && value.mode === "contact" && (
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

const cellCls = (bad: boolean) => cn(inputCls, "h-9 px-2.5", bad && "border-danger focus:ring-danger/20");

/**
 * Type numbers with a value per number: a table with the mobile number and one column per typed
 * variable. Columns can be pasted in from Excel; rows are capped at MAX_TYPED_ROWS.
 */
function TypedNumbersTable({ rows, typedVars, onChange }: { rows: TypedRow[]; typedVars: number[]; onChange: (rows: TypedRow[]) => void }) {
  const shown: TypedRow[] = rows.length > 0 ? rows : [{ phone: "", values: [] }];
  const count = shown.filter((r) => r.phone.trim()).length;

  /** Column 0 is the phone; column j is the value for typedVars[j - 1]. */
  function write(r: number, col: number, text: string) {
    onChange(
      shown.map((row, i) => {
        if (i !== r) return row;
        if (col === 0) return { ...row, phone: text };
        const idx = typedVars[col - 1];
        const len = Math.max(row.values.length, idx + 1);
        return { ...row, values: Array.from({ length: len }, (_, k) => (k === idx ? text : (row.values[k] ?? ""))) };
      }),
    );
  }

  /** A paste with tabs or lines is a block of cells (from Excel); a plain paste stays a normal paste. */
  function paste(e: ClipboardEvent<HTMLInputElement>, r: number, col: number) {
    const text = e.clipboardData.getData("text");
    if (!text.includes("\t") && !text.includes("\n")) return;
    e.preventDefault();
    onChange(pasteIntoRows(shown, r, col, text, typedVars));
  }

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-xl border border-[#e2e8f0]">
        <table className="w-full min-w-[420px] text-left">
          <thead className="bg-[#f8fafc] text-xs font-bold text-[#64748b]">
            <tr>
              <th scope="col" className="px-3 py-2">
                Mobile number
              </th>
              {typedVars.map((i) => (
                <th key={i} scope="col" className="px-3 py-2">
                  Variable {i + 1}
                </th>
              ))}
              <th scope="col" className="w-10 px-2 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f1f5f9]">
            {shown.map((row, r) => {
              const phoneBad = !row.phone.trim() && typedVars.some((i) => (row.values[i] ?? "").trim());
              return (
                <tr key={r}>
                  <td className="px-2 py-1.5">
                    <input
                      inputMode="tel"
                      placeholder="9876543210"
                      aria-label={`Mobile number, row ${r + 1}`}
                      aria-invalid={phoneBad || undefined}
                      className={cellCls(phoneBad)}
                      value={row.phone}
                      onChange={(e) => write(r, 0, e.target.value)}
                      onPaste={(e) => paste(e, r, 0)}
                    />
                  </td>
                  {typedVars.map((i, j) => {
                    const bad = row.phone.trim() !== "" && !(row.values[i] ?? "").trim();
                    return (
                      <td key={i} className="px-2 py-1.5">
                        <input
                          aria-label={`Variable ${i + 1}, row ${r + 1}`}
                          aria-invalid={bad || undefined}
                          className={cellCls(bad)}
                          value={row.values[i] ?? ""}
                          maxLength={100}
                          onChange={(e) => write(r, j + 1, e.target.value)}
                          onPaste={(e) => paste(e, r, j + 1)}
                        />
                      </td>
                    );
                  })}
                  <td className="px-2 py-1.5 text-right">
                    {shown.length > 1 && (
                      <button
                        type="button"
                        aria-label={`Remove row ${r + 1}`}
                        onClick={() => onChange(shown.filter((_, k) => k !== r))}
                        className="grid h-8 w-8 place-items-center rounded-lg text-[#64748b] hover:bg-[#f1f5f9] hover:text-danger"
                      >
                        <X size={16} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => onChange([...shown, { phone: "", values: [] }])}
          disabled={shown.length >= MAX_TYPED_ROWS}
          className="text-sm font-bold text-primary hover:underline disabled:opacity-40 disabled:no-underline"
        >
          + Add row
        </button>
        <Link href="/dashboard/sms/contacts" className="text-xs font-bold text-primary hover:underline">
          For bigger lists, use the Address Book →
        </Link>
      </div>
      <p className="text-xs text-[#64748b]">
        {formatCount(count)} number{count === 1 ? "" : "s"} · up to {MAX_TYPED_ROWS}. Tip: copy the columns from Excel and paste them into the first box.
      </p>
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
