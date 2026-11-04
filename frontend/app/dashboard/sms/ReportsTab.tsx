"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ChevronDown, ChevronRight, Download, Search } from "lucide-react";
import { toast } from "sonner";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid } from "@/components/MobileRecord";
import { api, type SmsCampaign, type SmsMessageFilters, type SmsReportSummary } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CampaignDetail, Pager } from "./CampaignDetail";
import { summarize } from "./DashboardCards";
import {
  MESSAGE_STATUSES,
  REPORT_PERIODS,
  campaignNeedsUpdates,
  campaignStage,
  clampRange,
  dailyBars,
  defaultRange,
  dltReason,
  formatCount,
  formatIst,
  friendlyError,
  istDateString,
  logColumns,
  maxToFor,
  humanizeKind,
  onTheWayCount,
  otpActionLabel,
  otpDelivery,
  sendProgress,
  statusLabel,
} from "./helpers";
import { MessageStatus, messageTime } from "./MessageStatus";
import { useSms } from "./SmsShell";
import { Badge, Btn, Card, CardHeader, Empty, Field, LoadError, Notice, Skeleton, TableWrap, inputCls, tdCls, thCls } from "./ui";
import { usePerm } from "./usePerm";

const PAGE = 50;
const LOGS_DAYS = 3;
const heading = "text-xs font-bold uppercase tracking-wider text-[#64748b]";

/**
 * Delivery Reports, top to bottom: pick a period → four totals → your sends (click one for its
 * messages) → every message in the period → the operator's raw log, folded away, for SMS your own
 * app sent with the API key.
 */
