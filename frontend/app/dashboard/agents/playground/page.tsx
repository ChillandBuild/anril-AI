"use client";
import { useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { CharacterSelect, useCharacters } from "@/components/agents/CharacterSelect";
import { PlaygroundChat } from "@/components/agents/PlaygroundChat";
import { PlaygroundSearch } from "@/components/agents/PlaygroundSearch";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

export default function PlaygroundPage() {
  const { characters, selected, select, error } = useCharacters();
  const [tab, setTab] = useState<"chat" | "search">("chat");

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      {error ? (
        <ErrorNote message={error} />
      ) : characters === null ? (
        <LoadingRows />
      ) : characters.length === 0 || !selected ? (
        <div className={`${CARD} text-sm text-ink-secondary`}>
          Make a character first on <Link href="/dashboard/agents/characters" className="text-primary underline">Characters</Link>.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CharacterSelect characters={characters} value={selected.id} onChange={select} />
            <div role="tablist" aria-label="Playground mode" className="flex gap-1 rounded-xl bg-surface-mid p-1">
              {(["chat", "search"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "rounded-lg px-3 py-1 text-sm font-medium capitalize",
                    tab === t ? "bg-white text-ink shadow-sm" : "text-ink-secondary hover:text-ink",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          {/* Both stay mounted so switching tabs keeps the chat history. */}
          <div hidden={tab !== "chat"}>
            <PlaygroundChat character={selected} />
          </div>
          <div hidden={tab !== "search"}>
            <PlaygroundSearch key={selected.id} character={selected} />
          </div>
        </>
      )}
    </div>
  );
}
