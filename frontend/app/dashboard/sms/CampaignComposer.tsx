"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Check } from "lucide-react";
import { toast } from "sonner";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, type SmsCampaign, type SmsTemplate, type SmsVarSource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { dateBounds, defaultWhen, formatSendTime, resolveWhen, untilSend, type WhenValue } from "@/lib/schedule-time";
import { EMPTY_RECIPIENTS, RecipientPicker, recipientRequest, recipientsReadyFor, type RecipientState } from "./RecipientPicker";
import {
  countVars,
  errorStatus,
  errorText,
  estimateLine,
  formatCount,
  friendlyError,
  groupExcluded,
  isVariableMapComplete,
  parseNumbers,
  sendBlock,
  splitTemplate,
} from "./helpers";
import { Badge, Btn, Card, CardHeader, ConsentCheck, Empty, Field, LoadError, Notice, inputCls } from "./ui";

const STEPS = ["Pick recipients", "Pick template", "Fill variables", "Review & send"];
const FIXED = "__fixed__";

function defaultName(): string {
  return `Campaign ${formatSendTime(new Date())}`;
}

/** Wording with each {#var#} shown as a numbered chip, or as the chosen value once mapped. */
function Wording({ message, map, fields }: { message: string; map?: (SmsVarSource | null)[]; fields?: { key: string; label: string }[] }) {
  return (
    <p className="whitespace-pre-wrap break-words text-sm text-[#334155]">
      {splitTemplate(message).map((part, i) => {
        if (part.kind === "text") return <Fragment key={i}>{part.text}</Fragment>;
        const src = map?.[part.index];
        let label = `Variable ${part.index + 1}`;
        if (src?.value) {
          label = src.source === "field" ? (fields?.find((f) => f.key === src.value)?.label ?? src.value) : src.value;
        }
        return (
          <span key={i} className="mx-0.5 inline-block rounded-md bg-primary-100 px-1.5 py-0.5 text-xs font-bold text-primary-dark">
            {label}
          </span>
        );
      })}
    </p>
  );
}

