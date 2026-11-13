"use client";
import { useState } from "react";
import { FileText, PenLine } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  companionsApi,
  type ApiError,
  type Companion,
  type CompanionKnowledgeHit,
  type CompanionMemoryHit,
  type CompanionSearchResult,
  type PlaygroundDefaults,
  type PlaygroundSources,
} from "@/lib/api";
import {
  NOTICE_KNOWLEDGE_ERROR,
  NOTICE_NOTHING,
  buildSearchView,
  documentLine,
  judgePill,
  meaningText,
  resultCountText,
  memoryPersonLine,
  memoryScoreText,
  memoryTag,
  sourcesSetting,
} from "@/components/agents/playground";
import { BTN_PRIMARY, INPUT } from "@/components/agents/ui";

const PERSON_HINT =
  "Add a person's user id to search their memories by meaning; without one, facts are matched word by word across everyone.";

/**
 * "What <name> finds", inside Advanced: type a question, see what the character would read.
 * Example: Maya, "Can I return my shoes?" -> a grey "Searched for: return policy for used shoes",
 * 2 passages from "Returns policy.pdf" ("judge 3/3 · kept") and Karthik's memory "Bought running
 * shoes" ("meaning 0.83"). Live defaults for everything except `sources` (the Answer from choice).
 */
export function PlaygroundSearch({
  character,
  sources,
  live,
}: {
  character: Companion;
  sources: PlaygroundSources;
  live: PlaygroundDefaults;
}) {
  const [q, setQ] = useState("");
  const [person, setPerson] = useState("");
  const [showDropped, setShowDropped] = useState(false);
  const [result, setResult] = useState<CompanionSearchResult | null>(null);
  const [ranWith, setRanWith] = useState<PlaygroundSources | null>(null);   // the sources that made `result`
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    const query = q.trim();
    if (!query || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await companionsApi.search(character.id, {
        in: sources,
        q: query,
        limit: live.results,
        ...(sources !== "knowledge" && person.trim() ? { external_user_id: person.trim() } : {}),
        settings: sourcesSetting(sources, live),
      });
      setResult(res);
      setRanWith(sources);
    } catch (err) {
      setResult(null);
      setError((err as ApiError).message || "Search failed.");
    } finally {
      setBusy(false);
    }
  };

  const view = result ? buildSearchView(result, { showDropped }) : null;
  const stale = !!ranWith && ranWith !== sources;

  return (
    <div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <label className="min-w-0 flex-1">
          <span className="sr-only">Search text</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} placeholder={`Ask what ${character.name} would look up…`} className={INPUT} />
        </label>
        <button type="submit" disabled={busy || !q.trim()} className={cn(BTN_PRIMARY, "shrink-0")}>
          Look up
        </button>
      </form>
      {sources !== "knowledge" && (
        <label className="mt-2 block">
          <span className="sr-only">User id (optional)</span>
          <input
            value={person}
            onChange={(e) => setPerson(e.target.value)}
            maxLength={200}
            placeholder="User id (optional)"
            className={cn(INPUT, "max-w-[260px] py-1.5 text-[13px]")}
          />
          {!person.trim() && <span className="mt-1 block text-xs text-ink-muted">{PERSON_HINT}</span>}
        </label>
      )}

      {busy && <p className="mt-3 text-sm text-ink-muted">Searching…</p>}
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}

      {/* The one live region: a short count, announced after each search. */}
      <p aria-live="polite" className={cn("text-xs text-ink-muted", view && "mt-3")}>
        {view ? resultCountText(view) : ""}
      </p>
      {result && view && (
        <div className="mt-2 flex flex-col gap-2.5">
          {stale && <p className="text-xs text-ink-muted">&ldquo;Answer from&rdquo; changed since this search. Look up again to apply it.</p>}
          {result.rewritten && <RewriteBox rewritten={result.rewritten} />}
          {view.knowledgeError && <p className="text-[13px] text-ink-secondary">{NOTICE_KNOWLEDGE_ERROR}</p>}
          {view.knowledge.map((hit, i) => (
            <KnowledgeRow key={`k${i}`} hit={hit} />
          ))}
          {view.memories.map((hit, i) => (
            <MemoryRow key={`m${i}`} hit={hit} mode={result.memory_mode} />
          ))}
          {view.hiddenLine && <p className="text-[13px] text-ink-secondary">{view.hiddenLine}</p>}
          {view.notices.map((n) => (
            <p key={n} className="text-[13px] text-ink-secondary">
              {n}
            </p>
          ))}
          {view.nothingPassed && <p className="text-[13px] text-ink-secondary">{NOTICE_NOTHING}</p>}
        </div>
      )}
      {result && (
        <label className="mt-3 flex items-center gap-2 text-[13px] text-ink-secondary">
          <input type="checkbox" checked={showDropped} onChange={(e) => setShowDropped(e.target.checked)} className="h-4 w-4 accent-primary" />
          Show pages it found but dropped
        </label>
      )}
    </div>
  );
}

