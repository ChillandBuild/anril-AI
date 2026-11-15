"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ChevronRight, RotateCw, Search } from "lucide-react";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { api, type OtpHistoryFilters, type OtpHistoryItem, type OtpStats } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatCount, formatIst, type Tone } from "../sms/helpers";
import { Btn, LoadError, Notice, Skeleton, TableWrap, inputCls, tdCls, thCls } from "../sms/ui";
import { Drawer, ChannelIcon, KpiTile, SectionCard, StatusPill, Timeline, ResultStatus, ChannelStatus, percent } from "./otpUi";
import { ORIGIN_LABELS, modeShortLabel, otpError, otpTimeline, sourceLabel } from "./otpShared";

const PAGE = 25;
const SEARCH_DEBOUNCE_MS = 300;

type Status = OtpHistoryItem["status"];
type Origin = OtpHistoryItem["origin"];
type Range = "7" | "30" | "90";

const STATUS_VALUES: Status[] = ["pending", "verified", "expired", "locked", "not_requested", "failed"];

const RESULT_OPTIONS: { value: Status | ""; label: string }[] = [
  { value: "", label: "All results" },
  { value: "pending", label: "Waiting" },
  { value: "verified", label: "Verified" },
  { value: "expired", label: "Expired" },
  { value: "locked", label: "Locked" },
  { value: "failed", label: "Not delivered" },
  { value: "not_requested", label: "Customer didn't ask" },
];

const CHANNEL_OPTIONS = [
  { value: "all", label: "All" },
  { value: "sms", label: "SMS" },
  { value: "whatsapp", label: "WhatsApp" },
] as const;

type Channel = (typeof CHANNEL_OPTIONS)[number]["value"];

const RANGE_OPTIONS: { value: Range; label: string }[] = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
];

type Filters = { status: Status | ""; channel: Channel; origin: Origin | ""; q: string };

const NO_FILTERS: Filters = { status: "", channel: "all", origin: "", q: "" };

function toApiFilters(f: Filters): OtpHistoryFilters {
  return {
    status: f.status || undefined,
    channel: f.channel === "all" ? undefined : f.channel,
    origin: f.origin || undefined,
    q: f.q.trim() || undefined,
  };
}

function hasFilters(f: Filters): boolean {
  return f.status !== "" || f.channel !== "all" || f.origin !== "" || f.q.trim() !== "";
}

function readStatus(raw: string | null): Status | "" {
  return STATUS_VALUES.find((s) => s === raw) ?? "";
}

/** Paging state for "Load more", tied to the filters it was loaded with. */
type Paging = { key: string; items: OtpHistoryItem[]; exhausted: boolean; busy: boolean; error: string };

