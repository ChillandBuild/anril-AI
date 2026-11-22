"use client";

import Link from "next/link";
import useSWR from "swr";
import { ArrowRight } from "lucide-react";
import { fetchOtpOverview, type OtpOverview } from "@/lib/otpOverviewApi";
import { cn } from "@/lib/utils";
import { formatIst } from "../../sms/helpers";
import { LoadError, Notice, Skeleton } from "../../sms/ui";
import { SectionCard } from "../otpUi";
import { otpError } from "../otpShared";
import {
  balanceView, changeVsLastMonth, dailyBars, formatIndian, hasAnyCodes, healthDot, percentLabel, problemParts,
  problemsTotal, type ChangeTone, type HealthDot,
} from "./overviewText";

const CHANGE_CLASS: Record<ChangeTone, string> = {
  up: "text-[#067647]",
  down: "text-[#b42318]",
  flat: "text-[#475467]",
  none: "text-[#475467]",
};

const DOT_CLASS: Record<HealthDot["tone"], string> = {
  green: "bg-[#12b76a]",
  amber: "bg-[#f79009]",
  grey: "bg-[#98a2b3]",
};

const labelCls = "text-xs font-bold uppercase tracking-[0.08em] text-[#475467]";
const bigNumberCls = "mt-2 font-display text-[28px] font-bold leading-none tabular-nums text-[#0A1528]";
const thClsOverview = "px-3 py-2 text-left text-xs font-bold uppercase tracking-wider text-[#475467]";
const tdClsOverview = "px-3 py-3 align-top text-sm text-[#334155]";

