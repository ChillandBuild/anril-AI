"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { companionsApi, type CompanionModel, type PlaygroundDefaults, type PlaygroundSources } from "@/lib/api";
import { useCharacters } from "@/components/agents/CharacterSelect";
import { PlaygroundAdvanced } from "@/components/agents/PlaygroundAdvanced";
import { PlaygroundChat } from "@/components/agents/PlaygroundChat";
import { FALLBACK_DEFAULTS } from "@/components/agents/playground";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

/**
 * Chat with a character exactly as website visitors will get it, with a small closed "Advanced"
 * section under it. Example: Maya on Gemini 3.1; the owner tries 3.5 for one chat, then "Use for
 * Maya" saves it. In Advanced, "Files only" makes the next test message answer from files alone.
 */
export default function PlaygroundPage() {
  const { characters, selected, select, replace, error } = useCharacters();
  const [live, setLive] = useState<PlaygroundDefaults>(FALLBACK_DEFAULTS);
  const [models, setModels] = useState<CompanionModel[]>([]);
  const [sources, setSources] = useState<PlaygroundSources>("all");

  useEffect(() => {
    companionsApi
      .models()
      .then((r) => {
        setModels(r.models);
        if (r.playground_defaults) setLive(r.playground_defaults);
      })
      .catch(() => setModels([]));   // the model chip just hides; the fallback numbers stay
  }, []);

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
        <section className={`${CARD} p-[18px]`} aria-label="Playground">
          <PlaygroundChat
            character={selected}
            characters={characters}
            onSelectCharacter={select}
            onCharacterSaved={replace}
            sources={sources}
            live={live}
            models={models}
          />
          <PlaygroundAdvanced character={selected} live={live} sources={sources} onSources={setSources} />
        </section>
      )}
    </div>
  );
}
