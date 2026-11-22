"use client";
import { useMemo, useState } from "react";
import { Loader2, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type TeachItem } from "@/lib/api";
import { SOURCE_LABEL, filterItems, taughtLabel } from "./teachLogic";

const FIELD =
  "w-full rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20";
const SMALL_BTN =
  "inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border-subtle bg-white px-3 font-label text-xs font-bold text-ink hover:border-primary/40 disabled:opacity-50";

function message(e: unknown) {
  return e instanceof Error && e.message ? e.message : "Could not save. Please try again.";
}

function Editor({ item, onDone }: { item: TeachItem | null; onDone: (saved?: TeachItem) => void }) {
  const [prompt, setPrompt] = useState(item?.prompt ?? "");
  const [reply, setReply] = useState(item?.reply ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const saved = item
        ? await api.aiTeach.saveItem(item.id, { prompt, reply })
        : await api.aiTeach.addItem({ kind: "answer", prompt, reply });
      toast.success(item ? "Answer updated" : "Answer saved");
      onDone(saved);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-2 rounded-xl border border-primary/25 bg-primary/[0.03] p-3">
      <label className="block font-label text-xs font-bold text-ink">
        When a customer asks
        <input value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={300} className={`${FIELD} mt-1 font-normal`}
          placeholder="e.g. Do you deliver to Chennai?" />
      </label>
      <label className="block font-label text-xs font-bold text-ink">
        The AI should say
        <textarea value={reply} onChange={(e) => setReply(e.target.value)} maxLength={1000} rows={3} className={`${FIELD} mt-1 resize-y font-normal`}
          placeholder="e.g. Yes, we deliver across India in 2 to 4 days." />
      </label>
      {error && <p role="alert" className="font-body text-xs text-danger">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !prompt.trim() || !reply.trim()} className="btn-primary min-h-9 disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" aria-hidden />} Save
        </button>
        <button type="button" onClick={() => onDone()} className={SMALL_BTN}>Cancel</button>
      </div>
    </form>
  );
}

export function AnswersCard({ items, canEdit, onChange }: { items: TeachItem[]; canEdit: boolean; onChange: () => void }) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const shown = useMemo(() => filterItems(items, query), [items, query]);

  async function remove(id: string) {
    try {
      await api.aiTeach.deleteItem(id);
      toast.success("Answer deleted");
      setConfirming(null);
      onChange();
    } catch (err) {
      toast.error(message(err));
    }
  }

  return (
    <section className="card space-y-3" aria-labelledby="answers-h">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="answers-h" className="font-display text-base font-bold text-ink">Answers to doubts</h2>
          <p className="font-body text-sm text-ink-secondary">What a customer asks, and what the AI should say.</p>
        </div>
        {canEdit && !adding && (
          <button type="button" onClick={() => setAdding(true)} className="btn-primary shrink-0">
            <Plus size={14} aria-hidden /> Add answer
          </button>
        )}
      </div>

      {adding && <Editor item={null} onDone={(saved) => { setAdding(false); if (saved) onChange(); }} />}

      {items.length > 4 && (
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search answers" placeholder="Search answers"
            className={`${FIELD} pl-9`} />
        </div>
      )}

      {items.length === 0 && !adding && (
        <p className="rounded-xl bg-surface-low px-3 py-4 font-body text-sm text-ink-secondary">
          Nothing taught yet. Answer a chat the AI handed over and tap Teach, or add one here.
        </p>
      )}
      {items.length > 0 && shown.length === 0 && <p className="font-body text-sm text-ink-secondary">No answer matches that search.</p>}

      <ul className="space-y-2">
        {shown.map((item) => (
          <li key={item.id} className="rounded-xl border border-border-subtle p-3">
            {editing === item.id ? (
              <Editor item={item} onDone={(saved) => { setEditing(null); if (saved) onChange(); }} />
            ) : (
              <>
                <p className="break-words font-body text-sm font-bold text-ink">{item.prompt}</p>
                <p className="mt-1 whitespace-pre-wrap break-words font-body text-sm text-ink-secondary">{item.reply}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-surface-low px-2 py-0.5 font-label text-xs text-ink-secondary">{SOURCE_LABEL[item.source]}</span>
                  {taughtLabel(item.times_taught) && (
                    <span className="font-label text-xs text-ink-secondary">{taughtLabel(item.times_taught)}</span>
                  )}
                  {canEdit && (
                    <span className="ml-auto flex gap-2">
                      {confirming === item.id ? (
                        <>
                          <button type="button" onClick={() => remove(item.id)} className={`${SMALL_BTN} border-danger text-danger`}>Yes, delete</button>
                          <button type="button" onClick={() => setConfirming(null)} className={SMALL_BTN}>Keep</button>
                        </>
                      ) : (
                        <>
                          <button type="button" onClick={() => setEditing(item.id)} className={SMALL_BTN} aria-label={`Edit answer: ${item.prompt}`}>
                            <Pencil size={13} aria-hidden /> Edit
                          </button>
                          <button type="button" onClick={() => setConfirming(item.id)} className={SMALL_BTN} aria-label={`Delete answer: ${item.prompt}`}>
                            <Trash2 size={13} aria-hidden /> Delete
                          </button>
                        </>
                      )}
                    </span>
                  )}
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
