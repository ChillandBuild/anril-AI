"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { companionKbApi, type KbCollection } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BTN_PRIMARY, BTN_ROW_DANGER, CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";
import { booksText, canDeleteCollection, collectionHref, collectionPagesText, readByText } from "@/components/agents/collectionRows";
import { BTN_ROW, ConfirmDialog, EmptyNote, NameDialog, errorText, useListHeading } from "@/components/agents/collectionUi";

type Dialog = { kind: "create" } | { kind: "rename"; collection: KbCollection } | { kind: "delete"; collection: KbCollection } | null;

export default function CollectionsPage() {
  const [collections, setCollections] = useState<KbCollection[] | null>(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [status, setStatus] = useState("");
  const { heading, focusHeading } = useListHeading("Collections", 2);

  const load = useCallback(() => {
    setError("");
    companionKbApi
      .listCollections()
      .then(setCollections)
      .catch((e) => setError(errorText(e, "Could not load collections.")));
  }, []);
  useEffect(load, [load]);

  const refresh = () => companionKbApi.listCollections().then(setCollections);

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      {heading}
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-ink-secondary">A collection is a group of files. A character reads one collection.</p>
        <button type="button" onClick={() => setDialog({ kind: "create" })} className={`${BTN_PRIMARY} shrink-0`} disabled={collections === null}>
          <Plus size={16} aria-hidden="true" />
          New collection
        </button>
      </div>

      <p className="sr-only" role="status">
        {status}
      </p>
      {error && <ErrorNote message={error} onRetry={collections === null ? load : undefined} />}

      {collections === null && !error ? (
        <LoadingRows />
      ) : collections && collections.length === 0 ? (
        <div className={CARD}>
          <EmptyNote
            action={
              <button type="button" className={BTN_PRIMARY} onClick={() => setDialog({ kind: "create" })}>
                New collection
              </button>
            }
          >
            No collections yet. Make one, then import files into it.
          </EmptyNote>
        </div>
      ) : collections ? (
        <section className={`${CARD} p-0`} aria-label="Your collections">
          <ul className="divide-y divide-border-subtle">
            {collections.map((c) => {
              const canDelete = canDeleteCollection(c);
              const hintId = `delete-hint-${c.id}`;
              return (
                <li key={c.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 space-y-1">
                    <Link href={collectionHref(c.id)} className="break-words font-medium text-ink hover:text-primary hover:underline">
                      {c.name}
                    </Link>
                    <p className="text-sm text-ink-secondary">
                      {booksText(c.book_count)}
                      {c.book_count > 0 ? ` · ${collectionPagesText(c)}` : ""}
                    </p>
                    <p className="break-words text-sm text-ink-secondary">Read by: {readByText(c.read_by)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 sm:justify-end">
                    <button type="button" className={BTN_ROW} onClick={() => setDialog({ kind: "rename", collection: c })} aria-label={`Rename ${c.name}`}>
                      Rename
                    </button>
                    <button
                      type="button"
                      className={cn(BTN_ROW_DANGER, !canDelete && "cursor-not-allowed opacity-50 hover:bg-white")}
                      aria-disabled={canDelete ? undefined : "true"}
                      aria-describedby={canDelete ? undefined : hintId}
                      title={canDelete ? undefined : "Delete its files first"}
                      onClick={() => {
                        if (canDelete) setDialog({ kind: "delete", collection: c });
                      }}
                      aria-label={`Delete ${c.name}`}
                    >
                      Delete
                    </button>
                    {!canDelete && (
                      <span id={hintId} className="w-full text-xs text-ink-secondary sm:text-right">
                        Delete its files first.
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {dialog?.kind === "create" && (
        <NameDialog
          title="New collection"
          intro="A collection is a group of files. A character reads one collection."
          initial=""
          submitLabel="Create"
          onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            await companionKbApi.createCollection(name);
            setDialog(null);
            setStatus(`Collection ${name} created.`);
            await refresh().catch(() => undefined);
          }}
        />
      )}
      {dialog?.kind === "rename" && (
        <NameDialog
          title="Rename collection"
          initial={dialog.collection.name}
          submitLabel="Save"
          onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            await companionKbApi.renameCollection(dialog.collection.id, name);
            setDialog(null);
            setStatus(`Renamed to ${name}.`);
            await refresh().catch(() => undefined);
          }}
        />
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title={`Delete "${dialog.collection.name}"?`}
          confirmLabel="Delete collection"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await companionKbApi.deleteCollection(dialog.collection.id);
            setDialog(null);
            setStatus(`Collection ${dialog.collection.name} deleted.`);
            await refresh().catch(() => undefined);
            focusHeading();
          }}
        >
          <p>This collection has no files in it.</p>
          <p className="font-medium text-ink">This cannot be undone.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
