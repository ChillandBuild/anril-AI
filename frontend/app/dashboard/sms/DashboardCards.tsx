"use client";

import { useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { CheckCircle2, ChevronDown, Circle, Loader2 } from "lucide-react";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, type SmsBalance, type SmsCampaign, type SmsDltList, type SmsStatus, type SmsWalletItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  CREDIT_MAX,
  CREDIT_MIN,
  CREDIT_NOTE_MAX,
  SUPPORT_FALLBACK,
  balanceLevel,
  campaignStatusLabel,
  campaignStatusTone,
  canCancelCampaign,
  creditAmountError,
  defaultRange,
  formatCount,
  formatIst,
  formatRupees,
  friendlyError,
  istDateString,
  requestedOn,
} from "./helpers";
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
    { key: "balance", label: "Have SMS balance above zero", done: (balance?.sms_count ?? 0) > 0, href: null, hint: "Use Add credit in the wallet" },
  ];
}

/** "1 of 5 done · next: …" for the collapsed setup line. */
export function setupProgress(rows: ChecklistRow[]): { done: number; total: number; next: string | null } {
  return { done: rows.filter((r) => r.done).length, total: rows.length, next: rows.find((r) => !r.done)?.label ?? null };
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
  const [open, setOpen] = useState(false);
  // The DLT list needs the Bulk9 key; before that the shell status alone decides.
  const dlt = useSWR(status.connected ? "sms:dlt-list" : null, () => api.sms.dltList(), SWR_OPTS);
  const rows = checklistRows({ status, dlt: dlt.data ?? null, balance });
  const p = setupProgress(rows);
  if (p.next == null) return null;
  return (
    <Card>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="sms-setup-steps"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 rounded-2xl px-4 py-3 text-left hover:bg-[#f8fafc] sm:px-5"
      >
        <span className="text-sm font-bold text-[#0A1528]">Setup</span>
        <span className="h-1.5 w-28 overflow-hidden rounded-full bg-[#e2e8f0]" aria-hidden="true">
          <span className="block h-full rounded-full bg-primary" style={{ width: `${(p.done / p.total) * 100}%` }} />
        </span>
        <span className="min-w-0 flex-1 text-sm text-[#64748b]">
          {p.done} of {p.total} done · next: {p.next}
        </span>
        <span className="flex items-center gap-1 text-sm font-bold text-primary">
          {open ? "Hide steps" : "Show steps"} <ChevronDown size={15} className={cn("transition-transform", open && "rotate-180")} />
        </span>
      </button>
      {open && (
        <ul id="sms-setup-steps" className="divide-y divide-[#e2e8f0] border-t border-[#e2e8f0]">
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
      )}
    </Card>
  );
}

const darkInputCls =
  "h-10 w-full rounded-xl border border-white/20 bg-white/5 px-3 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30";

/** Add credit, inline in the wallet card. Works before the Bulk9 key is set. */
function AddCreditForm() {
  const credit = useSWR("sms:credit-requests", () => api.sms.creditRequests(), SWR_OPTS);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const newestOpen = [...(credit.data?.items ?? [])]
    .filter((r) => r.status === "open")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const bad = creditAmountError(amount);
    if (bad) {
      setError(bad);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const trimmed = note.trim();
      await api.sms.requestCredit({ amount: Number(amount.trim()), ...(trimmed ? { note: trimmed } : {}) });
      setAmount("");
      setNote("");
      toast.success("Request sent. We'll top up your balance and mark it done.");
      void credit.mutate();
    } catch (err) {
      setError(friendlyError(err, "Couldn't send your request. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 border-t border-white/10 pt-4">
      <form onSubmit={(e) => void submit(e)} className="flex flex-wrap items-end gap-2.5" noValidate>
        <label className="flex min-w-[8rem] flex-1 flex-col gap-1.5 text-xs font-bold text-[#c9d6e3]">
          Add credit (₹)
          <input
            className={darkInputCls}
            inputMode="numeric"
            placeholder={`${CREDIT_MIN}–${CREDIT_MAX.toLocaleString("en-IN")}`}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <label className="flex min-w-[10rem] flex-[2] flex-col gap-1.5 text-xs font-bold text-[#c9d6e3]">
          Note (optional)
          <input className={darkInputCls} maxLength={CREDIT_NOTE_MAX} placeholder="e.g. Diwali campaign" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-white px-4 text-sm font-bold text-[#0A1528] hover:bg-[#e2e8f0] disabled:opacity-60"
        >
          {busy && <Loader2 size={14} className="animate-spin" />} Request credit
        </button>
      </form>
      {error && (
        <p role="alert" className="text-xs font-semibold text-[#fecaca]">
          {error}
        </p>
      )}
      {newestOpen && (
        <p className="text-xs text-[#9fb3c8]">
          {formatRupees(newestOpen.amount)} requested on {requestedOn(newestOpen.created_at)} · waiting
        </p>
      )}
    </div>
  );
}

export function WalletCard() {
  const { status, balance, balanceError, reloadBalance } = useSms();
  const { canManage } = usePerm();
  const support = status.support_contact || SUPPORT_FALLBACK;
  const now = useMemo(() => new Date(), []);
  const history = useSWR(status.connected ? "sms:wallet-history-dash" : null, () => api.sms.walletHistory(HISTORY_LIMIT), SWR_OPTS);
  const spend = history.data ? monthSpend(history.data.items, now, HISTORY_LIMIT) : null;
  const level = balance ? balanceLevel(balance.sms_count) : null;
  return (
    <section aria-label="Wallet" className="flex min-w-0 flex-col gap-4 rounded-2xl bg-[#0A1528] p-5 text-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#9fb3c8]">Wallet</p>
          {!status.connected ? (
            <p className="mt-1 text-sm text-[#c9d6e3]">Your balance shows here once your SMS account is ready.</p>
          ) : balance ? (
            <>
              <p className="mt-1 font-display text-3xl font-bold">{balance.wallet != null ? formatRupees(balance.wallet) : `${formatCount(balance.sms_count)} SMS`}</p>
              <p className="mt-1 text-sm text-[#c9d6e3]">
                {formatCount(balance.sms_count)} SMS left
                {level === "low" && <strong className="text-[#fde68a]"> · Low</strong>}
                {level === "empty" && <strong className="text-[#fecaca]"> · Top up needed</strong>}
                {spend && (
                  <>
                    {" · "}
                    {spend.partial ? "at least " : ""}
                    {formatRupees(spend.total)} spent this month
                  </>
                )}
              </p>
            </>
          ) : balanceError ? (
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-[#c9d6e3]">
              {friendlyError(balanceError, "Couldn't load your balance.")}
              <button type="button" onClick={reloadBalance} className="font-bold text-[#7fe0e2] hover:underline">
                Retry
              </button>
            </div>
          ) : (
            <div className="mt-2 h-9 w-40 animate-pulse rounded-lg bg-white/10" />
          )}
        </div>
        {status.connected && (
          <Link href="/dashboard/sms/transactions" className="text-sm font-bold text-[#7fe0e2] hover:underline">
            Transactions →
          </Link>
        )}
      </div>
      {canManage ? <AddCreditForm /> : <p className="border-t border-white/10 pt-4 text-xs text-[#9fb3c8]">Contact {support} to top up.</p>}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-xl bg-[#f8fafc] px-3 py-2.5">
      <p className="text-xs text-[#64748b]">{label}</p>
      <p className={cn("mt-0.5 font-display text-2xl font-bold text-[#0A1528]", tone === "good" && "text-[#036b6e]", tone === "bad" && "text-[#b4232f]")}>{value}</p>
    </div>
  );
}

/** Today's sends, with the last 7 days as one line. */
export function TodayCard() {
  const today = useMemo(() => istDateString(new Date()), []);
  const week = useMemo(() => defaultRange(today, 7), [today]);
  const day = useSWR(["sms:summary", today, today], () => api.sms.reportSummary(today, today), SWR_OPTS);
  const wk = useSWR(["sms:summary", week.from, week.to], () => api.sms.reportSummary(week.from, week.to), SWR_OPTS);
  const s = summarize(day.data?.anril);
  const w = summarize(wk.data?.anril);
  return (
    <Card className="flex min-w-0 flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[#64748b]">Today</h2>
        {wk.data && (
          <span className="text-xs text-[#64748b]">
            Last 7 days: {formatCount(w.sent)} sent{w.pct != null && ` · ${w.pct}% delivered`}
          </span>
        )}
      </div>
      {day.isLoading && !day.data ? (
        <Skeleton className="h-20" />
      ) : day.error && !day.data ? (
        <LoadError message={friendlyError(day.error, "Check your connection.")} onRetry={() => void day.mutate()} />
      ) : (
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Sent" value={formatCount(s.sent)} />
          <Stat label="Delivered" value={formatCount(s.delivered)} tone="good" />
          <Stat label="Failed" value={formatCount(s.failed)} tone={s.failed > 0 ? "bad" : undefined} />
        </div>
      )}
    </Card>
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
