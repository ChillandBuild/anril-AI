"use client";

import { useRef, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, type SmsManualDlt, type SmsPreview, type SmsTemplateType } from "@/lib/api";
import { cn } from "@/lib/utils";
import { dateBounds, defaultWhen, formatSendTime, resolveWhen, untilSend, type WhenValue } from "@/lib/schedule-time";
import { EMPTY_RECIPIENTS, RecipientPicker, recipientRequest, recipientsReadyFor, type RecipientState } from "./RecipientPicker";
import { UNICODE_NOTE, errorStatus, errorText, estimateLine, formatCount, friendlyError, sendBlock, smsCounterLine, smsSegments } from "./helpers";
import { Btn, Card, CardHeader, Field, Notice, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

const EMPTY_FORM = { name: "", sender_id: "", entity_id: "", dlt_template_id: "", message: "" };

/** "Send with DLT IDs": a campaign with wording and DLT ids typed in, not picked from the template list. */
export function ManualCampaignCard({ onOpenCampaigns }: { onOpenCampaigns?: () => void }) {
  const { canManage } = usePerm();
  const [form, setForm] = useState(EMPTY_FORM);
  const [templateType, setTemplateType] = useState<SmsTemplateType>("service");
  const [recipients, setRecipients] = useState<RecipientState>({ ...EMPTY_RECIPIENTS, tab: "contacts" });
  const [when, setWhen] = useState<WhenValue>(() => ({ ...defaultWhen(new Date()), mode: "now" }));
  const [preview, setPreview] = useState<{ key: string; data: SmsPreview } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const submittingRef = useRef(false);

  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const balance = useSWR("sms:balance", () => api.sms.balance(), { revalidateOnFocus: true, shouldRetryOnError: false });

  if (!canManage) return null;

  const set = (key: keyof typeof EMPTY_FORM) => (value: string) => {
    setCreated(false);
    setForm((f) => ({ ...f, [key]: value }));
  };
  const promotional = templateType === "promotional";
  const manual: SmsManualDlt = {
    sender_id: form.sender_id.trim(),
    entity_id: form.entity_id.trim(),
    dlt_template_id: form.dlt_template_id.trim(),
    template_type: templateType,
    message: form.message,
  };
  const recipientReq = recipientRequest(recipients, promotional);
  const requestKey = JSON.stringify([manual, recipientReq]);
  const formComplete = !!manual.sender_id && !!manual.entity_id && !!manual.dlt_template_id && !!manual.message.trim() && !!form.name.trim();
  const ready = formComplete && recipientsReadyFor(recipients, promotional);
  const freshPreview = preview && preview.key === requestKey ? preview.data : null;

  const now = new Date();
  const resolved = resolveWhen(when, now);
  const bounds = dateBounds(now);
  const scheduleBad = when.mode === "later" && !!resolved.error;
  const length = smsSegments(form.message);
  const block = sendBlock({
    loading: (status.isLoading && !status.data) || (balance.isLoading && !balance.data),
    peTm: status.data ? status.data.checklist.pe_tm === true : undefined,
    balance: balance.data?.sms_count,
    needed: freshPreview?.total_segments ?? 0,
    support: status.data?.support_contact || null,
  });
  const canCreate = !!freshPreview && freshPreview.eligible_count > 0 && !scheduleBad && !submitting && !block.blocked;

  async function runPreview() {
    setPreviewing(true);
    setError(null);
    const key = requestKey;
    try {
      const data = await api.sms.previewCampaign({ kind: "manual", manual, ...recipientReq });
      setPreview({ key, data });
    } catch (err) {
      setPreview(null);
      setError(friendlyError(err, "Couldn't build the preview."));
    } finally {
      setPreviewing(false);
    }
  }

  async function create() {
    if (submittingRef.current) return;
    const schedule = resolveWhen(when, new Date());
    if (schedule.error) {
      setError(schedule.error);
      setConfirming(false);
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await api.sms.createCampaign({
        kind: "manual",
        name: form.name.trim(),
        manual,
        ...recipientReq,
        send_at: when.mode === "later" && schedule.at ? schedule.at.toISOString() : null,
        idempotency_key: idempotencyKey,
      });
      toast.success(when.mode === "later" ? "Campaign scheduled." : "Campaign is sending.");
      setForm(EMPTY_FORM);
      setRecipients({ ...EMPTY_RECIPIENTS, tab: recipients.tab });
      setPreview(null);
      setIdempotencyKey(crypto.randomUUID());
      setCreated(true);
    } catch (err) {
      const code = errorStatus(err);
      if (code && code >= 400 && code < 500) setIdempotencyKey(crypto.randomUUID());
      setError(code === 409 ? errorText(err, "Couldn't create the campaign.") : friendlyError(err, "Couldn't create the campaign."));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
      setConfirming(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Send with DLT IDs"
        hint="For an approved template that isn't in your template list. The wording must match DLT exactly or it will fail."
      />
      <div className="space-y-4 p-4 sm:p-5">
        <Field label="Campaign name">
          <input className={`${inputCls} sm:max-w-md`} value={form.name} maxLength={80} onChange={(e) => set("name")(e.target.value)} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Sender ID">
            <input className={inputCls} value={form.sender_id} onChange={(e) => set("sender_id")(e.target.value)} />
          </Field>
          <Field label="DLT entity ID">
            <input className={inputCls} value={form.entity_id} onChange={(e) => set("entity_id")(e.target.value)} />
          </Field>
          <Field label="DLT template ID">
            <input className={inputCls} value={form.dlt_template_id} onChange={(e) => set("dlt_template_id")(e.target.value)} />
          </Field>
          <Field label="Type">
            <select className={inputCls} value={templateType} onChange={(e) => setTemplateType(e.target.value as SmsTemplateType)}>
              <option value="service">Service</option>
              <option value="promotional">Promotional</option>
            </select>
          </Field>
        </div>
        <div>
          <Field label="Message" hint="Exact approved wording">
            <textarea className={textareaCls} rows={4} value={form.message} onChange={(e) => set("message")(e.target.value)} />
          </Field>
          <p className="mt-1 text-xs font-semibold text-[#334155]" aria-live="polite">
            {smsCounterLine(form.message)}
          </p>
          {form.message && length.unicode && <p className="mt-0.5 text-xs text-[#b45309]">{UNICODE_NOTE}</p>}
        </div>

        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-[#64748b]">Who should get it?</h3>
          <RecipientPicker value={recipients} onChange={setRecipients} tabs={["contacts", "numbers"]} showConsent={promotional} />
        </div>

        <div className="space-y-3">
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
              <div className="grid gap-3 sm:max-w-md sm:grid-cols-2">
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
        </div>

        {freshPreview && (
          <div className="space-y-2 rounded-xl bg-[#f8fafc] p-3.5">
            <p className="text-sm font-bold text-[#0A1528]">
              {formatCount(freshPreview.eligible_count)} will get it
              {freshPreview.excluded.length > 0 || freshPreview.excluded_total ? (
                <span className="font-normal text-[#64748b]"> · {formatCount(freshPreview.excluded_total ?? freshPreview.excluded.length)} left out</span>
              ) : null}
              <span className="font-normal text-[#64748b]"> · {formatCount(freshPreview.total_segments)} SMS credits</span>
            </p>
            <p className={estimateLine(freshPreview).known ? "text-sm font-semibold text-[#0A1528]" : "text-xs text-[#64748b]"}>{estimateLine(freshPreview).text}</p>
            {freshPreview.eligible_count === 0 && <Notice tone="warn">No one is left to send to. Change the recipients and preview again.</Notice>}
          </div>
        )}
        {freshPreview && block.reason && <Notice tone="warn">{block.reason}</Notice>}
        {error && <Notice tone="danger">{error}</Notice>}
        {created && (
          <Notice tone="success">
            Campaign created.{" "}
            {onOpenCampaigns && (
              <button type="button" className="font-bold underline" onClick={onOpenCampaigns}>
                See it in Campaigns
              </button>
            )}
          </Notice>
        )}

        <div className="flex flex-wrap gap-2">
          <Btn variant="outline" busy={previewing} disabled={!ready || scheduleBad} onClick={() => void runPreview()}>
            Preview
          </Btn>
          <Btn disabled={!canCreate} onClick={() => setConfirming(true)}>
            {when.mode === "later" ? "Schedule campaign" : "Send campaign"}
          </Btn>
        </div>
      </div>

      <ConfirmModal
        open={confirming}
        onClose={() => !submitting && setConfirming(false)}
        onConfirm={() => void create()}
        title={when.mode === "later" ? "Schedule this campaign?" : "Send this campaign now?"}
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
    </Card>
  );
}
