"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { ArrowLeft, Check } from "lucide-react";
import { toast } from "sonner";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, type SmsCampaign, type SmsPreview, type SmsTemplate, type SmsVarSource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { dateBounds, defaultWhen, formatSendTime, resolveWhen, untilSend, type WhenValue } from "@/lib/schedule-time";
import { LeadPicker } from "./LeadPicker";
import {
  countVars,
  errorStatus,
  formatCount,
  formatRupees,
  friendlyError,
  groupExcluded,
  isVariableMapComplete,
  splitTemplate,
} from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, Field, LoadError, Notice, inputCls } from "./ui";

const STEPS = ["Pick leads", "Pick template", "Fill variables", "Review & send"];
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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [varMap, setVarMap] = useState<(SmsVarSource | null)[]>([]);
  const [name, setName] = useState(defaultName);
  const [when, setWhen] = useState<WhenValue>(() => ({ ...defaultWhen(new Date()), mode: "now" }));
  const [preview, setPreview] = useState<SmsPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  // One key per composer open: a double click or a retry after a lost reply cannot create a second campaign.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const submittingRef = useRef(false);
  const previewSeq = useRef(0);

  const templates = useSWR("sms:templates", () => api.sms.templates(), { revalidateOnFocus: false });
  const fields = useSWR("sms:campaign-fields", () => api.sms.campaignFields(), { revalidateOnFocus: false });

  const ready = useMemo(() => (templates.data?.templates ?? []).filter((t) => t.status === "ready"), [templates.data]);
  const template: SmsTemplate | null = ready.find((t) => t.id === templateId) ?? null;
  const varCount = template ? Math.max(template.var_count ?? 0, countVars(template.message)) : 0;
  const fieldList = fields.data?.fields ?? [];

  const now = useMemo(() => new Date(), []);
  const resolved = resolveWhen(when, now);
  const bounds = dateBounds(now);

  function pickTemplate(t: SmsTemplate) {
    setTemplateId(t.id);
    const n = Math.max(t.var_count ?? 0, countVars(t.message));
    setVarMap(Array.from({ length: n }, () => null));
    setPreview(null);
  }

  function setVar(i: number, value: SmsVarSource | null) {
    setVarMap((m) => {
      const next = [...m];
      next[i] = value;
      return next;
    });
    setPreview(null);
  }

  const canNext1 = selected.size > 0;
  const canNext2 = !!template;
  const canNext3 = !!template && isVariableMapComplete(varMap, varCount);

  async function loadPreview() {
    if (!template) return;
    const seq = ++previewSeq.current;
    setPreviewLoading(true);
    setPreviewError(null);
    setPreview(null);
    try {
      const res = await api.sms.previewCampaign({
        template_id: template.id,
        variable_map: varMap.slice(0, varCount).map((v) => v as SmsVarSource),
        lead_ids: Array.from(selected),
      });
      if (seq === previewSeq.current) setPreview(res);
    } catch (err) {
      if (seq === previewSeq.current) setPreviewError(friendlyError(err, "Couldn't build the preview."));
    } finally {
      if (seq === previewSeq.current) setPreviewLoading(false);
    }
  }

  useEffect(() => {
    if (step === 4 && !preview && !previewLoading && !previewError) void loadPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  function goNext() {
    if (step === 3) {
      setPreview(null);
      setPreviewError(null);
    }
    setStep((s) => Math.min(4, s + 1));
  }

  const scheduleBad = when.mode === "later" && !!resolved.error;
  const canSend = !!preview && preview.eligible_count > 0 && !previewLoading && !scheduleBad && name.trim().length > 0 && !submitting;

  async function submit() {
    if (!template || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const campaign = await api.sms.createCampaign({
        name: name.trim(),
        template_id: template.id,
        variable_map: varMap.slice(0, varCount).map((v) => v as SmsVarSource),
        lead_ids: Array.from(selected),
        send_at: when.mode === "later" && resolved.at ? resolved.at.toISOString() : null,
        idempotency_key: idempotencyKey,
      });
      toast.success(when.mode === "later" ? "Campaign scheduled." : "Campaign is sending.");
      onCreated(campaign);
    } catch (err) {
      const status = errorStatus(err);
      // A 4xx means nothing was created, so the next attempt may use a fresh key (the inputs may have changed).
      if (status && status >= 400 && status < 500) setIdempotencyKey(crypto.randomUUID());
      setSubmitError(friendlyError(err, "Couldn't create the campaign."));
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
          <CardHeader title="Who should get it?" hint="Pick up to 5,000 leads. Opted-out and non-Indian numbers are skipped for you on the last step." />
          <div className="p-4 sm:p-5">
            <LeadPicker selected={selected} onChange={setSelected} />
          </div>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader title="Pick a template" hint="Only Ready templates can be sent. Wording is fixed by your DLT approval." />
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
          </div>
        </Card>
      )}

      {step === 3 && template && (
        <Card>
          <CardHeader title="Fill the variables" hint="Each {#var#} in the wording takes a lead field (like Name) or the same fixed text for everyone." />
          <div className="space-y-4 p-4 sm:p-5">
            <div className="rounded-xl bg-[#f8fafc] p-3.5">
              <Wording message={template.message} map={varMap} fields={fieldList} />
            </div>
            {varCount === 0 ? (
              <p className="text-sm text-[#64748b]">This template has no variables. Continue to the review.</p>
            ) : fields.error && !fields.data ? (
              <LoadError message={friendlyError(fields.error, "Couldn't load lead fields.")} onRetry={() => void fields.mutate()} />
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
            <CardHeader title="Review" hint={`${formatCount(selected.size)} picked · sender ${template.sender_id}`} />
            <div className="space-y-4 p-4 sm:p-5">
              {previewLoading && <div className="h-40 animate-pulse rounded-xl bg-border-subtle" />}
              {previewError && (
                <div className="space-y-3">
                  <Notice tone="danger">{previewError}</Notice>
                  <Btn variant="outline" onClick={() => void loadPreview()}>
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
                    <div className="rounded-xl bg-[#f8fafc] p-3.5">
                      <p className="font-display text-2xl font-bold text-[#0A1528]">{formatRupees(preview.estimated_total)}</p>
                      <p className="text-xs font-semibold text-[#64748b]">estimated cost</p>
                    </div>
                  </div>
                  <p className="text-xs text-[#64748b]">
                    Estimated cost {formatRupees(preview.estimated_total)} (estimate — the real charge shows after sending)
                    {preview.price_per_sms != null && <> · {formatRupees(preview.price_per_sms)} per SMS</>}
                  </p>

                  {preview.samples.length > 0 && (
                    <div>
                      <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-[#64748b]">Sample messages</h3>
                      <ul className="space-y-2">
                        {preview.samples.map((s) => (
                          <li key={s.lead_id} className="rounded-xl border border-[#e2e8f0] p-3">
                            <p className="whitespace-pre-wrap break-words text-sm text-[#0A1528]">{s.content}</p>
                            <p className="mt-1.5 text-xs text-[#64748b]">
                              To {s.name || "lead"} · {s.segments} SMS{s.segments === 1 ? "" : "s"} each{s.unicode ? " · uses non-English characters" : ""}
                            </p>
                          </li>
                        ))}
                      </ul>
                      {anyUnicode && (
                        <p className="mt-2 text-xs text-[#b45309]">
                          Some text isn&apos;t plain English letters (Unicode). These messages are shorter per SMS, so they can use more than one SMS each and cost more.
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
                              {g.leads.slice(0, 200).map((l) => (
                                <li key={l.lead_id} className="truncate">
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
                  {preview.eligible_count === 0 && <Notice tone="warn">No one is left to send to. Go back and pick different leads.</Notice>}
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

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Btn variant="outline" onClick={() => (step === 1 ? onClose() : setStep((s) => s - 1))}>
          {step === 1 ? "Cancel" : "Back"}
        </Btn>
        {step < 4 ? (
          <Btn disabled={(step === 1 && !canNext1) || (step === 2 && !canNext2) || (step === 3 && !canNext3)} onClick={goNext}>
            Next
          </Btn>
        ) : (
          <Btn busy={submitting} disabled={!canSend} onClick={() => setConfirming(true)}>
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
            ? `${formatCount(preview.eligible_count)} people will get this SMS. Estimated cost ${formatRupees(preview.estimated_total)}. ${
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
