"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, type SmsPreview, type SmsTemplate, type SmsVarSource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { dateBounds, defaultWhen, formatSendTime, resolveWhen, untilSend, type WhenValue } from "@/lib/schedule-time";
import { NumbersPicker, useHasLeads } from "./RecipientPicker";
import { SendPreview } from "./SendPreview";
import { VariableMapper, Wording } from "./SendVars";
import { useSms } from "./SmsShell";
import {
  EMPTY_NUMBERS,
  EMPTY_OWN,
  UNICODE_NOTE,
  buildSendRequest,
  defaultSendName,
  errorStatus,
  errorText,
  fieldsSourceFor,
  formatCount,
  friendlyError,
  nextIdempotencyKey,
  pruneVarMap,
  sendBlock,
  sendFormProblem,
  sendType,
  smsCounterLine,
  sendSummary,
  smsSegments,
  templateVarCount,
  withNumbersChange,
  type NumbersState,
  type OwnDlt,
  type SendFormInput,
} from "./helpers";
import { Badge, Btn, Card, Field, LoadError, Notice, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

const OWN = "__own__";

/** The one Send SMS form: pick an approved template or Type my own, say who gets it, preview, send or schedule. */
export function SendForm() {
  const { canManage } = usePerm();
  const { reloadBalance, status: smsStatus } = useSms();
  const [choice, setChoice] = useState("");
  const [varMap, setVarMap] = useState<(SmsVarSource | null)[]>([]);
  const [own, setOwn] = useState<OwnDlt>(EMPTY_OWN);
  const [numbers, setNumbers] = useState<NumbersState>(EMPTY_NUMBERS);
  const [name, setName] = useState(() => defaultSendName(new Date()));
  const [when, setWhen] = useState<WhenValue>(() => ({ ...defaultWhen(new Date()), mode: "now" }));
  const [preview, setPreview] = useState<{ key: string; data: SmsPreview } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<{ scheduled: boolean } | null>(null);
  // One key per exact request (body, name, schedule): a double click or a retry after a lost reply
  // cannot create a second campaign, and any edit gets a fresh key.
  const keyRef = useRef<{ signature: string; key: string } | null>(null);
  const submittingRef = useRef(false);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const templates = useSWR("sms:templates", () => api.sms.templates(), { revalidateOnFocus: false });
  const senders = useSWR("sms:senders", () => api.sms.senders(), { revalidateOnFocus: false });
  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const balance = useSWR("sms:balance", () => api.sms.balance(), { revalidateOnFocus: true, shouldRetryOnError: false });
  const hasLeads = useHasLeads();

  const ready = useMemo(() => (templates.data?.templates ?? []).filter((t) => t.status === "ready" && t.template_type !== "unclassified"), [templates.data]);
  const route: SendFormInput["route"] = choice === OWN ? "own" : choice ? "template" : null;
  const template: SmsTemplate | null = route === "template" ? (ready.find((t) => t.id === choice) ?? null) : null;
  const varCount = templateVarCount(template);
  const input: SendFormInput = { route, template, varMap, own, numbers };
  const type = sendType(input);
  const promotional = type === "promotional";
  const problem = sendFormProblem(input);
  const request = buildSendRequest(input);
  const requestKey = JSON.stringify(request);
  const freshPreview = preview && request && preview.key === requestKey ? preview.data : null;

  const groupKey = numbers.groupIds.slice().sort().join(",");
  const fieldsSource = fieldsSourceFor(numbers.mode);
  const fields = useSWR(
    route === "template" && varCount > 0 ? ["sms:campaign-fields", fieldsSource, fieldsSource === "contacts" ? groupKey : ""] : null,
    () => api.sms.campaignFields(fieldsSource, numbers.groupIds),
    { revalidateOnFocus: false },
  );

  // Leads mode disappears if the client has none; fall back to Contact.
  useEffect(() => {
    if (numbers.mode === "leads" && !hasLeads) setNumbers((n) => withNumbersChange(n, { mode: "contact" }));
  }, [numbers.mode, hasLeads]);

  // Switching who gets the SMS changes which contact fields exist; forget mappings to fields that are gone.
  const offeredFields = fields.data?.fields;
  useEffect(() => {
    if (offeredFields) setVarMap((m) => pruneVarMap(m, offeredFields.map((f) => f.key)));
  }, [offeredFields]);

  const resolved = resolveWhen(when, now);
  const bounds = dateBounds(now);
  const scheduleBad = when.mode === "later" && !!resolved.error;
  const block = sendBlock({
    loading: (status.isLoading && !status.data) || (balance.isLoading && !balance.data),
    peTm: status.data ? status.data.checklist.pe_tm === true : undefined,
    balance: balance.data?.sms_count,
    needed: freshPreview?.total_segments ?? 0,
    support: status.data?.support_contact || null,
  });
  const canSend = !!freshPreview && freshPreview.eligible_count > 0 && !scheduleBad && name.trim().length > 0 && !submitting && !block.blocked;

  const message = route === "template" ? (template?.message ?? "") : own.message;
  const length = smsSegments(message.replace(/\{#var#\}/gi, "x"));

  function pickTemplate(value: string) {
    setChoice(value);
    setCreated(null);
    setError(null);
    // The consent tick was for the previous template's type; ask again.
    setNumbers((n) => withNumbersChange(n, { consent: false }));
    const t = ready.find((x) => x.id === value);
    setVarMap(Array.from({ length: templateVarCount(t ?? null) }, () => null));
  }

  function setVar(i: number, value: SmsVarSource | null) {
    setVarMap((m) => {
      const next = [...m];
      next[i] = value;
      return next;
    });
  }

  function setOwnField(patch: Partial<OwnDlt>) {
    setCreated(null);
    setOwn((o) => ({ ...o, ...patch }));
    if (patch.template_type) setNumbers((n) => ({ ...n, consent: false }));
  }

  if (!canManage) {
    return (
      <Card>
        <div className="p-4 sm:p-5">
          <Notice tone="info">You can view SMS reports, but sending needs the SMS manage permission. Ask the account owner.</Notice>
        </div>
      </Card>
    );
  }

  async function runPreview() {
    if (!request) return;
    setPreviewing(true);
    setError(null);
    const key = requestKey;
    try {
      const data = await api.sms.previewCampaign(request);
      setPreview({ key, data });
    } catch (err) {
      setPreview(null);
      setError(friendlyError(err, "Couldn't build the preview."));
    } finally {
      setPreviewing(false);
    }
  }

  async function send() {
    if (!request || submittingRef.current) return;
    const schedule = resolveWhen(when, new Date());
    if (schedule.error) {
      setError(schedule.error);
      setConfirming(false);
      return;
    }
    if (!canSend) {
      setConfirming(false);
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const sendAt = when.mode === "later" && schedule.at ? schedule.at.toISOString() : null;
      keyRef.current = nextIdempotencyKey(keyRef.current, JSON.stringify({ request, name: name.trim(), sendAt }), () => crypto.randomUUID());
      await api.sms.createCampaign({ ...request, name: name.trim(), send_at: sendAt, idempotency_key: keyRef.current.key });
      toast.success(when.mode === "later" ? "SMS scheduled." : "SMS is sending.");
      setCreated({ scheduled: when.mode === "later" });
      reloadBalance();
      setChoice("");
      setVarMap([]);
      setOwn(EMPTY_OWN);
      setNumbers((n) => ({ ...EMPTY_NUMBERS, mode: n.mode }));
      setPreview(null);
      setName(defaultSendName(new Date()));
      keyRef.current = null;
    } catch (err) {
      const code = errorStatus(err);
      // A 4xx means nothing was created, so the next attempt may use a fresh key.
      if (code && code >= 400 && code < 500) keyRef.current = null;
      // A 409 carries the exact reason (PE–TM not confirmed, not enough balance), so show it as sent.
      setError(code === 409 ? errorText(err, "Couldn't send the SMS.") : friendlyError(err, "Couldn't send the SMS."));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
      setConfirming(false);
    }
  }

  const locked = route === "template" && !!template;
  const senderList = senders.data?.senders ?? [];

  const sample = freshPreview?.samples[0] ?? null;
  const senderShown = locked ? (template?.sender_id ?? "") : own.sender_id;
  const summary = sendSummary({ preview: freshPreview, parts: sample?.segments ?? length.parts, balance: balance.data ?? null });
  const section = "text-xs font-bold uppercase tracking-wider text-[#64748b]";

  // Layout A: the form on the left, preview + cost + Send on the right. On a laptop the two columns
  // fill the screen under the app header (64px) and page padding (2 × 28px), so the page itself never
  // scrolls; a long column scrolls inside its own card. Phones stack the two and scroll normally.
  return (
    <div className="grid gap-4 lg:h-[calc(100dvh-7.5rem)] lg:grid-cols-[minmax(0,1fr)_minmax(20rem,24rem)]">
      <div className="min-h-0 space-y-4 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:p-5 lg:overflow-y-auto">
        {!smsStatus.checklist.pe_tm && (
          <Notice tone="warn">
            Sending unlocks after PE-TM binding.{" "}
            <Link href="/dashboard/sms/setup?tab=petm" className="font-bold underline">
              Finish binding
            </Link>
          </Notice>
        )}

        <section aria-labelledby="sms-send-message" className="space-y-3">
          <h2 id="sms-send-message" className={section}>
            Message
          </h2>
          <select aria-label="Template" className={inputCls} value={choice} onChange={(e) => pickTemplate(e.target.value)}>
            <option value="">Choose an approved template…</option>
            {ready.map((t) => (
              <option key={t.id} value={t.id}>
                {t.message.length > 70 ? `${t.message.slice(0, 70)}…` : t.message}
              </option>
            ))}
            <option value={OWN}>Type my own</option>
          </select>
          {templates.error && !templates.data && <LoadError message={friendlyError(templates.error, "Couldn't load your templates.")} onRetry={() => void templates.mutate()} />}

          {route === "template" && template && (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[#64748b]">
              <span className="font-bold text-[#0A1528]">{template.sender_id}</span>
              <span>· Entity {template.entity_id}</span>
              <span>· DLT {template.dlt_template_id}</span>
              <Badge tone={promotional ? "warn" : "neutral"}>{promotional ? "Promotional" : "Service"}</Badge>
            </p>
          )}

          {route === "own" && (
            <>
              <div className="grid gap-3 sm:grid-cols-4">
                <Field label="Sender ID">
                  <select
                    className={inputCls}
                    value={own.sender_id}
                    onChange={(e) => {
                      const s = senderList.find((x) => x.sender_id === e.target.value);
                      setOwnField({ sender_id: e.target.value, entity_id: s?.entity_id ?? "" });
                    }}
                  >
                    <option value="">{senders.isLoading ? "Loading…" : "Pick a sender"}</option>
                    {senderList.map((s) => (
                      <option key={s.sender_id} value={s.sender_id}>
                        {s.sender_id}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="DLT entity ID">
                  <input className={inputCls} value={own.entity_id} onChange={(e) => setOwnField({ entity_id: e.target.value })} />
                </Field>
                <Field label="DLT template ID">
                  <input className={inputCls} value={own.dlt_template_id} onChange={(e) => setOwnField({ dlt_template_id: e.target.value })} />
                </Field>
                <Field label="Type">
                  <select className={inputCls} value={own.template_type} onChange={(e) => setOwnField({ template_type: e.target.value as OwnDlt["template_type"] })}>
                    <option value="service">Service</option>
                    <option value="promotional">Promotional</option>
                  </select>
                </Field>
              </div>
              <Field label="Message" hint="Exact approved wording. No {#var#} here.">
                <textarea className={textareaCls} rows={3} value={own.message} onChange={(e) => setOwnField({ message: e.target.value })} />
              </Field>
            </>
          )}

          {route === "template" &&
            template &&
            varCount > 0 &&
            (fields.error && !fields.data ? (
              <LoadError message={friendlyError(fields.error, "Couldn't load the contact fields.")} onRetry={() => void fields.mutate()} />
            ) : (
              <VariableMapper varCount={varCount} varMap={varMap} fields={fields.data?.fields ?? []} onSet={setVar} />
            ))}

          {route !== null && message && (
            <div>
              <p className="text-xs font-semibold text-[#334155]" aria-live="polite">
                {length.unicode ? "Unicode" : "English"} · {smsCounterLine(message)}
                {varCount > 0 ? " (each variable counted as 1 character; the real length can differ)" : ""}
              </p>
              {length.unicode && <p className="mt-0.5 text-xs text-[#b45309]">{UNICODE_NOTE}</p>}
            </div>
          )}
        </section>

        <section aria-labelledby="sms-send-recipients" className="space-y-3 border-t border-[#f1f5f9] pt-4">
          <h2 id="sms-send-recipients" className={section}>
            Recipients
          </h2>
          <NumbersPicker
            value={numbers}
            onChange={(update) => {
              setCreated(null);
              setNumbers((prev) => withNumbersChange(prev, update(prev)));
            }}
            promotional={promotional}
            showLeads={hasLeads}
          />
        </section>

        <section className="space-y-2 border-t border-[#f1f5f9] pt-4">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Name" className="min-w-[12rem] flex-1">
              <input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            </Field>
            <div className="flex gap-2" role="radiogroup" aria-label="When to send">
              {(["now", "later"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="radio"
                  aria-checked={when.mode === m}
                  onClick={() => setWhen((w) => ({ ...w, mode: m }))}
                  className={cn(
                    "h-10 rounded-xl border px-4 text-sm font-bold",
                    when.mode === m ? "border-primary bg-primary/5 text-primary" : "border-[#e2e8f0] text-[#64748b] hover:border-slate-300",
                  )}
                >
                  {m === "now" ? "Now" : "Later"}
                </button>
              ))}
            </div>
            {when.mode === "later" && (
              <>
                <Field label="Date (IST)" className="w-40">
                  <input type="date" className={inputCls} value={when.date} min={bounds.min} max={bounds.max} onChange={(e) => setWhen((w) => ({ ...w, date: e.target.value }))} />
                </Field>
                <Field label="Time (IST)" className="w-32">
                  <input type="time" className={inputCls} value={when.time} onChange={(e) => setWhen((w) => ({ ...w, time: e.target.value }))} />
                </Field>
              </>
            )}
          </div>
          {when.mode === "later" &&
            (resolved.error ? (
              <p className="text-xs font-semibold text-danger">{resolved.error}</p>
            ) : (
              resolved.at && <p className="text-xs text-[#64748b]">Goes out {formatSendTime(resolved.at)} IST ({untilSend(resolved.at, now)}).</p>
            ))}
        </section>
      </div>

      <aside aria-label="Preview and send" className="flex min-h-0 flex-col gap-4 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:p-5 lg:overflow-y-auto">
        <h2 className={section}>Preview</h2>
        <div className="space-y-2 rounded-xl bg-[#0A1528] p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#9fb3c8]">{senderShown || "Sender ID"}</p>
          <div className="max-w-[92%] rounded-xl rounded-bl-sm bg-white px-3 py-2.5">
            {sample ? (
              <p className="whitespace-pre-wrap break-words text-sm text-[#0A1528]">{sample.content}</p>
            ) : message ? (
              <Wording message={message} map={route === "template" ? varMap : undefined} fields={fields.data?.fields} />
            ) : (
              <p className="text-sm text-[#94a3b8]">Pick a template to see the message.</p>
            )}
          </div>
          <p className="text-[11px] text-[#9fb3c8]">{sample ? `Shown with ${sample.name || "the first recipient"}'s values.` : "Press Preview to fill in real values."}</p>
        </div>

        <dl className="grid grid-cols-2 gap-y-2 text-sm">
          {summary.map((r) => (
            <div key={r.label} className="contents">
              <dt className="text-[#64748b]">{r.label}</dt>
              <dd className={cn("text-right font-bold text-[#0A1528]", r.bad && "text-danger")}>{r.value}</dd>
            </div>
          ))}
        </dl>

        {freshPreview && <SendPreview preview={freshPreview} />}
        {freshPreview && block.reason && <Notice tone="warn">{block.reason}</Notice>}
        {!freshPreview && problem && route !== null && <p className="text-xs text-[#64748b]">{problem}</p>}
        {error && <Notice tone="danger">{error}</Notice>}
        {created && (
          <Notice tone="success">
            {created.scheduled ? "SMS scheduled." : "SMS is sending."}{" "}
            <Link href="/dashboard/sms/reports" className="font-bold underline">
              See it in Reports
            </Link>
          </Notice>
        )}

        <div className="mt-auto grid gap-2">
          <Btn variant="outline" busy={previewing} disabled={!request || scheduleBad} onClick={() => void runPreview()}>
            {freshPreview ? "Preview again" : "Preview"}
          </Btn>
          <Btn
            className="h-12 text-base"
            disabled={!canSend}
            onClick={() => {
              const current = new Date();
              setNow(current);
              const schedule = resolveWhen(when, current);
              if (schedule.error) setError(schedule.error);
              else setConfirming(true);
            }}
          >
            {when.mode === "later" ? "Schedule" : "Send now"}
          </Btn>
          {!freshPreview && request && <p className="text-center text-xs text-[#64748b]">Preview first: it counts who gets it and what it costs.</p>}
        </div>
      </aside>

      <ConfirmModal
        open={confirming}
        onClose={() => !submitting && setConfirming(false)}
        onConfirm={() => void send()}
        title={when.mode === "later" ? "Schedule this SMS?" : "Send this SMS now?"}
        description={
          freshPreview
            ? `${formatCount(freshPreview.eligible_count)} people will get this SMS. ${
                when.mode === "later" && resolved.at ? `It goes out ${formatSendTime(resolved.at)} IST.` : "Sending can't be undone once it starts."
              }`
            : ""
        }
        confirmLabel={when.mode === "later" ? "Schedule" : "Send"}
        loading={submitting}
        loadingLabel="Working…"
      />
    </div>
  );
}
