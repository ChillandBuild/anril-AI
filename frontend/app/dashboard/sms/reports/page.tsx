"use client";

import { useRouter } from "next/navigation";
import { CampaignsTab } from "../CampaignsTab";
import { ReportsTab } from "../ReportsTab";
import { useSms } from "../SmsShell";

export default function SmsReportsPage() {
  const router = useRouter();
  const { reloadBalance } = useSms();
  return (
    <div className="space-y-4">
      <ReportsTab />
      <CampaignsTab onBalanceChanged={reloadBalance} onOpenTemplates={() => router.push("/dashboard/sms/setup")} />
    </div>
  );
}
