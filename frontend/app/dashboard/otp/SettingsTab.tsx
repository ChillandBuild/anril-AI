"use client";

import { useState, type FormEvent } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "sonner";
import { Copy, Plus } from "lucide-react";
import { api, type OtpMode, type OtpOverview, type OtpSettings } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatCount } from "../sms/helpers";
import { usePerm } from "../sms/usePerm";
import { Btn, Field, LoadError, Modal, Notice, Skeleton, inputCls } from "../sms/ui";
import { OTP_OVERVIEW_KEY, otpError } from "./otpShared";
import { CopyButton, ModeCards, SectionCard, SettingsRow, StatusPill } from "./otpUi";

const SMS_TEMPLATES_KEY = "otp:sms-templates";
const WA_TEMPLATES_KEY = "otp:wa-templates";

/** Stands in for the code in the template previews. */
const SAMPLE_CODE = "482913";

const WA_NOTE =
  'WhatsApp shows a Copy code button on these messages. For some accounts WhatsApp also adds an "I didn\'t request a code" button; if a customer taps it, Anril cancels that code and tells your server.';

const WA_LANGUAGES: { value: string; label: string }[] = [
  { value: "en", label: "English" },
  { value: "en_US", label: "English (US)" },
  { value: "hi", label: "Hindi" },
  { value: "ta", label: "Tamil" },
  { value: "te", label: "Telugu" },
  { value: "kn", label: "Kannada" },
  { value: "ml", label: "Malayalam" },
  { value: "mr", label: "Marathi" },
  { value: "bn", label: "Bengali" },
  { value: "gu", label: "Gujarati" },
];

/** Form state. Numbers stay as text while typing and are checked on save. */
type Draft = {
  mode: OtpMode;
  wait: string;
  codeLength: string;
  expiry: string;
  maxPerHour: string;
  maxAttempts: string;
  /** "sender_id|message_id", or "" for none. */
  smsKey: string;
  /** "name|language", or "" for none. */
  waKey: string;
  webhookUrl: string;
};

type Patch = Partial<Omit<OtpSettings, "has_webhook_secret">>;

type DraftErrors = Partial<Record<"wait" | "codeLength" | "expiry" | "maxPerHour" | "maxAttempts" | "webhookUrl", string>>;

function toDraft(s: OtpSettings): Draft {
  return {
    mode: s.default_mode,
    wait: String(s.fallback_wait_seconds),
    codeLength: String(s.code_length),
    expiry: String(s.expiry_minutes),
    maxPerHour: String(s.max_per_hour),
    maxAttempts: String(s.max_attempts),
    smsKey: s.sms_sender_id && s.sms_message_id ? `${s.sms_sender_id}|${s.sms_message_id}` : "",
    waKey: s.wa_template_name && s.wa_template_language ? `${s.wa_template_name}|${s.wa_template_language}` : "",
    webhookUrl: s.status_webhook_url ?? "",
  };
}

function splitKey(key: string): [string | null, string | null] {
  if (!key) return [null, null];
  const i = key.indexOf("|");
  return [key.slice(0, i), key.slice(i + 1)];
}

function readInt(raw: string, range: [number, number], label: string): { value: number } | { error: string } {
  const text = raw.trim();
  const n = Number(text);
  if (text === "" || !Number.isInteger(n) || n < range[0] || n > range[1]) {
    return { error: `${label} must be a whole number from ${range[0]} to ${formatCount(range[1])}.` };
  }
  return { value: n };
}

function isHttpsUrl(s: string): boolean {
  try {
    return new URL(s).protocol === "https:";
  } catch {
    return false;
  }
}

/** Minutes the SMS text promises ("Valid for 10 min"), or null when it doesn't say. Same rule as the server. */
function smsValidMinutes(message: string, range: [number, number]): number | null {
  const match = /\bvalid\s+(?:for\s+|till\s+|upto\s+|up to\s+)?(\d{1,3})\s*min/i.exec(message);
  if (!match) return null;
  const n = Number(match[1]);
  return n >= range[0] && n <= range[1] ? n : null;
}

