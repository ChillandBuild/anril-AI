"use client";
import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, type TeachItem } from "@/lib/api";
import { stripMarkdown } from "@/lib/utils";
import { likedMarks } from "@/components/ai-setup/likedMarks";

const FIELD =
  "w-full rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20";
const SMALL_BTN =
  "inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border-subtle bg-white px-3 font-label text-xs font-bold text-ink hover:border-primary/40 disabled:opacity-50";
const SHOWN_FIRST = 3;

function message(e: unknown) {
  return e instanceof Error && e.message ? e.message : "Could not save. Please try again.";
}

function AddExample({ onDone }: { onDone: (saved: boolean) => void }) {
  const [said, setSaid] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.aiTeach.addItem({ kind: "liked", prompt: said, reply });
      toast.success("Example saved");
      onDone(true);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-2 rounded-xl border border-primary/25 bg-primary/[0.03] p-3">
      <label className="block font-label text-xs font-bold text-ink">
        What the customer said
        <textarea value={said} onChange={(e) => setSaid(e.target.value)} maxLength={300} rows={2} className={`${FIELD} mt-1 resize-y font-normal`}
          placeholder="e.g. Is the bridal set available in red?" />
      </label>
      <label className="block font-label text-xs font-bold text-ink">
        The reply you like
        <textarea value={reply} onChange={(e) => setReply(e.target.value)} maxLength={1000} rows={3} className={`${FIELD} mt-1 resize-y font-normal`}
          placeholder="e.g. Yes, we have it in red. Want me to share a few photos?" />
      </label>
      {error && <p role="alert" className="font-body text-xs text-danger">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !said.trim() || !reply.trim()} className="btn-primary min-h-9 disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" aria-hidden />} Save
        </button>
        <button type="button" onClick={() => onDone(false)} className={SMALL_BTN}>Cancel</button>
      </div>
    </form>
  );
}

export function LikedCard({ items, canEdit, onChange }: { items: TeachItem[]; canEdit: boolean; onChange: () => void }) {
  const [adding, setAdding] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const fromChat = items.filter((i) => i.source === "chat").length;
  const shown = expanded ? items : items.slice(0, SHOWN_FIRST);

  async function remove(item: TeachItem) {
    try {
      // A reply liked from Chats is un-liked there, so its 👍 in the chat goes back to idle too.
      if (item.message_id) {
        await api.aiTeach.unlike(item.message_id);
        likedMarks.set(item.message_id, false);
      } else {
        await api.aiTeach.deleteItem(item.id);
      }
      toast.success("Example removed");
      setConfirming(null);
      onChange();
    } catch (err) {
      toast.error(message(err));
    }
  }

  return (
    <section className="card space-y-3" aria-labelledby="liked-h">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="liked-h" className="font-display text-base font-bold text-ink">👍 Replies you like</h2>
          <p className="font-body text-sm text-ink-secondary">
            {items.length > 0
              ? `the AI copies this style · ${items.length} saved · ${fromChat} came from 👍 in Chats`
              : "the AI copies this style"}
          </p>
          <p className="font-body text-xs text-ink-muted">
            Style only. Prices and facts still come from your Catalogue and Knowledge Base. The AI reads your 10 newest.
          </p>
        </div>
        {canEdit && !adding && (
          <button type="button" onClick={() => setAdding(true)} className="btn-primary shrink-0">
            <Plus size={14} aria-hidden /> Add example
          </button>
        )}
      </div>

      {adding && <AddExample onDone={(saved) => { setAdding(false); if (saved) onChange(); }} />}

      {items.length === 0 && !adding && (
        <p className="rounded-xl bg-surface-low px-3 py-4 font-body text-sm text-ink-secondary">
          No replies yet. Tap 👍 under a good AI reply in Chats, or add one here.
        </p>
      )}

      <ul className="space-y-2">
        {shown.map((item) => (
          <li key={item.id} className="rounded-xl bg-surface-low p-3">
            <p className="break-words font-body text-sm text-ink-secondary">Customer: &ldquo;{item.prompt}&rdquo;</p>
            <p className="mt-1 whitespace-pre-wrap break-words font-body text-sm text-ink">AI: &ldquo;{stripMarkdown(item.reply)}&rdquo;</p>
            {canEdit && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {confirming === item.id ? (
                  <>
                    <button type="button" onClick={() => void remove(item)} className={`${SMALL_BTN} border-danger text-danger`}>Yes, remove</button>
                    <button type="button" onClick={() => setConfirming(null)} className={SMALL_BTN}>Keep</button>
                  </>
                ) : (
                  <button type="button" onClick={() => setConfirming(item.id)} className={SMALL_BTN} aria-label={`Remove example: ${item.prompt}`}>
                    Remove
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>

      {items.length > SHOWN_FIRST && (
        <button type="button" onClick={() => setExpanded((v) => !v)} className="font-label text-xs font-bold text-primary underline">
          {expanded ? "show fewer" : `see all ${items.length}`}
        </button>
      )}
    </section>
  );
}
