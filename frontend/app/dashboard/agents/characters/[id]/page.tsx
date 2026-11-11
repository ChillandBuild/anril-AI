"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { companionsApi, type ApiError, type Companion } from "@/lib/api";
import { CharacterEditor } from "@/components/agents/CharacterEditor";
import { ErrorNote, LoadingRows } from "@/components/agents/ui";

export default function CharacterPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const [character, setCharacter] = useState<Companion | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    companionsApi
      .get(id)
      .then(setCharacter)
      .catch((e: ApiError) => setError(e.status === 404 ? "This character doesn't exist or was removed." : e.message || "Could not load the character."));
  }, [id]);
  useEffect(load, [load]);

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <Link href="/dashboard/agents/characters" className="inline-flex items-center gap-1 text-sm text-ink-secondary hover:text-primary">
        <ArrowLeft size={14} aria-hidden="true" /> All characters
      </Link>
      {error ? <ErrorNote message={error} onRetry={load} /> : character ? <CharacterEditor key={character.id} initial={character} /> : <LoadingRows rows={4} />}
    </div>
  );
}
