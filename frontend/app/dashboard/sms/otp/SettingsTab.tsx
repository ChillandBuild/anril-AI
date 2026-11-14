"use client";

import { useState, type FormEvent } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "sonner";
import { api, type OtpMode, type OtpOverview, type OtpSettings } from "@/lib/api";
import { formatCount } from "../helpers";
import { usePerm } from "../usePerm";
import { Badge, Btn, Card, CardHeader, Field, LoadError, Modal, Notice, Skeleton, inputCls } from "../ui";
import { ModePicker, OTP_OVERVIEW_KEY, otpError } from "./otpShared";

const SMS_TEMPLATES_KEY = "otp:sms-templates";
const WA_TEMPLATES_KEY = "otp:wa-templates";

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
      <Card>
        <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void mutate()} />
      </Card>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-64" />
        <Skeleton className="h-40" />
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
  const dirty = Object.keys(patch).length > 0;
  const hasErrors = Object.keys(errors).length > 0;
  const disabled = !canEdit || saving;

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setEdits((prev) => ({ ...prev, [key]: value }));
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
    <div className="space-y-4 pb-2">
      {!canEdit && (
        <Notice tone="info">Only people with settings permission can change these. Ask the account owner.</Notice>
      )}
      {saveError && <Notice tone="danger">{saveError}</Notice>}

      <Card>
        <CardHeader title="How codes are sent" hint="Pick the default. You can still choose another way for a single code." />
        <div className="space-y-4 p-4 sm:p-5">
          <ModePicker value={mode} onChange={(m) => set("mode", m)} disabled={disabled} showHints />

          {usesSms && !overview.channels.sms.ready && (
            <Notice tone="warn">{overview.channels.sms.problem ?? "SMS isn't ready yet."}</Notice>
          )}
          {usesWhatsapp && !overview.channels.whatsapp.ready && (
            <Notice tone="warn">{overview.channels.whatsapp.problem ?? "WhatsApp isn't ready yet."}</Notice>
          )}

          {mode === "sms_then_whatsapp" && (
            <NumberField
              label="Wait before sending on WhatsApp"
              hint={`Seconds. ${formatCount(limits.fallback_wait_seconds[0])} to ${formatCount(limits.fallback_wait_seconds[1])}.`}
              value={draft.wait}
              onChange={(v) => set("wait", v)}
              range={limits.fallback_wait_seconds}
              disabled={disabled}
              error={errors.wait}
              className="sm:max-w-xs"
            />
          )}
        </div>
      </Card>

      <Card>
        <CardHeader title="Code rules" />
        <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5 lg:grid-cols-4">
          <NumberField
            label="Code length"
            hint={`Digits. ${limits.code_length[0]} to ${limits.code_length[1]}.`}
            value={draft.codeLength}
            onChange={(v) => set("codeLength", v)}
            range={limits.code_length}
            disabled={disabled}
            error={errors.codeLength}
          />
          <NumberField
            label="Expires after (minutes)"
            hint={`${formatCount(limits.expiry_minutes[0])} to ${formatCount(limits.expiry_minutes[1])} minutes.`}
            value={draft.expiry}
            onChange={(v) => set("expiry", v)}
            range={limits.expiry_minutes}
            disabled={disabled}
            error={errors.expiry}
          />
          <NumberField
            label="Max codes per number per hour"
            hint={`${formatCount(limits.max_per_hour[0])} to ${formatCount(limits.max_per_hour[1])}.`}
            value={draft.maxPerHour}
            onChange={(v) => set("maxPerHour", v)}
            range={limits.max_per_hour}
            disabled={disabled}
            error={errors.maxPerHour}
          />
          <NumberField
            label="Wrong tries allowed"
            hint={`${limits.max_attempts[0]} to ${limits.max_attempts[1]}. Then the code locks.`}
            value={draft.maxAttempts}
            onChange={(v) => set("maxAttempts", v)}
            range={limits.max_attempts}
            disabled={disabled}
            error={errors.maxAttempts}
          />
        </div>
      </Card>

      <SmsTemplateCard value={draft.smsKey} onChange={(v) => set("smsKey", v)} disabled={disabled} />

      <WhatsappTemplateCard value={draft.waKey} onChange={(v) => set("waKey", v)} disabled={disabled} canCreate={canEdit} />

      <Card>
        <CardHeader title="Status updates to your server" hint="Anril tells your server when a code is delivered, read or fails." />
        <div className="space-y-5 p-4 sm:p-5">
          <div className="space-y-2">
            <Field label="Your server's address" hint="Must start with https://">
              <input
                className={inputCls}
                type="url"
                inputMode="url"
                autoComplete="off"
                placeholder="https://example.com/otp-status"
                value={draft.webhookUrl}
                disabled={disabled}
                onChange={(e) => set("webhookUrl", e.target.value)}
              />
            </Field>
            {errors.webhookUrl && <FieldError message={errors.webhookUrl} />}
          </div>

          <SigningSecret hasSecret={saved.has_webhook_secret} isOwner={isOwner} />

          <WebhookTest
            disabled={!canEdit || dirty || !saved.status_webhook_url}
            dirty={dirty}
            hasUrl={!!saved.status_webhook_url}
          />
        </div>
      </Card>

      {canEdit && dirty && (
        <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#e2e8f0] bg-white px-4 py-3 shadow-lg">
          <p className="text-sm font-semibold text-[#334155]">Unsaved changes</p>
          <div className="flex gap-2">
            <Btn variant="outline" disabled={saving} onClick={discard}>
              Discard
            </Btn>
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
  value,
  onChange,
  range,
  disabled,
  error,
  className,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  range: [number, number];
  disabled: boolean;
  error?: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <Field label={label} hint={hint}>
        <input
          className={inputCls}
          type="number"
          inputMode="numeric"
          min={range[0]}
          max={range[1]}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
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

function SmsTemplateCard({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled: boolean }) {
  const { data, error, isLoading, mutate } = useSWR(SMS_TEMPLATES_KEY, () => api.otp.smsTemplates(), { revalidateOnFocus: false });
  const templates = data?.templates ?? [];
  const chosen = templates.find((t) => `${t.sender_id}|${t.message_id}` === value);
  const knownKey = value === "" || chosen !== undefined;

  return (
    <Card>
      <CardHeader title="SMS template" hint="Your approved DLT template with one variable. The code goes into that variable." />
      <div className="space-y-3 p-4 sm:p-5">
        {error && !data ? (
          <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void mutate()} />
        ) : isLoading || !data ? (
          <Skeleton className="h-10" />
        ) : (
          <>
            {data.problem && <Notice tone="warn">{data.problem}</Notice>}
            <Field label="Template">
              <select
                className={`${inputCls} truncate`}
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
            </Field>
            {chosen && <p className="break-words rounded-xl bg-[#f8fafc] px-3 py-2 text-xs text-[#334155] whitespace-pre-wrap">{chosen.message}</p>}
          </>
        )}
      </div>
    </Card>
  );
}

function WhatsappTemplateCard({
  value,
  onChange,
  disabled,
  canCreate,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  canCreate: boolean;
}) {
  const [creating, setCreating] = useState(false);
  const { data, error, isLoading, mutate: reload } = useSWR(WA_TEMPLATES_KEY, () => api.otp.whatsappTemplates(), {
    revalidateOnFocus: false,
  });
  const templates = data?.templates ?? [];
  const known = value === "" || templates.some((t) => `${t.name}|${t.language}` === value);

  return (
    <Card>
      <CardHeader
        title="WhatsApp template"
        hint="Only approved templates can be used. Create one here if you don't have one yet."
        action={
          <Btn variant="outline" className="h-9" disabled={!canCreate || disabled} onClick={() => setCreating(true)}>
            Create new
          </Btn>
        }
      />
      <div className="space-y-3 p-4 sm:p-5">
        {error && !data ? (
          <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void reload()} />
        ) : isLoading || !data ? (
          <Skeleton className="h-10" />
        ) : (
          <>
            {data.problem && <Notice tone="warn">{data.problem}</Notice>}
            <Field label="Template">
              <select className={`${inputCls} truncate`} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
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
            </Field>
          </>
        )}
      </div>
      <div className="border-t border-[#e2e8f0] p-4 sm:p-5">
        <Notice tone="info">{WA_NOTE}</Notice>
      </div>

      <NewWhatsappTemplate
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => void reload()}
      />
    </Card>
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

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied");
    } catch {
      toast.error("Couldn't copy. Select the text and copy it.");
    }
  }

  return (
    <div className="space-y-3 border-t border-[#e2e8f0] pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-bold text-[#0A1528]">Signing secret</p>
          <p className="mt-0.5 text-xs text-[#64748b]">Lets your server check that an update really came from Anril.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={hasSecret ? "success" : "neutral"}>{hasSecret ? "Secret is set" : "No secret yet"}</Badge>
          {isOwner ? (
            <Btn variant="outline" className="h-9" busy={busy} onClick={() => void create()}>
              {hasSecret ? "Replace signing secret" : "Create signing secret"}
            </Btn>
          ) : (
            <p className="text-xs text-[#64748b]">Only the account owner can create the signing secret.</p>
          )}
        </div>
      </div>

      {secret && (
        <div className="space-y-3">
          <Notice tone="warn">Copy it now. Anril won&apos;t show it again.</Notice>
          <code className="block select-all break-all rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2.5 font-mono text-xs text-[#0A1528]">
            {secret}
          </code>
          <div className="flex flex-wrap gap-2">
            <Btn variant="outline" className="h-9" onClick={() => void copy(secret)}>
              Copy
            </Btn>
            <Btn variant="link" onClick={() => setSecret(null)}>
              I&apos;ve copied it
            </Btn>
          </div>
        </div>
      )}
    </div>
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
    <div className="space-y-3 border-t border-[#e2e8f0] pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-[#64748b]">{hint}</p>
        <Btn variant="outline" className="h-9" busy={busy} disabled={disabled} onClick={() => void test()}>
          Send test update
        </Btn>
      </div>
      {failure && <Notice tone="danger">{failure}</Notice>}
      {result?.ok && <Notice tone="success">Your server accepted the test update.</Notice>}
      {result && !result.ok && <Notice tone="danger">{result.error ?? "Your server didn't accept the test update."}</Notice>}
    </div>
  );
}
