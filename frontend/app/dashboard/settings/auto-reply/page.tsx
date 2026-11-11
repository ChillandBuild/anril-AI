"use client";
import { useState } from "react";
import { MessagesSquare, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useSettingsForm } from "../SettingsFormContext";
import { Fact, Facts, SettingsAccordion, SettingsSection, SummaryHint, SwitchPill } from "../SettingsSection";

const AI_AUTO_REPLY_KEY = "ai_auto_reply_enabled";
const AI_AUTO_REPLY_DEFAULT_ENABLED = true;

export default function AutoReplySettingsPage() {
  const { settingFor, canManageSettings, saveValues } = useSettingsForm();
  const [saving, setSaving] = useState(false);

  const stored = settingFor(AI_AUTO_REPLY_KEY)?.display_value;
  const enabled = stored === "Not set" || !stored ? AI_AUTO_REPLY_DEFAULT_ENABLED : stored === "true";

  // The card's switch is the only control, so it saves right away.
  async function toggle(next: boolean) {
    setSaving(true);
    try {
      await saveValues({ [AI_AUTO_REPLY_KEY]: next ? "true" : "false" });
      toast.success(`AI auto-reply turned ${next ? "on" : "off"}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Couldn't turn AI auto-reply ${next ? "on" : "off"}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsAccordion>
      <SettingsSection
        id="ai-auto-reply"
        icon={Sparkles}
        accent="violet"
        title="AI Auto-Reply"
        description="Turn on automatic AI replies for inbound messages on WhatsApp, Instagram, Facebook and Telegram. Turning it off also pauses AI follow-ups. Voice delivery is controlled by your operator plan settings."
        status={{ label: enabled ? "On" : "Off", tone: enabled ? "on" : "off" }}
        headerAction={
          <SwitchPill
            on={enabled}
            size="sm"
            loading={saving}
            disabled={!canManageSettings}
            aria-label="AI auto-reply on or off"
            onChange={toggle}
          />
        }
        summary={
          enabled ? (
            <Facts>
              <Fact icon={MessagesSquare}>WhatsApp · Instagram · Facebook · Telegram</Fact>
            </Facts>
          ) : (
            <SummaryHint>Off. Messages wait in the inbox until a teammate answers them.</SummaryHint>
          )
        }
      >
        <p className="font-body text-xs leading-relaxed text-ink-muted">
          {enabled
            ? "AI replies to inbound messages on every channel. When you turn it off, messages sit in the inbox until a teammate answers them, and each lead's AI switch is greyed out."
            : "AI replies are off. Inbound messages sit in the inbox until a teammate answers them, and each lead's AI switch is greyed out. Turn it on with the switch above."}
        </p>
      </SettingsSection>
    </SettingsAccordion>
  );
}
