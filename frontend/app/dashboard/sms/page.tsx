"use client";

import { RecentCard, SetupChecklistCard, TodayCard, UpcomingCard, WalletCard } from "./DashboardCards";
import { useSms } from "./SmsShell";

export default function SmsDashboardPage() {
  const { status } = useSms();
  return (
    <div className="space-y-4">
      <div className={status.connected ? "grid gap-4 lg:grid-cols-2" : undefined}>
        <WalletCard />
        {status.connected && <TodayCard />}
      </div>
      <SetupChecklistCard />
      {status.connected && (
        <div className="grid gap-4 md:grid-cols-2">
          <UpcomingCard />
          <RecentCard />
        </div>
      )}
    </div>
  );
}
