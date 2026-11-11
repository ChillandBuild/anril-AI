"use client";
import { MessagesSquare, Sparkles } from "lucide-react";
import { useSettingsForm } from "../SettingsFormContext";
import {
  Fact,
  Facts,
  SaveButton,
  SaveStatus,
  SectionFooter,
  SettingsAccordion,
  SettingsSection,
  SummaryHint,
  SwitchPill,
} from "../SettingsSection";

const AI_AUTO_REPLY_KEY = "ai_auto_reply_enabled";
const AI_AUTO_REPLY_DEFAULT_ENABLED = true;

export default function AutoReplySettingsPage() {
  const { settingFor, drafts, setDrafts, saveStates, canManageSettings, handleSave } = useSettingsForm();

  const stored = settingFor(AI_AUTO_REPLY_KEY)?.display_value;
  const enabled = drafts[AI_AUTO_REPLY_KEY] !== undefined
    ? drafts[AI_AUTO_REPLY_KEY] === "true"
    : (stored === "Not set" || !stored ? AI_AUTO_REPLY_DEFAULT_ENABLED : stored === "true");
  const dirty = (() => {
    const draft = drafts[AI_AUTO_REPLY_KEY];
    if (draft === undefined) return false;
    const storedNormalized = stored === "Not set" || !stored
      ? (AI_AUTO_REPLY_DEFAULT_ENABLED ? "true" : "false")
      : (stored === "true" ? "true" : "false");
    return draft !== storedNormalized;
  })();

  return (
    <SettingsAccordion>
      <SettingsSection
        id="ai-auto-reply"
        icon={Sparkles}
        accent="violet"
        title="AI Auto-Reply"
        description="Turn on automatic AI replies for inbound messages on WhatsApp, Instagram, Facebook and Telegram. Turning it off also pauses AI follow-ups. Voice delivery is controlled by your operator plan settings."
        status={{ label: enabled ? "On" : "Off", tone: enabled ? "on" : "off" }}
        dirty={dirty}
        headerAction={
          <SwitchPill
            on={enabled}
            size="sm"
            disabled={!canManageSettings}
            aria-label="AI auto-reply on or off"
            onChange={(next) => setDrafts((d) => ({ ...d, [AI_AUTO_REPLY_KEY]: next ? "true" : "false" }))}
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
          When off, inbound messages on every channel sit in the inbox until a teammate answers them, and each
          lead&apos;s AI switch is greyed out.
        </p>

        <SectionFooter
          status={<SaveStatus state={saveStates.automations_ai ?? "idle"} dirty={dirty} idleLabel={enabled ? "AI replies are enabled" : "AI replies are disabled"} />}
        >
          <SaveButton
            state={saveStates.automations_ai ?? "idle"}
            dirty={dirty}
            disabled={!canManageSettings}
            onClick={() => handleSave("automations_ai", [AI_AUTO_REPLY_KEY])}
          />
        </SectionFooter>
      </SettingsSection>
    </SettingsAccordion>
  );
}
