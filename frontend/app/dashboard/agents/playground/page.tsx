"use client";
import Link from "next/link";
import { CharacterSelect, useCharacters } from "@/components/agents/CharacterSelect";
import { PlaygroundChat } from "@/components/agents/PlaygroundChat";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

export default function PlaygroundPage() {
  const { characters, selected, select, error } = useCharacters();

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
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
          <CharacterSelect characters={characters} value={selected.id} onChange={select} />
          <PlaygroundChat character={selected} />
        </>
      )}
    </div>
  );
}
