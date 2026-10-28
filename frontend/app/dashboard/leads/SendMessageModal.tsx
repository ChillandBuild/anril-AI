"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CalendarClock, FileText, Loader2, MessageSquare, Send, X } from "lucide-react";
import { toast } from "sonner";
import { api, Lead, type SendDetailsTemplate } from "@/lib/api";
import { cn } from "@/lib/utils";
import { WhenToSend } from "@/components/schedule/WhenToSend";
import { defaultWhen, formatSendTime, resolveWhen, type WhenValue } from "@/lib/schedule-time";
import { VARIABLE_LABEL, blankVariables, renderTemplate, templateLabel } from "@/app/dashboard/telecalling/lib/send-details";

interface SendMessageModalProps {
  selectedLeads: Lead[];
  onClose: () => void;
  onAfterSend: () => void;
}

type Mode = "text" | "template";

const INPUT =
  "w-full px-4 py-2.5 bg-[#f8fafc] rounded-xl font-body text-sm text-[#0A1528] border border-[#e2e8f0] focus:outline-none focus:ring-2 focus:ring-primary";
const LABEL = "mb-1 block font-label text-[10px] font-bold uppercase tracking-wider text-[#64748b]";

function windowOpen(lead: Lead, now: number): boolean {
  return !!lead.last_inbound_at && now - new Date(lead.last_inbound_at).getTime() < 24 * 60 * 60 * 1000;
}

