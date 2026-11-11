"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { companionsApi, type CompanionPerson } from "@/lib/api";
import { CharacterSelect, useCharacters } from "@/components/agents/CharacterSelect";
import { PersonMemory } from "@/components/agents/PersonMemory";
import { BTN_SECONDARY, CARD, ErrorNote, INPUT, LoadingRows, formatDate } from "@/components/agents/ui";

const PAGE = 25;

export default function MemoriesPage() {
  const { characters, selected, select, error: listError } = useCharacters();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [people, setPeople] = useState<CompanionPerson[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<CompanionPerson | null>(null);

  // Debounce typing into the search box.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(query.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(() => {
    if (!selected) return;
    setError("");
    setPeople(null);
    companionsApi
      .people(selected.id, { q: search, limit: PAGE, offset })
      .then((r) => {
        setPeople(r.people);
        setTotal(r.total);
      })
      .catch((e: Error) => setError(e.message || "Could not load people."));
  }, [selected, search, offset]);
  useEffect(load, [load]);
  useEffect(() => setOpen(null), [selected?.id]);

  if (listError) return <div className="w-full p-4 sm:p-6"><ErrorNote message={listError} /></div>;
  if (characters === null) return <div className="w-full p-4 sm:p-6"><LoadingRows /></div>;
  if (!selected) {
    return (
      <div className="w-full p-4 sm:p-6">
        <div className={`${CARD} text-sm text-ink-secondary`}>
          Make a character first on <Link href="/dashboard/agents/characters" className="text-primary underline">Characters</Link>.
        </div>
      </div>
    );
  }

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <CharacterSelect characters={characters} value={selected.id} onChange={select} />
        <label className="relative min-w-[220px] flex-1 sm:max-w-xs">
          <span className="sr-only">Search people</span>
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by user id or name" maxLength={100} className={cn(INPUT, "pl-8")} />
        </label>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <section className={cn(CARD, "p-0")} aria-label="People">
          {error ? (
            <div className="p-4"><ErrorNote message={error} onRetry={load} /></div>
          ) : people === null ? (
            <div className="p-4"><LoadingRows /></div>
          ) : people.length === 0 ? (
            <p className="p-5 text-sm text-ink-secondary">{search ? `No one matches "${search}".` : `No one has talked to ${selected.name} yet.`}</p>
          ) : (
            <>
              <ul className="divide-y divide-border-subtle">
                {people.map((p) => (
                  <li key={p.external_user_id}>
                    <button
                      type="button"
                      onClick={() => setOpen(p)}
                      aria-current={open?.external_user_id === p.external_user_id ? "true" : undefined}
                      className={cn("w-full px-4 py-3 text-left transition-colors hover:bg-surface-mid/60", open?.external_user_id === p.external_user_id && "bg-primary/5")}
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-sm font-medium text-ink">{p.display_name || p.external_user_id}</span>
                        <span className="shrink-0 text-xs text-ink-muted">{formatDate(p.last_seen_at)}</span>
                      </div>
                      <div className="text-xs text-ink-muted">
                        {p.external_user_id} · {p.fact_count === null ? "private" : `${p.fact_count} facts`} · {p.message_count} messages
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
              {total > PAGE && (
                <div className="flex items-center justify-between border-t border-border-subtle px-4 py-2 text-xs text-ink-muted">
                  <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
                  <span className="flex gap-1">
                    <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className={cn(BTN_SECONDARY, "min-h-7 px-2 text-xs")}>Previous</button>
                    <button type="button" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} className={cn(BTN_SECONDARY, "min-h-7 px-2 text-xs")}>Next</button>
                  </span>
                </div>
              )}
            </>
          )}
        </section>

        {open ? (
          <PersonMemory
            key={`${selected.id}:${open.external_user_id}`}
            characterId={selected.id}
            person={open}
            onForgotten={() => {
              setOpen(null);
              load();
            }}
          />
        ) : (
          <div className={cn(CARD, "flex items-center justify-center text-sm text-ink-muted")}>Pick a person to see what {selected.name} remembers.</div>
        )}
      </div>
    </div>
  );
}
