"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, ExternalLink, Lightbulb, MessageSquareQuote, Users } from "lucide-react";
import { api, type AdPerformanceRow, type InboundResultLabels } from "@/lib/api";
import { useAdPeople } from "@/hooks/useApi";
import { cn } from "@/lib/utils";

/**
 * The lower half of the messaging ad panel: the ad from first look to payment, the
 * money, its ready-made first message, and the people behind its numbers.
 * Every count is the same set as the table row: people who first messaged in the dates.
 */

const DEFAULT_LABELS: InboundResultLabels = { booked: "Booked", paid: "Came / Paid", lost: "Lost" };
const PEOPLE_PAGE = 50;

function countText(value: number) {
  return Math.round(value).toLocaleString("en-IN");
}

function moneyText(value: number | null | undefined) {
  return value == null ? "—" : "₹" + Math.round(value).toLocaleString("en-IN");
}

function pct(part: number, whole: number) {
  const value = (part / whole) * 100;
  return `${value < 10 && value > 0 ? value.toFixed(1) : Math.round(value)}%`;
}

type Step = { label: string; value: number; note: string | null; share: number };

function journeySteps(row: AdPerformanceRow, labels: InboundResultLabels): Step[] {
  const taps = row.inline_link_clicks;
  // Bars are measured against the taps: the people who showed any interest.
  const share = (value: number) => (taps ? Math.min(1, value / taps) : 0);
  return [
    { label: "Saw the ad", value: row.impressions, note: null, share: 1 },
    {
      label: "Tapped to chat",
      value: taps,
      note: taps && row.impressions ? `1 in ${countText(row.impressions / taps)} who saw it` : null,
      share: share(taps),
    },
    { label: "Actually messaged", value: row.messages, note: taps ? `${pct(row.messages, taps)} of taps` : null, share: share(row.messages) },
    { label: "Hot leads", value: row.hot, note: row.messages ? `${pct(row.hot, row.messages)} of chats` : null, share: share(row.hot) },
    { label: labels.booked, value: row.booked, note: row.messages ? `${pct(row.booked, row.messages)} of chats` : null, share: share(row.booked) },
    { label: labels.paid, value: row.paid, note: row.booked ? `${countText(row.paid)} of ${countText(row.booked)} booked` : null, share: share(row.paid) },
  ];
}

/** The step where the most people fall away, with one thing to try. Needs 5+ people at the step before. */
export function biggestDrop(row: AdPerformanceRow, labels: InboundResultLabels): string | null {
  const drops = [
    {
      from: row.inline_link_clicks, to: row.messages,
      tip: () => `Only ${pct(row.messages, row.inline_link_clicks)} of people who tapped sent a message. Keep the ready-made first message short, so sending it takes one tap.`,
    },
    {
      from: row.messages, to: row.hot,
      tip: () => `Only ${pct(row.hot, row.messages)} of chats turned hot. Make the price or offer clear in the ad, so the right people message.`,
    },
    {
      from: row.hot, to: row.booked,
      tip: () => `${countText(row.hot)} hot leads, but ${countText(row.booked)} ${labels.booked.toLowerCase()}. Reply fast and ask them to book right in the chat.`,
    },
    {
      from: row.booked, to: row.paid,
      tip: () => `${countText(row.booked)} ${labels.booked.toLowerCase()}, but ${countText(row.paid)} paid. Send a reminder before the booking time.`,
    },
  ].filter((drop) => drop.from >= 5 && drop.to <= drop.from);
  if (!drops.length) return null;
  const worst = drops.reduce((a, b) => (b.to / b.from < a.to / a.from ? b : a));
  return worst.tip();
}

/** Ads Manager, opened on this one ad. */
function adsManagerUrl(row: AdPerformanceRow) {
  const account = (row.meta_ad_account_id || "").replace(/^act_/, "");
  const qs = new URLSearchParams({ act: account, selected_ad_ids: row.meta_ad_id });
  return `https://adsmanager.facebook.com/adsmanager/manage/ads?${qs}`;
}

const SEGMENTS: Record<string, { label: string; tone: string }> = {
  A: { label: "Hot", tone: "bg-rose-50 text-rose-700" },
  B: { label: "Warm", tone: "bg-amber-50 text-amber-700" },
  C: { label: "Cold", tone: "bg-sky-50 text-sky-700" },
  D: { label: "Not interested", tone: "bg-slate-100 text-slate-600" },
};