/** Only the fields that differ from what is saved, plus any problems with the draft. */
function buildPatch(saved: OtpSettings, d: Draft, limits: OtpOverview["limits"]): { patch: Patch; errors: DraftErrors } {
  const base = toDraft(saved);
  const patch: Patch = {};
  const errors: DraftErrors = {};

  if (d.mode !== base.mode) patch.default_mode = d.mode;

  if (d.mode === "sms_then_whatsapp" || d.wait !== base.wait) {
    const r = readInt(d.wait, limits.fallback_wait_seconds, "Wait time");
    if ("error" in r) errors.wait = r.error;
    else if (r.value !== saved.fallback_wait_seconds) patch.fallback_wait_seconds = r.value;
  }

  const code = readInt(d.codeLength, limits.code_length, "Code length");
  if ("error" in code) errors.codeLength = code.error;
  else if (code.value !== saved.code_length) patch.code_length = code.value;

  const expiry = readInt(d.expiry, limits.expiry_minutes, "Expiry");
  if ("error" in expiry) errors.expiry = expiry.error;
  else if (expiry.value !== saved.expiry_minutes) patch.expiry_minutes = expiry.value;

  const perHour = readInt(d.maxPerHour, limits.max_per_hour, "Codes per hour");
  if ("error" in perHour) errors.maxPerHour = perHour.error;
  else if (perHour.value !== saved.max_per_hour) patch.max_per_hour = perHour.value;

  const tries = readInt(d.maxAttempts, limits.max_attempts, "Wrong tries allowed");
  if ("error" in tries) errors.maxAttempts = tries.error;
  else if (tries.value !== saved.max_attempts) patch.max_attempts = tries.value;

  if (d.smsKey !== base.smsKey) {
    const [sender, message] = splitKey(d.smsKey);
    patch.sms_sender_id = sender;
    patch.sms_message_id = message;
  }

  if (d.waKey !== base.waKey) {
    const [name, language] = splitKey(d.waKey);
    patch.wa_template_name = name;
    patch.wa_template_language = language;
  }

  const url = d.webhookUrl.trim();
  if (url && !isHttpsUrl(url)) errors.webhookUrl = "Use an https:// address, e.g. https://example.com/otp-status.";
  const nextUrl = url || null;
  if (nextUrl !== (saved.status_webhook_url ?? null)) patch.status_webhook_url = nextUrl;

  return { patch, errors };
}

function waStatusLabel(status: string): string {
  switch (status) {
    case "APPROVED":
      return "Ready";
    case "PENDING":
      return "Waiting for approval";
    case "REJECTED":
      return "Rejected";
    case "PAUSED":
      return "Paused";
    default:
      return status.toLowerCase();
  }
}

export function SettingsTab() {
  const { can, isOwner } = usePerm();
  const canEdit = can("settings.manage");
  const { data, error, isLoading, mutate } = useSWR(OTP_OVERVIEW_KEY, () => api.otp.overview(), { revalidateOnFocus: false });

  if (error && !data) {
    return (
      <div className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
        <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void mutate()} />
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-72 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
    );
  }
  return <SettingsForm overview={data} canEdit={canEdit} isOwner={isOwner} />;
}

