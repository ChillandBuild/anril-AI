"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { companionKbApi, type KbDocument, type KbPage, type KbPassage } from "@/lib/api";
import { BTN_ROW_DANGER, BTN_SECONDARY, CARD, ErrorNote, LoadingRows, formatDate } from "@/components/agents/ui";
import { docState, docStateLabel, fileSizeText, pageMethodLabel, pagesText } from "@/components/agents/knowledgeRows";
import {
  anyPageFailed,
  collectionHref,
  filterPages,
  isNotFound,
  lettersText,
  needsRetry,
  pageSpanText,
  pageStatusLabel,
  showingText,
  sourceLabel,
  tierLabel,
  tierToggle,
  type PageFilter,
} from "@/components/agents/collectionRows";
import {
  BTN_ROW,
  ConfirmDialog,
  EmptyNote,
  MainResourceBadge,
  NotFoundNote,
  StatePill,
  Tabs,
  errorText,
  usePolling,
} from "@/components/agents/collectionUi";

type BookTab = "pages" | "passages";
const BOOK_TABS: { id: BookTab; label: string }[] = [
  { id: "pages", label: "Pages" },
  { id: "passages", label: "Passages" },
];
const PASSAGE_STEP = 100;

export default function BookPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-5xl p-4 sm:p-6"><LoadingRows /></div>}>
      <BookView />
    </Suspense>
  );
}

/** What the page and passage lists depend on: they change when this does. */
const progressOf = (d: KbDocument) => `${d.status}|${d.page_count}|${d.pages_ok}|${d.pages_failed}`;