export function HistoryTab() {
  const params = useSearchParams();

  // URL params are read once, on mount: ?status= pre-sets the Result filter, ?open= opens that code.
  const [status, setStatus] = useState<Status | "">(() => readStatus(params.get("status")));
  const [openId, setOpenId] = useState<string | null>(() => params.get("open") || null);
  const [channel, setChannel] = useState<Channel>("all");
  const [origin, setOrigin] = useState<Origin | "">("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [range, setRange] = useState<Range>("7");

  const searchTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(searchTimer.current), []);

  function onSearch(value: string) {
    setSearch(value);
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => setQ(value), SEARCH_DEBOUNCE_MS);
  }

  const filters: Filters = { status, channel, origin, q };
  const filterKey = JSON.stringify(filters);
  const filtered = hasFilters(filters);

  const history = useSWR(
    ["otp:history", filterKey],
    () => api.otp.history({ ...toApiFilters(filters), limit: PAGE }),
    { revalidateOnFocus: false, keepPreviousData: true },
  );

  const days = Number(range) as 7 | 30 | 90;
  const stats = useSWR(["otp:stats", days], () => api.otp.stats(days), { revalidateOnFocus: false, keepPreviousData: true });

  const detailId = openId;
  const detail = useSWR(detailId ? ["otp:detail", detailId] : null, () => api.otp.historyItem(detailId ?? ""), {
    revalidateOnFocus: false,
  });

  // Pages after the first, loaded with "Load more". The first page lives in SWR.
  const [paging, setPaging] = useState<Paging>({ key: "", items: [], exhausted: false, busy: false, error: "" });
  const generation = useRef(0);
  const pageState: Paging = paging.key === filterKey ? paging : { key: filterKey, items: [], exhausted: false, busy: false, error: "" };

  const data = history.data;
  const items = [...(data?.items ?? []), ...pageState.items];
  const canLoadMore = !pageState.exhausted && (data?.items.length ?? 0) === PAGE;

  async function loadMore() {
    const last = items[items.length - 1];
    if (!last) return;
    const key = filterKey;
    const gen = generation.current;
    setPaging({ key, items: pageState.items, exhausted: false, busy: true, error: "" });
    try {
      const res = await api.otp.history({ ...toApiFilters(filters), before: last.created_at, limit: PAGE });
      if (gen !== generation.current) return;
      setPaging((prev) =>
        prev.key !== key ? prev : { key, items: [...prev.items, ...res.items], exhausted: res.items.length < PAGE, busy: false, error: "" },
      );
    } catch (err) {
      if (gen !== generation.current) return;
      setPaging((prev) => (prev.key !== key ? prev : { ...prev, busy: false, error: otpError(err, "Couldn't load more. Try again.") }));
    }
  }

  function refresh() {
    generation.current += 1;
    setPaging({ key: filterKey, items: [], exhausted: false, busy: false, error: "" });
    void history.mutate();
  }

  function clearFilters() {
    window.clearTimeout(searchTimer.current);
    setStatus(NO_FILTERS.status);
    setChannel(NO_FILTERS.channel);
    setOrigin(NO_FILTERS.origin);
    setSearch("");
    setQ("");
  }

  const openItem = openId ? items.find((i) => i.otp_id === openId) : undefined;
  const drawerItem = detail.data?.item ?? openItem;

  const s = stats.data;
  const statsFailed = !!stats.error && !s;
  const problems = s ? s.by_status.failed + s.by_status.locked + s.by_status.not_requested : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Overview</p>
        <SegmentedControl
          size="sm"
          aria-label="Summary period"
          value={range}
          onChange={setRange}
          options={RANGE_OPTIONS}
        />
      </div>

      {statsFailed ? (
        <Notice tone="danger">
          <span>{"Couldn't load the summary. "}</span>
          <Btn variant="link" className="h-auto" onClick={() => void stats.mutate()}>
            Try again
          </Btn>
        </Notice>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile label="Codes sent" value={s ? formatCount(s.total) : "—"} sub={s ? `${formatCount(s.sms.sent)} by SMS · ${formatCount(s.whatsapp.sent)} by WhatsApp` : undefined} loading={!s} />
            <KpiTile
              label="Delivered"
              value={s ? percent(s.delivered_rate) : "—"}
              sub={s ? `${formatCount(s.delivered)} of ${formatCount(s.total)} reached the phone` : undefined}
              loading={!s}
            />
            <KpiTile
              label="Verified"
              value={s ? percent(s.verified_rate) : "—"}
              sub={s ? `${formatCount(s.by_status.verified)} of ${formatCount(s.anril_made)} codes Anril made` : undefined}
              hint="Codes your server makes are checked on your side, so they aren't counted here."
              loading={!s}
            />
            <KpiTile
              label="Problems"
              value={s ? formatCount(problems) : "—"}
              sub={s ? `${formatCount(s.by_status.failed)} not delivered · ${formatCount(s.by_status.locked)} locked · ${formatCount(s.by_status.not_requested)} not asked for` : undefined}
              loading={!s}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <SectionCard title="Codes per day">
              {s ? <DailyBars days={s.daily} /> : <Skeleton className="h-40" />}
            </SectionCard>
            <SectionCard title="By channel">
              {s ? <ChannelSummary stats={s} /> : <Skeleton className="h-40" />}
            </SectionCard>
          </div>
        </>
      )}

      <SectionCard title="All codes" description="Newest first. Click a row for the full story.">
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <div className="relative w-full sm:w-64">
              <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              <input
                type="search"
                value={search}
                onChange={(e) => onSearch(e.target.value)}
                placeholder="Search by phone number"
                aria-label="Search by phone number"
                className={cn(inputCls, "pl-9")}
              />
            </div>
            <select
              aria-label="Filter by result"
              value={status}
              onChange={(e) => setStatus(e.target.value as Status | "")}
              className={cn(inputCls, "w-auto min-w-[10rem]")}
            >
              {RESULT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <SegmentedControl size="sm" aria-label="Filter by channel" value={channel} onChange={setChannel} options={[...CHANNEL_OPTIONS]} />
            <select
              aria-label="Filter by source"
              value={origin}
              onChange={(e) => setOrigin(e.target.value as Origin | "")}
              className={cn(inputCls, "w-auto min-w-[10rem]")}
            >
              <option value="">All sources</option>
              {(Object.keys(ORIGIN_LABELS) as Origin[]).map((o) => (
                <option key={o} value={o}>
                  {ORIGIN_LABELS[o]}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={refresh}
              aria-label="Refresh"
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-[#475569] transition-colors hover:bg-[#f8fafc] hover:text-[#0A1528] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              <RotateCw size={16} className={cn(history.isValidating && !history.isLoading && "animate-spin")} aria-hidden="true" />
            </button>
            {filtered && (
              <Btn variant="link" className="h-10" onClick={clearFilters}>
                Clear filters
              </Btn>
            )}
          </div>

          {history.error && !data ? (
            <LoadError message={otpError(history.error, "Try again in a moment.")} onRetry={refresh} />
          ) : history.isLoading || !data ? (
            <div className="space-y-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : items.length === 0 ? (
            filtered ? (
              <div className="px-4 py-10 text-center">
                <p className="text-sm font-semibold text-[#0A1528]">No codes match these filters</p>
                <p className="mt-1 text-xs text-[#64748b]">Try a different result, channel or source.</p>
                <Btn variant="outline" className="mt-4 h-9" onClick={clearFilters}>
                  Clear filters
                </Btn>
              </div>
            ) : (
              <div className="px-4 py-10 text-center">
                <p className="text-sm font-semibold text-[#0A1528]">No codes yet</p>
                <p className="mt-1 text-xs text-[#64748b]">Codes sent from Send &amp; check, the API or the WhatsApp bot show up here.</p>
              </div>
            )
          ) : (
            <div className="relative overflow-hidden rounded-xl border border-[#e2e8f0]">
              <TableWrap>
                <table className="w-full min-w-[880px]">
                  <thead className="bg-[#f8fafc]">
                    <tr>
                      <th className={thCls}>Time</th>
                      <th className={thCls}>Phone</th>
                      <th className={thCls}>Way</th>
                      <th className={thCls}>Code</th>
                      <th className={thCls}>SMS</th>
                      <th className={thCls}>WhatsApp</th>
                      <th className={thCls}>Result</th>
                      <th className={thCls}>Source</th>
                      <th className={thCls}>
                        <span className="sr-only">Open</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it) => (
                      <HistoryRow key={it.otp_id} item={it} onOpen={() => setOpenId(it.otp_id)} />
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </div>
          )}

          {data && items.length > 0 && (
            <div className="flex flex-col items-center gap-2">
              {pageState.error && <Notice tone="danger" className="w-full">{pageState.error}</Notice>}
              {canLoadMore && (
                <Btn variant="outline" className="h-9" busy={pageState.busy} onClick={() => void loadMore()}>
                  Load more
                </Btn>
              )}
            </div>
          )}
        </div>
      </SectionCard>

      <Drawer
        open={openId !== null}
        onClose={() => setOpenId(null)}
        title={drawerItem?.phone ?? "Code details"}
        subtitle={drawerItem ? formatIst(drawerItem.created_at) : undefined}
      >
        {detail.error && !detail.data ? (
          <LoadError message={otpError(detail.error, "Try again in a moment.")} onRetry={() => void detail.mutate()} />
        ) : !detail.data ? (
          <div className="space-y-4">
            <Skeleton className="h-16" />
            <Skeleton className="h-40" />
          </div>
        ) : (
          <OtpDetail item={detail.data.item} updates={detail.data.updates} />
        )}
      </Drawer>
    </div>
  );
}

function splitIst(iso: string): [string, string] {
  const text = formatIst(iso);
  const at = text.indexOf(", ");
  return at < 0 ? [text, ""] : [text.slice(0, at), text.slice(at + 2)];
}

function HistoryRow({ item, onOpen }: { item: OtpHistoryItem; onOpen: () => void }) {
  function onKey(e: KeyboardEvent<HTMLTableRowElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    }
  }
  const [date, time] = splitIst(item.created_at);
  return (
    <tr
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKey}
      className="group cursor-pointer border-t border-[#e2e8f0] transition-colors hover:bg-[#f8fafc] focus-visible:bg-[#f8fafc] focus-visible:outline-none"
    >
      <td className={cn(tdCls, "whitespace-nowrap")}>
        <span className="block text-[#0A1528]">{date}</span>
        {time && <span className="block text-xs tabular-nums text-[#64748b]">{time}</span>}
      </td>
      <td className={cn(tdCls, "whitespace-nowrap font-semibold tabular-nums text-[#0A1528]")}>{item.phone}</td>
      <td className={cn(tdCls, "whitespace-nowrap")}>
        {modeShortLabel(item.mode)}
        <span className="block text-xs text-[#64748b]">Made by {item.source === "anril" ? "Anril" : "your server"}</span>
      </td>
      <td className={cn(tdCls, "whitespace-nowrap font-mono")}>{item.code || "—"}</td>
      <td className={tdCls}>
        <ChannelStatus status={item.sms.status} />
      </td>
      <td className={tdCls}>
        <ChannelStatus status={item.whatsapp.status} />
      </td>
      <td className={tdCls}>
        <div className="flex flex-wrap gap-1.5">
          <ResultStatus status={item.status} />
          {item.not_requested && item.status !== "not_requested" && <StatusPill tone="danger">Didn&apos;t ask</StatusPill>}
        </div>
      </td>
      <td className={cn(tdCls, "whitespace-nowrap")}>{ORIGIN_LABELS[item.origin]}</td>
      <td className="w-8 px-2 py-3 align-middle">
        <ChevronRight size={16} aria-hidden="true" className="text-[#cbd5e1] transition-colors group-hover:text-[#64748b]" />
      </td>
    </tr>
  );
}

function OtpDetail({ item: it, updates }: { item: OtpHistoryItem; updates: { event: string; status: string; attempts: number; last_error: string | null; created_at: string }[] }) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <ResultStatus status={it.status} />
        {it.not_requested && it.status !== "not_requested" && <StatusPill tone="danger">Didn&apos;t ask</StatusPill>}
        {it.whatsapp_backup_sent && <StatusPill tone="info">WhatsApp backup sent</StatusPill>}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <DetailRow label="Way">{modeShortLabel(it.mode)}</DetailRow>
        <DetailRow label="Made by">{sourceLabel(it.source)}</DetailRow>
        <DetailRow label="Source">{ORIGIN_LABELS[it.origin]}</DetailRow>
        <DetailRow label="Code">
          <span className="font-mono">{it.code || "—"}</span>
        </DetailRow>
        <DetailRow label="Wrong tries used">{String(it.attempts)}</DetailRow>
        <DetailRow label="Expires">{formatIst(it.expires_at)}</DetailRow>
        <DetailRow label="Verified at">{it.verified_at ? formatIst(it.verified_at) : "Not verified"}</DetailRow>
        <DetailRow label="Your reference">{it.ref || "—"}</DetailRow>
      </dl>

      <div className="space-y-3">
        <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">What happened</p>
        <Timeline items={otpTimeline(it, formatIst)} />
      </div>

      <div className="space-y-3">
        <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Updates sent to your server</p>
        {updates.length === 0 ? (
          <p className="text-sm text-[#64748b]">No updates were sent. Add a status URL in Settings to get them.</p>
        ) : (
          <Timeline
            items={updates.map((u, i) => {
              const tone: Tone = u.status === "delivered" ? "success" : u.status === "failed" ? "danger" : "neutral";
              return {
                key: `${u.event}-${u.created_at}-${i}`,
                title: updateTitle(u.event),
                time: formatIst(u.created_at),
                // The title is the event; the tone and detail say whether it reached the client's server.
                detail: `${u.status === "delivered" ? "Reached your server" : u.status === "failed" ? "Didn't reach your server" : "Waiting to send"} · ${u.attempts} ${u.attempts === 1 ? "try" : "tries"}${u.last_error ? ` · ${u.last_error}` : ""}`,
                tone,
              };
            })}
          />
        )}
      </div>
    </div>
  );
}