function SettingsForm({ overview, canEdit, isOwner }: { overview: OtpOverview; canEdit: boolean; isOwner: boolean }) {
  const { mutate } = useSWRConfig();
  const saved = overview.settings;
  const limits = overview.limits;

  // Only what the user has typed or picked is kept here. Everything else follows the saved settings.
  const [edits, setEdits] = useState<Partial<Draft>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const draft: Draft = { ...toDraft(saved), ...edits };
  const { patch, errors } = buildPatch(saved, draft, limits);
  // The SMS text is fixed by DLT, so the code must last exactly as long as the SMS says.
  const smsTemplates = useSWR(SMS_TEMPLATES_KEY, () => api.otp.smsTemplates(), { revalidateOnFocus: false });
  const smsTemplateList = smsTemplates.data?.templates ?? [];
  const chosenSms = smsTemplateList.find((t) => `${t.sender_id}|${t.message_id}` === draft.smsKey);
  const smsMinutes = chosenSms ? smsValidMinutes(chosenSms.message, limits.expiry_minutes) : null;
  if (smsMinutes !== null && !errors.expiry && Number(draft.expiry) !== smsMinutes) {
    errors.expiry = `Your SMS tells the customer the code is valid for ${smsMinutes} min. Set this to ${smsMinutes}, or pick another SMS.`;
  }
  const dirty = Object.keys(patch).length > 0;
  const hasErrors = Object.keys(errors).length > 0;
  const disabled = !canEdit || saving;

  // The WhatsApp preview quotes the expiry being typed, falling back to the saved value while it is not a valid number.
  const expiryCheck = readInt(draft.expiry, limits.expiry_minutes, "Expiry");
  const expiryPreview = "value" in expiryCheck ? expiryCheck.value : saved.expiry_minutes;

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setEdits((prev) => ({ ...prev, [key]: value }));
  }

  function pickSms(key: string) {
    const t = smsTemplateList.find((x) => `${x.sender_id}|${x.message_id}` === key);
    const n = t ? smsValidMinutes(t.message, limits.expiry_minutes) : null;
    setEdits((prev) => ({ ...prev, smsKey: key, ...(n !== null ? { expiry: String(n) } : {}) }));
  }

  function discard() {
    setEdits({});
    setSaveError("");
  }

  async function save() {
    if (!dirty || hasErrors) return;
    setSaving(true);
    setSaveError("");
    try {
      const res = await api.otp.saveSettings(patch);
      await mutate<OtpOverview>(OTP_OVERVIEW_KEY, (cur) => (cur ? { ...cur, settings: res.settings } : cur));
      setEdits({});
      toast.success("Settings saved");
    } catch (err) {
      setSaveError(otpError(err, "Couldn't save. Try again."));
    } finally {
      setSaving(false);
    }
  }

  const mode = draft.mode;
  const usesSms = mode === "sms" || mode === "both" || mode === "sms_then_whatsapp";
  const usesWhatsapp = mode === "whatsapp" || mode === "both" || mode === "sms_then_whatsapp";

  return (
    <div className="space-y-6 pb-24">
      {!canEdit && (
        <Notice tone="info">Only people with settings permission can change these. Ask the account owner.</Notice>
      )}
      {saveError && <Notice tone="danger">{saveError}</Notice>}

      <SectionCard title="Delivery" description="How codes reach your customers.">
        <div>
          <SettingsRow
            title="Default way to send"
            description="Used when a request doesn't say. You can still pick another way for a single code."
          >
            <ModeCards value={mode} onChange={(m) => set("mode", m)} disabled={disabled} />

            {(usesSms && !overview.channels.sms.ready) || (usesWhatsapp && !overview.channels.whatsapp.ready) ? (
              <div className="mt-4 space-y-3">
                {usesSms && !overview.channels.sms.ready && (
                  <Notice tone="warn">{overview.channels.sms.problem ?? "SMS isn't ready yet."}</Notice>
                )}
                {usesWhatsapp && !overview.channels.whatsapp.ready && (
                  <Notice tone="warn">{overview.channels.whatsapp.problem ?? "WhatsApp isn't ready yet."}</Notice>
                )}
              </div>
            ) : null}
          </SettingsRow>

          {mode === "sms_then_whatsapp" && (
            <SettingsRow
              title="WhatsApp backup wait"
              description="How long to wait for the SMS to be delivered before the same code goes on WhatsApp."
            >
              <NumberField
                label="WhatsApp backup wait"
                unit="seconds"
                hint={`${formatCount(limits.fallback_wait_seconds[0])} to ${formatCount(limits.fallback_wait_seconds[1])} seconds.`}
                value={draft.wait}
                onChange={(v) => set("wait", v)}
                disabled={disabled}
                error={errors.wait}
              />
            </SettingsRow>
          )}
        </div>
      </SectionCard>

      <SectionCard title="Code rules">
        <div>
          <SettingsRow title="Code length" description="How many digits Anril puts in a code.">
            <NumberField
              label="Code length"
              unit="digits"
              hint={`${limits.code_length[0]} to ${limits.code_length[1]}.`}
              value={draft.codeLength}
              onChange={(v) => set("codeLength", v)}
              disabled={disabled}
              error={errors.codeLength}
            />
          </SettingsRow>
          <SettingsRow title="Expires after" description="After this, the code stops working.">
            <NumberField
              label="Expires after"
              unit="minutes"
              hint={
                smsMinutes !== null
                  ? `Set by your SMS template: it tells the customer "valid for ${smsMinutes} min".`
                  : `${formatCount(limits.expiry_minutes[0])} to ${formatCount(limits.expiry_minutes[1])} minutes.`
              }
              value={draft.expiry}
              onChange={(v) => set("expiry", v)}
              disabled={disabled}
              error={errors.expiry}
            />
          </SettingsRow>
          <SettingsRow title="Codes per number per hour" description="Stops one number being flooded with codes.">
            <NumberField
              label="Codes per number per hour"
              unit="per hour"
              hint={`${formatCount(limits.max_per_hour[0])} to ${formatCount(limits.max_per_hour[1])}.`}
              value={draft.maxPerHour}
              onChange={(v) => set("maxPerHour", v)}
              disabled={disabled}
              error={errors.maxPerHour}
            />
          </SettingsRow>
          <SettingsRow title="Wrong tries allowed" description="After this many wrong tries the code locks.">
            <NumberField
              label="Wrong tries allowed"
              unit="tries"
              hint={`${limits.max_attempts[0]} to ${limits.max_attempts[1]}. Then the code locks.`}
              value={draft.maxAttempts}
              onChange={(v) => set("maxAttempts", v)}
              disabled={disabled}
              error={errors.maxAttempts}
            />
          </SettingsRow>
        </div>
      </SectionCard>

      <SectionCard title="Templates">
        <div>
          <SmsTemplateRow value={draft.smsKey} onChange={pickSms} disabled={disabled} />
          <WhatsappTemplateRow
            value={draft.waKey}
            onChange={(v) => set("waKey", v)}
            disabled={disabled}
            canCreate={canEdit}
            expiryMinutes={expiryPreview}
          />
        </div>
      </SectionCard>

      <SectionCard title="Status updates to your server" description="Anril tells your server when a code is delivered, read or fails.">
        <div>
          <SettingsRow title="Status URL" description="Must start with https://">
            <input
              className={inputCls}
              type="url"
              inputMode="url"
              autoComplete="off"
              placeholder="https://example.com/otp-status"
              aria-label="Status URL"
              aria-invalid={!!errors.webhookUrl}
              value={draft.webhookUrl}
              disabled={disabled}
              onChange={(e) => set("webhookUrl", e.target.value)}
            />
            {errors.webhookUrl && <FieldError message={errors.webhookUrl} />}
          </SettingsRow>

          <SigningSecret hasSecret={saved.has_webhook_secret} isOwner={isOwner} />

          <WebhookTest disabled={!canEdit || dirty || !saved.status_webhook_url} dirty={dirty} hasUrl={!!saved.status_webhook_url} />
        </div>
      </SectionCard>

      {canEdit && dirty && (
        <div className="sticky bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom,0px)+0.5rem)] lg:bottom-4 z-20 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#0A1528] px-5 py-3 text-white shadow-[0_12px_32px_rgba(10,21,40,0.28)]">
          <p className="flex items-center gap-2.5 text-sm font-semibold">
            <span className="h-2 w-2 shrink-0 rounded-full bg-[#f79009]" aria-hidden="true" />
            You have unsaved changes
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={discard}
              className="h-10 rounded-xl px-4 text-sm font-bold text-white/80 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30 disabled:opacity-50"
            >
              Discard
            </button>
            <Btn busy={saving} disabled={hasErrors} onClick={() => void save()}>
              Save
            </Btn>
          </div>
        </div>
      )}
    </div>
  );
}