/** "Searched for: “return policy for used shoes”", plus the Tamil version when it differs. */
function RewriteBox({ rewritten }: { rewritten: NonNullable<CompanionSearchResult["rewritten"]> }) {
  const tamil = rewritten.tamil && rewritten.tamil !== rewritten.english ? rewritten.tamil : "";
  return (
    <div className="rounded-[10px] bg-surface-mid px-2.5 py-2 text-[12.5px] text-ink-secondary">
      <p className="flex items-start gap-1.5">
        <PenLine size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
        <span>
          Searched for: <b className="font-semibold text-ink">“{rewritten.english}”</b>
        </span>
      </p>
      {tamil && <p className="pl-[19px]">Tamil: <b className="font-semibold text-ink">“{tamil}”</b></p>}
    </div>
  );
}

const TAG = "rounded-full bg-surface-mid px-2 py-px text-[11.5px]";
const PILL_TONE = { ok: "bg-green-100 text-success", bad: "bg-rose-100 text-danger", neutral: "bg-surface-mid text-ink-secondary" } as const;

function KnowledgeRow({ hit }: { hit: CompanionKnowledgeHit }) {
  const pill = judgePill(hit.score, hit.kept);
  const meaning = meaningText(hit.meaning);
  return (
    <article className={cn("rounded-xl border p-3", hit.kept ? "border-border" : "border-dashed border-border opacity-55")}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-secondary">
        <span className={TAG}>Knowledge</span>
        <span className="inline-flex items-center gap-1">
          <FileText size={13} aria-hidden="true" /> {documentLine(hit)}
        </span>
        {meaning && <span className="font-mono">{meaning}</span>}
        <span className={cn(TAG, PILL_TONE[pill.tone])}>{pill.text}</span>
      </div>
      {hit.heading_path && <p className="mb-1 text-xs text-ink-muted">{hit.heading_path}</p>}
      <p className="whitespace-pre-wrap text-sm text-ink">{hit.text}</p>
    </article>
  );
}

function MemoryRow({ hit, mode }: { hit: CompanionMemoryHit; mode: CompanionSearchResult["memory_mode"] }) {
  const score = memoryScoreText(hit, mode);
  const person = memoryPersonLine(hit);
  return (
    <article className={cn("rounded-xl border p-3", hit.kept ? "border-border" : "border-dashed border-border opacity-55")}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-secondary">
        <span className={TAG}>{memoryTag(hit.kind)}</span>
        {hit.day && <span>{hit.day}</span>}
        {score && <span className="font-mono">{score}</span>}
        {person && <span>{person}</span>}
      </div>
      <p className={cn("whitespace-pre-wrap text-sm text-ink", hit.status === "closed" && "text-ink-muted line-through")}>{hit.text}</p>
    </article>
  );
}
