"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, UserRound } from "lucide-react";
import { companionsApi, type Companion } from "@/lib/api";
import { LANGUAGE_LABEL, nextDraftName } from "@/components/agents/characterForm";
import { BTN_PRIMARY, CARD, ErrorNote, LoadingRows, StatusPill } from "@/components/agents/ui";

export default function CharactersPage() {
  const router = useRouter();
  const [characters, setCharacters] = useState<Companion[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setError("");
    companionsApi
      .list()
      .then(setCharacters)
      .catch((e: Error) => setError(e.message || "Could not load characters."));
  }, []);
  useEffect(load, [load]);

  const create = async () => {
    setCreating(true);
    setError("");
    try {
      const made = await companionsApi.create({ name: nextDraftName((characters ?? []).map((c) => c.name)), status: "draft" });
      router.push(`/dashboard/agents/characters/${made.id}`);
    } catch (e) {
      setError((e as Error).message || "Could not create a character.");
      setCreating(false);
    }
  };

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <div className="flex items-center justify-end">
        <button type="button" onClick={create} disabled={creating || characters === null} className={BTN_PRIMARY}>
          <Plus size={16} aria-hidden="true" />
          {creating ? "Creating…" : "New character"}
        </button>
      </div>

      {error && <ErrorNote message={error} onRetry={characters === null ? load : undefined} />}

      {characters === null && !error ? (
        <LoadingRows />
      ) : characters && characters.length === 0 ? (
        <div className={`${CARD} py-12 text-center`} role="status">
          <UserRound className="mx-auto text-ink-muted" size={28} aria-hidden="true" />
          <h2 className="mt-2 text-sm font-semibold text-ink">No characters yet</h2>
          <p className="mt-1 text-sm text-ink-secondary">A character is the AI person your customers chat with, like Maya, your support assistant.</p>
        </div>
      ) : characters ? (
        <div className={`${CARD} overflow-x-auto p-0`}>
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead className="border-b border-border-subtle text-xs uppercase tracking-wide text-ink-muted">
              <tr>
                <th scope="col" className="px-5 py-3 font-medium">Name</th>
                <th scope="col" className="px-5 py-3 font-medium">Status</th>
                <th scope="col" className="px-5 py-3 font-medium">Language</th>
                <th scope="col" className="px-5 py-3 font-medium">Memory</th>
              </tr>
            </thead>
            <tbody>
              {characters.map((c) => (
                <tr key={c.id} className="border-b border-border-subtle last:border-0 hover:bg-surface-mid/60">
                  <td className="px-5 py-3">
                    <Link href={`/dashboard/agents/characters/${c.id}`} className="font-medium text-ink hover:text-primary hover:underline">
                      {c.name}
                    </Link>
                    {c.role && <div className="max-w-[320px] truncate text-xs text-ink-muted">{c.role}</div>}
                  </td>
                  <td className="px-5 py-3"><StatusPill status={c.status} /></td>
                  <td className="px-5 py-3 text-ink-secondary">{LANGUAGE_LABEL[c.language] ?? c.language}</td>
                  <td className="px-5 py-3 text-ink-secondary">Level {c.memory_level}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
