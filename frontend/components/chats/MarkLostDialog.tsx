"use client";
import { useEffect, useMemo, useState } from "react";
import { Loader2, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { api, apiFetch, Lead, WabaTemplate } from "@/lib/api";
import { SwitchPill } from "@/components/ui/controls";
import { Select } from "@/components/ui/Select";
import { cleanOtherReason, OTHER_REASON_MAX } from "./notBuyingReason";

type Guess = { choices: string[]; reason: string | null; quote: string | null };

const DAYS = [
  { value: "30", label: "30 days" },
  { value: "60", label: "60 days" },
  { value: "90", label: "90 days" },
];

/** How many {{n}} blanks a template has. Try again uses templates with none, or just the name in {{1}}. */
export function blanks(body: string | null | undefined): number {
  return new Set((body ?? "").match(/\{\{\s*\d+\s*\}\}/g) ?? []).size;
}

/** The reason saved on the chat: the chip (or Other words), then the note. Fits the 120-character limit. */
export function lostReasonText(chip: string, note: string): string {
  return cleanOtherReason(note ? `${chip} · ${note}` : chip);
}

/**
 * Mark Lost: why didn't they go ahead? Reason chips for this business, the AI agent's guess from the
 * chat, an optional note, and "Try again later": an approved template scheduled N days from now.
 */
export function MarkLostDialog({
  lead,
  onClose,
  onSaved,
}: {
  lead: Lead;
  onClose: () => void;
  onSaved: (updated: Lead) => void;
}) {
  const name = (lead.name || "").trim().split(/\s+/)[0] || "this customer";
  const [guess, setGuess] = useState<Guess | null>(null);
  const [chip, setChip] = useState<string | null>(null);
  const [other, setOther] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [retry, setRetry] = useState(false);
  const [days, setDays] = useState("30");
  const [templates, setTemplates] = useState<WabaTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    apiFetch<Guess>(`/api/v1/chats/${lead.id}/lost-guess`)
      .then((g) => {
        if (!live) return;
        setGuess(g);
        if (g.reason) setChip(g.reason);
      })
      .catch(() => live && setGuess({ choices: [], reason: null, quote: null }));
    api.templates.list()
      .then((all) => {
        if (!live) return;
        const usable = all.filter((t) => t.status?.toUpperCase() === "APPROVED" && blanks(t.body_text) <= 1);
        setTemplates(usable);
        if (usable[0]) setTemplateId(usable[0].id);
      })
      .catch(() => {});
    return () => { live = false; };
  }, [lead.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !saving) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, saving]);

  const picked = other !== null ? cleanOtherReason(other) : chip;
  const template = useMemo(() => templates.find((t) => t.id === templateId), [templates, templateId]);
  const canSave = Boolean(picked) && !saving && (!retry || Boolean(template));

  async function save() {
    if (!canSave || !picked) return;
    setSaving(true);
    try {
      const updated = await api.chats.notBuying(lead.id, lostReasonText(picked, note.trim()));
      if (retry && template) {
        const sendAt = new Date(Date.now() + Number(days) * 86_400_000);
        sendAt.setHours(11, 0, 0, 0); // late morning, inside the 10 AM - 8 PM sending hours
        try {
          await api.leads.scheduleTemplate(lead.id, {
            template_id: template.id,
            variables: blanks(template.body_text) ? [name] : [],
            send_at: sendAt.toISOString(),
          });
        } catch (err) {
          toast.warning(`Marked Lost, but the try-again message wasn't scheduled. ${err instanceof Error ? err.message : ""}`.trim());
        }
      }
      onSaved({ ...lead, ...updated });
      toast.success(retry && template ? `Marked Lost. We'll try again in ${days} days.` : "Marked Lost");
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save that");
      setSaving(false);
    }
  }

  const chips = guess?.choices ?? [];
  const chipClass = (on: boolean) =>
    `rounded-full border px-3 py-1.5 text-[12.5px] font-semibold transition ${
      on ? "border-primary bg-primary/10 text-primary" : "border-[#e2e8f0] text-[#334155] hover:border-[#94a3b8]"
    }`;

  return (
    <div className="fixed inset-0 z-dialog flex items-end justify-center bg-[#0A1528]/45 sm:items-center sm:p-4" onMouseDown={() => !saving && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="mark-lost-title"
        onMouseDown={(e) => e.stopPropagation()}
        className="flex max-h-[calc(100dvh-1rem)] w-full max-w-[560px] flex-col overflow-hidden rounded-t-2xl bg-white shadow-[0_30px_80px_-20px_rgba(10,21,40,0.45)] sm:rounded-2xl"
      >
        <div className="flex items-start gap-3 px-6 pb-3 pt-5">
          <div className="min-w-0 flex-1">
            <h2 id="mark-lost-title" className="truncate font-display text-[17px] font-bold text-[#0A1528]">
              Mark {lead.name || "this customer"} as Lost
            </h2>
            <p className="mt-0.5 text-[12px] text-[#64748b]">Why didn&apos;t {name} go ahead? It helps the AI agent and your reports.</p>
          </div>
          <button onClick={onClose} disabled={saving} aria-label="Close" className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-6 pb-5">
          {guess === null ? (
            <div className="flex items-center gap-2 rounded-xl border border-primary/15 bg-primary-light/40 px-4 py-3 text-[12.5px] text-[#475467]">
              <Loader2 size={14} className="animate-spin text-primary" /> The AI agent is reading the chat…
            </div>
          ) : guess.reason ? (
            <div className="rounded-xl border border-primary/20 bg-primary-light/50 px-4 py-3 text-[13px] leading-relaxed text-[#0f4c47]">
              <Sparkles size={13} className="mr-1 inline -translate-y-px text-primary" aria-hidden="true" />
              <span className="font-bold">AI agent&apos;s guess: {guess.reason}.</span>
              {guess.quote && <> They said: <span className="italic">&ldquo;{guess.quote}&rdquo;</span></>}
            </div>
          ) : null}

          <section>
            <p className="mb-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">
              Why didn&apos;t they go ahead?
            </p>
            <div className="flex flex-wrap gap-1.5">
              {chips.map((c) => (
                <button key={c} type="button" aria-pressed={other === null && chip === c}
                  onClick={() => { setOther(null); setChip(c); }} className={chipClass(other === null && chip === c)}>
                  {c}
                </button>
              ))}
              <button type="button" aria-pressed={other !== null} onClick={() => setOther(other ?? "")} className={chipClass(other !== null)}>
                + Other
              </button>
            </div>
            {other !== null && (
              <input
                autoFocus
                value={other}
                maxLength={OTHER_REASON_MAX}
                onChange={(e) => setOther(e.target.value)}
                placeholder="The reason, in your words"
                aria-label="Other reason"
                className="mt-2 h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-[13px] focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            )}
          </section>

          <input
            value={note}
            maxLength={80}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (optional): e.g. wants ground floor"
            aria-label="Note"
            className="h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-[13px] focus:outline-none focus:ring-2 focus:ring-primary/20"
          />

          <section className="flex items-start gap-3 rounded-xl border border-[#eef1f5] bg-[#fbfcfd] px-4 py-3">
            <SwitchPill on={retry} onChange={setRetry} size="sm" aria-label="Try again later" disabled={templates.length === 0 || lead.opted_out} />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-[#0A1528]">Try again later</p>
              {lead.opted_out ? (
                <p className="text-[11.5px] text-[#64748b]">They said stop, so no offers go to them.</p>
              ) : templates.length === 0 ? (
                <p className="text-[11.5px] text-[#64748b]">Needs an approved WhatsApp template. Make one in WhatsApp › Templates.</p>
              ) : (
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-[#475467]">
                  Send
                  <Select size="sm" className="w-[200px]" aria-label="Template" value={templateId} onChange={setTemplateId}
                    options={templates.map((t) => ({ value: t.id, label: t.name }))} />
                  after
                  <Select size="sm" className="w-[104px]" aria-label="After" value={days} onChange={setDays} options={DAYS} />
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-[#eef1f5] px-6 py-4">
          <button type="button" onClick={onClose} disabled={saving}
            className="h-11 rounded-xl border border-[#e2e8f0] px-6 text-[13.5px] font-semibold text-[#334155] hover:bg-slate-50">
            Cancel
          </button>
          <button type="button" onClick={() => void save()} disabled={!canSave}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#475467] px-6 text-[13.5px] font-bold text-white hover:bg-[#344054] disabled:cursor-not-allowed disabled:opacity-45">
            {saving && <Loader2 size={15} className="animate-spin" />} Mark Lost
          </button>
        </div>
      </div>
    </div>
  );
}