function NumberField({
  label,
  hint,
  unit,
  value,
  onChange,
  disabled,
  error,
}: {
  label: string;
  hint: string;
  unit: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  error?: string;
}) {
  return (
    <div>
      <div className="relative max-w-[220px]">
        <input
          className={cn(inputCls, "pr-20")}
          type="number"
          inputMode="numeric"
          aria-label={label}
          aria-invalid={!!error}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[#94a3b8]">{unit}</span>
      </div>
      <p className="mt-1.5 text-xs text-[#64748b]">{hint}</p>
      {error && <FieldError message={error} />}
    </div>
  );
}

function FieldError({ message }: { message: string }) {
  return (
    <p role="alert" className="mt-1.5 text-xs font-semibold text-danger">
      {message}
    </p>
  );
}

/** The template message with its first {#var#} shown as the sample code. */
function withSampleCode(message: string) {
  const match = /\{#var#\}/i.exec(message);
  if (!match) return message;
  return (
    <>
      {message.slice(0, match.index)}
      <strong>{SAMPLE_CODE}</strong>
      {message.slice(match.index + match[0].length)}
    </>
  );
}

function SmsTemplateRow({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled: boolean }) {
  const { data, error, isLoading, mutate } = useSWR(SMS_TEMPLATES_KEY, () => api.otp.smsTemplates(), { revalidateOnFocus: false });
  const templates = data?.templates ?? [];
  const chosen = templates.find((t) => `${t.sender_id}|${t.message_id}` === value);
  const knownKey = value === "" || chosen !== undefined;

  return (
    <SettingsRow
      title="SMS template"
      description="Your approved DLT template with one variable. The code goes into that variable."
    >
      {error && !data ? (
        <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void mutate()} />
      ) : isLoading || !data ? (
        <Skeleton className="h-10" />
      ) : (
        <div className="space-y-3">
          {data.problem && <Notice tone="warn">{data.problem}</Notice>}
          <select
            className={`${inputCls} truncate`}
            aria-label="SMS template"
            value={value}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
          >
            <option value="">No template chosen</option>
            {templates.map((t) => {
              const key = `${t.sender_id}|${t.message_id}`;
              return (
                <option key={key} value={key}>
                  {`${t.sender_id} · ${t.message}`}
                </option>
              );
            })}
            {!knownKey && <option value={value}>Saved template (not in this list)</option>}
          </select>
          {chosen && (
            <div>
              <div className="max-w-sm break-words whitespace-pre-wrap rounded-2xl rounded-bl-md bg-[#f1f5f9] px-4 py-3 text-sm text-[#0A1528]">
                {withSampleCode(chosen.message)}
              </div>
              <p className="mt-2 text-xs text-[#64748b]">Preview with a sample code</p>
            </div>
          )}
        </div>
      )}
    </SettingsRow>
  );
}

function WhatsappTemplateRow({
  value,
  onChange,
  disabled,
  canCreate,
  expiryMinutes,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  canCreate: boolean;
  expiryMinutes: number;
}) {
  const [creating, setCreating] = useState(false);
  const { data, error, isLoading, mutate: reload } = useSWR(WA_TEMPLATES_KEY, () => api.otp.whatsappTemplates(), {
    revalidateOnFocus: false,
  });
  const templates = data?.templates ?? [];
  const known = value === "" || templates.some((t) => `${t.name}|${t.language}` === value);

  return (
    <SettingsRow
      title="WhatsApp template"
      description="Must be an approved authentication template. Create one here if you don't have one."
    >
      <div className="space-y-3">
        {data?.problem && <Notice tone="warn">{data.problem}</Notice>}

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            {error && !data ? (
              <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void reload()} />
            ) : isLoading || !data ? (
              <Skeleton className="h-10" />
            ) : (
              <select
                className={`${inputCls} truncate`}
                aria-label="WhatsApp template"
                value={value}
                disabled={disabled}
                onChange={(e) => onChange(e.target.value)}
              >
                <option value="">No template chosen</option>
                {templates.map((t) => {
                  const key = `${t.name}|${t.language}`;
                  const approved = t.status === "APPROVED";
                  return (
                    <option key={key} value={key} disabled={!approved}>
                      {approved ? `${t.name} (${t.language})` : `${t.name} (${t.language}) · ${waStatusLabel(t.status)}`}
                    </option>
                  );
                })}
                {!known && <option value={value}>Saved template (not in this list)</option>}
              </select>
            )}
          </div>
          <Btn variant="outline" className="h-10 shrink-0" disabled={!canCreate || disabled} onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" />
            Create new
          </Btn>
        </div>

        <div>
          <div className="max-w-sm rounded-2xl rounded-tl-md bg-[#e7fbe9] px-4 py-3 shadow-sm">
            <p className="text-sm text-[#0A1528]">
              <strong>{SAMPLE_CODE}</strong> is your verification code. For your security, do not share this code.
            </p>
            <p className="mt-1 text-xs text-[#64748b]">This code expires in {expiryMinutes} minutes.</p>
            <div className="mt-3 flex items-center justify-center gap-1.5 border-t border-black/10 pt-2.5 text-sm font-semibold text-primary">
              <Copy size={14} aria-hidden="true" />
              Copy code
            </div>
          </div>
          <p className="mt-2 text-xs text-[#64748b]">Preview with a sample code</p>
        </div>

        <p className="text-xs leading-relaxed text-[#64748b]">{WA_NOTE}</p>
      </div>

      <NewWhatsappTemplate open={creating} onClose={() => setCreating(false)} onCreated={() => void reload()} />
    </SettingsRow>
  );
}

