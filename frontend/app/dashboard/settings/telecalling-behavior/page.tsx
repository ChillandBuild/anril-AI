"use client";
import { useSettingsForm } from "../SettingsFormContext";
import { SettingsAccordion } from "../SettingsSection";
import { CallingCredentialsSection } from "../CallingCredentialsSection";
import { TelecallingConfigPanel } from "../TelecallingConfigPanel";

export default function TelecallingBehaviorSettingsPage() {
  const { canManageSettings, hasTelecmiConfig } = useSettingsForm();
  // One accordion for both cards so the shared rule applies: two or more
  // sections start collapsed (with Expand all in the header); a lone
  // assignment card opens. TeleCMI credentials only appear once the calling
  // provider is TeleCMI.
  return (
    <SettingsAccordion>
      <TelecallingConfigPanel canManage={canManageSettings} />
      {hasTelecmiConfig && (
        <div id="calling">
          <CallingCredentialsSection />
        </div>
      )}
    </SettingsAccordion>
  );
}
