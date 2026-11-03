"use client";

import { useRouter } from "next/navigation";
import { CampaignsTab } from "../CampaignsTab";
import { ManualCampaignCard } from "../ManualCampaignCard";
import { useSms } from "../SmsShell";

export default function SmsSendPage() {
  const router = useRouter();
  const { reloadBalance } = useSms();
  return (
    <div className="space-y-4">
      <CampaignsTab onBalanceChanged={reloadBalance} onOpenTemplates={() => router.push("/dashboard/sms/setup")} />
      <ManualCampaignCard onOpenCampaigns={() => router.push("/dashboard/sms/reports")} />
    </div>
  );
}
