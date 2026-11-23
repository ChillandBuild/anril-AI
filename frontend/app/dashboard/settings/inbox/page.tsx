"use client";
import { useSettingsForm } from "../SettingsFormContext";
import { InboxConfigPanel } from "../InboxConfigPanel";
import { AfterHoursPanel } from "../AfterHoursPanel";

export default function InboxSettingsPage() {
  const { canManageSettings } = useSettingsForm();
  return (
    <div className="space-y-4">
      <InboxConfigPanel canManage={canManageSettings} />
      <AfterHoursPanel canManage={canManageSettings} />
    </div>
  );
}
