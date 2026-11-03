"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { Download, Search } from "lucide-react";
import { toast } from "sonner";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid } from "@/components/MobileRecord";
import { api, type SmsMessageFilters } from "@/lib/api";
import { Pager } from "./CampaignDetail";
import {
  MESSAGE_STATUSES,
  clampRange,
  defaultRange,
  formatCount,
  formatIst,
  friendlyError,
  istDateString,
  logColumns,
  maxToFor,
  humanizeKind,
  otpActionLabel,
  scalarEntries,
  statusLabel,
} from "./helpers";
import { MessageStatus, messageTime } from "./MessageStatus";
import { Badge, Btn, Card, CardHeader, Empty, Field, LoadError, Notice, Skeleton, TableWrap, inputCls, tdCls, thCls } from "./ui";

const PAGE = 50;
const SUMMARY_DAYS = 30;
const LOGS_DAYS = 3;

export function ReportsTab() {
  return (
    <div className="space-y-4">
      <Summary />
      <Messages />
      <Logs />
      <OtpHistory />
    </div>
  );
}

function DateRange({ range, maxDays, today, onChange }: { range: { from: string; to: string }; maxDays: number; today: string; onChange: (r: { from: string; to: string }) => void }) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field label="From">
        <input type="date" className={inputCls} value={range.from} max={today} onChange={(e) => e.target.value && onChange(clampRange({ ...range, from: e.target.value }, "from", maxDays, today))} />
      </Field>
      <Field label="To">
        <input
          type="date"
          className={inputCls}
          value={range.to}
          min={range.from}
          max={maxToFor(range.from, maxDays, today)}
          onChange={(e) => e.target.value && onChange(clampRange({ ...range, to: e.target.value }, "to", maxDays, today))}
        />
      </Field>
    </div>
  );
}

