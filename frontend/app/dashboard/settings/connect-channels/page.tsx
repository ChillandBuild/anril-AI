"use client";
import { useSettingsForm } from "../SettingsFormContext";
import { SettingsAccordion } from "../SettingsSection";
import { CallingCredentialsSection } from "../CallingCredentialsSection";
import ConnectChannelsPanel from "./Panel";
import MarketplaceLeadsSection from "./MarketplaceLeadsSection";

export default function ConnectChannelsSettingsPage() {
  const { canManageSettings, hasTelecmiConfig } = useSettingsForm();
  return (
    <div className="space-y-6">
      <ConnectChannelsPanel canManage={canManageSettings} />
      {/* Collapsed by default. TeleCMI credentials live here, not as a separate
          settings page — only shown once the calling provider is confirmed as
          TeleCMI. IndiaMART & JustDial follow it. */}
      <SettingsAccordion startClosed>
        {hasTelecmiConfig && (
          <div id="calling">
            <CallingCredentialsSection />
          </div>
        )}
        <MarketplaceLeadsSection canManage={canManageSettings} />
      </SettingsAccordion>
    </div>
  );
}
