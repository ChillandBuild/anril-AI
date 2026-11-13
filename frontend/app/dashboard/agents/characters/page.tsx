"use client";
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Archive, Plus, RotateCcw, Trash2, UserRound } from "lucide-react";
import { companionsApi, type Companion } from "@/lib/api";
import { LANGUAGE_LABEL, nextDraftName } from "@/components/agents/characterForm";
import { CharacterDeleteDialog, type DeleteChoice } from "@/components/agents/CharacterDeleteDialog";
import { Tabs } from "@/components/agents/collectionUi";
import { BTN_PRIMARY, BTN_ROW_DANGER, BTN_SECONDARY, CARD, ErrorNote, LoadingRows, StatusPill } from "@/components/agents/ui";

type View = "active" | "archived";
const VIEWS: { id: View; label: string }[] = [
  { id: "active", label: "Active" },
  { id: "archived", label: "Archived" },
];

export default function CharactersPage() {
  // useSearchParams needs a Suspense boundary so the page can still be built ahead of time.
  return (
    <Suspense fallback={<div className="w-full p-4 sm:p-6"><LoadingRows /></div>}>
      <Characters />
    </Suspense>
  );
}

/**
 * Active | Archived. Example: the trash icon on Jothidar AI opens the Delete popup. Archive moves it to
 * the Archived tab, where Restore brings it back as Draft and "Delete permanently" erases it.
 */
function Characters() {
  const router = useRouter();
  const params = useSearchParams();
  const [view, setView] = useState<View>(params.get("tab") === "archived" ? "archived" : "active");
  const [characters, setCharacters] = useState<Companion[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [target, setTarget] = useState<Companion | null>(null);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    setError("");
    setCharacters(null);
    companionsApi
      .list(view === "archived")
      .then(setCharacters)
      .catch((e: Error) => setError(e.message || "Could not load characters."));
  }, [view]);
  useEffect(load, [load]);

  const switchView = (next: View) => {
    setView(next);
    setNotice("");
    router.replace(next === "archived" ? "/dashboard/agents/characters?tab=archived" : "/dashboard/agents/characters", { scroll: false });
  };

  const create = async () => {
    setCreating(true);
    setError("");
    try {
      // Names stay unique across archived ones too, so count every name the business has.
      const archived = view === "archived" ? characters ?? [] : await companionsApi.list(true).catch(() => []);
      const active = view === "active" ? characters ?? [] : await companionsApi.list().catch(() => []);
      const made = await companionsApi.create({ name: nextDraftName([...active, ...archived].map((c) => c.name)), status: "draft" });
      router.push(`/dashboard/agents/characters/${made.id}`);
    } catch (e) {
      setError((e as Error).message || "Could not create a character.");
      setCreating(false);
    }
  };

  const restore = async (c: Companion) => {
    setRestoring(c.id);
    setError("");
    try {
      await companionsApi.restore(c.id);
      setCharacters((list) => (list ?? []).filter((x) => x.id !== c.id));
      setNotice(`${c.name} is back as Draft in Active.`);
    } catch (e) {
      setError((e as Error).message || "Could not restore this character.");
    } finally {
      setRestoring(null);
    }
  };

  const done = (c: Companion, choice: DeleteChoice) => {
    setTarget(null);
    setCharacters((list) => (list ?? []).filter((x) => x.id !== c.id));
    setNotice(choice === "archive" ? `${c.name} is archived. Find it in the Archived tab.` : `${c.name} is deleted permanently.`);
  };

  const archivedView = view === "archived";

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <div className="flex items-center justify-end">
        <button type="button" onClick={create} disabled={creating || characters === null} className={BTN_PRIMARY}>
          <Plus size={16} aria-hidden="true" />
          {creating ? "Creating…" : "New character"}
        </button>
      </div>

      <section className={`${CARD} p-0`}>
        <Tabs label="Characters" tabs={VIEWS} active={view} onChange={switchView}>
          {() => (
            <div className="space-y-3 p-4">
              {notice && (
                <p role="status" className="text-sm text-ink-secondary">
                  {notice}
                </p>
              )}
              {error && <ErrorNote message={error} onRetry={characters === null ? load : undefined} />}

              {characters === null && !error ? (
                <LoadingRows />
              ) : characters && characters.length === 0 ? (
                <div className="py-10 text-center" role="status">
                  {archivedView ? (
                    <>
                      <Archive className="mx-auto text-ink-muted" size={28} aria-hidden="true" />
                      <h2 className="mt-2 text-sm font-semibold text-ink">No archived characters</h2>
                      <p className="mt-1 text-sm text-ink-secondary">Characters you archive land here. You can restore them or delete them for good.</p>
                    </>
                  ) : (
                    <>
                      <UserRound className="mx-auto text-ink-muted" size={28} aria-hidden="true" />
                      <h2 className="mt-2 text-sm font-semibold text-ink">No characters yet</h2>
                      <p className="mt-1 text-sm text-ink-secondary">A character is the AI person your customers chat with, like Maya, your support assistant.</p>
                    </>
                  )}
                </div>
              ) : characters ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead className="border-b border-border-subtle text-xs uppercase tracking-wide text-ink-muted">
                      <tr>
                        <th scope="col" className="px-3 py-3 font-medium">Name</th>
                        <th scope="col" className="px-3 py-3 font-medium">{archivedView ? "Archived" : "Status"}</th>
                        <th scope="col" className="px-3 py-3 font-medium">Language</th>
                        <th scope="col" className="px-3 py-3 font-medium">Memory</th>
                        <th scope="col" className="px-3 py-3 font-medium"><span className="sr-only">Actions</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {characters.map((c) => (
                        <tr key={c.id} className="border-b border-border-subtle last:border-0 hover:bg-surface-mid/60">
                          <td className="px-3 py-3">
                            <Link href={`/dashboard/agents/characters/${c.id}`} className="font-medium text-ink hover:text-primary hover:underline">
                              {c.name}
                            </Link>
                            {c.role && <div className="max-w-[320px] truncate text-xs text-ink-muted">{c.role}</div>}
                          </td>
                          <td className="px-3 py-3">
                            {archivedView ? (
                              <span className="text-ink-secondary">{c.archived_at ? new Date(c.archived_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—"}</span>
                            ) : (
                              <StatusPill status={c.status} />
                            )}
                          </td>
                          <td className="px-3 py-3 text-ink-secondary">{LANGUAGE_LABEL[c.language] ?? c.language}</td>
                          <td className="px-3 py-3 text-ink-secondary">Level {c.memory_level}</td>
                          <td className="px-3 py-3 text-right">
                            {archivedView ? (
                              <div className="flex justify-end gap-2">
                                <button type="button" onClick={() => restore(c)} disabled={restoring === c.id} className={BTN_SECONDARY}>
                                  <RotateCcw size={14} aria-hidden="true" />
                                  {restoring === c.id ? "Restoring…" : "Restore"}
                                </button>
                                <button type="button" onClick={() => setTarget(c)} className={BTN_ROW_DANGER}>
                                  Delete permanently
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setTarget(c)}
                                aria-label={`Delete ${c.name}`}
                                title="Delete"
                                className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-danger/10 hover:text-danger focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                              >
                                <Trash2 size={16} aria-hidden="true" />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
          )}
        </Tabs>
      </section>

      {target && (
        <CharacterDeleteDialog
          character={target}
          only={archivedView ? "delete" : undefined}
          onClose={() => setTarget(null)}
          onDone={(choice) => done(target, choice)}
        />
      )}
    </div>
  );
}