const RESULT_TONES: Record<string, string> = {
  paid: "text-emerald-700",
  booked: "text-primary-700",
  lost: "text-slate-500",
};

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <p className="mb-2 mt-7 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">{children}</p>;
}

function PeopleList({ row, dateFrom, dateTo, labels }: {
  row: AdPerformanceRow;
  dateFrom: string;
  dateTo: string;
  labels: InboundResultLabels;
}) {
  const router = useRouter();
  const [shown, setShown] = useState(PEOPLE_PAGE);
  const { data, error, mutate } = useAdPeople(row.ad_creative_id, { date_from: dateFrom, date_to: dateTo });
  const people = data?.data ?? [];

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl border border-surface-mid/70 p-6 text-center">
        <p className="text-xs text-on-surface-muted">Couldn&apos;t load the people right now.</p>
        <button type="button" onClick={() => mutate()}
          className="rounded-full bg-primary-600 px-3 py-1.5 font-label text-xs font-semibold text-white hover:bg-primary-700">
          Try again
        </button>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="divide-y divide-surface-mid/50 rounded-2xl border border-surface-mid/70">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex animate-pulse items-center gap-3 px-3 py-3">
            <div className="h-3 w-32 rounded bg-stone-200" />
            <div className="ml-auto h-3 w-16 rounded bg-stone-200" />
          </div>
        ))}
      </div>
    );
  }
  if (!people.length) {
    return <p className="rounded-2xl border border-surface-mid/70 p-6 text-center text-xs text-on-surface-muted">Nobody messaged from this ad in these dates.</p>;
  }
  return (
    <div className="overflow-hidden rounded-2xl border border-surface-mid/70">
      <ul className="divide-y divide-surface-mid/50">
        {people.slice(0, shown).map((person) => {
          const segment = SEGMENTS[person.segment ?? ""];
          const result = person.result === "none" ? null : labels[person.result];
          return (
            <li key={person.lead_id}>
              <button type="button" onClick={() => router.push(`/dashboard/conversations?lead=${person.lead_id}`)}
                title="Open their chat"
                className="group flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-surface-low/60">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-label text-xs font-bold text-on-surface group-hover:text-primary-700">
                    {person.name?.trim() || person.phone || "Unknown"}
                  </span>
                  {person.name?.trim() && person.phone && (
                    <span className="block truncate text-[10px] text-on-surface-muted">{person.phone}</span>
                  )}
                </span>
                {segment && <span className={cn("shrink-0 rounded-full px-2 py-0.5 font-label text-[10px] font-bold", segment.tone)}>{segment.label}</span>}
                <span className={cn("w-[104px] shrink-0 text-right font-label text-[11px] font-bold", RESULT_TONES[person.result] ?? "text-on-surface-muted")}>
                  <span className="block truncate">{result ?? "—"}</span>
                  {person.result === "paid" && person.earned > 0 && (
                    <span className="block text-[10px] font-semibold tabular-nums">{moneyText(person.earned)}</span>
                  )}
                </span>
                <ChevronRight size={14} className="shrink-0 text-stone-300 group-hover:text-primary-600" />
              </button>
            </li>
          );
        })}
      </ul>
      {people.length > shown && (
        <button type="button" onClick={() => setShown((n) => n + PEOPLE_PAGE)}
          className="w-full border-t border-surface-mid/50 py-2.5 font-label text-xs font-bold text-primary-700 hover:bg-surface-low/60">
          Show more ({countText(people.length - shown)} left)
        </button>
      )}
    </div>
  );
}

