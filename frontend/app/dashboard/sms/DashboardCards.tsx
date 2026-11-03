"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { CheckCircle2, Circle } from "lucide-react";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, type SmsBalance, type SmsCampaign, type SmsDltList, type SmsStatus, type SmsWalletItem } from "@/lib/api";
import { campaignStatusLabel, campaignStatusTone, canCancelCampaign, defaultRange, formatCount, formatIst, formatRupees, friendlyError, istDateString } from "./helpers";
import { useSms } from "./SmsShell";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Skeleton } from "./ui";
import { usePerm } from "./usePerm";

// ---- Pure helpers (unit-tested in DashboardCards.test.ts) ----

export interface ChecklistRow { key: string; label: string; done: boolean; href: string | null; hint: string }

/** The five setup steps in order. A step counts as done from either the shell status or the live DLT list. */
export function checklistRows(input: { status: SmsStatus; dlt: SmsDltList | null; balance: SmsBalance | null }): ChecklistRow[] {
  const { status, dlt, balance } = input;
  const entityDone = status.checklist.dlt || (dlt?.entities.length ?? 0) > 0;
  const senderDone = status.checklist.sender || (dlt?.senders ?? []).some((s) => s.status === "approved");
  return [
    { key: "entity", label: "Add your DLT entity", done: entityDone, href: "/dashboard/sms/setup?tab=entity", hint: "Add entity" },
    { key: "sender", label: "Get a Sender ID approved", done: senderDone, href: "/dashboard/sms/setup?tab=manager&sub=senders", hint: "Open DLT Manager" },
    { key: "template", label: "Get a content template approved", done: status.templates_ready, href: "/dashboard/sms/setup?tab=manager&sub=templates", hint: "Open DLT Manager" },
    { key: "petm", label: "Finish the PE-TM binding", done: status.checklist.pe_tm, href: "/dashboard/sms/setup?tab=petm", hint: "Open PE-TM Binding" },
    { key: "balance", label: "Have SMS balance above zero", done: (balance?.sms_count ?? 0) > 0, href: null, hint: "Use Add credit above" },
  ];
}

export interface DaySummary { sent: number; delivered: number; failed: number; pct: number | null }

/**
 * Sent = everything handed to the operator (submitted, delivered, failed, unknown).
 * Waiting, sending, skipped and cancelled messages are not counted. Delivered % is rounded;
 * null when nothing was sent, so the card shows a dash instead of 0%.
 */
export function summarize(anril: Record<string, number> | null | undefined): DaySummary {
  const n = (k: string) => Number(anril?.[k]) || 0;
  const delivered = n("delivered");
  const failed = n("failed");
  const sent = delivered + failed + n("submitted") + n("unknown");
  return { sent, delivered, failed, pct: sent > 0 ? Math.round((delivered / sent) * 100) : null };
}

/** Month of an instant as seen in India, "YYYY-MM". */
function istMonth(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return Number.isNaN(d.getTime()) ? "" : istDateString(d).slice(0, 7);
}

/**
 * ₹ spent on campaigns so far this IST month, from the wallet history (campaign rows carry the real
 * rupees debited). `partial` is true when the history was cut at `limit` while still inside this month,
 * so older spend may be missing and the number is "at least".
 */
export function monthSpend(items: SmsWalletItem[], now: Date, limit: number): { total: number; partial: boolean } {
  const month = istMonth(now);
  let total = 0;
  let oldest = "";
  for (const i of items) {
    const m = istMonth(i.at);
    if (m && (!oldest || m < oldest)) oldest = m;
    if (i.kind === "campaign" && m === month && i.amount != null) total += Math.abs(i.amount);
  }
  return { total, partial: items.length >= limit && oldest >= month };
}

/** Scheduled campaigns, soonest first. */
export function upcomingCampaigns(list: SmsCampaign[]): SmsCampaign[] {
  return list
    .filter((c) => c.status === "scheduled")
    .sort((a, b) => String(a.send_at ?? a.created_at).localeCompare(String(b.send_at ?? b.created_at)));
}

