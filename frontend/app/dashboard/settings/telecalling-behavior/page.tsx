"use client";
import { useSettingsForm } from "../SettingsFormContext";
import { SettingsAccordion } from "../SettingsSection";
import { CallingCredentialsSection } from "../CallingCredentialsSection";
import { TelecallingConfigPanel } from "../TelecallingConfigPanel";

export default function TelecallingBehaviorSettingsPage() {
  const { canManageSettings, hasTelecmiConfig } = useSettingsForm();
  return (
    <div className="space-y-6">
      <TelecallingConfigPanel canManage={canManageSettings} />
      {/* TeleCMI credentials live with the rest of telecalling. Collapsed by
          default; only shown once the calling provider is TeleCMI. */}
      {hasTelecmiConfig && (
        <SettingsAccordion startClosed>
          <div id="calling">
            <CallingCredentialsSection />
          </div>
        </SettingsAccordion>
      )}
    </div>
  );
}