function Summary() {
  const today = useMemo(() => istDateString(new Date()), []);
  const [range, setRange] = useState(() => defaultRange(today, 7));
  const { data, error, isLoading, mutate } = useSWR(["sms:summary", range.from, range.to], () => api.sms.reportSummary(range.from, range.to), {
    keepPreviousData: true,
    revalidateOnFocus: false,
  });
  const anril = Object.entries(data?.anril ?? {});
  const bulk9 = scalarEntries(data?.bulk9);
  return (
    <Card>
      <CardHeader title="Summary" hint={`Pick up to ${SUMMARY_DAYS} days.`} action={<DateRange range={range} maxDays={SUMMARY_DAYS} today={today} onChange={setRange} />} />
      <div className="space-y-4 p-4 sm:p-5">
        {isLoading && !data ? (
          <Skeleton className="h-24" />
        ) : error && !data ? (
          <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
        ) : (
          <>
            {anril.length === 0 ? (
              <Empty title="Nothing sent in this period." />
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {anril.map(([k, v]) => (
                  <div key={k} className="rounded-xl bg-[#f8fafc] px-3 py-2.5">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-[#64748b]">{statusLabel(k) === k ? humanizeKind(k) : statusLabel(k)}</p>
                    <p className="mt-0.5 font-display text-lg font-bold text-[#0A1528]">{formatCount(Number(v))}</p>
                  </div>
                ))}
              </div>
            )}
            {data?.error && <Notice tone="warn">{"Operator numbers aren't available right now."} {data.error}</Notice>}
            {bulk9.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-[#64748b]">From the operator</h3>
                <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {bulk9.map(([k, v]) => (
                    <div key={k} className="rounded-xl border border-[#e2e8f0] px-3 py-2">
                      <dt className="text-[10px] font-bold uppercase tracking-wider text-[#64748b]">{humanizeKind(k)}</dt>
                      <dd className="mt-0.5 break-words text-sm font-semibold text-[#0A1528]">{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

function Messages() {
  const campaigns = useSWRInfinite(
    (index, previous) => previous && previous.campaigns.length < PAGE ? null : ["sms:report-campaigns", index],
    ([, index]) => api.sms.campaigns(PAGE, index * PAGE),
    { revalidateOnFocus: false },
  );
  const campaignChoices = campaigns.data?.flatMap((page) => page.campaigns) ?? [];
  const moreCampaigns = !campaigns.data || campaigns.data[campaigns.data.length - 1]?.campaigns.length === PAGE;
  const [draft, setDraft] = useState<SmsMessageFilters>({});
  const [filters, setFilters] = useState<SmsMessageFilters>({});
  const [offset, setOffset] = useState(0);
  const [exporting, setExporting] = useState(false);

  const { data, error, isLoading, mutate } = useSWR(["sms:messages", filters, offset], () => api.sms.messages({ ...filters, limit: PAGE, offset }), {
    keepPreviousData: true,
    revalidateOnFocus: false,
    refreshInterval: (current) => current?.messages.some((message) => ["queued", "sending", "submitted", "unknown"].includes(message.status)) ? 10_000 : 0,
  });
  const rows = data?.messages ?? [];

  function apply() {
    setOffset(0);
    setFilters({ ...draft, search: draft.search?.trim() || undefined });
  }

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
      <CardHeader
        title="Messages"
        hint="One row per SMS."
        action={
          <Btn variant="outline" busy={exporting} onClick={() => void exportCsv()}>
            <Download size={14} /> Export CSV
          </Btn>
        }
      />
      <form
        className="grid gap-3 border-b border-[#f1f5f9] p-4 sm:grid-cols-2 sm:p-5 lg:grid-cols-5"
        onSubmit={(e) => {
          e.preventDefault();
          apply();
        }}
      >
        <Field label="Campaign">
          <select className={inputCls} value={draft.campaign_id ?? ""} onChange={(e) => setDraft((d) => ({ ...d, campaign_id: e.target.value || undefined }))}>
            <option value="">All campaigns</option>
            {campaignChoices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          {moreCampaigns && <Btn variant="link" busy={campaigns.isValidating} onClick={() => void campaigns.setSize(campaigns.size + 1)}>Load more campaigns</Btn>}
          {campaigns.error && <p className="text-xs text-danger">Couldn&apos;t load campaign choices. <button type="button" className="underline" onClick={() => void campaigns.mutate()}>Retry</button></p>}
        </Field>
        <Field label="Status">
          <select className={inputCls} value={draft.status ?? ""} onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value || undefined }))}>
            <option value="">All statuses</option>
            {MESSAGE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="From">
          <input type="date" className={inputCls} value={draft.from ?? ""} max={draft.to || undefined} onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value || undefined }))} />
        </Field>
        <Field label="To">
          <input type="date" className={inputCls} value={draft.to ?? ""} min={draft.from || undefined} onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value || undefined }))} />
        </Field>
        <Field label="Search">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
            <input className={`${inputCls} pl-9`} placeholder="Number or message" value={draft.search ?? ""} onChange={(e) => setDraft((d) => ({ ...d, search: e.target.value }))} />
          </div>
        </Field>
        <div className="sm:col-span-2 lg:col-span-5">
          <Btn type="submit">Apply filters</Btn>
        </div>
      </form>

      {isLoading && !data ? (
        <Skeleton className="m-4 h-48" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : rows.length === 0 ? (
        <Empty title="No messages match." />
      ) : (
        <>
          <div className="hidden md:block">
            <TableWrap>
              <table className="w-full min-w-[760px]">
                <thead>
                  <tr className="border-b border-[#f1f5f9]">
                    <th className={thCls}>Lead</th>
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

function Logs() {
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
    <Card>
      <CardHeader
        title="Operator SMS logs"
        hint={`Raw delivery logs from the operator. Up to ${LOGS_DAYS} days at a time.`}
        action={
          <DateRange
            range={range}
            maxDays={LOGS_DAYS}
            today={today}
            onChange={(r) => {
              setPage(1);
              setRange(r);
            }}
          />
        }
      />
      {isLoading && !data ? (
        <Skeleton className="m-4 h-32" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : (
        <>
          {data?.error && <Notice tone="warn" className="m-4">{data.error}</Notice>}
          {logs.length === 0 ? (
            <Empty title="No logs in this window." />
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
                          {row[c] == null ? "—" : String(row[c])}
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
    </Card>
  );
}

function OtpHistory() {
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
            <table className="w-full min-w-[640px]">
              <thead>
                <tr className="border-b border-[#f1f5f9]">
                  <th className={thCls}>Time (IST)</th>
                  <th className={thCls}>Mobile</th>
                  <th className={thCls}>Action</th>
                  <th className={thCls}>Result</th>
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
