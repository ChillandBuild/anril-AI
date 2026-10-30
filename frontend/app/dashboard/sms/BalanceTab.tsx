"use client";

import { useState } from "react";
import useSWR from "swr";
import { ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api, type SmsBalance } from "@/lib/api";
import { Pager } from "./CampaignDetail";
import { formatCount, formatIst, formatRupees, friendlyError, humanizeKind, packLabel } from "./helpers";
import type { Tone } from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Notice, Skeleton, TableWrap, tdCls, thCls } from "./ui";
import { usePerm } from "./usePerm";

const LEDGER_PAGE = 25;

function paymentTone(status: string): Tone {
  if (status === "paid" || status === "credited") return "success";
  if (status === "failed" || status === "expired" || status === "cancelled") return "danger";
  return "warn";
}

export function BalanceTab({ balance, balanceError, onReload }: { balance: SmsBalance | null; balanceError: string | null; onReload: () => void }) {
  const { canRecharge } = usePerm();
  const [busyAmount, setBusyAmount] = useState<number | null>(null);
  const [opened, setOpened] = useState(false);
  const [ledgerOffset, setLedgerOffset] = useState(0);

  const packs = useSWR("sms:packs", () => api.sms.rechargePacks(), { revalidateOnFocus: false });
  const payments = useSWR("sms:payments", () => api.sms.rechargePayments(), { revalidateOnFocus: true });
  const ledger = useSWR(["sms:ledger", ledgerOffset], () => api.sms.ledger(LEDGER_PAGE + 1, ledgerOffset), { keepPreviousData: true });

  async function recharge(amount: number) {
    if (busyAmount !== null) return;
    setBusyAmount(amount);
    try {
      const res = await api.sms.recharge(amount);
      // Open the Razorpay link in a new tab; the SMS are added by the server once payment completes.
      const win = window.open(res.short_url, "_blank", "noopener,noreferrer");
      if (!win) toast.message("Your browser blocked the payment tab. Use the Pay link in the payments table below.");
      setOpened(true);
      void payments.mutate();
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't start the payment"));
    } finally {
      setBusyAmount(null);
    }
  }

  const entries = ledger.data?.entries ?? [];
  const hasMore = entries.length > LEDGER_PAGE;
  const shownEntries = entries.slice(0, LEDGER_PAGE);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Balance" action={<Btn variant="link" onClick={() => { onReload(); void payments.mutate(); void ledger.mutate(); }}>Refresh</Btn>} />
        <div className="grid gap-3 p-4 sm:grid-cols-3 sm:p-5">
          {balance ? (
            <>
              <div className="rounded-xl bg-primary/5 p-4">
                <p className="font-display text-3xl font-bold text-[#0A1528]">{formatCount(balance.sms_count)}</p>
                <p className="text-xs font-semibold text-[#64748b]">SMS left</p>
              </div>
              <div className="rounded-xl bg-[#f8fafc] p-4">
                <p className="font-display text-3xl font-bold text-[#0A1528]">{formatRupees(balance.wallet)}</p>
                <p className="text-xs font-semibold text-[#64748b]">wallet value</p>
              </div>
              <div className="rounded-xl bg-[#f8fafc] p-4">
                <p className="font-display text-3xl font-bold text-[#0A1528]">{formatRupees(balance.price_per_sms)}</p>
                <p className="text-xs font-semibold text-[#64748b]">per SMS</p>
              </div>
            </>
          ) : balanceError ? (
            <div className="sm:col-span-3">
              <Notice tone="warn">{balanceError}</Notice>
            </div>
          ) : (
            <Skeleton className="h-24 sm:col-span-3" />
          )}
        </div>
      </Card>

      <Card>
        <CardHeader title="Recharge" hint="Pick a pack. You pay on a secure Razorpay page." />
        <div className="space-y-3 p-4 sm:p-5">
          {opened && <Notice tone="success">{"We'll add the SMS as soon as payment completes. This page updates on its own; you can also press Refresh above."}</Notice>}
          {packs.isLoading && !packs.data ? (
            <Skeleton className="h-24" />
          ) : packs.error && !packs.data ? (
            <LoadError message={friendlyError(packs.error, "Check your connection.")} onRetry={() => void packs.mutate()} />
          ) : (packs.data?.packs ?? []).length === 0 ? (
            <Empty title="No packs available yet." />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {packs.data?.packs.map((p) => (
                <div key={p.amount_rupees} className="flex flex-col justify-between gap-3 rounded-xl border border-[#e2e8f0] p-4">
                  <div>
                    <p className="font-display text-lg font-bold text-[#0A1528]">{packLabel(p.amount_rupees, p.sms_count)}</p>
                    {p.price_per_sms != null && <p className="text-xs text-[#64748b]">{formatRupees(p.price_per_sms)} per SMS</p>}
                  </div>
                  {canRecharge ? (
                    <Btn busy={busyAmount === p.amount_rupees} disabled={busyAmount !== null} onClick={() => void recharge(p.amount_rupees)}>
                      Recharge <ExternalLink size={13} />
                    </Btn>
                  ) : (
                    <p className="text-xs text-[#64748b]">Ask the account owner to recharge.</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Card>
        <CardHeader title="Payments" />
        {payments.isLoading && !payments.data ? (
          <Skeleton className="m-4 h-24" />
        ) : payments.error && !payments.data ? (
          <LoadError message={friendlyError(payments.error, "Check your connection.")} onRetry={() => void payments.mutate()} />
        ) : (payments.data?.payments ?? []).length === 0 ? (
          <Empty title="No payments yet." />
        ) : (
          <TableWrap>
            <table className="w-full min-w-[620px]">
              <thead>
                <tr className="border-b border-[#f1f5f9]">
                  <th className={thCls}>Date (IST)</th>
                  <th className={thCls}>Amount</th>
                  <th className={thCls}>SMS</th>
                  <th className={thCls}>Status</th>
                  <th className={thCls}></th>
                </tr>
              </thead>
              <tbody>
                {payments.data?.payments.map((p) => (
                  <tr key={p.id} className="border-b border-[#f1f5f9] last:border-0">
                    <td className={`${tdCls} whitespace-nowrap`}>{formatIst(p.created_at)}</td>
                    <td className={tdCls}>{formatRupees(p.amount_rupees)}</td>
                    <td className={tdCls}>{formatCount(p.sms_count)}</td>
                    <td className={tdCls}>
                      <Badge tone={paymentTone(p.status)}>{humanizeKind(p.status)}</Badge>
                      {p.error && <p className="mt-1 max-w-[220px] break-words text-xs text-[#64748b]">{p.error}</p>}
                    </td>
                    <td className={tdCls}>
                      {p.short_url && !p.credited_at && !["failed", "expired", "cancelled", "paid", "credited"].includes(p.status) && canRecharge && (
                        <a href={p.short_url} target="_blank" rel="noopener noreferrer" className="text-xs font-bold text-primary hover:underline">
                          Pay
                        </a>
                      )}
                      {p.credited_at && <span className="text-xs text-[#64748b]">Added {formatIst(p.credited_at)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <Card>
        <CardHeader title="Balance history" hint="Recharges, credits and what each campaign used." />
        {ledger.isLoading && !ledger.data ? (
          <Skeleton className="m-4 h-24" />
        ) : ledger.error && !ledger.data ? (
          <LoadError message={friendlyError(ledger.error, "Check your connection.")} onRetry={() => void ledger.mutate()} />
        ) : shownEntries.length === 0 ? (
          <Empty title="No history yet." />
        ) : (
          <>
            <TableWrap>
              <table className="w-full min-w-[640px]">
                <thead>
                  <tr className="border-b border-[#f1f5f9]">
                    <th className={thCls}>Date (IST)</th>
                    <th className={thCls}>What</th>
                    <th className={thCls}>SMS</th>
                    <th className={thCls}>Amount</th>
                    <th className={thCls}>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {shownEntries.map((e) => (
                    <tr key={e.id} className="border-b border-[#f1f5f9] last:border-0">
                      <td className={`${tdCls} whitespace-nowrap`}>{formatIst(e.created_at)}</td>
                      <td className={tdCls}>{humanizeKind(e.kind)}</td>
                      <td className={tdCls}>{e.sms_count != null ? formatCount(e.sms_count) : "—"}</td>
                      <td className={tdCls}>{e.amount != null ? formatRupees(e.amount) : "—"}</td>
                      <td className={`${tdCls} max-w-[260px] break-words`}>
                        {e.note || "—"}
                        {e.expiry_date && <span className="block text-xs text-[#64748b]">Expires {e.expiry_date}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <Pager offset={ledgerOffset} limit={LEDGER_PAGE} total={hasMore ? ledgerOffset + LEDGER_PAGE + 1 : ledgerOffset + shownEntries.length} onOffset={setLedgerOffset} />
          </>
        )}
      </Card>
    </div>
  );
}