export function ReportsTab() {
  const { reloadBalance } = useSms();
  const today = useMemo(() => istDateString(new Date()), []);
  const [days, setDays] = useState<number>(7);
  const [openSend, setOpenSend] = useState<string | null>(null);
  const range = useMemo(() => defaultRange(today, days), [today, days]);

  if (openSend) {
    return <CampaignDetail id={openSend} onBack={() => setOpenSend(null)} onChanged={reloadBalance} />;
  }

  return (
    <div className="space-y-5">
      <div role="radiogroup" aria-label="Period" className="inline-flex rounded-xl bg-[#f1f5f9] p-1">
        {REPORT_PERIODS.map((p) => (
          <button
            key={p.days}
            type="button"
            role="radio"
            aria-checked={days === p.days}
            onClick={() => setDays(p.days)}
            className={cn(
              "h-9 rounded-lg px-4 text-sm",
              days === p.days ? "bg-white font-bold text-[#0A1528] shadow-sm" : "font-semibold text-[#64748b] hover:text-[#0A1528]",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>
      <Totals range={range} />
      <Sends onOpen={setOpenSend} />
      <Messages range={range} />
      <ApiLogs />
    </div>
  );
}

function Totals({ range }: { range: { from: string; to: string } }) {
  const { data, error, isLoading, mutate } = useSWR(["sms:summary", range.from, range.to], () => api.sms.reportSummary(range.from, range.to), {
    keepPreviousData: true,
    revalidateOnFocus: false,
  });
  if (isLoading && !data) return <Skeleton className="h-24" />;
  if (error && !data) return <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />;
  const s = summarize(data?.anril);
  const waiting = onTheWayCount(data?.anril);
  const held = data?.held ?? 0;
  const tiles: { label: string; value: string; note?: string; tone?: string }[] = [
    { label: "Sent", value: formatCount(s.sent), note: "Handed to the operator" },
    { label: "Delivered", value: formatCount(s.delivered), note: s.pct != null ? `${s.pct}% of sent` : undefined, tone: "text-[#036b6e]" },
    { label: "Failed", value: formatCount(s.failed), tone: s.failed > 0 ? "text-[#b4232f]" : undefined },
    {
      label: "Waiting for delivery",
      value: formatCount(waiting),
      note: held > 0 ? `${formatCount(held)} held till 10 AM (night rule)` : waiting > 0 ? "No phone receipt yet" : undefined,
      tone: held > 0 ? "text-[#a16207]" : undefined,
    },
  ];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <Card key={t.label} className="px-4 py-3.5">
            <p className="text-xs font-semibold text-[#64748b]">{t.label}</p>
            <p className={cn("mt-1 font-display text-2xl font-bold text-[#0A1528]", t.tone)}>{t.value}</p>
            {t.note && <p className="mt-0.5 text-xs text-[#64748b]">{t.note}</p>}
          </Card>
        ))}
      </div>
      {waiting > 0 && (
        <p className="text-xs text-[#64748b]">
          Sent counts every SMS handed to the operator, so the ones still waiting are in it too. They move to Delivered or
          Failed when the phone network sends back its receipt.
        </p>
      )}
      {data?.daily && data.daily.length > 1 && <DailyChart days={data.daily} />}
    </div>
  );
}

const CHART_COLORS = { delivered: "#038285", failed: "#e11d48", waiting: "#cbd5e1", otp: "#6366f1" };

/** SMS per day (delivered / failed / waiting stacked) and OTPs per day, one column per Indian day. */
function DailyChart({ days }: { days: NonNullable<SmsReportSummary["daily"]> }) {
  const bars = dailyBars(days);
  const totalOtp = bars.reduce((n, b) => n + b.otp, 0);
  const totalSms = bars.reduce((n, b) => n + b.sms, 0);
  const narrow = bars.length > 10;
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className={heading}>By day</h2>
        <div className="flex flex-wrap gap-3 text-xs text-[#64748b]">
          {(["delivered", "failed", "waiting"] as const).map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: CHART_COLORS[k] }} />
              {k === "waiting" ? "Waiting" : k === "delivered" ? "Delivered" : "Failed"}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: CHART_COLORS.otp }} />
            OTPs
          </span>
        </div>
      </div>
      {totalSms + totalOtp === 0 ? (
        <p className="py-8 text-center text-sm text-[#64748b]">Nothing sent in this period.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <div className="flex min-w-full items-end gap-1.5" style={{ minWidth: narrow ? bars.length * 22 : undefined }}>
            {bars.map((b, i) => (
              <div key={b.day} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                <div className="flex h-32 w-full items-end justify-center gap-0.5">
                  <div
                    className="flex w-full max-w-[28px] flex-col-reverse overflow-hidden rounded-t"
                    style={{ height: `${b.smsPct}%` }}
                    title={`${b.label}: ${b.delivered} delivered, ${b.failed} failed, ${b.waiting} waiting`}
                  >
                    {b.sms > 0 && (["delivered", "failed", "waiting"] as const).map((k) =>
                      b[k] > 0 ? <span key={k} style={{ height: `${(b[k] / b.sms) * 100}%`, background: CHART_COLORS[k] }} /> : null,
                    )}
                  </div>
                  {totalOtp > 0 && (
                    <div className="w-full max-w-[10px] rounded-t" style={{ height: `${b.otpPct}%`, background: CHART_COLORS.otp }} title={`${b.label}: ${b.otp} OTPs`} />
                  )}
                </div>
                {!narrow && <span className="text-[11px] font-semibold text-[#0A1528]">{b.sms > 0 ? formatCount(b.sms) : ""}</span>}
                {!narrow || i % 5 === 0 ? (
                  <span className="whitespace-nowrap text-[10px] text-[#64748b]">{b.label}</span>
                ) : (
                  <span className="text-[10px]">&nbsp;</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      <p className="mt-3 text-xs text-[#64748b]">
        {formatCount(totalSms)} SMS and {formatCount(totalOtp)} OTPs sent from Anril in this period. OTPs your own app sends with the API key aren&apos;t counted.
      </p>
    </Card>
  );
}

function Sends({ onOpen }: { onOpen: (id: string) => void }) {
  const { canManage } = usePerm();
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading, mutate } = useSWR(["sms:campaigns", offset], () => api.sms.campaigns(51, offset), {
    refreshInterval: (d) => (d?.campaigns.some(campaignNeedsUpdates) ? 15_000 : 0),
  });
  const fetched = data?.campaigns ?? [];
  const list = fetched.slice(0, 50);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-2 pt-4 sm:px-5">
        <h2 className={heading}>Your sends</h2>
        <span className="text-xs text-[#64748b]">Click one to see who got it</span>
      </div>
      {isLoading && !data ? (
        <Skeleton className="m-4 h-32" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : list.length === 0 ? (
        <div className="px-4 py-10 text-center">
          <p className="text-sm font-semibold text-[#0A1528]">Nothing sent yet.</p>
          {canManage && (
            <Link href="/dashboard/sms/send" className="mt-2 inline-block text-sm font-bold text-primary hover:underline">
              Send your first SMS →
            </Link>
          )}
        </div>
      ) : (
        <ul className="divide-y divide-[#f1f5f9]">
          {list.map((c) => (
            <SendRow key={c.id} c={c} onOpen={() => onOpen(c.id)} />
          ))}
        </ul>
      )}
      {(offset > 0 || fetched.length > 50) && (
        <div className="flex items-center justify-between gap-2 border-t border-[#f1f5f9] px-4 py-3 text-xs text-[#64748b]">
          <span>Page {Math.floor(offset / 50) + 1}</span>
          <div className="flex gap-2">
            <Btn variant="outline" className="h-8 text-xs" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - 50))}>
              Previous
            </Btn>
            <Btn variant="outline" className="h-8 text-xs" disabled={fetched.length <= 50} onClick={() => setOffset((o) => o + 50)}>
              Next
            </Btn>
          </div>
        </div>
      )}
    </Card>
  );
}

function SendRow({ c, onOpen }: { c: SmsCampaign; onOpen: () => void }) {
  const p = sendProgress(c.counts, c.total);
  const stage = campaignStage(c, new Date());
  const scheduled = c.status === "scheduled";
  return (
    <li>
      <button type="button" onClick={onOpen} className="flex w-full flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3.5 text-left hover:bg-[#f8fafc] sm:px-5">
        <div className="min-w-0 flex-1 basis-56">
          <p className="truncate text-sm font-bold text-[#0A1528]">{c.name}</p>
          <p className="mt-0.5 text-xs text-[#64748b]">
            {scheduled && c.send_at ? `Goes out ${formatIst(c.send_at)}` : formatIst(c.created_at)} · {formatCount(c.total)} number{c.total === 1 ? "" : "s"}
          </p>
        </div>
        {!scheduled && c.total > 0 && (
          <div className="w-full sm:w-56">
            <div className="flex justify-between text-xs">
              <span className="font-semibold text-[#0A1528]">
                {formatCount(p.delivered)} delivered{p.pct != null && <span className="font-normal text-[#64748b]"> · {p.pct}%</span>}
              </span>
              {p.failed > 0 && <span className="font-semibold text-[#b4232f]">{formatCount(p.failed)} failed</span>}
            </div>
            <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-[#e9edf2]" aria-hidden>
              <span className="bg-[#038285]" style={{ width: `${(p.delivered / c.total) * 100}%` }} />
              <span className="bg-[#e11d48]" style={{ width: `${(p.failed / c.total) * 100}%` }} />
            </div>
          </div>
        )}
        <Badge tone={stage.tone}>{stage.label}</Badge>
        <ChevronRight size={16} className="hidden shrink-0 text-[#94a3b8] sm:block" />
      </button>
    </li>
  );
}

function Messages({ range }: { range: { from: string; to: string } }) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [exporting, setExporting] = useState(false);
  const filters: SmsMessageFilters = { from: range.from, to: range.to, status: status || undefined, search: query || undefined };

  const { data, error, isLoading, mutate } = useSWR(["sms:messages", filters, offset], () => api.sms.messages({ ...filters, limit: PAGE, offset }), {
    keepPreviousData: true,
    revalidateOnFocus: false,
    refreshInterval: (current) => (current?.messages.some((m) => ["queued", "sending", "submitted", "unknown"].includes(m.status)) ? 10_000 : 0),
  });
  const rows = data?.messages ?? [];

  async function exportCsv() {
    setExporting(true);
    try {
      await api.sms.exportMessagesCsv(filters);
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't export"));
    } finally {
      setExporting(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 px-4 pb-3 pt-4 sm:px-5">
        <h2 className={cn(heading, "mr-auto")}>Every message</h2>
        <form
          className="relative"
          onSubmit={(e) => {
            e.preventDefault();
            setOffset(0);
            setQuery(search.trim());
          }}
        >
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
          <input
            aria-label="Search by number or message"
            className={cn(inputCls, "h-9 w-56 pl-9")}
            placeholder="Number or message, then Enter"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              if (!e.target.value) setQuery("");
            }}
          />
        </form>
        <select
          aria-label="Status"
          className={cn(inputCls, "h-9 w-40")}
          value={status}
          onChange={(e) => {
            setOffset(0);
            setStatus(e.target.value);
          }}
        >
          <option value="">All statuses</option>
          {MESSAGE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </select>
        <Btn variant="outline" className="h-9" busy={exporting} onClick={() => void exportCsv()}>
          <Download size={14} /> Export
        </Btn>
      </div>

      {isLoading && !data ? (
        <Skeleton className="m-4 h-48" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : rows.length === 0 ? (
        <Empty title={query || status ? "No messages match." : "No messages in this period."} />
      ) : (
        <>
          <div className="hidden md:block">
            <TableWrap>
              <table className="w-full min-w-[760px]">
                <thead>
                  <tr className="border-b border-[#f1f5f9]">
                    <th className={thCls}>Name</th>
                    <th className={thCls}>Number</th>
                    <th className={thCls}>Status</th>
                    <th className={thCls}>SMS</th>
                    <th className={thCls}>Time (IST)</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((m) => (
                    <tr key={m.id} className="border-b border-[#f1f5f9] last:border-0">
                      <td className={tdCls}>{m.lead_name || "—"}</td>
                      <td className={`${tdCls} whitespace-nowrap`}>{m.phone}</td>
                      <td className={tdCls}>
                        <MessageStatus m={m} />
                      </td>
                      <td className={tdCls}>{m.sms_count ?? "—"}</td>
                      <td className={`${tdCls} whitespace-nowrap`}>{messageTime(m)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </div>
          <div className="space-y-3 p-3 md:hidden">
            {rows.map((m) => (
              <MobileRecordCard key={m.id}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-[#0A1528]">{m.lead_name || m.phone}</p>
                    <p className="text-xs text-[#64748b]">{m.phone}</p>
                  </div>
                  <MessageStatus m={m} />
                </div>
                <MobileRecordGrid>
                  <MobileRecordField label="SMS" value={m.sms_count ?? "—"} />
                  <MobileRecordField className="col-span-2" label="Time (IST)" value={messageTime(m)} />
                </MobileRecordGrid>
              </MobileRecordCard>
            ))}
          </div>
          <Pager offset={offset} limit={PAGE} total={data?.total ?? 0} onOffset={setOffset} />
        </>
      )}
    </Card>
  );
}

/** SMS your own app sent with the API key never pass through Anril, so only the operator's log has them. */
function ApiLogs() {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-4 py-3.5 text-left sm:px-5">
        {open ? <ChevronDown size={16} className="text-[#64748b]" /> : <ChevronRight size={16} className="text-[#64748b]" />}
        <span className="text-sm font-bold text-[#0A1528]">SMS sent from your own app (API)</span>
        <span className="hidden text-xs text-[#64748b] sm:inline">· the operator&apos;s raw log, {LOGS_DAYS} days at a time</span>
      </button>
      {open && <LogsBody />}
    </Card>
  );
}

function LogsBody() {
  const today = useMemo(() => istDateString(new Date()), []);
  const [range, setRange] = useState(() => defaultRange(today, LOGS_DAYS));
  const [page, setPage] = useState(1);
  const { data, error, isLoading, mutate } = useSWR(["sms:logs", range.from, range.to, page], () => api.sms.reportLogs(range.from, range.to, page, 25), {
    keepPreviousData: true,
    revalidateOnFocus: false,
  });
  const logs = data?.logs ?? [];
  const cols = logColumns(logs);
  return (
    <div className="border-t border-[#f1f5f9]">
      <div className="flex flex-wrap items-end gap-3 px-4 py-3 sm:px-5">
        <Field label="From">
          <input
            type="date"
            className={inputCls}
            value={range.from}
            max={today}
            onChange={(e) => {
              if (!e.target.value) return;
              setPage(1);
              setRange(clampRange({ ...range, from: e.target.value }, "from", LOGS_DAYS, today));
            }}
          />
        </Field>
        <Field label="To">
          <input
            type="date"
            className={inputCls}
            value={range.to}
            min={range.from}
            max={maxToFor(range.from, LOGS_DAYS, today)}
            onChange={(e) => {
              if (!e.target.value) return;
              setPage(1);
              setRange(clampRange({ ...range, to: e.target.value }, "to", LOGS_DAYS, today));
            }}
          />
        </Field>
      </div>
      {isLoading && !data ? (
        <Skeleton className="m-4 h-32" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : (
        <>
          {data?.error && <Notice tone="warn" className="m-4">{data.error}</Notice>}
          {logs.length === 0 ? (
            <Empty title="No logs in these days." />
          ) : (
            <TableWrap>
              <table className="w-full min-w-[640px]">
                <thead>
                  <tr className="border-b border-[#f1f5f9]">
                    {cols.map((c) => (
                      <th key={c} className={thCls}>
                        {humanizeKind(c)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {logs.map((row, i) => (
                    <tr key={i} className="border-b border-[#f1f5f9] last:border-0">
                      {cols.map((c) => (
                        <td key={c} className={`${tdCls} max-w-[260px] break-words`}>
                          <LogCell column={c} value={row[c]} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
          <div className="flex items-center justify-between border-t border-[#f1f5f9] px-4 py-3 text-xs text-[#64748b]">
            <span>Page {page}</span>
            <div className="flex gap-2">
              <Btn variant="outline" className="h-8 text-xs" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Btn>
              <Btn variant="outline" className="h-8 text-xs" disabled={logs.length < 25} onClick={() => setPage((p) => p + 1)}>
                Next
              </Btn>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function OtpHistory() {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading, mutate } = useSWR(["sms:otp-history", offset], () => api.sms.otpHistory(PAGE, offset), {
    keepPreviousData: true,
    revalidateOnFocus: false,
  });
  const items = data?.items ?? [];
  return (
    <Card>
      <CardHeader title="OTP history" hint="OTPs sent, resent and checked from this dashboard." />
      {isLoading && !data ? (
        <Skeleton className="m-4 h-32" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : items.length === 0 ? (
        <Empty title="No OTPs sent from Anril yet." hint="OTPs your own app sends with your API key don't show here." />
      ) : (
        <>
          <TableWrap>
            <table className="w-full min-w-[720px]">
              <thead>
                <tr className="border-b border-[#f1f5f9]">
                  <th className={thCls}>Time (IST)</th>
                  <th className={thCls}>Mobile</th>
                  <th className={thCls}>Action</th>
                  <th className={thCls}>Result</th>
                  <th className={thCls}>Delivery</th>
                  <th className={thCls}>Note</th>
                </tr>
              </thead>
              <tbody>
                {items.map((o) => (
                  <tr key={o.id} className="border-b border-[#f1f5f9] last:border-0">
                    <td className={`${tdCls} whitespace-nowrap`}>{formatIst(o.created_at)}</td>
                    <td className={`${tdCls} whitespace-nowrap`}>{o.mobile}</td>
                    <td className={tdCls}>{otpActionLabel(o.action)}</td>
                    <td className={tdCls}>
                      <Badge tone={o.ok ? "success" : "danger"}>{o.ok ? "OK" : "Failed"}</Badge>
                    </td>
                    <td className={tdCls}>
                      {(() => {
                        const d = otpDelivery(o.delivery_status);
                        return d.tone ? <Badge tone={d.tone}>{d.label}</Badge> : <span className="text-[#94a3b8]">{d.label}</span>;
                      })()}
                    </td>
                    <td className={`${tdCls} max-w-[260px] truncate text-[#64748b]`} title={o.message ?? undefined}>
                      {o.message || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          <Pager offset={offset} limit={PAGE} total={data?.total ?? 0} onOffset={setOffset} />
        </>
      )}
    </Card>
  );
}

/** One raw-log cell. The status description (a DLT / operator code) is shown in plain English with the raw code on hover. */
function LogCell({ column, value }: { column: string; value: unknown }) {
  if (value == null) return <>—</>;
  const text = String(value);
  if (!/^status[ _-]?desc/i.test(column)) return <>{text}</>;
  const reason = dltReason(text);
  if (!reason.text) return <>—</>;
  return (
    <span title={reason.code ?? undefined}>
      {reason.text}
      {reason.code && reason.code.toLowerCase() !== reason.text.toLowerCase() && <span className="block text-[10px] text-[#94a3b8]">{reason.code}</span>}
    </span>
  );
}
