"use client";

import useSWR from "swr";
import { Download } from "lucide-react";
import { api } from "@/lib/api";
import { useSms } from "./SmsShell";
import {
  WALLET_KIND_LABELS,
  formatCount,
  formatIst,
  formatRate,
  formatRupees,
  formatSignedSms,
  friendlyError,
  planSummary,
  walletCsv,
  walletKindTone,
} from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Skeleton, TableWrap, tdCls, thCls } from "./ui";

function downloadCsv(csv: string) {
  const url = window.URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "sms_balance_history.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

const HISTORY_LIMIT = 100;

/** Price per SMS, what's left and what's been used: the operator panel's Plan Details, in plain words. */
function PlanCard({ items, loaded }: { items: Parameters<typeof planSummary>[1]; loaded: boolean }) {
  const { balance } = useSms();
  if (!balance || !loaded) return <Skeleton className="h-28" />;
  const p = planSummary(balance, items, HISTORY_LIMIT);
  const stats: { label: string; value: string; note?: string }[] = [
    { label: "Price per SMS", value: p.perSms != null ? formatRate(p.perSms) : "—", note: "For one SMS of up to 160 characters" },
    { label: "SMS left", value: formatCount(p.smsLeft), note: p.moneyLeft != null ? `${formatRupees(p.moneyLeft)} left` : undefined },
    { label: "Used so far", value: `${p.partial ? "≥ " : ""}${formatCount(p.used)}`, note: "Sends from Anril and your own app" },
    { label: "Plan total", value: `${p.partial ? "≥ " : ""}${formatCount(p.total)}`, note: "Left + used" },
  ];
  return (
    <Card>
      <CardHeader title="Your plan" hint="Long SMS (over 160 characters, or 70 in Tamil) count as 2 or more SMS." />
      <div className="grid grid-cols-2 gap-3 p-4 sm:p-5 lg:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl bg-[#f8fafc] px-3.5 py-3">
            <p className="text-xs font-semibold text-[#64748b]">{s.label}</p>
            <p className="mt-1 font-display text-xl font-bold text-[#0A1528]">{s.value}</p>
            {s.note && <p className="mt-0.5 text-xs text-[#64748b]">{s.note}</p>}
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Transactions: the plan, then the balance history. The balance itself also shows on the Dashboard wallet card. */
export function BalanceTab() {
  const history = useSWR("sms:wallet-history", () => api.sms.walletHistory(HISTORY_LIMIT), { revalidateOnFocus: false });
  const items = history.data?.items ?? [];

  return (
    <div className="space-y-4">
      <PlanCard items={items} loaded={!!history.data || !!history.error} />
      <Card>
        <CardHeader
          title="Balance history"
          hint="Top-ups are worked out from balance changes, checked every 15 minutes."
          action={
            <Btn variant="outline" className="h-9" disabled={items.length === 0} onClick={() => downloadCsv(walletCsv(items))}>
              <Download size={14} /> Export CSV
            </Btn>
          }
        />
        {history.isLoading && !history.data ? (
          <Skeleton className="m-4 h-40" />
        ) : history.error && !history.data ? (
          <LoadError message={friendlyError(history.error, "Check your connection.")} onRetry={() => void history.mutate()} />
        ) : items.length === 0 ? (
          <Empty title="No balance changes yet." />
        ) : (
          <TableWrap>
            <table className="w-full min-w-[520px]">
              <thead>
                <tr className="border-b border-[#f1f5f9]">
                  <th className={thCls}>Date</th>
                  <th className={thCls}>What</th>
                  <th className={`${thCls} text-right`}>SMS</th>
                  <th className={`${thCls} text-right`}>Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f1f5f9]">
                {items.map((item, i) => (
                  <tr key={`${item.at}-${i}`}>
                    <td className={`${tdCls} whitespace-nowrap`}>{formatIst(item.at)}</td>
                    <td className={tdCls}>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={walletKindTone(item.kind)}>{WALLET_KIND_LABELS[item.kind] ?? item.kind}</Badge>
                        {item.label && <span className="min-w-0 break-words">{item.label}</span>}
                      </div>
                    </td>
                    <td className={`${tdCls} whitespace-nowrap text-right font-bold ${item.sms > 0 ? "text-[#15803d]" : "text-[#0A1528]"}`}>{formatSignedSms(item.sms)}</td>
                    <td className={`${tdCls} whitespace-nowrap text-right`}>{item.amount == null ? "—" : formatRupees(item.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}
