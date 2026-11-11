"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { companionKbApi, type KbCollection, type KbDocument } from "@/lib/api";
import { ImportCard } from "@/components/agents/ImportCard";
import { anyReading, docState, docStateLabel, failedPagesText, pagesText } from "@/components/agents/knowledgeRows";
import { CARD, ErrorNote, LoadingRows, formatDate } from "@/components/agents/ui";
import { usePolling } from "@/components/agents/collectionUi";
import { bookHref, processingBooks, recentBooks } from "@/components/agents/uploadQueue";

export default function AgentsUploadPage() {
  // useSearchParams needs a Suspense boundary so the page can still be built ahead of time.
  return (
    <Suspense fallback={<div className="w-full p-4 sm:p-6"><LoadingRows rows={4} /></div>}>
      <UploadPage />
    </Suspense>
  );
}

function UploadPage() {
  const preselect = useSearchParams().get("collection");
  const [collections, setCollections] = useState<KbCollection[] | null>(null);
  const [collectionsError, setCollectionsError] = useState("");
  const [docs, setDocs] = useState<KbDocument[] | null>(null);
  const [docsError, setDocsError] = useState("");
  const alive = useRef(true);
  const docsSeq = useRef(0);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const loadCollections = useCallback(() => {
    setCollectionsError("");
    companionKbApi
      .listCollections()
      .then((c) => alive.current && setCollections(c))
      .catch((e: Error) => alive.current && setCollectionsError(e.message || "Could not load your collections."));
  }, []);

  // Only the newest answer is kept, so a slow older request cannot overwrite a newer list.
  const fetchDocs = useCallback(async () => {
    const mine = ++docsSeq.current;
    const list = await companionKbApi.listDocuments();
    if (alive.current && mine === docsSeq.current) setDocs(list);
  }, []);

  /** quiet = refresh in the background: keep the list on screen and ignore a failed refresh. */
  const loadDocs = useCallback(
    (quiet = false) => {
      if (!quiet) setDocsError("");
      fetchDocs().catch((e: Error) => {
        if (alive.current && !quiet) setDocsError(e.message || "Could not load your files.");
      });
    },
    [fetchDocs],
  );

  useEffect(() => {
    loadCollections();
    loadDocs();
  }, [loadCollections, loadDocs]);

  // Poll while any file is being read. Driven by the fetched list, so it also works after a reload.
  const reading = docs ? anyReading(docs) : false;
  usePolling(fetchDocs, reading);

  const onChanged = useCallback(() => {
    loadDocs(true);
    // File counts in the collection list change too.
    companionKbApi
      .listCollections()
      .then((c) => alive.current && setCollections(c))
      .catch(() => undefined);
  }, [loadDocs]);

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <ImportCard
          collections={collections}
          collectionsError={collectionsError}
          onRetryCollections={loadCollections}
          initialCollectionId={preselect}
          onCollectionCreated={(c) => setCollections((prev) => (prev ? [...prev, c] : [c]))}
          onChanged={onChanged}
        />
        <ProcessingList docs={docs} error={docsError} onRetry={() => loadDocs()} />
      </div>
      <RecentList docs={docs} error={docsError} onRetry={() => loadDocs()} />
    </div>
  );
}

function ProcessingList({ docs, error, onRetry }: { docs: KbDocument[] | null; error: string; onRetry: () => void }) {
  const rows = docs ? processingBooks(docs) : [];
  return (
    <section className={CARD} aria-labelledby="processing-title">
      <h2 id="processing-title" className="mb-3 text-sm font-semibold text-ink">
        Processing
      </h2>
      <p className="sr-only" role="status">
        {docs && !error ? (rows.length > 0 ? `${rows.length} ${rows.length === 1 ? "file" : "files"} being read` : "No files being read") : ""}
      </p>
      {error ? (
        <ErrorNote message={error} onRetry={onRetry} />
      ) : docs === null ? (
        <LoadingRows rows={2} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-ink-secondary">Nothing is being read right now. Drop a file on the left to start.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((d) => {
            const pct = d.page_count > 0 ? Math.round((100 * (d.pages_ok + d.pages_failed)) / d.page_count) : 0;
            return (
              <li key={d.id} className="text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <Link href={bookHref(d)} className="min-w-0 truncate font-medium text-ink underline-offset-2 hover:underline">
                    {d.title}
                  </Link>
                  <span className="text-xs text-ink-secondary">{d.collection_name}</span>
                </div>
                <p className="text-ink-secondary">{pagesText(d)}</p>
                <div
                  role="progressbar"
                  aria-label={`Reading ${d.title}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={pct}
                  className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-mid"
                >
                  <div className="h-full bg-primary transition-[width]" style={{ width: `${pct}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function RecentList({ docs, error, onRetry }: { docs: KbDocument[] | null; error: string; onRetry: () => void }) {
  const rows = docs ? recentBooks(docs) : [];
  return (
    <section className={`${CARD} p-0`} aria-labelledby="recent-title">
      <div className="flex items-center justify-between gap-3 px-5 pb-2 pt-4">
        <h2 id="recent-title" className="text-sm font-semibold text-ink">
          Recently added
        </h2>
        <Link href="/dashboard/agents/collections" className="text-sm font-medium text-primary underline-offset-2 hover:underline">
          See all collections
        </Link>
      </div>
      <div className="px-5 pb-5">
        {error ? (
          <ErrorNote message={error} onRetry={onRetry} />
        ) : docs === null ? (
          <LoadingRows rows={3} />
        ) : rows.length === 0 ? (
          <p className="text-sm text-ink-secondary">No files yet. Drop a file above, pick a collection and press Import.</p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {rows.map((d) => {
              const state = docState(d);
              const gaps = failedPagesText(d.failed_pages);
              const note = state === "gaps" || state === "failed" ? [gaps, d.error].filter(Boolean).join(". ") : "";
              return (
                <li key={d.id}>
                  <Link href={bookHref(d)} className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-3 hover:bg-surface-mid focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">{d.title}</span>
                      <span className="block truncate text-xs text-ink-secondary">
                        {d.collection_name}, added {formatDate(d.created_at)}
                      </span>
                      <span className="block text-xs text-ink-secondary">{pagesText(d)}</span>
                      {note && <span className={state === "failed" ? "block text-xs text-danger" : "block text-xs text-amber-700"}>{note}</span>}
                    </span>
                    <span
                      className={
                        state === "failed"
                          ? "shrink-0 rounded-full bg-danger/10 px-2 py-0.5 text-xs font-medium text-danger"
                          : state === "gaps"
                            ? "shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700"
                            : state === "ready"
                              ? "shrink-0 rounded-full bg-success/10 px-2 py-0.5 text-xs font-medium text-success"
                              : "shrink-0 rounded-full bg-surface-mid px-2 py-0.5 text-xs font-medium text-ink-secondary"
                      }
                    >
                      {docStateLabel(state)}
                    </span>
                    <ChevronRight size={16} className="shrink-0 text-ink-muted" aria-hidden="true" />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
