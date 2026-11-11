"use client";
import { useState } from "react";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  companionsApi,
  type ApiError,
  type Companion,
  type CompanionSearchIn,
  type CompanionSearchResult,
} from "@/lib/api";
import { SECTION_LABEL } from "@/components/agents/memoryGraph";
import { scoreLabel, sourceText } from "@/components/agents/playground";
import { BTN_PRIMARY, CARD, INPUT, formatDate } from "@/components/agents/ui";

const SOURCES: { id: CompanionSearchIn; label: string; hint: string }[] = [
  { id: "knowledge", label: "Knowledge", hint: "The book passages this character would read for a question." },
  { id: "memories", label: "Memories", hint: "Facts this character remembers, matched word by word." },
];

/**
 * See what a character would find. Example: Jothidar AI, Knowledge, "Kumbham rasi this week" →
 * 3 passages from "Rasi palan" with "Match 3 of 3" on top. Memories, "Zoho" → Karthik's
 * "Interview at Zoho on 20 Nov".
 */
export function PlaygroundSearch({ character }: { character: Companion }) {
  const [source, setSource] = useState<CompanionSearchIn>("knowledge");
  const [q, setQ] = useState("");
  const [person, setPerson] = useState("");
  const [result, setResult] = useState<CompanionSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = q.trim();
    if (!query || busy) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await companionsApi.search(character.id, {
          in: source,
          q: query,
          limit: 10,
          ...(source === "memories" && person.trim() ? { external_user_id: person.trim() } : {}),
        }),
      );
    } catch (err) {
      setResult(null);
      setError((err as ApiError).message || "Search failed.");
    } finally {
      setBusy(false);
    }
  };

  const pick = (next: CompanionSearchIn) => {
    setSource(next);
    setResult(null);
    setError("");
  };

  return (
    <section className={cn(CARD, "space-y-4")} aria-label={`Search what ${character.name} would find`}>
      <div role="radiogroup" aria-label="Search in" className="flex gap-1">
        {SOURCES.map((s) => (
          <button
            key={s.id}
            type="button"
            role="radio"
            aria-checked={source === s.id}
            onClick={() => pick(s.id)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-medium",
              source === s.id ? "bg-primary/10 text-primary" : "text-ink-secondary hover:bg-surface-mid",
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-ink-muted">{SOURCES.find((s) => s.id === source)?.hint}</p>

      <form onSubmit={run} className="flex flex-wrap gap-2">
        <label className="min-w-[200px] flex-1">
          <span className="sr-only">Search text</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            maxLength={500}
            placeholder={source === "knowledge" ? "e.g. Kumbham rasi this week" : "e.g. Zoho interview"}
            className={INPUT}
          />
        </label>
        {source === "memories" && (
          <label className="w-full sm:w-44">
            <span className="sr-only">User id (optional)</span>
            <input
              value={person}
              onChange={(e) => setPerson(e.target.value)}
              maxLength={200}
              placeholder="User id (optional)"
              className={INPUT}
            />
          </label>
        )}
        <button type="submit" disabled={busy || !q.trim()} className={BTN_PRIMARY}>
          <Search size={14} aria-hidden="true" /> {busy ? "Searching…" : "Search"}
        </button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {result && (
        <div aria-live="polite">
          {result.results.length === 0 ? (
            <p className="text-sm text-ink-secondary">
              {result.in === "knowledge"
                ? !character.knowledge_collection_id
                  ? `${character.name} has no collection yet. Pick one in the character's Knowledge tab.`
                  : !result.needs_docs
                    ? "That message did not need the books."
                    : `Nothing in ${character.name}'s books matches that.`
                : `${character.name} doesn't remember anything with those words.`}
            </p>
          ) : result.in === "knowledge" ? (
            <ol className="space-y-2">
              {result.results.map((hit, i) => (
                <li key={i} className="rounded-xl border border-border-subtle px-3 py-2.5">
                  <div className="mb-1 flex items-baseline justify-between gap-2 text-xs text-ink-muted">
                    <span className="truncate">{sourceText(hit)}</span>
                    <span className="shrink-0 font-medium tabular-nums text-primary">{scoreLabel(hit.score)}</span>
                  </div>
                  {hit.heading_path && <p className="mb-1 text-xs text-ink-muted">{hit.heading_path}</p>}
                  <p className="whitespace-pre-wrap text-sm text-ink">{hit.text}</p>
                </li>
              ))}
            </ol>
          ) : (
            <ul className="divide-y divide-border-subtle">
              {result.results.map((hit, i) => (
                <li key={i} className="flex items-start gap-3 py-2.5">
                  <span className="mt-0.5 w-16 shrink-0 text-xs font-medium uppercase tracking-wide text-ink-muted">
                    {SECTION_LABEL[hit.section]}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className={cn("text-sm text-ink", hit.status === "closed" && "text-ink-muted line-through")}>{hit.text}</p>
                    <p className="text-xs text-ink-muted">
                      {hit.display_name ? `${hit.display_name} (${hit.external_user_id})` : hit.external_user_id}
                      {hit.learned_at ? ` · ${formatDate(hit.learned_at)}` : ""}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
