"use client";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { MEDIA_RULE_PRESETS, mediaRuleApi } from "@/lib/replySettingsApi";

const FIELD =
  "w-full rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20";

/** v9.2 #171: what the AI does when a customer sends a photo or a voice note. One short rule, kept in the AI's instructions. */
export function MediaRuleCard({ canEdit }: { canEdit: boolean }) {
  const [saved, setSaved] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [max, setMax] = useState(300);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mediaRuleApi
      .get()
      .then((r) => {
        setSaved(r.rule);
        setText(r.rule);
        setMax(r.max_chars);
      })
      .catch(() => setError("Could not load this rule. Please refresh."));
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy || saved === null) return;
    setBusy(true);
    setError(null);
    try {
      const r = await mediaRuleApi.save(text);
      setSaved(r.rule);
      setText(r.rule);
      toast.success(r.rule ? "Rule saved" : "Rule removed");
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const changed = saved !== null && text.trim() !== saved;
  return (
    <section className="card space-y-3" aria-labelledby="media-h">
      <div>
        <h2 id="media-h" className="font-display text-base font-bold text-ink">Photos and voice notes</h2>
        <p className="font-body text-sm text-ink-secondary">What should the AI do when a customer sends a photo or a voice note?</p>
      </div>
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          {MEDIA_RULE_PRESETS.map((p) => (
            <button key={p.label} type="button" onClick={() => setText(p.text.slice(0, max))}
              className="min-h-9 rounded-full border border-border-subtle bg-white px-3 py-1 font-body text-sm text-ink hover:border-primary/40">
              {p.label}
            </button>
          ))}
        </div>
      )}
      <form onSubmit={save} className="space-y-2">
        <label className="sr-only" htmlFor="media-rule">Rule for photos and voice notes</label>
        <textarea
          id="media-rule"
          rows={3}
          value={text}
          maxLength={max}
          disabled={!canEdit || saved === null}
          onChange={(e) => setText(e.target.value)}
          placeholder="Not set. The AI answers as it normally would."
          className={FIELD}
        />
        {error && <p role="alert" className="font-body text-sm text-danger">{error}</p>}
        <div className="flex items-center justify-between gap-3">
          <span className="font-body text-xs text-ink-muted">{text.length}/{max}</span>
          {canEdit && (
            <button type="submit" disabled={busy || !changed} className="btn-primary disabled:opacity-60">
              {busy && <Loader2 size={14} className="animate-spin" aria-hidden />} Save rule
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
