"use client";

import { Clock } from "lucide-react";
import { OpenHoursEditor } from "@/components/OpenHoursEditor";
import { useSettingsForm } from "../SettingsFormContext";
import { Card, InShort, PageHeader } from "../payments/MyBusinessUi";

// v9.2 #92: Settings › My business › Open hours. The same editor as setup step 3.
export default function OpenHoursPage() {
  const { canManageSettings } = useSettingsForm();
  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 animate-slide-up">
      <PageHeader icon={Clock} title="Open hours" subtitle="When your shop is open. One place: everything else reads it." />
      <InShort>
        The AI agent tells customers when you&apos;re closed and when you open next, the booking link only offers
        times inside these hours, and the after-hours message follows them.
      </InShort>
      <Card id="open-hours-card" title="When is your shop open?" hint="India time. Switch a day off if you are closed that day.">
        <OpenHoursEditor canManage={canManageSettings} />
      </Card>
      {!canManageSettings && <p className="font-body text-xs text-ink-muted">Only people who can change settings can edit this.</p>}
    </div>
  );
}
