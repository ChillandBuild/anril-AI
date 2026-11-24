"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Calendar, Check, ChevronDown, ChevronLeft, ChevronRight, Download, X } from "lucide-react";
import { api, API_URL, DealSource, DealStats, getAuthHeaders } from "@/lib/api";
import { SOURCE_LABEL } from "@/lib/deal-filters";
import { cn, istTodayIso } from "@/lib/utils";
import { CompareGrid, MonthGrid, Popover } from "@/components/deals/insights/MonthPicker";
import { KpiStrip } from "@/components/deals/insights/KpiStrip";
import { SalesCalendar } from "@/components/deals/insights/SalesCalendar";
import { TrendChart } from "@/components/deals/insights/TrendChart";
import { Breakdown } from "@/components/deals/insights/Breakdown";
import {
  averageTotals,
  daysInMonth,
  fillDays,
  MAX_COMPARE,
  Metric,
  monthLabel,
  monthsText,
  shiftMonth,
  SOURCE_COLOR,
  SOURCE_ORDER,
  totalsUpTo,
} from "@/components/deals/insights/shared";

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

interface Loaded {
  key: string;
  base: DealStats;
  filtered: DealStats;
  /** One per comparison month, same order as the `vs` months. */
  compare: DealStats[];
}

export function InsightsTab() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const today = istTodayIso();
  const currentMonth = today.slice(0, 7);
  const todayDay = Number(today.slice(8));

  // URL state: ?month=2026-10&vs=2026-07,2026-08|none&src=whatsapp,form — survives refresh and can be shared.
  // No `vs` means "previous month", so that default follows the month being viewed.
  const rawMonth = searchParams.get("month");
  const month = rawMonth && MONTH_RE.test(rawMonth) && rawMonth <= currentMonth ? rawMonth : currentMonth;
  const rawVs = searchParams.get("vs") ?? "";
  const prevMonth = shiftMonth(month, -1);
  const vsKey = useMemo(() => {
    if (rawVs === "none") return "";
    const picked = Array.from(new Set(rawVs.split(",")))
      .filter((m) => MONTH_RE.test(m) && m <= currentMonth && m !== month)
      .sort()
      .slice(-MAX_COMPARE);
    return (picked.length ? picked : [prevMonth]).join(",");
  }, [rawVs, currentMonth, month, prevMonth]);
  const compareMonths = useMemo(() => (vsKey ? vsKey.split(",") : []), [vsKey]);
  const srcParam = searchParams.get("src") ?? "";
  const sources = useMemo(
    () => SOURCE_ORDER.filter((s) => srcParam.split(",").includes(s)),
    [srcParam]
  );

  const [metric, setMetric] = useState<Metric>("revenue");
  const [mode, setMode] = useState<"running" | "daily">("running");
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [data, setData] = useState<Loaded | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [activeMonths, setActiveMonths] = useState<Set<string>>(new Set());
  const requestId = useRef(0);

  const setParams = useCallback(
    (patch: Record<string, string | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === null) params.delete(k);
        else params.set(k, v);
      }
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const loadKey = `${month}|${vsKey}|${sources.join(",")}`;

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError(false);
    try {
      const filteredBy = sources.length > 0 ? sources : undefined;
      const [base, filtered, compare] = await Promise.all([
        api.deals.stats(month),
        filteredBy ? api.deals.stats(month, filteredBy) : Promise.resolve(null),
        Promise.all(compareMonths.map((m) => api.deals.stats(m, filteredBy))),
      ]);
      if (id !== requestId.current) return;
      setData({ key: loadKey, base, filtered: filtered ?? base, compare });
    } catch {
      if (id === requestId.current) setError(true);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [month, compareMonths, sources, loadKey]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setSelectedDay(null);
  }, [month]);

  useEffect(() => {
    api.deals
      .activeMonths()
      .then((res) => setActiveMonths(new Set(res.months)))
      .catch(() => setActiveMonths(new Set()));
  }, []);

  async function downloadExport() {
    setDownloading(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}${api.deals.exportPath(month, "xlsx")}`, { headers: auth });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `deals-${month}.xlsx`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setError(true);
    } finally {
      setDownloading(false);
    }
  }

  function toggleSource(s: DealSource) {
    const next = sources.includes(s) ? sources.filter((x) => x !== s) : [...sources, s];
    setParams({ src: next.length ? next.join(",") : null });
  }

  const days = useMemo(() => fillDays(data?.filtered ?? null, month), [data, month]);
  // Only use comparison data that matches the months asked for (it lags one load behind a change).
  const compares = useMemo(
    () =>
      data && data.compare.length === compareMonths.length
        ? compareMonths.map((m, i) => ({ month: m, days: fillDays(data.compare[i], m) }))
        : [],
    [data, compareMonths]
  );

  if (!data) {
    if (error) {
      return (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-sm text-[#64748b]">Couldn&apos;t load insights.</p>
          <button
            type="button"
            onClick={load}
            className="rounded-xl bg-primary px-4 py-2 text-xs font-bold text-white hover:bg-primary/90"
          >
            Retry
          </button>
        </div>
      );
    }
    return (
      <div className="space-y-3.5">
        <div className="h-9 w-64 animate-pulse rounded-xl bg-[#f1f5f9]" />
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-5">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-2xl bg-[#f1f5f9]" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
          <div className="h-96 animate-pulse rounded-2xl bg-[#f1f5f9]" />
          <div className="h-96 animate-pulse rounded-2xl bg-[#f1f5f9]" />
        </div>
      </div>
    );
  }

  const isCurrent = month === currentMonth;
  const lastDay = isCurrent ? todayDay : daysInMonth(month);
  const now = totalsUpTo(days, lastDay);
  // While a month is running, compare the same dates (1–14) of each comparison month.
  const before = averageTotals(compares.map((c) => totalsUpTo(c.days, isCurrent ? todayDay : c.days.length)));
  const sameDays = isCurrent ? ` 1–${todayDay}` : "";
  const compareText = compares.length
    ? compares.length === 1
      ? `vs ${monthLabel(compares[0].month, true)}${sameDays}`
      : `vs avg of ${compares.length} months${isCurrent ? ` (1–${todayDay})` : ""}`
    : null;
  const compareTitle = compares.length > 1 ? `Average of ${monthsText(compareMonths)}${sameDays ? `, days${sameDays}` : ""}` : undefined;

  const sourceQuery = sources.length ? `&source=${sources.join(",")}` : "";
  const shownSources = SOURCE_ORDER.filter((s) => data.base.by_source[s]?.count || sources.includes(s));
  const lastYear = shiftMonth(month, -12);
  const lastThree = [shiftMonth(month, -3), shiftMonth(month, -2), prevMonth];
  const presets = [
    { months: [prevMonth], label: "Previous month", hint: monthLabel(prevMonth, true) },
    { months: lastThree, label: "Last 3 months", hint: monthsText(lastThree) },
    { months: [lastYear], label: "Same month last year", hint: monthLabel(lastYear, true) },
  ];
  const setCompare = (months: string[]) => {
    const sorted = [...months].sort();
    setParams({ vs: sorted.length === 0 ? "none" : sorted.join(",") === prevMonth ? null : sorted.join(",") });
  };
  const compareLabel =
    compareMonths.length === 0
      ? "Compare with…"
      : compareMonths.length === 1
        ? `Compare: ${monthLabel(compareMonths[0], true)}`
        : `Compare: ${compareMonths.length} months`;
  const stale = loading && data.key !== loadKey;

  return (
    <div className={cn("space-y-3.5 transition-opacity", stale && "opacity-70")}>
      {/* Month, comparison, download */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center overflow-hidden rounded-xl border border-[#e2e8f0] bg-white">
          <button
            type="button"
            onClick={() => setParams({ month: shiftMonth(month, -1) })}
            aria-label="Previous month"
            className="grid h-9 w-9 place-items-center text-[#334155] hover:bg-[#f8fafc]"
          >
            <ChevronLeft size={16} />
          </button>
          <Popover
            trigger={(open, toggle) => (
              <button
                type="button"
                onClick={toggle}
                aria-expanded={open}
                className="flex h-9 items-center gap-1.5 border-x border-[#e2e8f0] px-3 text-[13px] font-extrabold text-[#0A1528] hover:bg-[#f8fafc]"
              >
                <Calendar size={14} className="text-[#64748b]" />
                {monthLabel(month)}
              </button>
            )}
          >
            {(close) => (
              <MonthGrid
                value={month}
                max={currentMonth}
                activeMonths={activeMonths}
                onPick={(m) => {
                  setParams({ month: m === currentMonth ? null : m });
                  close();
                }}
              />
            )}
          </Popover>
          <button
            type="button"
            onClick={() => {
              const next = shiftMonth(month, 1);
              setParams({ month: next === currentMonth ? null : next });
            }}
            disabled={isCurrent}
            aria-label="Next month"
            className="grid h-9 w-9 place-items-center text-[#334155] hover:bg-[#f8fafc] disabled:text-slate-300 disabled:hover:bg-transparent"
          >
            <ChevronRight size={16} />
          </button>
        </div>

        <div className="flex items-center">
          <Popover
            trigger={(open, toggle) => (
              <button
                type="button"
                onClick={toggle}
                aria-expanded={open}
                title={compareMonths.length > 1 ? `Comparing with ${monthsText(compareMonths)}` : undefined}
                className={cn(
                  "flex h-9 items-center gap-1.5 border px-3 text-xs font-bold transition-colors",
                  compareMonths.length
                    ? "rounded-l-xl border-primary bg-primary/5 text-primary"
                    : "rounded-xl border-[#e2e8f0] bg-white text-[#0A1528] hover:border-slate-300"
                )}
              >
                <span className="max-w-[200px] truncate">{compareLabel}</span>
                <ChevronDown size={12} className={cn("shrink-0 transition-transform", open && "rotate-180")} />
              </button>
            )}
          >
            {(close) => (
              <div className="w-[264px]">
                {presets.map((opt) => (
                  <button
                    key={opt.label}
                    type="button"
                    onClick={() => {
                      setCompare(opt.months);
                      close();
                    }}
                    className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-semibold text-[#334155] hover:bg-slate-50"
                  >
                    <span className="min-w-0 truncate">
                      {opt.label} <span className="text-[#94a3b8]">· {opt.hint}</span>
                    </span>
                    {vsKey === [...opt.months].sort().join(",") && <Check size={14} className="shrink-0 text-primary" />}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => {
                    setCompare([]);
                    close();
                  }}
                  className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs font-semibold text-[#334155] hover:bg-slate-50"
                >
                  No comparison
                  {compareMonths.length === 0 && <Check size={14} className="text-primary" />}
                </button>
                <div className="mx-1 mt-1 border-t border-[#f1f5f9] pt-2">
                  <p className="px-1.5 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                    Or pick up to {MAX_COMPARE} months
                  </p>
                  <CompareGrid
                    key={vsKey}
                    picked={compareMonths}
                    max={currentMonth}
                    exclude={month}
                    activeMonths={activeMonths}
                    onApply={(months) => {
                      setCompare(months);
                      close();
                    }}
                  />
                </div>
              </div>
            )}
          </Popover>
          {compareMonths.length > 0 && (
            <button
              type="button"
              onClick={() => setParams({ vs: "none" })}
              aria-label="Stop comparing"
              title="Stop comparing"
              className="grid h-9 w-8 place-items-center rounded-r-xl border border-l-0 border-primary bg-primary/5 text-primary hover:bg-primary/10"
            >
              <X size={13} />
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={downloadExport}
          disabled={downloading}
          title="Excel file of this month's sales for your accountant. Uses the business details from Settings → Business details."
          className="ml-auto flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 text-xs font-bold text-[#0A1528] transition-colors hover:bg-[#f8fafc] disabled:opacity-40"
        >
          <Download size={14} />
          {downloading ? "Preparing…" : "Download for auditor"}
        </button>
      </div>

      {/* Source filter */}
      {(shownSources.length > 1 || sources.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[10px] font-extrabold uppercase tracking-wider text-[#64748b]">Source</span>
          <button
            type="button"
            onClick={() => setParams({ src: null })}
            aria-pressed={sources.length === 0}
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-bold transition-colors",
              sources.length === 0 ? "border-primary bg-primary text-white" : "border-[#e2e8f0] bg-white text-[#334155] hover:border-slate-300"
            )}
          >
            All sources
          </button>
          {shownSources.map((s) => {
            const on = sources.includes(s);
            return (
              <button
                key={s}
                type="button"
                onClick={() => toggleSource(s)}
                aria-pressed={on}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-bold transition-colors",
                  on ? "border-primary bg-primary text-white" : "border-[#e2e8f0] bg-white text-[#334155] hover:border-slate-300"
                )}
              >
                <i className="h-[7px] w-[7px] rounded-[3px]" style={{ background: SOURCE_COLOR[s] }} />
                {SOURCE_LABEL[s]}
              </button>
            );
          })}
        </div>
      )}

      {error && (
        <div className="flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-4 py-2">
          <p className="text-xs text-amber-700">Couldn&apos;t refresh just now. Showing the last numbers that loaded.</p>
          <button type="button" onClick={load} className="text-xs font-bold text-amber-700 hover:opacity-70">
            Retry
          </button>
        </div>
      )}

      <KpiStrip
        metric={metric}
        onMetric={setMetric}
        now={now}
        before={before}
        compareText={compareText}
        compareTitle={compareTitle}
        days={days}
        upTo={lastDay}
        lostCount={data.filtered.lost_count}
        openCount={data.filtered.open_count}
        openTotal={data.filtered.open_total_paise}
        lostHref={`/dashboard/deals?tab=deals&stage=lost${sourceQuery}`}
        openHref={`/dashboard/deals?tab=deals&stage=awaiting_payment${sourceQuery}`}
      />

      {data.base.won_count === 0 && (
        <p className="rounded-xl border border-dashed border-[#e2e8f0] bg-white px-4 py-3 text-xs text-[#64748b]">
          No deals were paid in {monthLabel(month)}{isCurrent ? " yet" : ""}. A deal shows up here on the day it&apos;s marked won.{" "}
          <Link href="/dashboard/deals?tab=deals" className="font-bold text-primary hover:opacity-70">
            Go to deals →
          </Link>
        </p>
      )}

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <SalesCalendar
          month={month}
          days={days}
          metric={metric}
          lastDay={lastDay}
          today={isCurrent ? todayDay : null}
          selectedDay={selectedDay}
          onSelect={setSelectedDay}
        />
        <TrendChart
          month={month}
          days={days}
          lastDay={lastDay}
          today={isCurrent ? todayDay : null}
          compares={compares}
          metric={metric}
          mode={mode}
          onMode={setMode}
          selectedDay={selectedDay}
          onSelect={setSelectedDay}
        />
      </div>

      <Breakdown
        allSources={data.base.by_source}
        selected={sources}
        onToggleSource={toggleSource}
        topItems={data.filtered.top_items}
        lowStock={data.base.low_stock}
      />
    </div>
  );
}