function BookView() {
  const { collectionId, documentId } = useParams<{ collectionId: string; documentId: string }>();
  const router = useRouter();
  const [doc, setDoc] = useState<KbDocument | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [tab, setTab] = useState<BookTab>("pages");
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Bumped after a retry or while reading so the open tab fetches its list again.
  const [refreshKey, setRefreshKey] = useState(0);
  const seq = useRef(0);
  // pages read / failed / status as last seen, so the lists refetch only when one of them changes.
  const progressRef = useRef<string | null>(null);

  const fetchDoc = useCallback(async () => {
    const mine = ++seq.current;
    const d = await companionKbApi.getDocument(documentId);
    if (mine === seq.current) setDoc(d);
    return d;
  }, [documentId]);

  const load = useCallback(() => {
    setError("");
    setMissing(false);
    fetchDoc()
      .then((d) => {
        progressRef.current = progressOf(d);
      })
      .catch((e) => {
        if (isNotFound(e)) setMissing(true);
        else setError(errorText(e, "Could not load this book."));
      });
  }, [fetchDoc]);
  useEffect(() => {
    setDoc(null);
    load();
  }, [load]);

  const reading = doc?.status === "processing";
  usePolling(
    async () => {
      const d = await fetchDoc();
      const now = progressOf(d);
      if (progressRef.current !== null && now !== progressRef.current) setRefreshKey((k) => k + 1);
      progressRef.current = now;
    },
    reading,
  );

  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setActionError("");
    setStatus("");
    try {
      try {
        await action();
      } catch (e) {
        setActionError(errorText(e, "That did not work. Please try again."));
        return;
      }
      // The action worked. If only the refresh fails, keep what is on screen; the next poll or a reload fixes it.
      try {
        progressRef.current = progressOf(await fetchDoc());
        setRefreshKey((k) => k + 1);
      } catch {
        // ignored on purpose
      }
      setStatus(done);
    } finally {
      setBusy(false);
    }
  };

  const backHref = collectionHref(doc?.collection_id ?? collectionId);

  if (missing) {
    return (
      <div className="mx-auto max-w-5xl p-4 sm:p-6">
        <NotFoundNote
          message="This book does not exist, or it was deleted."
          backHref={collectionHref(collectionId)}
          backLabel="Back to the collection"
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <Link href={backHref} className="inline-block text-sm text-ink-secondary hover:text-primary hover:underline">
        &lsaquo; {doc?.collection_name ?? "Collection"}
      </Link>
      {error && <ErrorNote message={error} onRetry={load} />}
      {actionError && <ErrorNote message={actionError} />}
      <p className="sr-only" role="status">
        {status}
      </p>

      {doc === null && !error ? (
        <LoadingRows rows={2} />
      ) : doc ? (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h2 className="break-words text-xl font-semibold text-ink">{doc.title}</h2>
              {doc.tier === 1 && <MainResourceBadge />}
              <StatePill state={docState(doc)} label={docStateLabel(docState(doc))} />
            </div>
            <button type="button" className={`${BTN_ROW_DANGER} shrink-0`} onClick={() => setConfirmDelete(true)} disabled={busy}>
              Delete book
            </button>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
            <section className={`${CARD} min-w-0 p-0`}>
              <Tabs label="Book" tabs={BOOK_TABS} active={tab} onChange={setTab}>
                {(id) =>
                  id === "pages" ? (
                    <PagesPanel doc={doc} refreshKey={refreshKey} busy={busy} onRetry={() => act(() => companionKbApi.retryDocument(doc.id), "Retrying the failed pages.")} />
                  ) : (
                    <PassagesPanel doc={doc} refreshKey={refreshKey} />
                  )
                }
              </Tabs>
            </section>

            <aside className={`${CARD} h-fit`} aria-labelledby="book-details">
              <h3 id="book-details" className="text-xs font-semibold uppercase tracking-wide text-ink-secondary">
                Details
              </h3>
              <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
                <Detail label="Title" value={doc.title} />
                <Detail label="Collection" value={doc.collection_name} />
                <Detail label="Type" value={doc.file_type.toUpperCase()} />
                <Detail label="Size" value={fileSizeText(doc.size_bytes)} />
                <Detail label="Role" value={tierLabel(doc.tier)} />
                <Detail label="Status" value={docStateLabel(docState(doc))} />
                <Detail label="Pages read" value={pagesText(doc)} />
                <Detail label="Source" value={sourceLabel(doc.source)} />
                <Detail label="Added" value={formatDate(doc.created_at)} />
              </dl>
              <div className="mt-4 flex flex-col gap-2">
                {needsRetry(doc) && (
                  <button type="button" className={BTN_ROW} disabled={busy} onClick={() => act(() => companionKbApi.retryDocument(doc.id), "Retrying the failed pages.")}>
                    Retry failed pages
                  </button>
                )}
                <button
                  type="button"
                  className={BTN_ROW}
                  disabled={busy}
                  onClick={() => act(() => companionKbApi.updateDocument(doc.id, { tier: tierToggle(doc.tier).next }), "Book updated.")}
                >
                  {tierToggle(doc.tier).label}
                </button>
              </div>
              {reading && <p className="mt-3 text-xs text-ink-secondary">Still reading. Pages already read can be searched now.</p>}
            </aside>
          </div>

          {confirmDelete && (
            <ConfirmDialog
              title={`Delete "${doc.title}"?`}
              confirmLabel="Delete book"
              onClose={() => setConfirmDelete(false)}
              onConfirm={async () => {
                await companionKbApi.deleteDocument(doc.id);
                router.push(collectionHref(doc.collection_id));
              }}
            >
              <p>
                {doc.page_count > 0 ? `${doc.title} and its ${doc.page_count} ${doc.page_count === 1 ? "page" : "pages"} are removed` : `${doc.title} is removed`}
                , along with the passages made from them. Characters stop answering from it.
              </p>
              <p className="font-medium text-ink">This cannot be undone.</p>
            </ConfirmDialog>
          )}
        </>
      ) : null}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{value}</dd>
    </>
  );
}

const FILTERS: { id: PageFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "failed", label: "Failed" },
  { id: "scanned", label: "Scanned" },
];