export function CampaignComposer({ onClose, onCreated }: { onClose: () => void; onCreated: (c: SmsCampaign) => void }) {
  const [step, setStep] = useState(1);
  const [recipients, setRecipients] = useState<RecipientState>(EMPTY_RECIPIENTS);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [varMap, setVarMap] = useState<(SmsVarSource | null)[]>([]);
  const [name, setName] = useState(defaultName);
  const [when, setWhen] = useState<WhenValue>(() => ({ ...defaultWhen(new Date()), mode: "now" }));
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  // One key per composer open: a double click or a retry after a lost reply cannot create a second campaign.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const submittingRef = useRef(false);

  const templates = useSWR("sms:templates", () => api.sms.templates(), { revalidateOnFocus: false });
  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const balance = useSWR("sms:balance", () => api.sms.balance(), { revalidateOnFocus: true, shouldRetryOnError: false });
  const groupIdList = Array.from(recipients.groupIds).sort();
  const fieldsSource = recipients.tab === "contacts" ? "contacts" : "leads";
  const fields = useSWR(
    ["sms:campaign-fields", fieldsSource, fieldsSource === "contacts" ? groupIdList.join(",") : ""],
    () => api.sms.campaignFields(fieldsSource, groupIdList),
    { revalidateOnFocus: false },
  );

  const ready = useMemo(() => (templates.data?.templates ?? []).filter((t) => t.status === "ready" && t.template_type !== "unclassified"), [templates.data]);
  const template: SmsTemplate | null = ready.find((t) => t.id === templateId) ?? null;
  const varCount = template ? Math.max(template.var_count ?? 0, countVars(template.message)) : 0;
  const fieldList = fields.data?.fields ?? [];

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const promotional = template?.template_type === "promotional";
  const recipientReq = recipientRequest(recipients, promotional);
  const inputKey = JSON.stringify([template, varMap, recipientReq]);
  const { data: preview, error: previewFailure, isLoading: previewLoading, mutate: reloadPreview } = useSWR(
    step === 4 && template && recipientsReadyFor(recipients, promotional) && isVariableMapComplete(varMap, varCount) ? ["sms:preview", inputKey] : null,
    () => api.sms.previewCampaign({ kind: "template", template_id: template!.id, variable_map: varMap.slice(0, varCount) as SmsVarSource[], ...recipientReq }),
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const previewError = previewFailure ? friendlyError(previewFailure, "Couldn't build the preview.") : null;
  const resolved = resolveWhen(when, now);
  const bounds = dateBounds(now);

  function pickTemplate(t: SmsTemplate) {
    setTemplateId(t.id);
    const n = Math.max(t.var_count ?? 0, countVars(t.message));
    setVarMap(Array.from({ length: n }, () => null));
  }

  function setVar(i: number, value: SmsVarSource | null) {
    setVarMap((m) => {
      const next = [...m];
      next[i] = value;
      return next;
    });
  }

  const canNext1 = recipientsReadyFor(recipients, false);
  // Whether the pasted-numbers consent tick is needed depends on the template, so it is checked here.
  const canNext2 = !!template && recipientsReadyFor(recipients, promotional);
  const canNext3 = !!template && isVariableMapComplete(varMap, varCount);

  function goNext() {
    setStep((current) => Math.min(4, current + 1));
  }

  const scheduleBad = when.mode === "later" && !!resolved.error;
  const block = sendBlock({
    loading: (status.isLoading && !status.data) || (balance.isLoading && !balance.data),
    peTm: status.data ? status.data.checklist.pe_tm === true : undefined,
    balance: balance.data?.sms_count,
    needed: preview?.total_segments ?? 0,
    support: status.data?.support_contact || null,
  });
  const canSend = !!preview && preview.eligible_count > 0 && !previewLoading && !scheduleBad && name.trim().length > 0 && !submitting && !block.blocked;

  async function submit() {
    if (!template || submittingRef.current) return;
    const freshSchedule = resolveWhen(when, new Date());
    if (freshSchedule.error) {
      setSubmitError(freshSchedule.error);
      setConfirming(false);
      return;
    }
    if (!canSend) {
      setConfirming(false);
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const campaign = await api.sms.createCampaign({
        name: name.trim(),
        kind: "template",
        template_id: template.id,
        variable_map: varMap.slice(0, varCount).map((v) => v as SmsVarSource),
        ...recipientReq,
        send_at: when.mode === "later" && freshSchedule.at ? freshSchedule.at.toISOString() : null,
        idempotency_key: idempotencyKey,
      });
      toast.success(when.mode === "later" ? "Campaign scheduled." : "Campaign is sending.");
      onCreated(campaign);
    } catch (err) {
      const status = errorStatus(err);
      // A 4xx means nothing was created, so the next attempt may use a fresh key (the inputs may have changed).
      if (status && status >= 400 && status < 500) setIdempotencyKey(crypto.randomUUID());
      // A 409 here carries the exact reason (PE–TM not confirmed, not enough balance), so show it as sent.
      setSubmitError(status === 409 ? errorText(err, "Couldn't create the campaign.") : friendlyError(err, "Couldn't create the campaign."));
      setConfirming(false);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  const excludedGroups = preview ? groupExcluded(preview.excluded) : [];
  const anyUnicode = preview?.samples.some((s) => s.unicode) ?? false;

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-3">
        <button type="button" onClick={onClose} className="flex items-center gap-1 text-sm font-bold text-primary hover:underline">
          <ArrowLeft size={15} /> Campaigns
        </button>
        <h2 className="font-display text-lg font-bold text-[#0A1528]">New campaign</h2>
      </div>

      <ol className="flex flex-wrap gap-2" aria-label="Steps">
        {STEPS.map((label, i) => {
          const n = i + 1;
          const done = step > n;
          const active = step === n;
          return (
            <li
              key={label}
              aria-current={active ? "step" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold",
                active ? "border-primary bg-primary/5 text-primary" : done ? "border-[#bbf7d0] bg-[#ecfdf3] text-[#15803d]" : "border-[#e2e8f0] text-[#94a3b8]",
              )}
            >
              <span className="grid h-5 w-5 place-items-center rounded-full bg-black/5 text-[11px]">{done ? <Check size={12} /> : n}</span>
              {label}
            </li>
          );
        })}
      </ol>

      {step === 1 && (
        <Card>
          <CardHeader title="Who should get it?" hint="Pick saved contact groups, up to 5,000 leads, or paste up to 5,000 numbers. Opted-out and non-Indian numbers are skipped for you on the last step." />
          <div className="p-4 sm:p-5">
            <RecipientPicker value={recipients} onChange={setRecipients} />
          </div>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader title="Pick a template" hint="Ready templates need a Service or Promotional type chosen in Templates before sending. Wording is fixed by your DLT approval." />
          <div className="space-y-3 p-4 sm:p-5">
            {templates.isLoading ? (
              <div className="h-32 animate-pulse rounded-xl bg-border-subtle" />
            ) : templates.error && !templates.data ? (
              <LoadError message={friendlyError(templates.error, "Check your connection.")} onRetry={() => void templates.mutate()} />
            ) : ready.length === 0 ? (
              <Empty title="No Ready templates yet." hint="Add or refresh templates in the Templates tab once your DLT approval is done." />
            ) : (
              ready.map((t) => {
                const active = t.id === templateId;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => pickTemplate(t)}
                    aria-pressed={active}
                    className={cn(
                      "block w-full rounded-xl border p-3.5 text-left transition-all",
                      active ? "border-2 border-primary bg-primary/5 ring-4 ring-primary/10" : "border-[#e2e8f0] hover:border-slate-300",
                    )}
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <Badge tone="info">Sender {t.sender_id}</Badge>
                      <Badge tone={t.template_type === "promotional" ? "warn" : "neutral"}>
                        {t.template_type === "promotional" ? "Promotional" : "Service"}
                      </Badge>
                      <span className="text-xs text-[#64748b]">{Math.max(t.var_count, countVars(t.message))} variable(s)</span>
                    </div>
                    <Wording message={t.message} />
                  </button>
                );
              })
            )}
            {recipients.tab === "numbers" && promotional && (
              <div className="space-y-2">
                <Notice tone="warn">This is a promotional template. Pasted numbers need your confirmation before you can continue.</Notice>
                <ConsentCheck checked={recipients.consent} onChange={(consent) => setRecipients((r) => ({ ...r, consent }))} />
              </div>
            )}
          </div>
        </Card>
      )}

      {step === 3 && template && (
        <Card>
          <CardHeader title="Fill the variables" hint="Each {#var#} in the wording takes a recipient field (like Name) or the same fixed text for everyone." />
          <div className="space-y-4 p-4 sm:p-5">
            <div className="rounded-xl bg-[#f8fafc] p-3.5">
              <Wording message={template.message} map={varMap} fields={fieldList} />
            </div>
            {varCount === 0 ? (
              <p className="text-sm text-[#64748b]">This template has no variables. Continue to the review.</p>
            ) : fields.error && !fields.data ? (
              <LoadError message={friendlyError(fields.error, "Couldn't load recipient fields.")} onRetry={() => void fields.mutate()} />
            ) : (
              <div className="space-y-3">
                {Array.from({ length: varCount }, (_, i) => {
                  const cur = varMap[i];
                  const mode = cur ? (cur.source === "field" ? cur.value : FIXED) : "";
                  return (
                    <div key={i} className="grid gap-2 sm:grid-cols-[110px_minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
                      <p className="text-sm font-bold text-[#0A1528] sm:pb-2.5">Variable {i + 1}</p>
                      <Field label="Use">
                        <select
                          className={inputCls}
                          value={mode}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (!v) setVar(i, null);
                            else if (v === FIXED) setVar(i, { source: "text", value: cur?.source === "text" ? cur.value : "" });
                            else setVar(i, { source: "field", value: v });
                          }}
                        >
                          <option value="">Choose…</option>
                          {fieldList.map((f) => (
                            <option key={f.key} value={f.key}>
                              {f.label}
                            </option>
                          ))}
                          <option value={FIXED}>Fixed text for everyone</option>
                        </select>
                      </Field>
                      {cur?.source === "text" && (
                        <Field label="Text">
                          <input
                            className={inputCls}
                            value={cur.value}
                            maxLength={100}
                            placeholder="e.g. 2 Nov"
                            onChange={(e) => setVar(i, { source: "text", value: e.target.value })}
                          />
                        </Field>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </Card>
      )}

      {step === 4 && template && (
        <div className="space-y-4">
          <Card>
            <CardHeader title="Review" hint={`${recipients.tab === "contacts" ? `${formatCount(recipients.groupIds.size)} group(s)` : recipients.tab === "leads" ? `${formatCount(recipients.leadIds.size)} lead(s)` : `${formatCount(parseNumbers(recipients.numbersText).length)} number(s)`} picked · sender ${template.sender_id}`} />
            <div className="space-y-4 p-4 sm:p-5">
              {previewLoading && <div className="h-40 animate-pulse rounded-xl bg-border-subtle" />}
              {previewError && (
                <div className="space-y-3">
                  <Notice tone="danger">{previewError}</Notice>
                  <Btn variant="outline" onClick={() => void reloadPreview()}>
                    Try again
                  </Btn>
                </div>
              )}
              {preview && (
                <>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-xl bg-[#ecfdf3] p-3.5">
                      <p className="font-display text-2xl font-bold text-[#15803d]">{formatCount(preview.eligible_count)}</p>
                      <p className="text-xs font-semibold text-[#15803d]">will get it</p>
                    </div>
                    <div className="rounded-xl bg-[#fff7e6] p-3.5">
                      <p className="font-display text-2xl font-bold text-[#b45309]">{formatCount(preview.excluded.length)}</p>
                      <p className="text-xs font-semibold text-[#b45309]">left out</p>
                    </div>
                    <div className="rounded-xl bg-surface-low p-3.5">
                      <p className="font-display text-2xl font-bold text-ink">{formatCount(preview.total_segments)}</p>
                      <p className="text-xs font-semibold text-ink-muted">estimated SMS credits</p>
                    </div>
                  </div>
                  <p className={estimateLine(preview).known ? "text-sm font-semibold text-[#0A1528]" : "text-xs text-[#64748b]"}>{estimateLine(preview).text}</p>

                  {preview.samples.length > 0 && (
                    <div>
                      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-[#64748b]">Sample messages</h3>
                      <ul className="space-y-2">
                        {preview.samples.map((s, i) => (
                          <li key={s.lead_id ?? i} className="rounded-xl border border-[#e2e8f0] p-3">
                            <p className="whitespace-pre-wrap break-words text-sm text-[#0A1528]">{s.content}</p>
                            <p className="mt-1.5 text-xs text-[#64748b]">
                              To {s.name || "recipient"} · {s.segments} SMS{s.segments === 1 ? "" : "s"} each{s.unicode ? " · uses non-English characters" : ""}
                            </p>
                          </li>
                        ))}
                      </ul>
                      {anyUnicode && (
                        <p className="mt-2 text-xs text-[#b45309]">
                          Some text isn&apos;t plain English letters (Unicode). These messages are shorter per SMS, so they can use more than one SMS each and use more credits.
                        </p>
                      )}
                    </div>
                  )}

                  {excludedGroups.length > 0 && (
                    <div>
                      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-[#64748b]">Left out</h3>
                      <div className="space-y-2">
                        {excludedGroups.map((g) => (
                          <details key={g.reason} className="rounded-xl border border-[#e2e8f0] px-3 py-2">
                            <summary className="cursor-pointer text-sm font-semibold text-[#0A1528]">
                              {g.reason} <span className="font-normal text-[#64748b]">· {formatCount(g.leads.length)}</span>
                            </summary>
                            <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-[#64748b]">
                              {g.leads.slice(0, 200).map((l, i) => (
                                <li key={l.lead_id ?? i} className="truncate">
                                  {l.name || "No name"} · {l.phone ?? "no number"}
                                </li>
                              ))}
                              {g.leads.length > 200 && <li>and {formatCount(g.leads.length - 200)} more</li>}
                            </ul>
                          </details>
                        ))}
                      </div>
                    </div>
                  )}
                  {preview.eligible_count === 0 && <Notice tone="warn">No one is left to send to. Go back and pick different recipients.</Notice>}
                </>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader title="When to send" />
            <div className="space-y-4 p-4 sm:p-5">
              <Field label="Campaign name">
                <input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
              </Field>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="When to send">
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
                    {m === "now" ? "Send now" : "Schedule"}
                  </button>
                ))}
              </div>
              {when.mode === "later" && (
                <div className="space-y-2">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Date (IST)">
                      <input type="date" className={inputCls} value={when.date} min={bounds.min} max={bounds.max} onChange={(e) => setWhen((w) => ({ ...w, date: e.target.value }))} />
                    </Field>
                    <Field label="Time (IST)">
                      <input type="time" className={inputCls} value={when.time} onChange={(e) => setWhen((w) => ({ ...w, time: e.target.value }))} />
                    </Field>
                  </div>
                  {resolved.error ? (
                    <p className="text-xs font-semibold text-danger">{resolved.error}</p>
                  ) : (
                    resolved.at && <p className="text-xs text-[#64748b]">Goes out {formatSendTime(resolved.at)} IST ({untilSend(resolved.at, now)}).</p>
                  )}
                </div>
              )}
              {submitError && <Notice tone="danger">{submitError}</Notice>}
            </div>
          </Card>
        </div>
      )}

      {step === 4 && preview && block.reason && <Notice tone="warn">{block.reason}</Notice>}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Btn variant="outline" onClick={() => (step === 1 ? onClose() : setStep((s) => s - 1))}>
          {step === 1 ? "Cancel" : "Back"}
        </Btn>
        {step < 4 ? (
          <Btn disabled={(step === 1 && !canNext1) || (step === 2 && !canNext2) || (step === 3 && !canNext3)} onClick={goNext}>
            Next
          </Btn>
        ) : (
          <Btn busy={submitting} disabled={!canSend} onClick={() => {
            const current = new Date();
            setNow(current);
            const schedule = resolveWhen(when, current);
            if (schedule.error) setSubmitError(schedule.error);
            else setConfirming(true);
          }}>
            {when.mode === "later" ? "Schedule campaign" : "Send now"}
          </Btn>
        )}
      </div>

      <ConfirmModal
        open={confirming}
        onClose={() => !submitting && setConfirming(false)}
        onConfirm={() => void submit()}
        title={when.mode === "later" ? "Schedule this campaign?" : "Send this campaign now?"}
        description={
          preview
            ? `${formatCount(preview.eligible_count)} people will get this SMS. ${
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