const UPDATE_TITLES: Record<string, string> = {
  sms_delivered: "SMS delivered",
  whatsapp_read: "WhatsApp read",
  not_requested: "Not requested",
  test: "Test",
};

function updateTitle(event: string): string {
  return UPDATE_TITLES[event] ?? capitalize(event.replace(/_/g, " ")).replace(/\bsms\b/i, "SMS").replace(/\bwhatsapp\b/i, "WhatsApp");
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">{label}</dt>
      <dd className="mt-1 break-words text-sm text-[#0A1528]">{children}</dd>
    </div>
  );
}

/** Pure CSS bar chart, one column per day. Sent is the full bar, verified sits at its base. */
function DailyBars({ days }: { days: OtpStats["daily"] }) {
  const maxSent = Math.max(0, ...days.map((d) => d.sent));
  if (days.length === 0 || maxSent === 0) {
    return <p className="flex h-40 items-center justify-center text-sm text-[#64748b]">No codes in this period</p>;
  }
  const step = days.length <= 7 ? 1 : days.length <= 30 ? 5 : 15;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-4 text-xs text-[#475569]">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-[2px] bg-primary/25" aria-hidden="true" />
          Sent
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-[2px] bg-primary" aria-hidden="true" />
          Verified
        </span>
      </div>
      <div role="img" aria-label="Bar chart of codes sent and verified per day" className="flex h-40 items-end gap-[3px] lg:h-[264px]">
        {days.map((d) => {
          const sentPct = (d.sent / maxSent) * 100;
          const verifiedPct = d.sent > 0 ? Math.min(100, (d.verified / d.sent) * 100) : 0;
          return (
            <div key={d.day} className="relative flex h-full flex-1 items-end justify-center" title={`${dayLabel(d.day)}: ${d.sent} sent, ${d.verified} verified`}>
              <div className="relative w-full max-w-[44px] rounded-t-[4px] bg-primary/25" style={{ height: d.sent > 0 ? `max(2px, ${sentPct}%)` : "0px" }}>
                {d.verified > 0 && (
                  <div className="absolute inset-x-0 bottom-0 rounded-t-[3px] bg-primary" style={{ height: `max(2px, ${verifiedPct}%)` }} />
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex gap-[3px]">
        {days.map((d, i) => (
          <span key={d.day} className="flex-1 text-center text-[10px] tabular-nums text-[#94a3b8]">
            {i % step === 0 ? dayNumber(d.day) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function dayLabel(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-IN", { timeZone: "UTC", day: "numeric", month: "short" });
}

function dayNumber(day: string): string {
  return String(Number(day.slice(8, 10)));
}

function ChannelSummary({ stats }: { stats: OtpStats }) {
  return (
    <div className="space-y-5">
      <ChannelBlock
        channel="sms"
        name="SMS"
        sent={stats.sms.sent}
        delivered={stats.sms.delivered}
        rows={[
          { label: "Sent", value: stats.sms.sent },
          { label: "Delivered", value: stats.sms.delivered },
          { label: "Failed", value: stats.sms.failed },
        ]}
      />
      <ChannelBlock
        channel="whatsapp"
        name="WhatsApp"
        sent={stats.whatsapp.sent}
        delivered={stats.whatsapp.delivered}
        rows={[
          { label: "Sent", value: stats.whatsapp.sent },
          { label: "Delivered", value: stats.whatsapp.delivered },
          { label: "Read", value: stats.whatsapp.read },
          { label: "Failed", value: stats.whatsapp.failed },
        ]}
      />
      <p className="border-t border-[#eef2f6] pt-4 text-xs text-[#64748b]">WhatsApp backups sent: {formatCount(stats.whatsapp_backups)}</p>
    </div>
  );
}

function ChannelBlock({
  channel,
  name,
  sent,
  delivered,
  rows,
}: {
  channel: "sms" | "whatsapp";
  name: string;
  sent: number;
  delivered: number;
  rows: { label: string; value: number }[];
}) {
  const pct = sent > 0 ? Math.min(100, (delivered / sent) * 100) : 0;
  return (
    <div>
      <div className="flex items-center gap-3">
        <ChannelIcon channel={channel} />
        <p className="text-sm font-bold text-[#0A1528]">{name}</p>
      </div>
      <dl className="mt-3 space-y-1.5">
        {rows.map((r) => (
          <div key={r.label} className="flex justify-between text-sm">
            <dt className="text-[#64748b]">{r.label}</dt>
            <dd className="tabular-nums text-[#0A1528]">{formatCount(r.value)}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#eef2f6]" role="progressbar" aria-label={`${name} delivered`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
