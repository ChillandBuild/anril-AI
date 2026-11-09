"use client";
import { useEffect, useState } from "react";
import { companionsApi, type Companion } from "@/lib/api";
import { cn } from "@/lib/utils";
import { INPUT } from "@/components/agents/ui";

const STORE_KEY = "anril.agents.character";

function readStored(): string | null {
  try {
    return window.sessionStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
}

/**
 * The characters list plus the one picked, shared by Install, Playground and
 * Memories so switching pages keeps the same character (sessionStorage).
 * Default: the last one picked, else the first Live one, else the first.
 */
export function useCharacters() {
  const [characters, setCharacters] = useState<Companion[] | null>(null);
  const [selectedId, setSelectedId] = useState<string>("");
  const [error, setError] = useState("");

  useEffect(() => {
    companionsApi
      .list()
      .then((list) => {
        setCharacters(list);
        const stored = readStored();
        const pick = list.find((c) => c.id === stored) ?? list.find((c) => c.status === "live") ?? list[0];
        setSelectedId(pick?.id ?? "");
      })
      .catch((e: Error) => setError(e.message || "Could not load characters."));
  }, []);

  const select = (id: string) => {
    setSelectedId(id);
    try {
      window.sessionStorage.setItem(STORE_KEY, id);
    } catch {
      /* private mode: just don't remember */
    }
  };

  const selected = characters?.find((c) => c.id === selectedId) ?? null;
  return { characters, selected, select, error };
}

export function CharacterSelect({
  characters,
  value,
  onChange,
  className,
}: {
  characters: Companion[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <label className={cn("flex items-center gap-2 text-sm text-ink-secondary", className)}>
      <span className="shrink-0">Character</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cn(INPUT, "w-auto min-w-[180px] py-1.5")}>
        {characters.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
            {c.status !== "live" ? ` (${c.status})` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