function NewWhatsappTemplate({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  return (
    <Modal open={open} title="Create a WhatsApp login template" onClose={onClose}>
      <CreateTemplateForm onClose={onClose} onCreated={onCreated} />
    </Modal>
  );
}

const TEMPLATE_NAME_RE = /^[a-z0-9_]+$/;

/** Mounted only while the dialog is open, so each open starts from the defaults. */
function CreateTemplateForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("anril_login_code");
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const clean = name.trim();
    if (!TEMPLATE_NAME_RE.test(clean)) {
      setError("Use only lowercase letters, numbers and underscores.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.otp.createWhatsappTemplate({ name: clean, language });
      toast.success("Sent to WhatsApp for approval. It shows as Ready here once approved.");
      onCreated();
      onClose();
    } catch (err) {
      setError(otpError(err, "Couldn't create the template. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Template name" hint="Lowercase letters, numbers and underscores only.">
        <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
      </Field>
      <Field label="Language">
        <select className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value)}>
          {WA_LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {`${l.label} (${l.value})`}
            </option>
          ))}
        </select>
      </Field>
      {error && <Notice tone="danger">{error}</Notice>}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Btn variant="outline" onClick={onClose} disabled={busy}>
          Cancel
        </Btn>
        <Btn type="submit" busy={busy} disabled={!name.trim()}>
          Send for approval
        </Btn>
      </div>
    </form>
  );
}

