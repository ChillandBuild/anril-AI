"use client";

import useSWR from "swr";
import { CheckTick } from "@/components/ui/controls";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LeadPicker } from "./LeadPicker";
import { MAX_PASTED_NUMBERS, buildRecipients, formatCount, friendlyError, parseNumbers, recipientsReady, type RecipientTab } from "./helpers";
import { Empty, Field, LoadError, Skeleton, textareaCls } from "./ui";
import { ConsentCheck } from "./ui";

export interface RecipientState {
  tab: RecipientTab;
  leadIds: Set<string>;
  groupIds: Set<string>;
  numbersText: string;
  consent: boolean;
}

export const EMPTY_RECIPIENTS: RecipientState = { tab: "contacts", leadIds: new Set(), groupIds: new Set(), numbersText: "", consent: false };

const TAB_LABELS: Record<RecipientTab, string> = { contacts: "SMS contacts", leads: "Leads", numbers: "Paste numbers" };

export function recipientsReadyFor(r: RecipientState, promotional: boolean): boolean {
  return recipientsReady({ tab: r.tab, leadIds: Array.from(r.leadIds), groupIds: Array.from(r.groupIds), numbersText: r.numbersText, promotional, consent: r.consent });
}

export function recipientRequest(r: RecipientState, promotional: boolean) {
  return buildRecipients({ tab: r.tab, leadIds: Array.from(r.leadIds), groupIds: Array.from(r.groupIds), numbersText: r.numbersText, promotional, consent: r.consent });
}

/** Source tabs for who gets a campaign: saved contact groups, leads, or pasted numbers. */
export function RecipientPicker({
  value,
  onChange,
  tabs = ["contacts", "leads", "numbers"],
  showConsent = false,
}: {
  value: RecipientState;
  onChange: (next: RecipientState) => void;
  tabs?: RecipientTab[];
  /** Show the promotional consent tick under pasted numbers. */
  showConsent?: boolean;
}) {
  const set = (patch: Partial<RecipientState>) => onChange({ ...value, ...patch });
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Where recipients come from" className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={value.tab === t}
            onClick={() => set({ tab: t })}
            className={cn(
              "h-9 rounded-full border px-4 text-sm font-bold",
              value.tab === t ? "border-primary bg-primary/5 text-primary" : "border-[#e2e8f0] text-[#64748b] hover:border-slate-300",
            )}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {value.tab === "contacts" && <GroupPicker selected={value.groupIds} onChange={(groupIds) => set({ groupIds })} />}
      {value.tab === "leads" && <LeadPicker selected={value.leadIds} onChange={(leadIds) => set({ leadIds })} />}
      {value.tab === "numbers" && (
        <div className="space-y-3">
          <NumbersBox value={value.numbersText} onChange={(numbersText) => set({ numbersText })} />
          {showConsent && <ConsentCheck checked={value.consent} onChange={(consent) => set({ consent })} />}
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
    else next.add(id);
    onChange(next);
  }

  if (groups.isLoading && !groups.data) return <Skeleton className="h-32" />;
  if (groups.error && !groups.data) return <LoadError message={friendlyError(groups.error, "Check your connection.")} onRetry={() => void groups.mutate()} />;
  if (list.length === 0) return <Empty title="No contact groups yet." hint="Add contacts in the Contacts tab and put them in a group first." />;

  return (
    <div className="space-y-2">
      <p className="text-sm font-bold text-[#0A1528]">
        {formatCount(picked.length)} group{picked.length === 1 ? "" : "s"} picked
        {picked.length > 0 && <span className="font-normal text-[#64748b]"> · up to {formatCount(upTo)} contacts (someone in two groups gets one SMS)</span>}
      </p>
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
      <textarea className={textareaCls} rows={8} value={value} placeholder={"9876543210\n9123456780"} onChange={(e) => onChange(e.target.value)} />
      <span className={cn("mt-1 block text-xs", over ? "font-semibold text-danger" : "text-[#64748b]")}>
        {formatCount(count)} number{count === 1 ? "" : "s"}
        {over ? `, too many. Remove ${formatCount(count - MAX_PASTED_NUMBERS)}.` : ""}
      </span>
    </Field>
  );
}
