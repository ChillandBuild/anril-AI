"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { AlertCircle, Check, CheckCircle2, FileText, Loader2, UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { UploadCancelledError, companionKbApi, type KbCollection, type KbLimits } from "@/lib/api";
import { KB_ACCEPT, KB_TYPE_CHIPS, fileSizeText } from "@/components/agents/knowledgeRows";
import { CollectionPicker } from "@/components/agents/CollectionPicker";
import { SalesPicker } from "@/components/agents/SalesPicker";
import { BTN_PRIMARY, BTN_SECONDARY, CARD, ErrorNote, INPUT, LoadingRows } from "@/components/agents/ui";
import {
  CANCELLED_TEXT,
  DONE_LINGER_MS,
  importLabel,
  isBusy,
  itemStatusText,
  sortPickedFiles,
  stagedCount,
  uploadOne,
  uploadSummary,
  type UploadItem,
} from "@/components/agents/uploadQueue";

const ROW = "flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle px-5 py-4";

/**
 * The upload card: drop files, pick a collection, say if it is a regular file or the main resource, Import.
 * Example: drop "Returns policy.pdf", pick "Product guides", press Import. The file goes straight to storage,
 * then is registered as a file there and starts being read. One file failing never stops the others.
 */
export function ImportCard({
  collections,
  collectionsError,
  onRetryCollections,
  initialCollectionId,
  onCollectionCreated,
  onChanged,
}: {
  /** null while loading. */
  collections: KbCollection[] | null;
  collectionsError: string;
  onRetryCollections: () => void;
  /** From ?collection=<id> in the address. */
  initialCollectionId: string | null;
  onCollectionCreated: (c: KbCollection) => void;
  /** A file was added: the page refreshes its lists. */
  onChanged: () => void;
}) {
  const hintId = useId();
  const [collectionId, setCollectionId] = useState<string | null>(initialCollectionId);
  const [tier, setTier] = useState<1 | 2>(2);
  const [items, setItems] = useState<UploadItem[]>([]);
  /** Finished files that already left the list (they still count in "3 of 5 uploaded"). */
  const [cleared, setCleared] = useState(0);
  const lingerTimers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const [refused, setRefused] = useState<string[]>([]);
  const [limits, setLimits] = useState<KbLimits | null>(null);
  const [limitsFailed, setLimitsFailed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [needCollection, setNeedCollection] = useState(false);
  const [salesOpen, setSalesOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);
  const alive = useRef(true);
  // Always the latest list, so an Import that is already running can see a file that was removed.
  const itemsRef = useRef<UploadItem[]>([]);
  /** One per file that is uploading, so its Cancel can stop just that file. */
  const cancels = useRef(new Map<string, AbortController>());
  itemsRef.current = items;

  useEffect(() => {
    alive.current = true;
    const timers = lingerTimers.current;
    return () => {
      alive.current = false;
      timers.forEach(clearTimeout);
      timers.clear();
    };
  }, []);

  useEffect(() => {
    companionKbApi
      .limits()
      .then((l) => alive.current && setLimits(l))
      .catch(() => alive.current && setLimitsFailed(true));
  }, []);

  // The address may name a collection before the list has loaded; ignore one that does not exist.
  const selected = collections?.find((c) => c.id === collectionId) ?? null;

  const patch = useCallback((id: string, change: Partial<UploadItem>) => {
    if (!alive.current) return;
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...change } : i)));
  }, []);

  const addFiles = (list: FileList | File[] | null) => {
    if (!list) return;
    const { accepted, refused: bad } = sortPickedFiles(Array.from(list), items.map((i) => i.file), limits?.max_bytes ?? null);
    setRefused(bad);
    if (accepted.length === 0) return;
    // A new batch after the last one finished starts the count again.
    if (!isBusy(items) && stagedCount(items) === 0) setCleared(0);
    setItems((prev) => [
      ...prev,
      ...accepted.map<UploadItem>((file) => ({
        id: `f${nextId.current++}`,
        file,
        status: "staged",
        progress: 0,
        error: "",
        collectionId: null,
        tier: null,
      })),
    ]);
  };

  /** Removes a finished row and keeps it in the count. Does nothing if it is already gone. */
  const clearDone = (id: string) => {
    if (!alive.current || !itemsRef.current.some((i) => i.id === id && i.status === "done")) return;
    itemsRef.current = itemsRef.current.filter((i) => i.id !== id);
    setItems((prev) => prev.filter((i) => i.id !== id));
    setCleared((n) => n + 1);
  };

  const runItem = async (item: UploadItem, target: { collectionId: string; tier: 1 | 2 }) => {
    patch(item.id, { status: "uploading", progress: 0, error: "", collectionId: target.collectionId, tier: target.tier });
    const controller = new AbortController();
    cancels.current.set(item.id, controller);
    try {
      await uploadOne(companionKbApi, item.file, target, {
        onStep: (s) => patch(item.id, { status: s }),
        onProgress: (f) => patch(item.id, { progress: f }),
        signal: controller.signal,
      });
      patch(item.id, { status: "done", progress: 1 });
      if (alive.current) onChanged();
      // Show the green tick, then take the row away by itself. Failed files stay with Retry.
      const timer = setTimeout(() => {
        lingerTimers.current.delete(timer);
        clearDone(item.id);
      }, DONE_LINGER_MS);
      lingerTimers.current.add(timer);
    } catch (e) {
      if (e instanceof UploadCancelledError) {
        patch(item.id, { status: "staged", progress: 0, error: CANCELLED_TEXT });
      } else {
        patch(item.id, { status: "error", error: (e as Error).message || "Upload failed. Please try again." });
      }
    } finally {
      cancels.current.delete(item.id);
    }
  };

  const importAll = async () => {
    if (!selected) {
      setNeedCollection(true);
      setPickerOpen(true);
      return;
    }
    const target = { collectionId: selected.id, tier };
    const todo = items.filter((i) => i.status === "staged");
    for (const item of todo) {
      // Removed while an earlier file was uploading: skip it.
      if (!itemsRef.current.some((i) => i.id === item.id && i.status === "staged")) continue;
      await runItem(item, target);
    }
  };

  const retry = (item: UploadItem) => {
    if (!item.collectionId || !item.tier) return;
    void runItem(item, { collectionId: item.collectionId, tier: item.tier });
  };

  const openSales = () => {
    if (!selected) {
      setNeedCollection(true);
      setPickerOpen(true);
      return;
    }
    setSalesOpen(true);
  };

  const busy = isBusy(items);
  const staged = stagedCount(items);

  return (
    <section className={cn(CARD, "p-0")} aria-labelledby="import-title">
      <h2 id="import-title" className="sr-only">
        Upload files
      </h2>

      <div className="space-y-3 p-5">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            addFiles(e.dataTransfer.files);
          }}
          aria-describedby={`${hintId}-types`}
          className={cn(
            "flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
            dragging ? "border-primary bg-primary/5" : "border-border hover:bg-surface-mid/50",
          )}
        >
          <UploadCloud size={24} className="text-ink-muted" aria-hidden="true" />
          <span className="text-sm font-medium text-ink">Drop files here or click to browse</span>
          <span id={`${hintId}-types`} className="flex flex-wrap items-center justify-center gap-1.5">
            {KB_TYPE_CHIPS.map((c) => (
              <span
                key={c.label}
                className={cn(
                  "rounded-md border px-1.5 py-0.5 font-mono text-[11px] text-ink-secondary",
                  c.later ? "border-dashed border-border-subtle text-ink-secondary" : "border-border",
                )}
                title={c.later ? "Video support comes later" : undefined}
              >
                {c.label}
                {c.later ? " (later)" : ""}
              </span>
            ))}
          </span>
          <span className="text-xs text-ink-secondary">
            {limits ? `Up to ${fileSizeText(limits.max_bytes)} per file.` : limitsFailed ? "The size limit could not be loaded. The server checks it when you import." : "Checking the size limit…"}
          </span>
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={KB_ACCEPT}
          className="sr-only"
          tabIndex={-1}
          aria-label="Choose files to upload"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />

        {refused.length > 0 && (
          <ul role="alert" className="space-y-1 text-sm text-danger">
            {refused.map((m) => (
              <li key={m} className="flex items-start gap-1.5">
                <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                <span>{m}</span>
              </li>
            ))}
          </ul>
        )}

        <p className="sr-only" role="status">
          {uploadSummary(cleared, items)}
        </p>

        {items.length > 0 && (
          <ul className="space-y-2" aria-label="Files to import">
            {items.map((item) => (
              <li key={item.id} className="rounded-lg bg-surface-mid px-3 py-2 text-sm">
                <div className="flex items-center gap-2">
                  {item.status === "error" ? (
                    <AlertCircle size={14} className="shrink-0 text-danger" aria-hidden="true" />
                  ) : item.status === "done" ? (
                    <CheckCircle2 size={14} className="shrink-0 text-success" aria-hidden="true" />
                  ) : item.status === "uploading" || item.status === "registering" ? (
                    <Loader2 size={14} className="shrink-0 animate-spin text-ink-muted" aria-hidden="true" />
                  ) : (
                    <FileText size={14} className="shrink-0 text-ink-muted" aria-hidden="true" />
                  )}
                  <span className="min-w-0 flex-1 truncate font-medium text-ink">{item.file.name}</span>
                  <span className="shrink-0 text-xs text-ink-secondary">{fileSizeText(item.file.size)}</span>
                  {item.status === "error" && (
                    <button type="button" onClick={() => retry(item)} disabled={busy} className="shrink-0 text-xs font-medium text-primary underline underline-offset-2 disabled:opacity-50" aria-label={`Retry ${item.file.name}`}>
                      Retry
                    </button>
                  )}
                  {item.status === "uploading" && (
                    <button
                      type="button"
                      onClick={() => cancels.current.get(item.id)?.abort()}
                      className="shrink-0 text-xs font-medium text-ink-secondary underline underline-offset-2 hover:text-danger"
                      aria-label={`Cancel upload of ${item.file.name}`}
                    >
                      Cancel
                    </button>
                  )}
                  {(item.status === "staged" || item.status === "error" || item.status === "done") && (
                    <button
                      type="button"
                      aria-label={item.status === "done" ? `Dismiss ${item.file.name}` : `Remove ${item.file.name}`}
                      onClick={() => (item.status === "done" ? clearDone(item.id) : setItems((p) => p.filter((x) => x.id !== item.id)))}
                      className="shrink-0 rounded p-1 text-ink-secondary hover:text-danger"
                    >
                      <X size={14} aria-hidden="true" />
                    </button>
                  )}
                </div>
                {item.status === "uploading" && (
                  <div
                    role="progressbar"
                    aria-label={`Uploading ${item.file.name}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(item.progress * 100)}
                    className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-border-subtle"
                  >
                    <div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(item.progress * 100)}%` }} />
                  </div>
                )}
                <p className={cn("mt-1 text-xs", item.status === "error" ? "text-danger" : "text-ink-secondary")} role={item.status === "error" ? "alert" : undefined}>
                  {itemStatusText(item)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={ROW}>
        <div className="min-w-0 flex-1 basis-60">
          <h3 className="text-sm font-semibold text-ink-secondary">
            Add from the web <span className="ml-1 rounded-full bg-surface-mid px-2 py-0.5 text-[11px] font-medium text-ink-secondary">Later</span>
          </h3>
          <div className="mt-2 flex gap-2">
            <input type="text" disabled placeholder="https://example.com/article" aria-label="Web address (coming later)" className={cn(INPUT, "min-w-0 flex-1 cursor-not-allowed bg-surface-mid")} />
            <button type="button" disabled className={BTN_SECONDARY}>
              Add
            </button>
          </div>
        </div>
      </div>

      <div className={ROW}>
        <div className="min-w-0 flex-1 basis-60">
          <h3 className="text-sm font-semibold text-ink">Add from Anril Sales</h3>
          <p className="text-xs text-ink-secondary">Copy a file you already uploaded there. The Sales copy is not changed.</p>
        </div>
        <button type="button" onClick={openSales} className={BTN_SECONDARY}>
          Choose files
        </button>
      </div>

      <div className={ROW}>
        <div className="min-w-0 flex-1 basis-60">
          <h3 className="text-sm font-semibold text-ink">Collection</h3>
          {needCollection && !selected ? (
            <p id={hintId} role="alert" className="text-xs font-medium text-danger">
              Pick a collection first.
            </p>
          ) : (
            <p id={hintId} className="text-xs text-ink-secondary">
              Files go into this collection. A character reads one collection.
            </p>
          )}
        </div>
        {collectionsError ? (
          <div className="w-full sm:w-72">
            <ErrorNote message={collectionsError} onRetry={onRetryCollections} />
          </div>
        ) : collections === null ? (
          <div className="w-full sm:w-72">
            <LoadingRows rows={1} />
          </div>
        ) : (
          <CollectionPicker
            value={selected?.id ?? null}
            onChange={(id) => {
              setCollectionId(id);
              if (id) setNeedCollection(false);
            }}
            collections={collections}
            onCreated={onCollectionCreated}
            invalid={needCollection && !selected}
            describedBy={hintId}
            open={pickerOpen}
            onOpenChange={setPickerOpen}
          />
        )}
      </div>

      <div className={ROW}>
        <div className="min-w-0 flex-1 basis-60">
          <h3 id={`${hintId}-tier`} className="text-sm font-semibold text-ink">
            This file is
          </h3>
          <p className="text-xs text-ink-secondary">The main resource is searched first. Mark the file that answers most questions.</p>
        </div>
        <div role="radiogroup" aria-labelledby={`${hintId}-tier`} className="inline-flex rounded-xl border border-border p-0.5">
          {(
            [
              [2, "A regular file"],
              [1, "The main resource"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="relative cursor-pointer">
              <input type="radio" name={`${hintId}-tier`} checked={tier === value} onChange={() => setTier(value)} className="peer sr-only" />
              <span className="inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-sm text-ink-secondary peer-checked:bg-primary peer-checked:font-semibold peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary">
                {tier === value && <Check size={14} aria-hidden="true" />}
                {label}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className={cn(ROW, "justify-end")}>
        <button type="button" onClick={importAll} disabled={busy || staged === 0} className={BTN_PRIMARY}>
          {busy ? "Importing…" : importLabel(staged)}
        </button>
      </div>

      {selected && (
        <SalesPicker
          open={salesOpen}
          onClose={() => setSalesOpen(false)}
          collectionId={selected.id}
          collectionName={selected.name}
          tier={tier}
          onAdded={onChanged}
        />
      )}
    </section>
  );
}
