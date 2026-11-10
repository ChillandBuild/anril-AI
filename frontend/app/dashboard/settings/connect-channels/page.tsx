"use client";
import { useSettingsForm } from "../SettingsFormContext";
import { SettingsAccordion } from "../SettingsSection";
import ConnectChannelsPanel from "./Panel";
import MarketplaceLeadsSection from "./MarketplaceLeadsSection";

export default function ConnectChannelsSettingsPage() {
  const { canManageSettings } = useSettingsForm();
  return (
    <div className="space-y-6">
      <ConnectChannelsPanel canManage={canManageSettings} />
      {/* Collapsed by default. TeleCMI credentials moved to Telecalling behaviour. */}
      <SettingsAccordion startClosed>
        <MarketplaceLeadsSection canManage={canManageSettings} />
      </SettingsAccordion>
    </div>
  );
}
