"use client";

import type { SmsBalance } from "@/lib/api";
import { formatCount } from "./helpers";
import { Btn, Card, CardHeader, Notice, Skeleton } from "./ui";

export function BalanceTab({ balance, balanceError, onReload }: { balance: SmsBalance | null; balanceError: string | null; onReload: () => void }) {
  return (
    <Card>
      <CardHeader title="Balance" action={<Btn variant="link" onClick={onReload}>Refresh</Btn>} />
      <div className="space-y-4 p-4 sm:p-5">
        {balance ? (
          <div className="rounded-xl bg-primary/5 p-4">
            <p className="font-display text-3xl font-bold text-ink">{formatCount(balance.sms_count)}</p>
            <p className="text-xs font-semibold text-ink-muted">SMS left</p>
          </div>
        ) : balanceError ? <Notice tone="warn">{balanceError}</Notice> : <Skeleton className="h-24" />}
        <p className="text-sm text-ink-muted">Contact Anril to recharge or get help with your SMS balance.</p>
      </div>
    </Card>
  );
}
