"use client";
import { useState } from "react";
import { Loader2, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { api, type TeachItem } from "@/lib/api";

const FIELD =
  "w-full rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20";

function message(e: unknown) {
  return e instanceof Error && e.message ? e.message : "Could not save. Please try again.";
}

export function WordsCard({ items, canEdit, onChange }: { items: TeachItem[]; canEdit: boolean; onChange: () => void }) {
  const [open, setOpen] = useState<TeachItem | "new" | null>(null);
  const [word, setWord] = useState("");
  const [meaning, setMeaning] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function start(target: TeachItem | "new") {
    setOpen(target);
    setWord(target === "new" ? "" : target.prompt);
    setMeaning(target === "new" ? "" : target.reply);
    setError(null);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !open) return;
    setBusy(true);
    setError(null);
    try {
      if (open === "new") await api.aiTeach.addItem({ kind: "word", prompt: word, reply: meaning });
      else await api.aiTeach.saveItem(open.id, { prompt: word, reply: meaning });
      toast.success("Word saved");
      setOpen(null);
      onChange();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!open || open === "new") return;
    try {
      await api.aiTeach.deleteItem(open.id);
      toast.success("Word deleted");
      setOpen(null);
      onChange();
    } catch (err) {
      setError(message(err));
    }
  }

  return (
    <section className="card space-y-3" aria-labelledby="words-h">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="words-h" className="font-display text-base font-bold text-ink">Words your shop uses</h2>
          <p className="font-body text-sm text-ink-secondary">So the AI understands your own words, like &quot;pattu&quot; = silk saree.</p>
        </div>
        {canEdit && open === null && (
          <button type="button" onClick={() => start("new")} className="btn-primary shrink-0">
            <Plus size={14} aria-hidden /> Add word
          </button>
        )}
      </div>

      {items.length === 0 && open === null && <p className="rounded-xl bg-surface-low px-3 py-4 font-body text-sm text-ink-secondary">No words added yet.</p>}

      <ul className="flex flex-wrap gap-2">
        {items.map((w) => {
          const chip = (
            <>
              <span className="font-bold">{w.prompt}</span> = {w.reply}
            </>
          );
          return (
            <li key={w.id}>
              {canEdit ? (
                <button type="button" onClick={() => start(w)} aria-label={`Edit word ${w.prompt}`}
                  className="min-h-9 rounded-full border border-border-subtle bg-white px-3 py-1 text-left font-body text-sm text-ink hover:border-primary/40">
                  {chip}
                </button>
              ) : (
                <span className="inline-block rounded-full border border-border-subtle bg-white px-3 py-1 font-body text-sm text-ink">{chip}</span>
              )}
            </li>
          );
        })}
      </ul>

      {open !== null && (
        <form onSubmit={save} className="space-y-2 rounded-xl border border-primary/25 bg-primary/[0.03] p-3">
          <label className="block font-label text-xs font-bold text-ink">
            Word
            <input value={word} onChange={(e) => setWord(e.target.value)} maxLength={80} className={`${FIELD} mt-1 font-normal`} placeholder="e.g. pattu" />
          </label>
          <label className="block font-label text-xs font-bold text-ink">
            What it means
            <input value={meaning} onChange={(e) => setMeaning(e.target.value)} maxLength={1000} className={`${FIELD} mt-1 font-normal`} placeholder="e.g. silk saree" />
          </label>
          {error && <p role="alert" className="font-body text-xs text-danger">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={busy || !word.trim() || !meaning.trim()} className="btn-primary min-h-9 disabled:opacity-50">
              {busy && <Loader2 size={14} className="animate-spin" aria-hidden />} Save
            </button>
            <button type="button" onClick={() => setOpen(null)} className="btn-secondary min-h-9">Cancel</button>
            {open !== "new" && (
              <button type="button" onClick={remove} className="btn-secondary ml-auto min-h-9 text-danger">
                <X size={13} aria-hidden /> Delete word
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}
