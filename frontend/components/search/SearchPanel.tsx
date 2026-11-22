"use client";
import { cn } from "@/lib/utils";
import { FOOTER_TEXT, canSearch, highlightParts, type SearchRow } from "./searchLogic";
import type { SearchState } from "./useSearchResults";

export function Highlight({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlightParts(text, query).map((part, i) =>
        part.match ? (
          <mark key={i} className="rounded-sm bg-primary-light px-0.5 font-bold text-primary">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

export function optionId(listId: string, index: number) {
  return `${listId}-opt-${index}`;
}

interface Props {
  listId: string;
  query: string;
  state: SearchState;
  rows: SearchRow[];
  activeIndex: number;
  onActive: (index: number) => void;
  onPick: (row: SearchRow) => void;
}

/** The answers: grouped rows, or the empty / waiting / error line. Shared by the dropdown and the phone sheet. */
export function SearchPanel({ listId, query, state, rows, activeIndex, onActive, onPick }: Props) {
  const q = query.trim();
  const note = (text: string) => <p className="px-4 py-6 text-center text-[14px] text-ink-muted">{text}</p>;
  // The answer on screen is for an older query, or a newer one is on its way.
  const stale = state.status === "loading" || state.forQuery !== q;
  let body;
  if (!canSearch(q)) {
    body = note("Type at least 2 letters or digits.");
  } else if (state.status === "error" && state.forQuery === q) {
    body = note("Search isn't working right now. Try again in a moment.");
  } else if (state.status === "idle" || (stale && state.sections.length === 0)) {
    body = note("Searching…");
  } else if (state.sections.length === 0) {
    body = note(`No matches for "${q}"`);
  } else {
    let index = -1;
    body = (
      <div id={listId} role="listbox" aria-label="Search results" aria-busy={stale} className={cn(stale && "opacity-60")}>
        {state.sections.map((section) => (
          <div key={section.key} role="group" aria-label={section.heading}>
            <p className="px-4 pb-1 pt-3 text-[12px] font-bold tracking-[0.08em] text-ink-muted">{section.heading}</p>
            {section.rows.map((row) => {
              index += 1;
              const i = index;
              const active = i === activeIndex;
              return (
                <div
                  key={row.id}
                  id={optionId(listId, i)}
                  role="option"
                  aria-selected={active}
                  onMouseEnter={() => onActive(i)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => onPick(row)}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center gap-3 px-4 py-2",
                    active ? "bg-primary-light" : "hover:bg-[#f1f5f9]",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[14px] font-semibold text-ink"><Highlight text={row.title} query={q} /></p>
                    {row.subtitle && (
                      <p className="truncate text-[12px] text-ink-muted"><Highlight text={row.subtitle} query={q} /></p>
                    )}
                    {row.meta && <p className="truncate text-[12px] text-ink-muted">{row.meta}</p>}
                  </div>
                  <span className="shrink-0 text-[12px] font-semibold text-primary">Open ›</span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    );
  }
  return (
    <>
      {body}
      <span className="sr-only" aria-live="polite">{canSearch(q) && !stale ? `${rows.length} results` : ""}</span>
      <p className="border-t border-[#e2e8f0] px-4 py-3 text-[12px] leading-snug text-ink-muted">{FOOTER_TEXT}</p>
    </>
  );
}
