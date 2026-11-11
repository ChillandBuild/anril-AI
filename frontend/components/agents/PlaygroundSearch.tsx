"use client";
import { useState } from "react";
import { FileText, PenLine, User } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  companionsApi,
  type ApiError,
  type Companion,
  type CompanionKnowledgeHit,
  type CompanionMemoryHit,
  type CompanionSearchResult,
  type PlaygroundDefaults,
} from "@/lib/api";
import {
  NOTICE_KNOWLEDGE_ERROR,
  NOTICE_NOTHING,
  SEARCH_KEYS,
  buildSearchView,
  changedSettings,
  documentLine,
  judgePill,
  meaningText,
  resultCountText,
  memoryPersonLine,
  memoryScoreText,
  memoryTag,
  settingsToSend,
  type ResultDisplay,
} from "@/components/agents/playground";
import { CharacterSelect } from "@/components/agents/CharacterSelect";
import { Hero, PromptBox } from "@/components/agents/PlaygroundParts";

const PERSON_HINT =
  "Add a person's user id to search their memories by meaning; without one, facts are matched word by word across everyone.";

/**
 * See what a character would find. Example: Maya, "Can I return my shoes?" -> a grey
 * "Searched for: return policy for used shoes", 2 passages from "Returns policy.pdf"
 * ("judge 3/3 · kept") and Karthik's memory "Bought running shoes" ("meaning 0.83").
 */
export function PlaygroundSearch({
  character,
  characters,
  onSelectCharacter,
  settings,
  live,
  display,
}: {
  character: Companion;
  characters: Companion[];
  onSelectCharacter: (id: string) => void;
  settings: PlaygroundDefaults;
  live: PlaygroundDefaults;
  display: ResultDisplay;
}) {
  const [q, setQ] = useState("");
  const [person, setPerson] = useState("");
  const [result, setResult] = useState<CompanionSearchResult | null>(null);
  const [ranWith, setRanWith] = useState<PlaygroundDefaults | null>(null);   // the settings that made `result`
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    const query = q.trim();
    if (!query || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await companionsApi.search(character.id, {
        in: settings.sources,
        q: query,
        limit: settings.results,
        ...(settings.sources !== "knowledge" && person.trim() ? { external_user_id: person.trim() } : {}),
        settings: settingsToSend(settings, live, SEARCH_KEYS),
      });
      setResult(res);
      setRanWith(settings);
    } catch (err) {
      setResult(null);
      setError((err as ApiError).message || "Search failed.");
    } finally {
      setBusy(false);
    }
  };

  // The hidden-memories line names the strictness the search ran with, not the stepper's value now.
  const view = result
    ? buildSearchView(result, { showDropped: display.showDropped, strictness: (ranWith ?? settings).memory_floor })
    : null;
  const stale = !!ranWith && changedSettings(settings, ranWith).some((k) => SEARCH_KEYS.includes(k));

  return (
    <div>
      {!result && !error && <Hero title={`Search across what ${character.name} knows`} />}
      <div className={cn(result || error ? "mt-4" : "")}>
        <PromptBox
          id="playground-search"
          label="Search text"
          value={q}
          onChange={setQ}
          onSubmit={() => void run()}
          maxLength={500}
          placeholder={`Search what ${character.name} knows…`}
          sendDisabled={busy || !q.trim()}
          pickers={
            <>
              <CharacterSelect characters={characters} value={character.id} onChange={onSelectCharacter} inline />
              <label className="inline-flex items-center gap-1.5 text-ink-secondary">
                <User size={14} aria-hidden="true" />
                <span className="sr-only">User id (optional)</span>
                <input
                  value={person}
                  onChange={(e) => setPerson(e.target.value)}
                  maxLength={200}
                  placeholder="User id (optional)"
                  className="w-40 rounded-md bg-transparent py-0.5 font-medium text-primary placeholder:font-normal placeholder:text-ink-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                />
              </label>
            </>
          }
        />
      </div>

      {!person.trim() && settings.sources !== "knowledge" && (
        <p className="mx-auto mt-3 max-w-[720px] text-center text-[13px] text-ink-secondary">{PERSON_HINT}</p>
      )}
      {!result && !error && (
        <p className="mx-auto mt-3 max-w-[720px] text-center text-[13px] text-ink-secondary">
          Meaning + word search over {character.name}&apos;s files and what people told it.
        </p>
      )}

      {busy && <p className="mx-auto mt-4 max-w-[720px] text-sm text-ink-muted">Searching…</p>}
      {error && (
        <p role="alert" className="mx-auto mt-4 max-w-[720px] text-sm text-danger">
          {error}
        </p>
      )}

      {/* The one live region: a short count, announced after each search. */}
      <p aria-live="polite" className={cn("mx-auto max-w-[720px] text-xs text-ink-muted", view && "mt-4")}>
        {view ? resultCountText(view) : ""}
      </p>
      {result && view && (
        <div className="mx-auto mt-2 flex max-w-[720px] flex-col gap-2.5">
          {stale && <p className="text-xs text-ink-muted">Settings changed since this search. Search again to apply them.</p>}
          {result.rewritten && <RewriteBox rewritten={result.rewritten} />}
          {view.knowledgeError && <p className="text-center text-[13px] text-ink-secondary">{NOTICE_KNOWLEDGE_ERROR}</p>}
          {view.knowledge.map((hit, i) => (
            <KnowledgeRow key={`k${i}`} hit={hit} showDocs={display.showDocs} />
          ))}
          {view.memories.map((hit, i) => (
            <MemoryRow key={`m${i}`} hit={hit} mode={result.memory_mode} />
          ))}
          {view.hiddenLine && <p className="text-center text-[13px] text-ink-secondary">{view.hiddenLine}</p>}
          {view.notices.map((n) => (
            <p key={n} className="text-center text-[13px] text-ink-secondary">
              {n}
            </p>
          ))}
          {view.nothingPassed && (
            <p className="text-center text-[13px] text-ink-secondary">{NOTICE_NOTHING}</p>
          )}
        </div>
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

function KnowledgeRow({ hit, showDocs }: { hit: CompanionKnowledgeHit; showDocs: boolean }) {
  const pill = judgePill(hit.score, hit.kept);
  const meaning = meaningText(hit.meaning);
  return (
    <article className={cn("rounded-xl border p-3", hit.kept ? "border-border" : "border-dashed border-border opacity-55")}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-secondary">
        <span className={TAG}>Knowledge</span>
        {showDocs && (
          <span className="inline-flex items-center gap-1">
            <FileText size={13} aria-hidden="true" /> {documentLine(hit)}
          </span>
        )}
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