function SigningSecret({ hasSecret, isOwner }: { hasSecret: boolean; isOwner: boolean }) {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);

  async function create() {
    if (hasSecret && !window.confirm("Replace the signing secret? Your server must use the new one, or its checks will fail.")) return;
    setBusy(true);
    try {
      const res = await api.otp.rotateWebhookSecret();
      setSecret(res.secret);
      void mutate(OTP_OVERVIEW_KEY);
    } catch (err) {
      toast.error(otpError(err, "Couldn't create the signing secret. Try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsRow title="Signing secret" description="Lets your server check that an update really came from Anril.">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill tone={hasSecret ? "success" : "neutral"}>{hasSecret ? "Secret is set" : "No secret yet"}</StatusPill>
          {isOwner ? (
            <Btn variant="outline" className="h-9" busy={busy} onClick={() => void create()}>
              {hasSecret ? "Replace signing secret" : "Create signing secret"}
            </Btn>
          ) : (
            <p className="text-xs text-[#64748b]">Only the account owner can create the signing secret.</p>
          )}
        </div>

        {secret && (
          <div className="space-y-3 rounded-xl border border-[#fedf89] bg-[#fffaeb] p-4">
            <p className="text-sm font-semibold text-[#b54708]">Copy it now. Anril won&apos;t show it again.</p>
            <div className="flex items-center gap-2 rounded-xl border border-[#e2e8f0] bg-white py-1.5 pl-3 pr-1.5">
              <code className="min-w-0 flex-1 select-all break-all font-mono text-xs text-[#0A1528]">{secret}</code>
              <CopyButton text={secret} />
            </div>
            <Btn variant="link" onClick={() => setSecret(null)}>
              I&apos;ve copied it
            </Btn>
          </div>
        )}
      </div>
    </SettingsRow>
  );
}

function WebhookTest({ disabled, dirty, hasUrl }: { disabled: boolean; dirty: boolean; hasUrl: boolean }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; error: string | null } | null>(null);
  const [failure, setFailure] = useState("");

  async function test() {
    setBusy(true);
    setResult(null);
    setFailure("");
    try {
      setResult(await api.otp.testWebhook());
    } catch (err) {
      setFailure(otpError(err, "Couldn't send the test update. Try again."));
    } finally {
      setBusy(false);
    }
  }

  let hint = "Sends a sample update to the address above.";
  if (dirty) hint = "Save your changes first, then send a test.";
  else if (!hasUrl) hint = "Save an address first, then send a test.";

  return (
    <SettingsRow title="Test" description={hint}>
      <div className="space-y-3">
        <Btn variant="outline" className="h-9" busy={busy} disabled={disabled} onClick={() => void test()}>
          Send test update
        </Btn>
        {failure && <Notice tone="danger">{failure}</Notice>}
        {result?.ok && <Notice tone="success">Your server accepted the test update.</Notice>}
        {result && !result.ok && <Notice tone="danger">{result.error ?? "Your server didn't accept the test update."}</Notice>}
      </div>
    </SettingsRow>
  );
}
