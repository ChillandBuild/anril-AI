"use client";
import { useState } from "react";
import { Phone, Eye, EyeOff, Hash, KeyRound } from "lucide-react";
import { API_URL } from "@/lib/api";
import { useSettingsForm, CLEAR_SECRET } from "./SettingsFormContext";
import {
  Fact, Facts, SaveButton, SaveStatus, SectionFooter, SettingsSection, SummaryHint,
} from "./SettingsSection";

// TeleCMI credentials for click-to-call telecalling. Lives on the Telecalling
// behaviour page (its own "Calling (TeleCMI)" section) rather than a separate nav
// entry — the caller decides whether to render this at all, gated on
// hasTelecmiConfig (see telecalling-behavior/page.tsx).

type FieldDef = {
  key: string; label: string; placeholder?: string; secret: boolean;
  required?: boolean; hint?: string;
};

const VOICE_SECTION = {
  id: "voice",
  label: "Calling (TeleCMI)",
  icon: Phone,
  description: "Cloud Telephony (TeleCMI) credentials for click-to-call telecalling. Per-caller User IDs are set on the Team / Roles page.",
  fields: [
    { key: "telecmi_app_id", label: "App ID", placeholder: "e.g. 1111113", secret: false, required: true, hint: "Found in TeleCMI Dashboard → Developer → App Secret" },
    { key: "telecmi_secret", label: "App Secret", placeholder: "Paste your App Secret", secret: true, required: true, hint: "Found in TeleCMI Dashboard → Developer → App Secret" },
    { key: "telecmi_callerid", label: "Caller ID (DID shown to leads)", placeholder: "e.g. 919876543210", secret: false, required: true, hint: "The outbound business number provisioned in your TeleCMI account" },
    { key: "telecmi_webhook_secret", label: "Webhook Secret", secret: true, required: false, hint: "Optional: Appended as ?webhook_secret= to your Cloud Telephony CDR webhook URL" },
  ] as FieldDef[],
};

function OutlinedField({
  label, value, onChange, placeholder, type = "text", rightSlot, hint, disabled = false,
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: "text" | "password"; rightSlot?: React.ReactNode; hint?: string; disabled?: boolean;
}) {
  return (
    <div className="space-y-1">
      <div className="relative">
        <input
          type={type}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? " "}
          className="peer w-full px-4 pt-5 pb-2 pr-10 rounded-xl bg-white border border-border text-sm font-body text-ink placeholder:text-ink-muted/40 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 transition disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted"
        />
        <label className="pointer-events-none absolute left-3 -top-2 px-1.5 text-[11px] font-label font-medium text-ink-muted bg-white tracking-wide">
          {label}
        </label>
        {rightSlot && (
          <div className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center">
            {rightSlot}
          </div>
        )}
      </div>
      {hint && <p className="text-[11px] text-ink-muted font-body pl-1">{hint}</p>}
    </div>
  );
}

