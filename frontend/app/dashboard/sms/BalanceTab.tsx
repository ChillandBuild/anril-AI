"use client";

import useSWR from "swr";
import { Download } from "lucide-react";
import { api } from "@/lib/api";
import {
  WALLET_KIND_LABELS,
  formatIst,
  formatRupees,
  formatSignedSms,
  friendlyError,
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

/** Transactions: the balance history. The balance itself lives on the Dashboard wallet card. */
export function BalanceTab() {
  const history = useSWR("sms:wallet-history", () => api.sms.walletHistory(100), { revalidateOnFocus: false });
  const items = history.data?.items ?? [];

  return (
    <div className="space-y-4">
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
