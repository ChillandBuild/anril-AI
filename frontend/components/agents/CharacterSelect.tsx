"use client";
import { useEffect, useId, useState } from "react";
import { companionsApi, type Companion } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";

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

  /** Swap in a character the server just returned, e.g. after the Playground saved its model. */
  const replace = (updated: Companion) =>
    setCharacters((list) => (list ? list.map((c) => (c.id === updated.id ? updated : c)) : list));

  const selected = characters?.find((c) => c.id === selectedId) ?? null;
  return { characters, selected, select, replace, error };
}

export function CharacterSelect({
  characters,
  value,
  onChange,
  className,
  inline = false,
}: {
  characters: Companion[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
  /** Plain teal text with no border, for a picker row under an input box (Playground). */
  inline?: boolean;
}) {
  const labelId = useId();
  const options = characters.map((c) => ({ value: c.id, label: `${c.name}${c.status !== "live" ? ` (${c.status})` : ""}` }));
  if (inline) {
    return (
      <div className={cn("flex items-center gap-1.5 text-sm text-ink-secondary", className)}>
        <Select
          size="sm"
          aria-label="Character"
          className="h-7 w-auto max-w-[220px] border-transparent bg-transparent px-1.5 font-semibold text-primary hover:border-transparent hover:bg-surface-mid"
          value={value}
          onChange={onChange}
          options={options}
        />
      </div>
    );
  }
  return (
    <div className={cn("flex items-center gap-2 text-sm text-ink-secondary", className)}>
      <span id={labelId} className="shrink-0">
        Character
      </span>
      <Select size="sm" aria-labelledby={labelId} className="w-auto min-w-[180px]" value={value} onChange={onChange} options={options} />
    </div>
  );
}
