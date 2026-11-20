"use client";
import { useState } from "react";
import { ChevronDown, ClipboardList, Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useLeadFormAnswers, useSendableForms } from "@/hooks/useApi";

function when(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
}

/**
 * Customer panel: the WhatsApp Forms this customer submitted (newest first) and a way to send them
 * one. Hidden for accounts without WhatsApp Forms.
 */
export function LeadForms({ leadId }: { leadId: string }) {
  const { role, permissions } = useAuthRole();
  const canReply = role === "owner" || permissions.includes("conversations.reply");
  const { data: answers, mutate } = useLeadFormAnswers(leadId);
  const { data: sendable } = useSendableForms(canReply);
  const [open, setOpen] = useState<string | null>(null);
  const [formId, setFormId] = useState("");
  const [sending, setSending] = useState(false);

  if (!answers?.available) return null;
  const forms = sendable?.data ?? [];
  const chosen = formId || forms[0]?.id || "";

  async function send() {
    if (!chosen) return;
    setSending(true);
    try {
      await api.whatsappForms.send(chosen, leadId);
      toast.success("Form sent on WhatsApp.");
      await mutate();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't send the form.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 font-label text-[11px] font-bold uppercase tracking-wider text-on-surface-muted">
        <ClipboardList size={12} /> WhatsApp Forms
      </p>
      {answers.data.length === 0 ? (
        <p className="font-body text-xs text-on-surface-muted">No forms submitted yet.</p>
      ) : (
        <ul className="space-y-2">
          {answers.data.map((entry) => (
            <li key={entry.id} className="rounded-lg ring-1 ring-surface-mid">
              <button
                type="button"
                onClick={() => setOpen(open === entry.id ? null : entry.id)}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
                aria-expanded={open === entry.id}
              >
                <span className="min-w-0">
                  <span className="block truncate font-label text-xs font-semibold text-on-surface">{entry.form_name}</span>
                  <span className="block font-body text-[11px] text-on-surface-muted">{when(entry.submitted_at)}</span>
                </span>
                <ChevronDown size={14} className={cn("shrink-0 text-on-surface-muted transition-transform", open === entry.id && "rotate-180")} />
              </button>
              {open === entry.id && (
                <dl className="space-y-1.5 border-t border-surface-mid px-3 py-2">
                  {entry.answers.map((a, i) => (
                    <div key={i}>
                      <dt className="font-body text-[11px] text-on-surface-muted">{a.label}</dt>
                      <dd className="break-words font-body text-xs text-on-surface">{a.value}</dd>
                    </div>
                  ))}
                  <div>
                    <dt className="font-body text-[11px] text-on-surface-muted">Offers on WhatsApp</dt>
                    <dd className="font-body text-xs text-on-surface">{entry.offers ? "Yes" : "No"}</dd>
                  </div>
                </dl>
              )}
            </li>
          ))}
        </ul>
      )}
      {canReply && forms.length > 0 && (
        <div className="flex items-center gap-2 pt-1">
          <Select size="sm" aria-label="Form to send" value={chosen} onChange={setFormId} className="min-w-0 flex-1"
            options={forms.map((f) => ({ value: f.id, label: f.name }))} />
          <button
            type="button"
            onClick={send}
            disabled={sending || !chosen}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 font-label text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-50"
          >
            {sending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Send form
          </button>
        </div>
      )}
    </div>
  );
}
