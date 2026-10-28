"use client";
import { useCallback, useEffect, useState } from "react";
import { CalendarClock, FileText, MessageCircle, MessageSquare, RefreshCw, Send } from "lucide-react";
import { toast } from "sonner";
import { api, type ScheduledTemplate, type SendDetailsContext, type SendDetailsTemplate } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { useScheduledTemplates } from "@/hooks/useScheduledTemplates";
import { WhenToSend } from "@/components/schedule/WhenToSend";
import { ScheduledRows } from "@/components/schedule/scheduled-messages";
import { defaultWhen, formatSendTime, resolveWhen, type WhenValue } from "@/lib/schedule-time";
import { VARIABLE_LABEL, blankVariables, renderTemplate, templateLabel } from "../lib/send-details";

type ReadyContext = Extract<SendDetailsContext, { available: true }>;
type SendAs = "free" | "template";

export interface SendDetailsViewProps {
  context: ReadyContext;
  sending: boolean;
  readOnly?: boolean;
  /** Inside a dialog that already has a title, so the card drops its own heading. */
  inDialog?: boolean;
  scheduled?: ScheduledTemplate[];
  onSendText: (text: string) => void;
  onSendTemplate: (template: SendDetailsTemplate, values: string[]) => void;
  onSchedule?: (template: SendDetailsTemplate, values: string[], at: Date) => void;
  onCancelScheduled?: (id: string) => void;
}

const SEND = "flex w-full items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 font-label text-xs font-bold text-white shadow-sm transition-all hover:bg-emerald-700 disabled:opacity-50";

/**
 * Presentational: a free message inside the 24 h window, or an approved template at any time.
 * A template goes now or at a time the person picks (Schedule).
 */