function SecretField({
  label, storedMask, isSet, newValue, onChange, hint, disabled = false,
}: {
  label: string; storedMask: string; isSet: boolean;
  newValue: string; onChange: (v: string) => void; hint?: string; disabled?: boolean;
}) {
  const [show, setShow] = useState(false);
  const [editing, setEditing] = useState(false);
  const willClear = newValue === CLEAR_SECRET;
  const showInput = editing || (newValue.length > 0 && !willClear) || !isSet;

  return (
    <div className="space-y-1">
      {willClear ? (
        <div className="relative w-full">
          <div className="w-full px-4 pt-5 pb-2 rounded-xl bg-red-50 border border-red-200 font-body text-sm text-red-700 flex items-center justify-between">
            <span>Will be cleared on save</span>
            <button type="button" onClick={() => onChange("")} className="text-[11px] font-label font-semibold text-primary underline">
              Undo
            </button>
          </div>
          <span className="pointer-events-none absolute left-3 -top-2 px-1.5 text-[11px] font-label font-medium text-ink-muted bg-white tracking-wide">
            {label}
          </span>
        </div>
      ) : !showInput ? (
        <div className="relative w-full group">
          <button type="button" disabled={disabled} onClick={() => setEditing(true)} className="w-full text-left disabled:cursor-not-allowed">
            <div className="w-full px-4 pt-5 pb-2 rounded-xl bg-white border border-border font-mono text-sm text-ink-secondary cursor-text group-hover:border-primary/40 transition group-disabled:cursor-not-allowed group-disabled:bg-surface-subtle group-disabled:text-ink-muted">
              {storedMask}
            </div>
          </button>
          <span className="pointer-events-none absolute left-3 -top-2 px-1.5 text-[11px] font-label font-medium text-ink-muted bg-white tracking-wide">
            {label}
          </span>
          <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-3 opacity-0 group-hover:opacity-100 transition">
            {isSet && !disabled && (
              <button type="button" onClick={() => onChange(CLEAR_SECRET)} className="text-[11px] font-label font-semibold text-red-600 hover:text-red-700">
                Clear
              </button>
            )}
            <button type="button" onClick={() => setEditing(true)} disabled={disabled} className="text-[11px] font-label font-semibold text-primary">
              Edit
            </button>
          </div>
        </div>
      ) : (
        <OutlinedField
          label={label}
          value={newValue}
          onChange={onChange}
          type={show ? "text" : "password"}
          placeholder={isSet ? "Enter new value to replace existing" : "Paste your value here"}
          rightSlot={
            <button type="button" onClick={() => setShow(s => !s)} className="p-1 text-ink-muted hover:text-ink-secondary" tabIndex={-1}>
              {show ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          }
          disabled={disabled}
        />
      )}
      {hint && <p className="text-[11px] text-ink-muted font-body pl-1">{hint}</p>}
    </div>
  );
}

export function CallingCredentialsSection() {
  const { settingFor, drafts, setDrafts, saveStates, canManageSettings, tenantId, handleSave } = useSettingsForm();

  const voiceConfigured = VOICE_SECTION.fields.filter(f => f.required !== false).every(f => settingFor(f.key)?.is_set);
  const dirty = VOICE_SECTION.fields.some(f => {
    const meta = settingFor(f.key);
    const draft = drafts[f.key] ?? "";
    if (f.secret) return draft.length > 0;
    const stored = meta?.display_value === "Not set" ? "" : (meta?.display_value ?? "");
    return draft !== stored;
  });
  const secretMap = Object.fromEntries(VOICE_SECTION.fields.map(f => [f.key, f.secret]));
  const shown = (key: string) => {
    const v = settingFor(key)?.display_value;
    return v && v !== "Not set" ? v : null;
  };
  const appId = shown("telecmi_app_id");
  const callerId = shown("telecmi_callerid");

  return (
    <SettingsSection
        id="voice-credentials"
        icon={VOICE_SECTION.icon}
        accent="amber"
        title={VOICE_SECTION.label}
        description={VOICE_SECTION.description}
        status={{ label: voiceConfigured ? "Configured" : "Not configured", tone: voiceConfigured ? "on" : "warn" }}
        dirty={dirty}
        summary={
          voiceConfigured ? (
            <Facts>
              {appId && <Fact icon={KeyRound} mono>App ID {appId}</Fact>}
              {callerId && <Fact icon={Hash} mono>Caller ID {callerId}</Fact>}
            </Facts>
          ) : (
            <SummaryHint tone="warn">Add your App ID, App Secret and Caller ID to start calling.</SummaryHint>
          )
        }
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {VOICE_SECTION.fields.map((field) => {
            const meta = settingFor(field.key);
            const draft = drafts[field.key] ?? "";
            const labelWithOptional = field.required === false ? `${field.label} (optional)` : field.label;
            if (field.secret) {
              return (
                <SecretField
                  key={field.key}
                  label={labelWithOptional}
                  storedMask={meta?.display_value ?? "Not set"}
                  isSet={!!meta?.is_set}
                  newValue={draft}
                  onChange={v => setDrafts(d => ({ ...d, [field.key]: v }))}
                  hint={field.hint}
                  disabled={!canManageSettings}
                />
              );
            }
            return (
              <OutlinedField
                key={field.key}
                label={labelWithOptional}
                value={draft}
                onChange={v => setDrafts(d => ({ ...d, [field.key]: v }))}
                placeholder={field.placeholder}
                hint={field.hint}
                disabled={!canManageSettings}
              />
            );
          })}
        </div>

        {/* Webhook URL + setup guide */}
        {(() => {
          const cdrUrl = tenantId
            ? `${API_URL}/api/v1/calls/telecmi-cdr/${tenantId}`
            : null;
          return (
            <div className="mt-5 space-y-2 rounded-2xl border border-border bg-surface-subtle p-4 font-body text-xs">
              <p className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-secondary">TeleCMI CHUB Setup Guide</p>
              <ol className="list-inside list-decimal space-y-1.5 text-ink-secondary">
                <li>Log in to your <a href="https://connle.telecmi.com/login" target="_blank" rel="noopener noreferrer" className="font-semibold text-primary underline">TeleCMI Dashboard</a> and click on your business number.</li>
                <li>Go to the <span className="font-semibold">DEVELOPER</span> tab on the top menu, then select <span className="font-semibold">APP SECRET</span> in the sub-menu.</li>
                <li>Copy your <span className="font-semibold">App ID</span> and <span className="font-semibold">App Secret</span>, and paste them into the fields above.</li>
                <li>Ensure your <span className="font-semibold">Caller ID</span> matches your TeleCMI virtual/business number (with country code, e.g. 91...).</li>
                <li>Go to <span className="font-semibold">SETTINGS → WEBHOOKS</span>, click <span className="font-semibold">Add</span>, choose Type as <span className="font-semibold">Call report</span>, Method as <span className="font-semibold">POST</span>, and paste your CDR Webhook URL:<br />
                  <code className="mt-1 inline-block select-all break-all rounded border border-border bg-white px-2 py-1 font-mono text-[11px] text-ink">
                    {cdrUrl ?? "Retrieving webhook URL…"}
                  </code>
                </li>
                <li>If using a Webhook Secret, append it to your Webhook URL: <code className="rounded border border-border bg-white px-1 py-0.5 font-mono text-[10px]">?webhook_secret=YOUR_SECRET</code></li>
                <li>Configure each telecaller&apos;s TeleCMI <span className="font-semibold">User ID</span> on the <span className="font-semibold">Team / Roles page</span>.</li>
              </ol>
            </div>
          );
        })()}

        <SectionFooter
          status={<SaveStatus state={saveStates.voice ?? "idle"} dirty={dirty} idleLabel={voiceConfigured ? "Credentials are set" : "Credentials not set yet"} />}
        >
          <SaveButton
            state={saveStates.voice ?? "idle"}
            dirty={dirty}
            disabled={!canManageSettings}
            onClick={() => handleSave("voice", VOICE_SECTION.fields.map(f => f.key), secretMap)}
          />
        </SectionFooter>
    </SettingsSection>
  );
}