/** The page list (no text) and, for the one chosen page, its text. */
function PagesPanel({ doc, refreshKey, busy, onRetry }: { doc: KbDocument; refreshKey: number; busy: boolean; onRetry: () => void }) {
  const [pages, setPages] = useState<KbPage[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<PageFilter>("all");
  const [selected, setSelected] = useState<number | null>(null);

  const seq = useRef(0);

  // Only the newest answer is kept, so a slow older request cannot overwrite a newer list.
  const load = useCallback(() => {
    const mine = ++seq.current;
    setError("");
    companionKbApi
      .listPages(doc.id)
      .then((list) => {
        if (mine === seq.current) setPages(list);
      })
      .catch((e) => {
        if (mine === seq.current) setError(errorText(e, "Could not load the pages."));
      });
  }, [doc.id]);
  useEffect(load, [load, refreshKey]);

  if (error && pages === null) {
    return (
      <div className="p-4">
        <ErrorNote message={error} onRetry={load} />
      </div>
    );
  }
  if (pages === null) {
    return (
      <div className="p-4">
        <LoadingRows />
      </div>
    );
  }
  if (pages.length === 0) {
    return <EmptyNote>{doc.status === "processing" ? "Counting pages. They appear here as they are read." : "No pages were found in this file."}</EmptyNote>;
  }

  const shown = filterPages(pages, filter);
  const current = pages.find((p) => p.page_no === selected) ?? null;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <div role="group" aria-label="Show pages" className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${filter === f.id ? "border-primary bg-primary/10 text-primary-dark" : "border-border text-ink-secondary hover:bg-surface-mid"}`}
            >
              {f.label} {filterPages(pages, f.id).length}
            </button>
          ))}
        </div>
        {anyPageFailed(pages) && (
          <button type="button" className={`${BTN_ROW} ml-auto`} onClick={onRetry} disabled={busy}>
            Retry failed pages
          </button>
        )}
      </div>
      {error && (
        <div className="px-4 pb-3">
          <ErrorNote message={error} onRetry={load} />
        </div>
      )}
      <div className="grid gap-4 px-4 pb-4 md:grid-cols-[14rem_minmax(0,1fr)]">
        <ul aria-label="Pages" className="max-h-56 divide-y divide-border-subtle overflow-y-auto rounded-xl border border-border-subtle md:max-h-[30rem]">
          {shown.length === 0 && <li className="px-3 py-4 text-sm text-ink-secondary">No pages match.</li>}
          {shown.map((p) => (
            <li key={p.page_no}>
              <button
                type="button"
                aria-pressed={selected === p.page_no}
                onClick={() => setSelected(selected === p.page_no ? null : p.page_no)}
                className={`block w-full px-3 py-2 text-left text-sm hover:bg-surface-mid focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary ${selected === p.page_no ? "bg-primary/10" : ""}`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium text-ink">Page {p.page_no}</span>
                  <span className={p.status === "failed" ? "text-xs font-medium text-danger" : "text-xs text-ink-secondary"}>
                    {pageStatusLabel(p.status)}
                  </span>
                </span>
                <span className="block text-xs text-ink-secondary">
                  {[pageMethodLabel(p), lettersText(p)].filter(Boolean).join(" · ") || " "}
                </span>
                {p.status === "failed" && p.error && <span className="block break-words text-xs text-danger">{p.error}</span>}
              </button>
            </li>
          ))}
        </ul>
        <PageText docId={doc.id} page={current} />
      </div>
    </div>
  );
}

/** Loads one page's text when it is chosen, and again when its status changes (read, or failed). */
function PageText({ docId, page }: { docId: string; page: KbPage | null }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState("");
  const pageNo = page?.page_no ?? null;
  const pageStatus = page?.status ?? null;

  useEffect(() => {
    setText(null);
    setError("");
    if (pageNo === null || pageStatus !== "ok") return;
    let cancelled = false;
    companionKbApi
      .getPage(docId, pageNo)
      .then((p) => {
        if (!cancelled) setText(p.text ?? "");
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e, "Could not load this page."));
      });
    return () => {
      cancelled = true;
    };
  }, [docId, pageNo, pageStatus]);

  return (
    <div className="min-w-0 rounded-xl border border-border-subtle p-3">
      <p className="sr-only" role="status">
        {page && page.status === "ok" && text !== null ? `Page ${page.page_no} loaded` : ""}
      </p>
      {page === null ? (
        <p className="text-sm text-ink-secondary">Choose a page to see what was read from it.</p>
      ) : (
        <>
          <h3 className="text-sm font-semibold text-ink">Page {page.page_no}</h3>
          {page.status === "pending" && <p className="mt-2 text-sm text-ink-secondary">This page has not been read yet.</p>}
          {page.status === "failed" && (
            <p role="alert" className="mt-2 break-words text-sm text-danger">
              {page.error || "This page could not be read. Press Retry failed pages to try again."}
            </p>
          )}
          {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
          {page.status === "ok" && text === null && !error && <p className="mt-2 text-sm text-ink-secondary">Loading the text…</p>}
          {page.status === "ok" && text !== null && (
            <div
              tabIndex={0}
              role="region"
              aria-label={`Text read from page ${page.page_no}`}
              className="mt-2 max-h-[26rem] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-mid p-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            >
              {text || "No text was found on this page."}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The pieces search looks through. Cut to 100 at a time so a big book stays quick. */
function PassagesPanel({ doc, refreshKey }: { doc: KbDocument; refreshKey: number }) {
  const [rows, setRows] = useState<KbPassage[] | null>(null);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState(PASSAGE_STEP);

  const seq = useRef(0);

  // Only the newest answer is kept, so a slow older request cannot overwrite a newer list.
  const load = useCallback(() => {
    const mine = ++seq.current;
    setError("");
    companionKbApi
      .listPassages(doc.id)
      .then((list) => {
        if (mine === seq.current) setRows(list);
      })
      .catch((e) => {
        if (mine === seq.current) setError(errorText(e, "Could not load the passages."));
      });
  }, [doc.id]);
  useEffect(load, [load, refreshKey]);

  if (error && rows === null) {
    return (
      <div className="p-4">
        <ErrorNote message={error} onRetry={load} />
      </div>
    );
  }
  if (rows === null) {
    return (
      <div className="p-4">
        <LoadingRows />
      </div>
    );
  }
  if (rows.length === 0) {
    return <EmptyNote>{doc.status === "processing" ? "Passages appear here as pages are read." : "No passages were made from this book."}</EmptyNote>;
  }

  const more = showingText(Math.min(limit, rows.length), rows.length);
  return (
    <div>
      <p className="px-4 py-3 text-sm text-ink-secondary">These are the pieces search looks through. Each keeps its heading and page numbers.</p>
      <ol className="divide-y divide-border-subtle border-t border-border-subtle">
        {rows.slice(0, limit).map((p) => (
          <li key={p.id} className="space-y-1 px-4 py-3">
            <p className="text-sm font-medium text-ink">
              <span className="text-ink-secondary">{p.seq}.</span> {p.heading_path || "No heading"}{" "}
              <span className="whitespace-nowrap text-xs font-normal text-ink-secondary">{pageSpanText(p.page_from, p.page_to)}</span>
            </p>
            <div tabIndex={0} role="region" aria-label={`Passage ${p.seq} text`} className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-sm text-ink-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
              {p.text}
            </div>
          </li>
        ))}
      </ol>
      {more && (
        <div className="flex items-center justify-between gap-3 border-t border-border-subtle px-4 py-3">
          <span className="text-sm text-ink-secondary">{more}</span>
          <button type="button" className={BTN_SECONDARY} onClick={() => setLimit((l) => l + PASSAGE_STEP)}>
            Show {PASSAGE_STEP} more
          </button>
        </div>
      )}
    </div>
  );
}
