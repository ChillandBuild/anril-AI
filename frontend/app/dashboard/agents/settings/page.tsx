"use client";
import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { companionsApi, type CompanionMemoryScope } from "@/lib/api";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

const OPTIONS: { value: CompanionMemoryScope; title: string; example: string }[] = [
  {
    value: "character",
    title: "This character only",
    example: "Karthik tells Maya he prefers email. Only Maya remembers it.",
  },
  {
    value: "business",
    title: "Whole business",
    example: "Karthik tells Maya he prefers email. Every one of your characters remembers it.",
  },
];

export default function AgentsSettingsPage() {
  const [scope, setScope] = useState<CompanionMemoryScope | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    setError("");
    companionsApi
      .memorySettings()
      .then((r) => setScope(r.memory_scope))
      .catch((e: Error) => setError(e.message || "Could not load settings."));
  }, []);
  useEffect(load, [load]);

  const choose = async (value: CompanionMemoryScope) => {
    if (value === scope || saving) return;
    const previous = scope;
    setScope(value);
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const r = await companionsApi.setMemorySettings(value);
      setScope(r.memory_scope);
      setSaved(true);
    } catch (e) {
      setScope(previous);
      setError((e as Error).message || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      {error && <ErrorNote message={error} onRetry={scope === null ? load : undefined} />}
      {scope === null && !error ? (
        <LoadingRows rows={2} />
      ) : scope ? (
        <section className={cn(CARD, "space-y-3")} aria-labelledby="memory-scope">
          <div>
            <h2 id="memory-scope" className="text-sm font-semibold text-ink">Who remembers what a person says</h2>
            <p className="mt-1 text-sm text-ink-secondary">Applies to every character at memory level 2.</p>
          </div>
          <div role="radiogroup" aria-labelledby="memory-scope" className="grid gap-3 sm:grid-cols-2">
            {OPTIONS.map((o) => {
              const active = scope === o.value;
              return (
                <button
                  key={o.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={saving}
                  onClick={() => choose(o.value)}
                  className={cn(
                    "rounded-xl border p-4 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
                    active ? "border-primary bg-primary/5" : "border-border hover:bg-surface-mid",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className={cn("h-3.5 w-3.5 rounded-full border-2", active ? "border-primary bg-primary" : "border-ink-muted")} aria-hidden="true" />
                    <span className="text-sm font-semibold text-ink">{o.title}</span>
                  </div>
                  <p className="mt-2 text-xs text-ink-secondary">{o.example}</p>
                </button>
              );
            })}
          </div>
          <p aria-live="polite" className="text-xs text-ink-muted">{saving ? "Saving…" : saved ? "Saved" : ""}</p>
        </section>
      ) : null}
    </div>
  );
}
