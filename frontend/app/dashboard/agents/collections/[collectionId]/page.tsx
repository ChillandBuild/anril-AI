"use client";
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { companionKbApi, type KbCollection } from "@/lib/api";
import { BTN_PRIMARY, CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";
import { BookList } from "@/components/agents/BookList";
import { ShortcutList } from "@/components/agents/ShortcutList";
import { GapList } from "@/components/agents/GapList";
import { COLLECTION_TABS, importHref, isNotFound, parseTab, readByText, type CollectionTab } from "@/components/agents/collectionRows";
import { NotFoundNote, Tabs, errorText } from "@/components/agents/collectionUi";

const LIST_HREF = "/dashboard/agents/collections";

export default function CollectionPage() {
  return (
    <Suspense fallback={<div className="w-full p-4 sm:p-6"><LoadingRows /></div>}>
      <CollectionView />
    </Suspense>
  );
}

function CollectionView() {
  const { collectionId } = useParams<{ collectionId: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const tab = parseTab(search.get("tab"));

  const [collection, setCollection] = useState<KbCollection | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    setMissing(false);
    // There is no single-collection route; the list is short and also says who reads each one.
    companionKbApi
      .listCollections()
      .then((all) => {
        const found = all.find((c) => c.id === collectionId);
        if (found) setCollection(found);
        else setMissing(true);
      })
      .catch((e) => {
        if (isNotFound(e)) setMissing(true);
        else setError(errorText(e, "Could not load this collection."));
      });
  }, [collectionId]);
  useEffect(() => {
    setCollection(null);
    load();
  }, [load]);

  const setTab = (next: CollectionTab) => {
    const params = new URLSearchParams(search.toString());
    params.set("tab", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  };

  if (missing) {
    return (
      <div className="w-full p-4 sm:p-6">
        <NotFoundNote message="This collection does not exist, or it was deleted." backHref={LIST_HREF} backLabel="Back to collections" />
      </div>
    );
  }

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <Link href={LIST_HREF} className="inline-block text-sm text-ink-secondary hover:text-primary hover:underline">
        &lsaquo; Collections
      </Link>

      {error && <ErrorNote message={error} onRetry={load} />}

      {collection === null && !error ? (
        <LoadingRows rows={2} />
      ) : collection ? (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h2 className="break-words text-xl font-semibold text-ink">{collection.name}</h2>
              <p className="mt-0.5 break-words text-sm text-ink-secondary">Read by: {readByText(collection.read_by)}</p>
            </div>
            <Link href={importHref(collection.id)} className={`${BTN_PRIMARY} shrink-0`}>
              Import
            </Link>
          </div>

          <section className={`${CARD} p-0`}>
            <Tabs label="Collection" tabs={COLLECTION_TABS} active={tab} onChange={setTab}>
              {(id) =>
                id === "books" ? (
                  <BookList key={collection.id} collectionId={collection.id} />
                ) : id === "shortcuts" ? (
                  <ShortcutList key={collection.id} collectionId={collection.id} />
                ) : (
                  <GapList key={collection.id} collectionId={collection.id} />
                )
              }
            </Tabs>
          </section>
        </>
      ) : null}
    </div>
  );
}