export function AdJourney({ row, dateFrom, dateTo }: { row: AdPerformanceRow; dateFrom: string; dateTo: string }) {
  const [labels, setLabels] = useState<InboundResultLabels>(DEFAULT_LABELS);
  const [showPeople, setShowPeople] = useState(false);
  const peopleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.inboundLeads.resultLabels().then(setLabels).catch(() => {});
  }, []);

  useEffect(() => {
    if (showPeople) peopleRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [showPeople]);

  const steps = journeySteps(row, labels);
  const drop = biggestDrop(row, labels);
  const money = [
    { label: "Spent", value: moneyText(row.spend), sub: null },
    { label: "Cost per booking", value: moneyText(row.cost_per_booking), sub: row.booked ? `${countText(row.booked)} ${labels.booked.toLowerCase()}` : "none yet" },
    { label: "Earned", value: moneyText(row.revenue), sub: row.paid ? `from ${countText(row.paid)} paid` : "nobody paid yet", tone: "text-emerald-700" },
    { label: "Back per ₹1", value: row.roas == null ? "—" : `₹${row.roas.toFixed(2)}`, sub: "earned ÷ spent" },
  ];

  return (
    <>
      <SectionTitle>From seeing the ad to paying</SectionTitle>
      <ol className="space-y-1.5 rounded-2xl border border-surface-mid/70 p-3">
        {steps.map((step, index) => (
          <li key={step.label} className="grid grid-cols-[minmax(0,9.5rem)_1fr_auto] items-center gap-3">
            <span className="flex min-w-0 items-center gap-2">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-low font-label text-[10px] font-bold text-on-surface-muted">{index + 1}</span>
              <span className="truncate font-label text-xs font-semibold text-on-surface">{step.label}</span>
            </span>
            <span className="h-2 overflow-hidden rounded-full bg-surface-low" aria-hidden="true">
              <span
                className={cn("block h-full rounded-full", index === 0 ? "bg-primary-200" : index >= 4 ? "bg-emerald-500" : "bg-primary-500")}
                style={{ width: `${Math.max(step.value ? 3 : 0, step.share * 100)}%` }}
              />
            </span>
            <span className="min-w-[5.5rem] text-right">
              <span className="block font-display text-sm font-bold tabular-nums text-on-surface">{countText(step.value)}</span>
              {step.note && <span className="block text-[10px] leading-3 text-on-surface-muted">{step.note}</span>}
            </span>
          </li>
        ))}
      </ol>
      {drop && (
        <p className="mt-2 flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
          <Lightbulb size={14} className="mt-0.5 shrink-0" />
          <span><span className="font-bold">Biggest drop:</span> {drop}</span>
        </p>
      )}

      <SectionTitle>Money</SectionTitle>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {money.map((tile) => (
          <div key={tile.label} className="rounded-2xl border border-surface-mid/70 p-3">
            <p className={cn("font-display text-lg font-bold tabular-nums text-on-surface", tile.tone)}>{tile.value}</p>
            <p className="mt-0.5 font-label text-[10px] text-on-surface-muted">{tile.label}</p>
            {tile.sub && <p className="mt-0.5 text-[10px] text-on-surface-muted">{tile.sub}</p>}
          </div>
        ))}
      </div>

      {row.prefilled_greeting_text?.trim() && (
        <>
          <SectionTitle>Ready-made first message</SectionTitle>
          <p className="flex items-start gap-2 rounded-2xl bg-surface-low/70 p-3 text-xs leading-5 text-on-surface">
            <MessageSquareQuote size={14} className="mt-0.5 shrink-0 text-on-surface-muted" />
            <span className="whitespace-pre-wrap">{row.prefilled_greeting_text.trim()}</span>
          </p>
        </>
      )}

      <div className="mt-6 flex flex-wrap gap-2">
        <button type="button" onClick={() => setShowPeople((open) => !open)} disabled={!row.messages}
          aria-expanded={showPeople}
          className="flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 font-label text-xs font-bold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-40">
          <Users size={13} />
          {showPeople ? "Hide the people" : `See these ${countText(row.messages)} ${row.messages === 1 ? "person" : "people"}`}
        </button>
        {row.meta_ad_id && row.meta_ad_account_id && (
          <a href={adsManagerUrl(row)} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-xl border border-surface-mid bg-white px-3.5 py-2 font-label text-xs font-bold text-on-surface transition-colors hover:border-stone-300">
            Open in Meta <ExternalLink size={12} />
          </a>
        )}
      </div>

      {showPeople && (
        <div ref={peopleRef} className="scroll-mt-4">
          <SectionTitle>The people who messaged</SectionTitle>
          <PeopleList row={row} dateFrom={dateFrom} dateTo={dateTo} labels={labels} />
        </div>
      )}
    </>
  );
}