export function SendDetailsView({
  context,
  sending,
  readOnly = false,
  inDialog = false,
  scheduled = [],
  onSendText,
  onSendTemplate,
  onSchedule,
  onCancelScheduled,
}: SendDetailsViewProps) {
  const [text, setText] = useState(context.free_text);
  const [templateId, setTemplateId] = useState(context.templates[0]?.id ?? "");
  const template = context.templates.find((t) => t.id === templateId) ?? null;
  const [values, setValues] = useState<string[]>(template ? template.variables.map((v) => v.value) : []);
  const blanks = template ? blankVariables(values) : 0;
  const [sendAs, setSendAs] = useState<SendAs>(context.window_open ? "free" : "template");
  const [when, setWhen] = useState<WhenValue>(() => defaultWhen(new Date()));
  // Filled-in details fold into one line. Blanks keep the fields open, and they stay open while typed into.
  const [fieldsOpen, setFieldsOpen] = useState(blanks > 0);

  // The useState initialisers above only run once. When the parent re-fetches (e.g. after
  // a send, or the customer's last-inbound time moving the window), `context` is a new
  // object and the draft has to re-sync to it -- otherwise a sent message's stale text
  // sits in the box after the reload instead of the fresh pre-fill.
  useEffect(() => {
    setText(context.free_text);
    const firstTemplate = context.templates[0] ?? null;
    const firstValues = firstTemplate ? firstTemplate.variables.map((v) => v.value) : [];
    setTemplateId(firstTemplate?.id ?? "");
    setValues(firstValues);
    setFieldsOpen(blankVariables(firstValues) > 0);
    setSendAs(context.window_open ? "free" : "template");
  }, [context]);

  function pickTemplate(id: string) {
    setTemplateId(id);
    const next = context.templates.find((t) => t.id === id);
    const nextValues = next ? next.variables.map((v) => v.value) : [];
    setValues(nextValues);
    setFieldsOpen(blankVariables(nextValues) > 0);
  }

  const hasTemplates = context.templates.length > 0;
  const isTemplate = !context.window_open || sendAs === "template";
  const resolved = resolveWhen(when, new Date());
  const scheduling = isTemplate && resolved.mode === "later";
  const canChange = !readOnly && !!onCancelScheduled;

  let action: { label: string; icon: "send" | "schedule"; disabled: boolean; run: () => void } | null = null;
  if (!isTemplate) {
    action = { label: "Send", icon: "send", disabled: !text.trim(), run: () => onSendText(text.trim()) };
  } else if (hasTemplates && template) {
    if (blanks > 0) {
      action = { label: `Fill ${blanks} blank${blanks === 1 ? "" : "s"}`, icon: "send", disabled: true, run: () => {} };
    } else if (scheduling) {
      action = {
        label: "Schedule template",
        icon: "schedule",
        disabled: !onSchedule || !!resolved.error || !resolved.at,
        run: () => resolved.at && onSchedule?.(template, values, resolved.at),
      };
    } else {
      action = { label: "Send template", icon: "send", disabled: false, run: () => onSendTemplate(template, values) };
    }
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2.5 rounded-2xl border border-[#e2e8f0] bg-white px-4 py-3.5 shadow-sm">
      {!inDialog && (
        <h3 className="flex items-center gap-1.5 font-display text-xs font-black uppercase tracking-widest text-[#13284A]">
          <MessageCircle size={12} className="text-emerald-500" /> Send details on WhatsApp
        </h3>
      )}
      <span
        className={`inline-flex items-center gap-1.5 self-start rounded-full border px-2 py-0.5 font-label text-[10px] font-bold ${
          context.window_open ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
        }`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${context.window_open ? "bg-emerald-500" : "bg-amber-500"}`} />
        {context.window_open
          ? `Free message · customer wrote ${context.last_inbound_at ? timeAgo(context.last_inbound_at) : "recently"}`
          : "Template needed · no message from the customer in 24 h"}
      </span>

      {context.window_open && hasTemplates && (
        <div role="tablist" aria-label="Send as" className="grid grid-cols-2 gap-1 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-1">
          {([
            ["free", "Free message", MessageSquare],
            ["template", "Template", FileText],
          ] as const).map(([value, label, Icon]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={sendAs === value}
              onClick={() => setSendAs(value)}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-lg py-2 font-label text-xs font-bold transition-all",
                sendAs === value ? "bg-white text-primary shadow-sm" : "text-[#64748b] hover:text-[#0A1528]",
              )}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
      )}

      <ScheduledRows items={scheduled} canChange={canChange} onCancel={(id) => onCancelScheduled?.(id)} />

      {!isTemplate ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={context.window_open && hasTemplates ? 5 : 7}
          aria-label="Message"
          className="w-full resize-none rounded-xl border border-[#e2e8f0] bg-[#f8fafc]/40 p-3 font-body text-xs leading-relaxed transition-all focus:bg-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
        />
      ) : !hasTemplates ? (
        <p className="rounded-xl border border-dashed border-[#e2e8f0] bg-[#f8fafc] p-3 font-body text-[11px] leading-relaxed text-[#475569]">
          No approved templates yet. Add one under Templates (for example <span className="font-semibold">call_details_share</span>) and it shows here once Meta approves it.
        </p>
      ) : (
        <>
          <select
            value={templateId}
            onChange={(e) => pickTemplate(e.target.value)}
            aria-label="Template"
            className="w-full rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-body text-xs text-[#1e293b] focus:outline-none focus:ring-2 focus:ring-emerald-300"
          >
            {context.templates.map((t) => (
              <option key={t.id} value={t.id}>{templateLabel(t)}</option>
            ))}
          </select>
          {template && template.variables.length > 0 && (
            <button
              type="button"
              onClick={() => setFieldsOpen((open) => !open)}
              disabled={blanks > 0}
              aria-expanded={fieldsOpen}
              className="flex w-full items-center justify-between gap-2 rounded-[10px] border border-[#e2e8f0] bg-[#f8fafc] px-2.5 py-1.5 text-left font-label text-[11px] font-semibold text-[#64748b] disabled:cursor-default"
            >
              <span>{fieldsOpen ? "Template details" : `${template.variables.length} detail${template.variables.length === 1 ? "" : "s"} filled in`}</span>
              <b className={cn("font-extrabold", blanks > 0 ? "text-amber-700" : "text-primary")}>
                {blanks > 0 ? `${blanks} to fill` : fieldsOpen ? "Hide" : "Edit"}
              </b>
            </button>
          )}
          {fieldsOpen &&
            template?.variables.map((v, i) => (
              <label key={v.key} className="block">
                <span className="mb-1 block font-label text-[10px] font-black uppercase tracking-wider text-[#94a3b8]">
                  {`{{${v.key}}}`} · {v.role ? VARIABLE_LABEL[v.role] : "Fill this in"}
                </span>
                <input
                  value={values[i] ?? ""}
                  onChange={(e) => setValues((prev) => prev.map((x, j) => (j === i ? e.target.value : x)))}
                  className={`w-full rounded-lg border px-2.5 py-1.5 font-body text-xs focus:outline-none focus:ring-2 focus:ring-emerald-300 ${
                    (values[i] ?? "").trim() ? "border-[#e2e8f0] bg-white" : "border-amber-300 bg-amber-50/50"
                  }`}
                />
              </label>
            ))}
          {template && (
            <div className="whitespace-pre-wrap rounded-xl border border-primary-100 bg-primary-50 px-3 py-2.5 font-body text-[11px] leading-[1.55] text-[#13284A]">
              {renderTemplate(template.body_text, values)}
            </div>
          )}
          <WhenToSend idPrefix="send-details" value={when} onChange={setWhen} disabled={readOnly} />
        </>
      )}

      {action && (
        // Pinned to the bottom of a scrolling dialog so it is always in reach.
        <div className="sticky bottom-0 z-[1] pb-2 pt-2" style={{ background: "linear-gradient(to top, #fff 80%, rgba(255,255,255,0))" }}>
          <button type="button" disabled={readOnly || sending || action.disabled} onClick={action.run} className={SEND}>
            {sending ? <RefreshCw size={12} className="animate-spin" /> : action.icon === "schedule" ? <CalendarClock size={12} /> : <Send size={12} />}
            {action.label}
          </button>
        </div>
      )}
      <p className="font-label text-[10px] text-[#94a3b8]">Sends from your business number and shows in Conversations.</p>
    </div>
  );
}

// Last answer per lead, so reopening a lead shows the card at once while it refreshes.
const contextCache = new Map<string, SendDetailsContext>();

/** Holds the card's space while the first answer loads, so Quick Note doesn't jump. */
function SendDetailsSkeleton() {
  return (
    <div aria-hidden className="flex min-w-0 flex-1 animate-pulse flex-col gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
      <div className="h-3 w-40 rounded bg-[#f0ece6]" />
      <div className="h-4 w-56 rounded-full bg-[#f5f2ed]" />
      <div className="min-h-[120px] flex-1 rounded-xl bg-[#f8fafc]" />
      <div className="h-8 rounded-xl bg-[#f0ece6]" />
    </div>
  );
}

/** Lead page card. Hidden when the tenant has no WhatsApp or the lead opted out. */
export default function SendDetailsCard({
  leadId,
  readOnly = false,
  explainUnavailable = false,
  inDialog = false,
  onScheduleChange,
}: {
  leadId: string;
  readOnly?: boolean;
  /** In a dialog opened just for this, say why nothing can be sent instead of showing nothing. */
  explainUnavailable?: boolean;
  /** Inside a dialog that already has a title. */
  inDialog?: boolean;
  /** Called after a template is scheduled, cancelled, undone or moved, so a thread can refresh its bubbles. */
  onScheduleChange?: () => void;
}) {
  const [context, setContext] = useState<SendDetailsContext | null>(() => contextCache.get(leadId) ?? null);
  const [sending, setSending] = useState(false);
  const scheduledTemplates = useScheduledTemplates(leadId, { onChanged: onScheduleChange });

  const load = useCallback((force = false) => {
    api.leads.sendDetailsContext(leadId)
      .then((next) => {
        const cached = contextCache.get(leadId);
        // An unchanged refresh keeps the old object: a new one resets any draft being typed.
        if (!force && cached && JSON.stringify(cached) === JSON.stringify(next)) return setContext(cached);
        contextCache.set(leadId, next);
        setContext(next);
      })
      .catch(() => setContext({ available: false }));
  }, [leadId]);

  useEffect(() => {
    setContext(contextCache.get(leadId) ?? null);
    load();
  }, [leadId, load]);

  if (!context) return <SendDetailsSkeleton />;
  if (!context.available) {
    return explainUnavailable ? (
      <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 font-body text-sm text-amber-800">
        WhatsApp templates can&apos;t go to this lead. They need a WhatsApp number on the lead, a connected WhatsApp
        account, and a lead who hasn&apos;t opted out.
      </p>
    ) : null;
  }

  async function send(body: { text: string } | { template_id: string; variables: string[] }) {
    setSending(true);
    try {
      await api.leads.sendDetails(leadId, body);
      toast.success("Sent on WhatsApp. It's in Conversations.");
      load(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "WhatsApp didn't send it");
    } finally {
      setSending(false);
    }
  }

  async function schedule(template: SendDetailsTemplate, values: string[], at: Date) {
    setSending(true);
    try {
      await api.leads.scheduleTemplate(leadId, { template_id: template.id, variables: values, send_at: at.toISOString() });
      toast.success(`Scheduled for ${formatSendTime(at)} IST. You can cancel it until then.`);
      await scheduledTemplates.refresh();
      onScheduleChange?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't schedule it");
    } finally {
      setSending(false);
    }
  }

  return (
    <SendDetailsView
      key={leadId}
      context={context}
      sending={sending}
      readOnly={readOnly}
      inDialog={inDialog}
      scheduled={scheduledTemplates.items}
      onSendText={(text) => void send({ text })}
      onSendTemplate={(template, values) => void send({ template_id: template.id, variables: values })}
      onSchedule={(template, values, at) => void schedule(template, values, at)}
      onCancelScheduled={(id) => void scheduledTemplates.cancel(id)}
    />
  );
}