/** The latest `max` campaigns that are not waiting to go out, newest first. */
export function recentCampaigns(list: SmsCampaign[], max = 5): SmsCampaign[] {
  return list
    .filter((c) => c.status !== "scheduled")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, max);
}

// ---- Cards ----

const HISTORY_LIMIT = 200;
const SWR_OPTS = { revalidateOnFocus: false, shouldRetryOnError: false } as const;

export function SetupChecklistCard() {
  const { status, balance } = useSms();
  const dlt = useSWR("sms:dlt-list", () => api.sms.dltList(), SWR_OPTS);
  // A failed DLT read only means we trust the shell status alone; it never blocks the checklist.
  const rows = checklistRows({ status, dlt: dlt.data ?? null, balance });
  const left = rows.filter((r) => !r.done).length;
  if (left === 0) return null;
  return (
    <Card>
      <CardHeader title="Finish setting up" hint={`${left} of ${rows.length} steps left before you can send.`} />
      <ul className="divide-y divide-[#e2e8f0]">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center gap-3 px-4 py-3 sm:px-5">
            {r.done ? <CheckCircle2 size={18} className="shrink-0 text-success" /> : <Circle size={18} className="shrink-0 text-[#94a3b8]" />}
            <span className={r.done ? "min-w-0 flex-1 text-sm text-[#64748b] line-through" : "min-w-0 flex-1 text-sm font-semibold text-[#0A1528]"}>{r.label}</span>
            {!r.done &&
              (r.href ? (
                <Link href={r.href} className="shrink-0 text-sm font-bold text-primary hover:underline">
                  {r.hint}
                </Link>
              ) : (
                <span className="shrink-0 text-xs text-[#64748b]">{r.hint}</span>
              ))}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-[#f8fafc] px-3 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wider text-[#64748b]">{label}</p>
      <p className="mt-0.5 font-display text-lg font-bold text-[#0A1528]">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-[#64748b]">{sub}</p>}
    </div>
  );
}

export function WalletCard() {
  const { balance, balanceError, reloadBalance } = useSms();
  const now = useMemo(() => new Date(), []);
  const history = useSWR("sms:wallet-history-dash", () => api.sms.walletHistory(HISTORY_LIMIT), SWR_OPTS);
  const spend = history.data ? monthSpend(history.data.items, now, HISTORY_LIMIT) : null;
  return (
    <Card>
      <CardHeader title="Wallet" hint="Your balance and what you've spent this month." />
      {!balance && balanceError ? (
        <LoadError message={friendlyError(balanceError, "Check your connection.")} onRetry={reloadBalance} />
      ) : !balance ? (
        <Skeleton className="m-4 h-20 sm:m-5" />
      ) : (
        <div className="grid grid-cols-1 gap-2 p-4 sm:grid-cols-3 sm:p-5">
          <Stat label="Balance" value={balance.wallet != null ? formatRupees(balance.wallet) : "—"} />
          <Stat label="SMS left" value={formatCount(balance.sms_count)} />
          <Stat
            label="Spent this month"
            value={spend ? `${spend.partial ? "At least " : ""}${formatRupees(spend.total)}` : history.error ? "—" : "…"}
            sub={history.error ? "Couldn't load" : undefined}
          />
        </div>
      )}
    </Card>
  );
}

function SummaryCard({ title, from, to }: { title: string; from: string; to: string }) {
  const { data, error, isLoading, mutate } = useSWR(["sms:summary", from, to], () => api.sms.reportSummary(from, to), SWR_OPTS);
  const s = summarize(data?.anril);
  return (
    <Card>
      <CardHeader title={title} />
      {isLoading && !data ? (
        <Skeleton className="m-4 h-20 sm:m-5" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : (
        <div className="grid grid-cols-2 gap-2 p-4 sm:p-5">
          <Stat label="Sent" value={formatCount(s.sent)} />
          <Stat label="Delivered" value={formatCount(s.delivered)} />
          <Stat label="Failed" value={formatCount(s.failed)} />
          <Stat label="Delivered %" value={s.pct == null ? "—" : `${s.pct}%`} />
        </div>
      )}
    </Card>
  );
}

export function StatsCards() {
  const today = useMemo(() => istDateString(new Date()), []);
  const week = useMemo(() => defaultRange(today, 7), [today]);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <SummaryCard title="Today" from={today} to={today} />
      <SummaryCard title="Last 7 days" from={week.from} to={week.to} />
    </div>
  );
}

const CAMPAIGNS_KEY = "sms:dashboard-campaigns";

export function UpcomingCard() {
  const { canManage } = usePerm();
  const { reloadBalance } = useSms();
  const { data, error, isLoading, mutate } = useSWR(CAMPAIGNS_KEY, () => api.sms.campaigns(50, 0), SWR_OPTS);
  const [target, setTarget] = useState<SmsCampaign | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const upcoming = upcomingCampaigns(data?.campaigns ?? []);

  async function cancel() {
    if (!target) return;
    setCancelling(true);
    try {
      await api.sms.cancelCampaign(target.id);
      toast.success("Campaign cancelled. Waiting messages will not be sent.");
      setTarget(null);
      await mutate();
      reloadBalance();
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't cancel the campaign"));
      setTarget(null);
      void mutate();
    } finally {
      setCancelling(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Upcoming sends" hint="Campaigns scheduled for later." />
      {isLoading && !data ? (
        <Skeleton className="m-4 h-20 sm:m-5" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : upcoming.length === 0 ? (
        <Empty title="Nothing scheduled." hint="Pick a later time when you send a campaign and it will show up here." />
      ) : (
        <ul className="divide-y divide-[#e2e8f0]">
          {upcoming.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-[#0A1528]">{c.name}</p>
                <p className="text-xs text-[#64748b]">
                  {formatIst(c.send_at)} · {formatCount(c.total)} numbers
                </p>
              </div>
              {canManage && canCancelCampaign(c.status) && (
                <Btn variant="danger" className="h-9" onClick={() => setTarget(c)}>
                  Cancel
                </Btn>
              )}
            </li>
          ))}
        </ul>
      )}
      <ConfirmModal
        open={target != null}
        onClose={() => !cancelling && setTarget(null)}
        onConfirm={() => void cancel()}
        title="Cancel this campaign?"
        description={`"${target?.name ?? ""}" has not been sent yet. Cancelling stops every waiting message.`}
        tone="danger"
        confirmLabel="Cancel campaign"
        cancelLabel="Keep it"
        loading={cancelling}
        loadingLabel="Cancelling…"
      />
    </Card>
  );
}

export function RecentCard() {
  // Same key and fetcher as UpcomingCard, so SWR shares one request between the two.
  const { data, error, isLoading, mutate } = useSWR(CAMPAIGNS_KEY, () => api.sms.campaigns(50, 0), SWR_OPTS);
  const recent = recentCampaigns(data?.campaigns ?? []);
  return (
    <Card>
      <CardHeader
        title="Recent sends"
        action={
          <Link href="/dashboard/sms/reports" className="text-sm font-bold text-primary hover:underline">
            Delivery Reports
          </Link>
        }
      />
      {isLoading && !data ? (
        <Skeleton className="m-4 h-20 sm:m-5" />
      ) : error && !data ? (
        <LoadError message={friendlyError(error, "Check your connection.")} onRetry={() => void mutate()} />
      ) : recent.length === 0 ? (
        <Empty title="No sends yet." />
      ) : (
        <ul className="divide-y divide-[#e2e8f0]">
          {recent.map((c) => (
            <li key={c.id}>
              <Link href="/dashboard/sms/reports" className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-[#f8fafc] sm:px-5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-[#0A1528]">{c.name}</p>
                  <p className="text-xs text-[#64748b]">
                    {formatIst(c.created_at)} · {formatCount(c.total)} numbers
                  </p>
                </div>
                <Badge tone={campaignStatusTone(c.status)}>{campaignStatusLabel(c.status)}</Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
