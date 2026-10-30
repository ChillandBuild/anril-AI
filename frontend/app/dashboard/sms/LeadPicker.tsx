"use client";

import { useState } from "react";
import useSWR from "swr";
import { Search } from "lucide-react";
import { toast } from "sonner";
import { api, type Lead } from "@/lib/api";
import { CheckTick } from "@/components/ui/controls";
import { formatPhone } from "@/lib/utils";
import { MAX_LEADS_PER_CAMPAIGN, errorText, formatCount } from "./helpers";
import { Badge, Btn, Empty, LoadError, inputCls } from "./ui";

const PAGE_SIZE = 50;
const FETCH_PAGE = 200;

const SEGMENTS = [
  { value: "", label: "All segments" },
  { value: "A", label: "Segment A (hot)" },
  { value: "B", label: "Segment B" },
  { value: "C", label: "Segment C" },
  { value: "D", label: "Segment D" },
];

/** Picks leads with the same list/search/segment filters as Leads. Selection is a set of lead ids. */
export function LeadPicker({ selected, onChange }: { selected: Set<string>; onChange: (next: Set<string>) => void }) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [segment, setSegment] = useState("");
  const [page, setPage] = useState(1);
  const [selectingAll, setSelectingAll] = useState(false);

  const { data, error, isLoading, mutate } = useSWR(
    ["sms:lead-picker", query, segment, page],
    () => api.leads.listPage({ search: query || undefined, segment: segment || undefined, page, limit: PAGE_SIZE, sort: "newest" }),
    { keepPreviousData: true, revalidateOnFocus: false },
  );

  const leads = data?.data ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pickable = leads.filter((l) => !!l.phone);
  const allOnPage = pickable.length > 0 && pickable.every((l) => selected.has(l.id));
  const someOnPage = pickable.some((l) => selected.has(l.id));
  const atCap = selected.size >= MAX_LEADS_PER_CAMPAIGN;

  function toggle(lead: Lead) {
    const next = new Set(selected);
    if (next.has(lead.id)) next.delete(lead.id);
    else if (next.size < MAX_LEADS_PER_CAMPAIGN) next.add(lead.id);
    else toast.error(`You can pick up to ${formatCount(MAX_LEADS_PER_CAMPAIGN)} leads per campaign.`);
    onChange(next);
  }

  function togglePage(on: boolean) {
    const next = new Set(selected);
    for (const l of pickable) {
      if (!on) next.delete(l.id);
      else if (next.size < MAX_LEADS_PER_CAMPAIGN) next.add(l.id);
    }
    if (on && next.size >= MAX_LEADS_PER_CAMPAIGN && pickable.some((l) => !next.has(l.id))) {
      toast.error(`Stopped at ${formatCount(MAX_LEADS_PER_CAMPAIGN)} leads, the most one campaign can hold.`);
    }
    onChange(next);
  }

  async function selectAllMatching() {
    setSelectingAll(true);
    try {
      const next = new Set(selected);
      let p = 1;
      let reachedCap = false;
      for (;;) {
        const res = await api.leads.listPage({ search: query || undefined, segment: segment || undefined, page: p, limit: FETCH_PAGE, sort: "newest" });
        for (const l of res.data) {
          if (!l.phone) continue;
          if (next.size >= MAX_LEADS_PER_CAMPAIGN) {
            reachedCap = true;
            break;
          }
          next.add(l.id);
        }
        if (reachedCap || res.data.length < FETCH_PAGE || p * FETCH_PAGE >= res.total) break;
        p += 1;
      }
      onChange(next);
      if (reachedCap) toast.message(`Picked the first ${formatCount(MAX_LEADS_PER_CAMPAIGN)} leads, the most one campaign can hold.`);
    } catch (err) {
      toast.error(errorText(err, "Couldn't load all matching leads"));
    } finally {
      setSelectingAll(false);
    }
  }

  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQuery(search.trim());
        }}
      >
        <div className="relative min-w-[200px] flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
          <input
            type="text"
            aria-label="Search leads"
            placeholder="Search name or number"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`${inputCls} pl-9`}
          />
        </div>
        <select
          aria-label="Segment"
          value={segment}
          onChange={(e) => {
            setSegment(e.target.value);
            setPage(1);
          }}
          className={`${inputCls} w-auto`}
        >
          {SEGMENTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <Btn type="submit" variant="outline">
          Search
        </Btn>
      </form>

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p className="font-bold text-[#0A1528]">
          {formatCount(selected.size)} picked <span className="font-normal text-[#64748b]">of up to {formatCount(MAX_LEADS_PER_CAMPAIGN)}</span>
        </p>
        <div className="flex flex-wrap gap-2">
          {total > 0 && (
            <Btn variant="outline" className="h-8 text-xs" busy={selectingAll} disabled={atCap} onClick={() => void selectAllMatching()}>
              Pick all {formatCount(Math.min(total, MAX_LEADS_PER_CAMPAIGN))} matching
            </Btn>
          )}
          {selected.size > 0 && (
            <Btn variant="link" className="text-xs" onClick={() => onChange(new Set())}>
              Clear
            </Btn>
          )}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-[#e2e8f0]">
        {error && !data ? (
          <LoadError message={errorText(error, "Check your connection and try again.")} onRetry={() => void mutate()} />
        ) : isLoading && !data ? (
          <div className="h-48 animate-pulse bg-border-subtle" />
        ) : leads.length === 0 ? (
          <Empty title="No leads match." hint="Try a different search or segment." />
        ) : (
          <ul className="divide-y divide-[#f1f5f9]">
            <li className="flex items-center gap-3 bg-[#f8fafc] px-3 py-2 text-xs font-bold text-[#64748b]">
              <CheckTick checked={allOnPage} indeterminate={someOnPage && !allOnPage} onChange={togglePage} aria-label="Pick everyone on this page" />
              This page ({pickable.length})
            </li>
            {leads.map((lead) => {
              const noPhone = !lead.phone;
              return (
                <li key={lead.id} className="flex items-center gap-3 px-3 py-2.5">
                  <CheckTick
                    checked={selected.has(lead.id)}
                    disabled={noPhone || (atCap && !selected.has(lead.id))}
                    onChange={() => toggle(lead)}
                    aria-label={`Pick ${lead.name ?? lead.phone ?? "lead"}`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-[#0A1528]">{lead.name || "No name"}</p>
                    <p className="truncate text-xs text-[#64748b]">{noPhone ? "No phone number" : formatPhone(lead.phone)}</p>
                  </div>
                  {lead.opted_out && <Badge tone="warn">Opted out</Badge>}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between text-xs text-[#64748b]">
          <span>
            Page {page} of {formatCount(pages)} · {formatCount(total)} leads
          </span>
          <div className="flex gap-2">
            <Btn variant="outline" className="h-8 text-xs" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Btn>
            <Btn variant="outline" className="h-8 text-xs" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Btn>
          </div>
        </div>
      )}
    </div>
  );
}
