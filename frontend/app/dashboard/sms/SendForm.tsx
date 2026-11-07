"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";
import { api, type SmsPreview, type SmsCampaignPreviewRequest, type SmsTemplate, type SmsVarSource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { dateBounds, defaultWhen, formatSendTime, resolveWhen, untilSend, type WhenValue } from "@/lib/schedule-time";
import { NumbersPicker, useHasLeads } from "./RecipientPicker";
import { AddTemplatePanel, type TemplatePrefill } from "./DltForms";
import { matchesQuery } from "./dltSetup";
import { SendConfirm } from "./SendConfirm";
import { SendPreview } from "./SendPreview";
import { SenderChips, TemplateCard } from "./TemplateCard";
import { VariableMapper, Wording } from "./SendVars";
import { useSms } from "./SmsShell";
import {
  EMPTY_NUMBERS,
  SEND_PREFILL_KEY,
  UNICODE_NOTE,
  buildSendRequest,
  errorStatus,
  errorText,
  fieldsSourceFor,
  formatCount,
  friendlyError,
  hasCurlyQuotes,
  languageLine,
  matchSavedTemplate,
  sendNameFor,
  sendersFrom,
  straightenQuotes,
  hasLink,
  nextIdempotencyKey,
  pruneVarMap,
  sendBlock,
  sendFormProblem,
  sendType,
  sendPrefill,
  smsSegments,
  templateVarCount,
  withNumbersChange,
  type NumbersState,
  type SendFormInput,
  NIGHT_RULE,
  quietRelease,
  EMPTY_MANUAL,
  MANUAL_WARNING,
  categoryLabel,
  countVars,
  type ManualInput,
} from "./helpers";
import { Badge, Btn, Card, Empty, Field, LoadError, Notice, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

/** Wait this long after the last change before asking the server for a fresh preview. */
const PREVIEW_DELAY_MS = 600;
/** Show the template search once a sender has more cards than fit at a glance. */
const SEARCH_FROM = 5;

type SendTab = "saved" | "manual";
const TABS: { id: SendTab; label: string; hint: string }[] = [
  { id: "saved", label: "Saved templates", hint: "Pick a sender, then one of its approved templates." },
  { id: "manual", label: "DLT Manual", hint: "New sender, entity or message? Type the DLT details yourself." },
];

/**
 * The one Send SMS form. Two tabs: Saved templates (sender chips, then phone-style template cards) or
 * DLT Manual (Bulk9 route=dlt_manual: an added sender, the DLT IDs and the exact text). Then who gets
 * it and when; Send SMS opens a popup with the counts, SMS credits and ₹ at the client's plan price.
 */
export function SendForm() {
  const { canManage } = usePerm();
  const { reloadBalance } = useSms();
  const [tab, setTab] = useState<SendTab>("saved");
  const [sender, setSender] = useState("");
  const [query, setQuery] = useState("");
  const [choice, setChoice] = useState("");
  const [manual, setManual] = useState<ManualInput>(EMPTY_MANUAL);
  const [varMap, setVarMap] = useState<(SmsVarSource | null)[]>([]);
  const [numbers, setNumbers] = useState<NumbersState>(EMPTY_NUMBERS);
  // Empty = use the automatic name ("KELIR · 14893 · 7 Nov").
  const [name, setName] = useState("");
  const [when, setWhen] = useState<WhenValue>(() => ({ ...defaultWhen(new Date()), mode: "now" }));
  const [preview, setPreview] = useState<{ key: string; data: SmsPreview } | null>(null);
  const [previewError, setPreviewError] = useState<{ key: string; message: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // After a DLT Manual send, `save` fills "Save to my templates" (null when it matched a saved one).
  const [created, setCreated] = useState<{ scheduled: boolean; save: TemplatePrefill | null } | null>(null);
  const [saving, setSaving] = useState<TemplatePrefill | null>(null);
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
  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const balance = useSWR("sms:balance", () => api.sms.balance(), { revalidateOnFocus: true, shouldRetryOnError: false });
  const hasLeads = useHasLeads();

  // Every approved template can be sent: its category is DLT's, never the client's choice.
  const ready = useMemo(() => (templates.data?.templates ?? []).filter((t) => t.status === "ready"), [templates.data]);
  const isManual = tab === "manual";
  const senderList = useMemo(() => sendersFrom(ready), [ready]);
  // No chip tapped yet: the first sender's cards show (most clients have one sender).
  const activeSender = senderList.some((s) => s.sender_id === sender) ? sender : (senderList[0]?.sender_id ?? "");
  const senderCards = ready.filter((t) => t.sender_id === activeSender);
  const cards = senderCards.filter((t) => matchesQuery([t.message, t.message_id, t.dlt_template_id], query));
  const template: SmsTemplate | null = !isManual && choice ? (ready.find((t) => t.id === choice) ?? null) : null;
  const savedMatch = isManual ? matchSavedTemplate(ready, manual.sender_id, manual.message) : null;
  const senders = useSWR(isManual ? "sms:senders" : null, () => api.sms.senders(), { revalidateOnFocus: false });
  const varCount = templateVarCount(template);
  const input: SendFormInput = { template, manual: isManual ? manual : null, varMap, numbers };
  const type = sendType(input);
  const promotional = type === "promotional";
  const problem = sendFormProblem(input);
  const request = buildSendRequest(input);
  const requestKey = JSON.stringify(request);
  const freshPreview = preview && request && preview.key === requestKey ? preview.data : null;
  const resolved = resolveWhen(when, now);
  const bounds = dateBounds(now);
  const scheduleBad = when.mode === "later" && !!resolved.error;
  // Sent (or scheduled) between 9 PM and 10 AM: the operator holds it until 10 AM.
  const nightRelease = scheduleBad ? null : quietRelease(when.mode === "later" ? resolved.at : now);
  const previewFailed = previewError?.key === requestKey ? previewError.message : null;
  // True from the moment the request changes until its preview lands (or fails).
  const updating = !!request && !scheduleBad && !freshPreview && !previewFailed;
  // While updating, keep showing the previous numbers (dimmed) instead of blanking the card.
  const shown = freshPreview ?? (updating ? (preview?.data ?? null) : null);

  const groupKey = numbers.groupIds.slice().sort().join(",");
  const fieldsSource = fieldsSourceFor(numbers.mode);
  const fields = useSWR(
    template && varCount > 0 ? ["sms:campaign-fields", fieldsSource, fieldsSource === "contacts" ? groupKey : ""] : null,
    () => api.sms.campaignFields(fieldsSource, numbers.groupIds),
    { revalidateOnFocus: false },
  );

  // Opened from the Address Book ("Send SMS" on a group, or on picked contacts): start with them.
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.sessionStorage.getItem(SEND_PREFILL_KEY);
      window.sessionStorage.removeItem(SEND_PREFILL_KEY);
    } catch {
      // Storage blocked: the ?groups= hand-off still works.
    }
    const patch = sendPrefill(window.location.search, stored);
    if (patch) setNumbers((n) => withNumbersChange(n, patch));
  }, []);

  // Leads mode disappears if the client has none; fall back to Contact.
  useEffect(() => {
    if (numbers.mode === "leads" && !hasLeads) setNumbers((n) => withNumbersChange(n, { mode: "contact" }));
  }, [numbers.mode, hasLeads]);

  // Switching who gets the SMS changes which contact fields exist; forget mappings to fields that are gone.
  const offeredFields = fields.data?.fields;
  useEffect(() => {
    if (offeredFields) setVarMap((m) => pruneVarMap(m, offeredFields.map((f) => f.key)));
  }, [offeredFields]);

  // Auto-preview: 600 ms after the last change to a valid request, ask the server who gets it and
  // what it costs. A reply for an older request is dropped.
  useEffect(() => {
    const body = JSON.parse(requestKey) as SmsCampaignPreviewRequest | null;
    if (!body || scheduleBad) return;
    let current = true;
    const timer = window.setTimeout(() => {
      api.sms
        .previewCampaign(body)
        .then((data) => {
          if (!current) return;
          setPreview({ key: requestKey, data });
          setPreviewError(null);
        })
        .catch((err) => {
          if (!current) return;
          setPreview(null);
          setPreviewError({ key: requestKey, message: friendlyError(err, "Couldn't build the preview.") });
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [requestKey, scheduleBad, retry]);

  const block = sendBlock({
    loading: (status.isLoading && !status.data) || (balance.isLoading && !balance.data),
    balance: balance.data?.sms_count,
    needed: freshPreview?.total_segments ?? 0,
    support: status.data?.support_contact || null,
  });
  const canSend = !!freshPreview && freshPreview.eligible_count > 0 && !scheduleBad && !submitting && !block.blocked;

  const message = isManual ? manual.message : (template?.message ?? "");
  const length = smsSegments(message.replace(/\{#var#\}/gi, "x"));
  const senderShown = isManual ? manual.sender_id : (template?.sender_id ?? activeSender);
  const autoName = sendNameFor(senderShown, isManual ? "DLT Manual" : (template?.message_id ?? "Template"), now);

  function pickTemplate(value: string) {
    setChoice(value);
    setTab("saved");
    setCreated(null);
    setError(null);
    // The consent tick was for the previous template's type; ask again.
    setNumbers((n) => withNumbersChange(n, { consent: false }));
    const t = ready.find((x) => x.id === value);
    setVarMap(Array.from({ length: templateVarCount(t ?? null) }, () => null));
  }

  // "Use this template" on the Templates page opens /dashboard/sms/send?template=<id>: pick it once loaded.
  const templateFromUrl = useRef(false);
  useEffect(() => {
    if (templateFromUrl.current) return;
    const id = new URLSearchParams(window.location.search).get("template");
    if (!id) {
      templateFromUrl.current = true;
      return;
    }
    const found = ready.find((t) => t.id === id);
    if (found) {
      templateFromUrl.current = true;
      setSender(found.sender_id);
      setQuery("");
      pickTemplate(id);
    } else if (templates.data && !templates.isValidating) {
      templateFromUrl.current = true; // a cached list may lack it; give up only after the fresh one
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs until the template is found or the fresh list lacks it
  }, [ready, templates.isValidating]);

  function switchTab(next: SendTab) {
    if (next === tab) return;
    setTab(next);
    setCreated(null);
    setError(null);
    // Service vs promotional can change with the tab; ask for consent again.
    setNumbers((n) => withNumbersChange(n, { consent: false }));
  }

  function pickSender(value: string) {
    setSender(value);
    setQuery("");
    // A card from another sender stays chosen only if it belongs to this one.
    if (template && template.sender_id !== value) pickTemplate("");
  }

  function patchManual(patch: Partial<ManualInput>) {
    setCreated(null);
    setManual((m) => ({ ...m, ...patch }));
  }

  function setVar(i: number, value: SmsVarSource | null) {
    setVarMap((m) => {
      const next = [...m];
      next[i] = value;
      return next;
    });
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
      const finalName = name.trim() || autoName;
      keyRef.current = nextIdempotencyKey(keyRef.current, JSON.stringify({ request, name: name.trim(), sendAt }), () => crypto.randomUUID());
      await api.sms.createCampaign({ ...request, name: finalName, send_at: sendAt, idempotency_key: keyRef.current.key });
      toast.success(when.mode === "later" ? "SMS scheduled." : "SMS is sending.");
      const save: TemplatePrefill | null =
        isManual && !savedMatch
          ? { entity_id: manual.entity_id, sender_id: manual.sender_id, dlt_template_id: manual.dlt_template_id.trim(), message_text: manual.message.trim() }
          : null;
      setCreated({ scheduled: when.mode === "later", save });
      reloadBalance();
      setChoice("");
      setManual(EMPTY_MANUAL);
      setVarMap([]);
      setNumbers((n) => ({ ...EMPTY_NUMBERS, mode: n.mode }));
      setPreview(null);
      setName("");
      keyRef.current = null;
    } catch (err) {
      const code = errorStatus(err);
      // A 4xx means nothing was created, so the next attempt may use a fresh key.
      if (code && code >= 400 && code < 500) keyRef.current = null;
      // A 409 carries the exact reason (not enough balance), so show it as sent.
      setError(code === 409 ? errorText(err, "Couldn't send the SMS.") : friendlyError(err, "Couldn't send the SMS."));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
      setConfirming(false);
    }
  }

  const sample = shown?.samples[0] ?? null;
  const section = "text-xs font-bold uppercase tracking-wider text-[#64748b]";

  // Three numbered steps on the left; the page scrolls normally. On a laptop the preview + cost + Send
  // card sits on the right and stays pinned under the app header (64px) + page padding (28px) as you
  // scroll. Phones stack the card under step 3.
  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,24rem)]">
      <div className="space-y-5 rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm sm:p-6">
        <div>
          <div role="group" aria-label="How to send" className="mb-2 grid gap-2 sm:grid-cols-2">
            {TABS.map((t) => {
              const on = tab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => switchTab(t.id)}
                  className={cn(
                    "rounded-xl border px-4 py-3 text-left transition-colors",
                    on ? "border-[#038285] bg-[#e6f4f4]" : "border-[#e2e8f0] bg-white hover:border-[#94a3b8]",
                  )}
                >
                  <span className={cn("block text-sm font-extrabold", on ? "text-[#036b6e]" : "text-[#0A1528]")}>{t.label}</span>
                  <span className="mt-0.5 block text-xs text-[#64748b]">{t.hint}</span>
                </button>
              );
            })}
          </div>

          <Step n={1} id="sms-send-message" title={isManual ? "Type the DLT details" : "Pick a sender and template"}>
            {templates.error && !templates.data && <LoadError message={friendlyError(templates.error, "Couldn't load your templates.")} onRetry={() => void templates.mutate()} />}

            {!isManual && (
              <>
                {templates.data && ready.length === 0 ? (
                  <Empty
                    title="No approved templates yet."
                    hint="Add one under DLT setup → Content Template, or use DLT Manual to send with the DLT IDs."
                  />
                ) : (
                  <>
                    <SenderChips label="Sender" senders={senderList} value={activeSender} onChange={pickSender} />
                    {senderCards.length >= SEARCH_FROM && (
                      <label className="relative block sm:max-w-xs">
                        <span className="sr-only">Search {activeSender} templates</span>
                        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
                        <input className={cn(inputCls, "pl-9")} placeholder="Search the message text" value={query} onChange={(e) => setQuery(e.target.value)} />
                      </label>
                    )}
                    {cards.length === 0 && senderCards.length > 0 ? (
                      <p className="text-sm text-[#64748b]">No {activeSender} template has that text.</p>
                    ) : (
                      <ul aria-label={`${activeSender} templates`} className="grid gap-3 sm:grid-cols-2">
                        {cards.map((t) => (
                          <TemplateCard key={t.id} t={t} variant="pick" selected={choice === t.id} onPick={() => pickTemplate(t.id)} />
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </>
            )}

            {isManual && (
              <ManualFields
                value={manual}
                onChange={patchManual}
                senders={senders}
                match={savedMatch}
                onUseMatch={(t) => {
                  setSender(t.sender_id);
                  setQuery("");
                  pickTemplate(t.id);
                }}
              />
            )}

            {(template || isManual) && hasLink(message) && (
              <Notice tone="warn">
                This message has a link. The link must be whitelisted on your DLT portal (CTA / URL whitelisting) for this sender, or the telecom blocks the SMS.
              </Notice>
            )}

            {template && (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[#64748b]">
                <span className="font-bold text-[#0A1528]">{template.sender_id}</span>
                <span>· Entity {template.entity_id}</span>
                <span>· DLT {template.dlt_template_id}</span>
                <Badge tone={promotional ? "warn" : "neutral"}>{categoryLabel(template.template_type)}</Badge>
              </p>
            )}

            {template &&
              varCount > 0 &&
              (fields.error && !fields.data ? (
                <LoadError message={friendlyError(fields.error, "Couldn't load the contact fields.")} onRetry={() => void fields.mutate()} />
              ) : (
                <VariableMapper varCount={varCount} varMap={varMap} fields={fields.data?.fields ?? []} onSet={setVar} />
              ))}

            {message && (template || isManual) && (
              <div>
                <p className="text-xs font-semibold text-[#334155]" aria-live="polite">
                  {languageLine(message.replace(/\{#var#\}/gi, "x"))}
                  {varCount > 0 ? " (each variable counted as 1 character; the real length can differ)" : ""}
                </p>
                {length.unicode && <p className="mt-0.5 text-xs text-[#b45309]">{UNICODE_NOTE}</p>}
              </div>
            )}
          </Step>

          <Step n={2} id="sms-send-recipients" title="Who gets it">
            <NumbersPicker
              value={numbers}
              onChange={(update) => {
                setCreated(null);
                setNumbers((prev) => withNumbersChange(prev, update(prev)));
              }}
              promotional={promotional}
              showLeads={hasLeads}
            />
          </Step>

          <Step n={3} id="sms-send-when" title="When">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name this send (optional)" hint="So you can find it later in Reports">
                <input className={inputCls} value={name} placeholder={autoName} maxLength={80} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label="Send">
                <select className={inputCls} value={when.mode} onChange={(e) => setWhen((w) => ({ ...w, mode: e.target.value as WhenValue["mode"] }))}>
                  <option value="now">Right now</option>
                  <option value="later">Later…</option>
                </select>
              </Field>
              {when.mode === "later" && (
                <>
                  <Field label="Date (IST)">
                    <input type="date" className={inputCls} value={when.date} min={bounds.min} max={bounds.max} onChange={(e) => setWhen((w) => ({ ...w, date: e.target.value }))} />
                  </Field>
                  <Field label="Time (IST)">
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
          </Step>
        </div>
      </div>

      <aside
        aria-label="Preview and send"
        className="flex flex-col gap-4 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:p-5 lg:sticky lg:top-[5.75rem] lg:max-h-[calc(100dvh-7.5rem)] lg:overflow-y-auto"
      >
        <h2 className={section}>Preview</h2>
        <div className="space-y-2 rounded-xl bg-[#0A1528] p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#9fb3c8]">{senderShown || "Sender ID"}</p>
          <div className="max-w-[92%] rounded-xl rounded-bl-sm bg-white px-3 py-2.5">
            {sample ? (
              <p className="whitespace-pre-wrap break-words text-sm text-[#0A1528]">{sample.content}</p>
            ) : message ? (
              <Wording message={message} map={varMap} fields={fields.data?.fields} />
            ) : (
              <p className="text-sm text-[#94a3b8]">{isManual ? "Type the message to see it here." : "Pick a template to see the message."}</p>
            )}
          </div>
          <p className="text-[11px] text-[#9fb3c8]">{sample ? `Shown with ${sample.name || "the first recipient"}'s values.` : "Real values fill in automatically."}</p>
        </div>

        {updating && (
          <p className="-mb-2 text-xs font-semibold text-[#64748b]" role="status" aria-live="polite">
            Updating…
          </p>
        )}

        {shown && (
          <p className={cn("text-sm text-[#334155] transition-opacity", updating && "opacity-50")}>
            <span className="font-bold text-[#0A1528]">{formatCount(shown.eligible_count)}</span> {shown.eligible_count === 1 ? "person" : "people"} ·{" "}
            <span className="font-bold text-[#0A1528]">{formatCount(shown.total_segments)}</span> SMS credits. Press Send SMS to check the cost and confirm.
          </p>
        )}

        {shown && (
          <div className={cn("transition-opacity", updating && "opacity-50")}>
            <SendPreview preview={shown} />
          </div>
        )}
        {freshPreview && block.reason && <Notice tone="warn">{block.reason}</Notice>}
        {nightRelease && (
          <Notice tone="warn">
            This SMS will go out at {formatSendTime(nightRelease)}, not straight away. {NIGHT_RULE} SMS credits are used when you send.
          </Notice>
        )}
        {!shown && problem && (template !== null || isManual) && <p className="text-xs text-[#64748b]">{problem}</p>}
        {previewFailed && (
          <Notice tone="danger">
            {previewFailed}{" "}
            <button type="button" className="font-bold underline" onClick={() => setRetry((n) => n + 1)}>
              Try again
            </button>
          </Notice>
        )}
        {error && <Notice tone="danger">{error}</Notice>}
        {created && (
          <Notice tone="success">
            {created.scheduled ? "SMS scheduled." : "SMS is sending."}{" "}
            <Link href="/dashboard/sms/reports" className="font-bold underline">
              See it in Reports
            </Link>
            {created.save && (
              <span className="mt-2 block">
                <Btn variant="outline" onClick={() => setSaving(created.save)}>
                  <Plus size={14} /> Save to my templates
                </Btn>
                <span className="mt-1 block text-xs">Next time it&apos;s one tap under Saved templates, with no IDs to type.</span>
              </span>
            )}
          </Notice>
        )}

        <div className="grid gap-2">
          <Btn
            className="h-12 text-base"
            disabled={!canSend}
            onClick={() => {
              const current = new Date();
              setNow(current);
              const schedule = resolveWhen(when, current);
              if (schedule.error) setError(schedule.error);
              else {
                void balance.mutate();
                setConfirming(true);
              }
            }}
          >
            {when.mode === "later" ? "Schedule SMS" : "Send SMS"}
          </Btn>
        </div>
      </aside>

      {freshPreview && (
        <SendConfirm
          open={confirming}
          onClose={() => setConfirming(false)}
          onConfirm={() => void send()}
          submitting={submitting}
          preview={freshPreview}
          balance={balance.data ?? null}
          sender={senderShown}
          source={isManual ? `DLT Manual · ${manual.dlt_template_id}` : template?.message_id ? `Template #${template.message_id}` : `DLT ${template?.dlt_template_id ?? "template"}`}
          manual={isManual}
          sendAt={when.mode === "later" ? resolved.at : null}
          nightRelease={nightRelease}
        />
      )}
      <AddTemplatePanel
        open={!!saving}
        onClose={() => setSaving(null)}
        initial={saving ?? undefined}
        onSaved={() => setCreated((c) => (c ? { ...c, save: null } : c))}
      />
    </div>
  );
}

/**
 * DLT Manual: an added sender (Bulk9 needs it in DLT Manager first, so it is never typed freely), its
 * entity (filled in, editable), the DLT template ID and the exact approved text, with live checks.
 */
function ManualFields({
  value,
  onChange,
  senders,
  match,
  onUseMatch,
}: {
  value: ManualInput;
  onChange: (patch: Partial<ManualInput>) => void;
  senders: { data?: { senders: { sender_id: string; entity_id: string; entity_name: string | null }[] }; error?: unknown; isLoading: boolean; mutate: () => unknown };
  match: SmsTemplate | null;
  onUseMatch: (t: SmsTemplate) => void;
}) {
  const list = senders.data?.senders ?? [];
  const pickedSender = list.find((s) => s.sender_id === value.sender_id) ?? null;
  // A sender can sit under more than one entity; the dropdown keys on both.
  const picked = value.sender_id ? `${value.sender_id}|${list.some((s) => s.sender_id === value.sender_id && s.entity_id === value.entity_id) ? value.entity_id : (pickedSender?.entity_id ?? "")}` : "";
  const entityChanged = !!pickedSender && !!value.entity_id && !list.some((s) => s.sender_id === value.sender_id && s.entity_id === value.entity_id);
  const id = value.dlt_template_id;
  const leftoverVars = countVars(value.message) > 0;
  return (
    <div className="space-y-3 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-3.5">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="min-w-0">
          <div className="mb-1 flex items-center justify-between gap-2">
            <label htmlFor="sms-manual-sender" className="text-xs font-bold text-[#334155]">
              Sender ID
            </label>
            <Link href="/dashboard/sms/setup?sub=senders" className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline">
              <Plus size={12} /> Add sender
            </Link>
          </div>
          <select
            id="sms-manual-sender"
            className={inputCls}
            value={picked}
            disabled={senders.isLoading && !senders.data}
            onChange={(e) => {
              const s = list.find((x) => `${x.sender_id}|${x.entity_id}` === e.target.value);
              onChange({ sender_id: s?.sender_id ?? "", entity_id: s?.entity_id ?? "" });
            }}
          >
            <option value="">{senders.isLoading && !senders.data ? "Loading…" : "Choose a sender ID…"}</option>
            {list.map((s) => (
              <option key={`${s.sender_id}|${s.entity_id}`} value={`${s.sender_id}|${s.entity_id}`}>
                {s.sender_id}
                {s.entity_name ? ` · ${s.entity_name}` : ""}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-[11px] text-[#64748b]">Only senders added in DLT Manager can send.</span>
        </div>
        <Field label="Entity ID" hint={entityChanged ? "Different from this sender's saved entity. Check it matches your DLT portal." : "Fills in from the sender. You can change it."}>
          <input
            className={inputCls}
            inputMode="numeric"
            maxLength={30}
            value={value.entity_id}
            disabled={!value.sender_id}
            onChange={(e) => onChange({ entity_id: e.target.value.replace(/\D/g, "") })}
          />
        </Field>
      </div>
      {senders.error && !senders.data ? <LoadError message={friendlyError(senders.error, "Couldn't load your sender IDs.")} onRetry={() => void senders.mutate()} /> : null}
      {senders.data && list.length === 0 && <p className="text-xs text-[#64748b]">No approved sender IDs yet. Use Add sender first.</p>}
      <Field
        label="DLT template ID"
        hint={id && id.length !== 19 ? `DLT template IDs are usually 19 digits (this has ${id.length}).` : "The 19-digit number from your DLT portal (Jio, Airtel, Vi)."}
      >
        <input className={inputCls} inputMode="numeric" maxLength={30} placeholder="1707171234567890123" value={id} onChange={(e) => onChange({ dlt_template_id: e.target.value.replace(/\D/g, "") })} />
      </Field>
      <Field label="Message" hint="Paste it exactly as approved on DLT, with the real values in place of {#var#}. One changed character and the operator blocks it.">
        <textarea className={textareaCls} rows={4} maxLength={2000} value={value.message} onChange={(e) => onChange({ message: e.target.value })} />
      </Field>
      {match && (
        <Notice tone="success">
          This matches your saved template <span className="font-bold">#{match.message_id ?? match.dlt_template_id}</span>. Send it from Saved templates instead: no IDs to type and no typo risk.{" "}
          <button type="button" className="font-bold underline" onClick={() => onUseMatch(match)}>
            Use #{match.message_id ?? match.dlt_template_id}
          </button>
        </Notice>
      )}
      {leftoverVars && <Notice tone="danger">Replace each {"{#var#}"} with the real value. DLT Manual sends the text exactly as typed.</Notice>}
      {hasCurlyQuotes(value.message) && (
        <Notice tone="warn">
          This has a curly quote (’ or “ ”). It makes the SMS Unicode (70 characters per SMS), and DLT most likely approved a straight one.{" "}
          <button type="button" className="font-bold underline" onClick={() => onChange({ message: straightenQuotes(value.message) })}>
            Fix quotes
          </button>
        </Notice>
      )}
      <Notice tone="warn">{MANUAL_WARNING}</Notice>
    </div>
  );
}

/** One numbered step of the Send SMS form: a dark number circle, a title, then the step's fields. */
function Step({ n, id, title, children }: { n: number; id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex gap-4 border-t border-[#e9edf2] py-6 first:border-t-0 first:pt-1 last:pb-1">
      <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#0A1528] text-sm font-extrabold text-white">
        {n}
      </span>
      <div className="min-w-0 flex-1 space-y-3">
        <h2 id={id} className="mt-1 text-base font-extrabold text-[#0A1528]">
          {title}
        </h2>
        {children}
      </div>
    </section>
  );
}