export function SendMessageModal({ selectedLeads, onClose, onAfterSend }: SendMessageModalProps) {
  const [now] = useState(() => Date.now());
  const openLeads = useMemo(() => selectedLeads.filter((l) => windowOpen(l, now)), [selectedLeads, now]);
  const skipped = selectedLeads.length - openLeads.length;

  // A template reaches everyone, so it is the default when nobody can get a free message.
  const [mode, setMode] = useState<Mode>(openLeads.length === 0 ? "template" : "text");
  const [message, setMessage] = useState("");
  const [templates, setTemplates] = useState<SendDetailsTemplate[] | null>(null);
  const [templatesNote, setTemplatesNote] = useState<string | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [values, setValues] = useState<string[]>([]);
  const [nameFallback, setNameFallback] = useState("");
  const [sending, setSending] = useState(false);
  const [progress, setProgress] = useState(0);
  const [when, setWhen] = useState<WhenValue>(() => defaultWhen(new Date()));

  // The approved templates come with the selected lead's send context.
  useEffect(() => {
    if (mode !== "template" || templates !== null) return;
    let stopped = false;
    (async () => {
      for (const lead of selectedLeads) {
        try {
          const ctx = await api.leads.sendDetailsContext(lead.id);
          if (stopped) return;
          if (ctx.available) {
            setTemplates(ctx.templates);
            if (ctx.templates[0]) setTemplateId(ctx.templates[0].id);
            return;
          }
        } catch {
          // try the next lead
        }
      }
      if (!stopped) {
        setTemplates([]);
        setTemplatesNote("WhatsApp isn't available for these leads (no number, opted out, or WhatsApp not connected).");
      }
    })();
    return () => {
      stopped = true;
    };
  }, [mode, templates, selectedLeads]);

  const template = useMemo(() => templates?.find((t) => t.id === templateId) ?? null, [templates, templateId]);
  const nameIndex = template ? template.variables.findIndex((v) => v.role === "customer_name") : -1;
  const unnamed = selectedLeads.filter((l) => !(l.name || "").trim()).length;

  useEffect(() => {
    // Each lead's own name goes in the name blank at send time; the rest are shared.
    setValues(template ? template.variables.map((v) => (v.role === "customer_name" ? "" : v.value)) : []);
  }, [template]);

  function valuesFor(lead: Lead): string[] {
    if (nameIndex < 0) return values;
    return values.map((v, i) => (i === nameIndex ? (lead.name || "").trim() || nameFallback.trim() : v));
  }

  const sharedBlanksLeft = template ? blankVariables(values.filter((_, i) => i !== nameIndex)) : 0;
  const needsFallback = nameIndex >= 0 && unnamed > 0 && !nameFallback.trim();
  const resolved = resolveWhen(when, new Date());
  const scheduling = mode === "template" && resolved.mode === "later";
  const canSend =
    !sending &&
    (mode === "text"
      ? openLeads.length > 0 && message.trim().length > 0
      : !!template && sharedBlanksLeft === 0 && !needsFallback && !(scheduling && resolved.error));

  async function send() {
    if (!canSend) return;
    setSending(true);
    setProgress(0);
    const targets = mode === "text" ? openLeads : selectedLeads;
    let sent = 0;
    let failed = 0;
    for (const lead of targets) {
      try {
        if (mode === "text") await api.leads.sendMessage(lead.id, message.trim());
        else if (template && scheduling && resolved.at) {
          await api.leads.scheduleTemplate(lead.id, {
            template_id: template.id,
            variables: valuesFor(lead),
            send_at: resolved.at.toISOString(),
          });
        } else if (template) await api.leads.sendDetails(lead.id, { template_id: template.id, variables: valuesFor(lead) });
        sent++;
      } catch {
        failed++;
      }
      setProgress((n) => n + 1);
    }
    setSending(false);
    let msg = scheduling && resolved.at ? `Scheduled ${sent} for ${formatSendTime(resolved.at)} IST` : `Sent ${sent}`;
    if (mode === "text" && skipped > 0) msg += ` · ${skipped} skipped, reply window closed`;
    if (failed > 0) msg += ` · ${failed} failed`;
    if (sent > 0) toast.success(msg);
    else toast.error(msg);
    onAfterSend();
    onClose();
  }

  const previewLead = selectedLeads.find((l) => (l.name || "").trim()) ?? selectedLeads[0];
  const total = mode === "text" ? openLeads.length : selectedLeads.length;

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-lg w-full max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto px-5 pt-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display text-lg font-bold text-[#0A1528]">
            Send message <span className="font-body text-sm font-semibold text-[#64748b]">· {selectedLeads.length} selected</span>
          </h3>
          <button onClick={onClose} aria-label="Close" className="text-[#64748b] hover:text-[#0A1528]">
            <X size={20} />
          </button>
        </div>

        <div role="tablist" className="mb-4 grid grid-cols-2 gap-1 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-1">
          {([
            ["text", "Free message", MessageSquare],
            ["template", "Template", FileText],
          ] as const).map(([value, label, Icon]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              onClick={() => setMode(value)}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-lg py-2 font-label text-xs font-bold transition-all",
                mode === value ? "bg-white text-primary shadow-sm" : "text-[#64748b] hover:text-[#0A1528]",
              )}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        {mode === "text" ? (
          openLeads.length === 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-xs leading-relaxed text-amber-800">
                None of the selected leads messaged you in the last 24 hours, so WhatsApp won&apos;t deliver a free
                message.{" "}
                <button type="button" onClick={() => setMode("template")} className="font-bold underline underline-offset-2">
                  Send a template instead
                </button>
              </p>
            </div>
          ) : (
            <>
              <p className="mb-3 text-xs text-[#64748b]">
                Goes to {openLeads.length} of {selectedLeads.length} selected
                {skipped > 0 && (
                  <>
                    {" "}· {skipped} skipped, reply window closed.{" "}
                    <button type="button" onClick={() => setMode("template")} className="font-semibold text-primary hover:underline">
                      Use a template to reach all {selectedLeads.length}
                    </button>
                  </>
                )}
              </p>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                placeholder="Type your message..."
                className={cn(INPUT, "resize-none py-3")}
              />
            </>
          )
        ) : templates === null ? (
          <div className="flex items-center gap-2 rounded-xl bg-[#f8fafc] p-4 text-sm text-[#64748b]">
            <Loader2 size={14} className="animate-spin" /> Loading templates…
          </div>
        ) : templates.length === 0 ? (
          <div className="rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-4 text-sm text-[#64748b]">
            {templatesNote ?? "No approved text templates on this WhatsApp number yet."}{" "}
            <Link href="/dashboard/templates" className="font-semibold text-primary hover:underline">
              Create one on the Templates page
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-[#64748b]">Templates reach every selected lead, even after the 24-hour window.</p>
            <div>
              <label className={LABEL} htmlFor="bulk-template">Template</label>
              <select id="bulk-template" value={templateId} onChange={(e) => setTemplateId(e.target.value)} className={cn(INPUT, "cursor-pointer")}>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{templateLabel(t)}</option>
                ))}
              </select>
            </div>

            {template?.variables.map((v, i) =>
              i === nameIndex ? (
                <div key={v.key} className="rounded-xl border border-primary/15 bg-primary-light/60 px-3 py-2.5">
                  <p className="font-label text-[10px] font-bold uppercase tracking-wider text-primary">
                    {`{{${v.key}}}`} · Customer name
                  </p>
                  <p className="mt-0.5 text-xs text-[#334155]">Filled with each lead&apos;s own name.</p>
                  {unnamed > 0 && (
                    <div className="mt-2">
                      <label className={LABEL} htmlFor="bulk-name-fallback">
                        {unnamed} {unnamed === 1 ? "lead has" : "leads have"} no name. Use this instead
                      </label>
                      <input
                        id="bulk-name-fallback"
                        value={nameFallback}
                        onChange={(e) => setNameFallback(e.target.value)}
                        placeholder="e.g. Sir/Madam"
                        className={cn(INPUT, "bg-white")}
                      />
                    </div>
                  )}
                </div>
              ) : (
                <div key={v.key}>
                  <label className={LABEL} htmlFor={`bulk-var-${v.key}`}>
                    {`{{${v.key}}}`} · {v.role ? VARIABLE_LABEL[v.role] : "Fill this in"}
                  </label>
                  <input
                    id={`bulk-var-${v.key}`}
                    value={values[i] ?? ""}
                    onChange={(e) => setValues((prev) => prev.map((old, j) => (j === i ? e.target.value : old)))}
                    className={INPUT}
                  />
                </div>
              ),
            )}

            {template && previewLead && (
              <div>
                <span className={LABEL}>Preview{previewLead.name ? ` for ${previewLead.name}` : ""}</span>
                <p className="whitespace-pre-wrap rounded-xl border border-primary/15 bg-primary-light px-4 py-3 font-body text-sm text-[#0A1528]">
                  {renderTemplate(template.body_text, valuesFor(previewLead))}
                </p>
              </div>
            )}

            {template && <WhenToSend idPrefix="bulk" variant="form" value={when} onChange={setWhen} disabled={sending} />}
          </div>
        )}

        {/* Pinned to the bottom of the scrolling dialog so Send stays in reach. */}
        <div className="sticky bottom-0 -mx-5 mt-4 flex items-center justify-end gap-2 bg-white px-5 pb-5 pt-3">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-[#f1f5f9] text-[#0A1528] rounded-xl font-label text-sm font-semibold hover:bg-[#e2e8f0]"
          >
            Cancel
          </button>
          <button
            onClick={send}
            disabled={!canSend}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-50"
          >
            {sending ? <Loader2 size={14} className="animate-spin" /> : scheduling ? <CalendarClock size={14} /> : <Send size={14} />}
            {sending
              ? `${scheduling ? "Scheduling" : "Sending"} ${progress}/${total}…`
              : scheduling
                ? `Schedule for ${total}`
                : `Send to ${total}`}
          </button>
        </div>
      </div>
    </div>
  );
}