export function OverviewView() {
  const { data, error, isLoading, mutate } = useSWR("otp:overview-page", fetchOtpOverview, { revalidateOnFocus: false });

  if (error && !data) {
    return (
      <SectionCard title="Overview">
        <LoadError message={otpError(error, "Couldn't load the overview.")} onRetry={() => void mutate()} />
      </SectionCard>
    );
  }
  if (!data) {
    return (
      <div className="space-y-4" aria-busy={isLoading}>
        <Skeleton className="h-14" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }
  return <Loaded data={data} />;
}

function Loaded({ data }: { data: OtpOverview }) {
  return (
    <div className="space-y-4">
      <section aria-label="In short" className="rounded-2xl border border-[#e2e8f0] bg-white px-5 py-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
        <p className={labelCls}>In short</p>
        <p className="mt-1.5 text-base font-semibold text-[#0A1528]">{data.in_short}</p>
      </section>

      {!data.available && (
        <Notice tone="warn">
          {"We couldn't read your code history just now, so the numbers below show zero. Your codes are still being sent. Try again in a little while."}
        </Notice>
      )}

      <Tiles data={data} />

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Where codes come from" description="This month.">
          <Sources data={data} />
        </SectionCard>
        <SectionCard title="Codes per day, last 7 days">
          <DailyBars data={data} />
        </SectionCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <BalanceCard data={data} />
        <SectionCard title="Is everything working?">
          <ul className="divide-y divide-[#eef2f6]">
            {data.health.map((h) => {
              const dot = healthDot(h.ok);
              return (
                <li key={h.key} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                  <span className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", DOT_CLASS[dot.tone])} aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-[#0A1528]">
                      {h.label}
                      <span className="sr-only">: {dot.word}</span>
                    </p>
                    <p className="mt-0.5 break-words text-sm text-[#475467]">{h.detail}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </SectionCard>
      </div>
    </div>
  );
}

function Tile({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("min-w-0 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)] sm:p-5", className)}>
      <p className={labelCls}>{label}</p>
      {children}
    </div>
  );
}

function Tiles({ data }: { data: OtpOverview }) {
  const m = data.month;
  const change = changeVsLastMonth(m);
  const problems = problemsTotal(m);
  const parts = problemParts(m);
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Tile label="Codes sent">
        <p className={bigNumberCls}>{formatIndian(m.sent)}</p>
        <p className={cn("mt-2 text-sm font-medium", CHANGE_CLASS[change.tone])}>{change.text}</p>
      </Tile>
      <Tile label="Used">
        <p className={bigNumberCls}>{percentLabel(m.used_pct)}</p>
        <p className="mt-2 text-sm text-[#475467]">
          {m.used_pct === null ? "Nothing to measure yet" : `${formatIndian(m.verified)} codes used`}
        </p>
      </Tile>
      <Tile label="By WhatsApp">
        <p className={bigNumberCls}>{formatIndian(m.by_whatsapp)}</p>
        <p className="mt-2 text-sm text-[#475467]">
          {m.backups > 0 ? `${formatIndian(m.backups)} as a backup after SMS` : "This month"}
        </p>
      </Tile>
      <Tile label="By SMS">
        <p className={bigNumberCls}>{formatIndian(m.by_sms)}</p>
        <p className="mt-2 text-sm text-[#475467]">This month</p>
      </Tile>
      <Tile label="Problems" className="col-span-2 lg:col-span-1">
        <p className={cn(bigNumberCls, problems > 0 && "text-[#b54708]")}>{formatIndian(problems)}</p>
        {parts.length === 0 ? (
          <p className="mt-2 text-sm text-[#475467]">No problems this month</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {parts.map((p) => (
              <li key={p.status} className="text-sm">
                <Link href={p.href} className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                  {p.text}
                  <ArrowRight size={12} aria-hidden="true" />
                  <span className="sr-only">see History</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Tile>
    </div>
  );
}

function Sources({ data }: { data: OtpOverview }) {
  if (data.sources.length === 0) {
    return <p className="py-6 text-center text-sm text-[#475467]">No codes sent this month yet.</p>;
  }
  return (
    <table className="w-full table-fixed border-collapse">
      <thead>
        <tr className="border-b border-[#eef2f6]">
          <th scope="col" className={thClsOverview}>Source</th>
          <th scope="col" className={cn(thClsOverview, "w-20 text-right")}>Sent</th>
          <th scope="col" className={cn(thClsOverview, "w-20 text-right")}>Used</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-[#eef2f6]">
        {data.sources.map((s) => (
          <tr key={s.key}>
            <td className={cn(tdClsOverview, "break-words font-medium text-[#0A1528]")}>{s.label}</td>
            <td className={cn(tdClsOverview, "text-right tabular-nums")}>{formatIndian(s.sent)}</td>
            <td className={cn(tdClsOverview, "text-right tabular-nums")}>{percentLabel(s.used_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DailyBars({ data }: { data: OtpOverview }) {
  if (!hasAnyCodes(data.daily_7)) {
    return <p className="flex h-40 items-center justify-center text-sm text-[#475467]">No codes in the last 7 days</p>;
  }
  const bars = dailyBars(data.daily_7);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-4 text-sm text-[#475467]">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[2px] bg-primary/25" aria-hidden="true" />
          Sent
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[2px] bg-primary" aria-hidden="true" />
          Used
        </span>
      </div>
      <div role="img" aria-label="Bar chart of codes sent and used on each of the last 7 days" className="flex h-40 items-end gap-1.5">
        {bars.map((b) => (
          <div key={b.day} title={b.title} className="relative flex h-full flex-1 items-end justify-center">
            <div className="relative w-full max-w-[44px] rounded-t-[4px] bg-primary/25" style={{ height: b.sent > 0 ? `max(2px, ${b.sentPct}%)` : "0px" }}>
              {b.verified > 0 && <div className="absolute inset-x-0 bottom-0 rounded-t-[3px] bg-primary" style={{ height: `max(2px, ${b.verifiedPct}%)` }} />}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-1.5">
        {bars.map((b) => (
          <span key={b.day} className="flex-1 text-center text-xs leading-tight tabular-nums text-[#475467]">
            {b.weekday}
            <br />
            {b.dayNumber}
          </span>
        ))}
      </div>
    </div>
  );
}

function BalanceCard({ data }: { data: OtpOverview }) {
  const view = balanceView(data.balance);
  return (
    <SectionCard title="Balance" description="SMS left in your Anril SMS account.">
      <p className={cn("font-display text-[28px] font-bold leading-none tabular-nums", view.low ? "text-[#b54708]" : "text-[#0A1528]")}>
        {view.headline}
      </p>
      {data.balance.checked_at && <p className="mt-2 text-sm text-[#475467]">Checked {formatIst(data.balance.checked_at)}</p>}
      {view.low && <p className="mt-2 text-sm font-medium text-[#b54708]">Running low. Ask your Anril account manager to top up.</p>}
      <p className="mt-3 text-sm text-[#475467]">{view.alertLine}</p>
      <Link href="/dashboard/sms" className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
        Open SMS
        <ArrowRight size={14} aria-hidden="true" />
      </Link>
    </SectionCard>
  );
}
