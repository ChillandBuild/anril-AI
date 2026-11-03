"use client";

import { RecentCard, SetupChecklistCard, StatsCards, UpcomingCard, WalletCard } from "./DashboardCards";

export default function SmsDashboardPage() {
  return (
    <div className="space-y-4">
      <SetupChecklistCard />
      <WalletCard />
      <StatsCards />
      <div className="grid gap-4 md:grid-cols-2">
        <UpcomingCard />
        <RecentCard />
      </div>
    </div>
  );
}
