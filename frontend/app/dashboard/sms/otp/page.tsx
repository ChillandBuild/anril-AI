"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { OtpConsole } from "../DeveloperTab";
import { OtpHistory } from "../ReportsTab";
import { Skeleton } from "../ui";
import { OtpApiTab } from "./ApiTab";
import { HistoryTab } from "./HistoryTab";
import { OTP_TABS } from "./otpShared";
import { SendTab } from "./SendTab";
import { SettingsTab } from "./SettingsTab";

export default function SmsOtpPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-40" />
        </div>
      }
    >
      <OtpTabs />
    </Suspense>
  );
}

/** The tab names and the header pills live in AppHeader's HEADER_TABS; unknown ?tab= values open the first tab. */
function OtpTabs() {
  const tab = useSearchParams().get("tab") ?? "";
  const active = OTP_TABS.find((t) => t.value === tab)?.value ?? OTP_TABS[0].value;

  switch (active) {
    case "history":
      return <HistoryTab />;
    case "settings":
      return <SettingsTab />;
    case "api":
      return <OtpApiTab />;
    case "smart":
      return (
        <div className="space-y-4">
          <OtpConsole />
          <OtpHistory />
        </div>
      );
    default:
      return <SendTab />;
  }
}
