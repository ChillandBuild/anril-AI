"use client";

import { useEffect, useMemo, useState } from "react";
import { GripVertical, Image as ImageIcon, Loader2, Pencil, Upload, X } from "lucide-react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "@/lib/utils";
import { api, CatalogItem, CatalogMedia } from "@/lib/api";
import { ShopFiles } from "./ShopFiles";

function SortablePhoto({
  media,
  canManage,
  onLabelSave,
  onDelete,
}: {
  media: CatalogMedia;
  canManage: boolean;
  onLabelSave: (id: string, label: string) => void;
  onDelete: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: media.id });
  const [isEditing, setIsEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState(media.label || "");

  useEffect(() => {
    setDraftLabel(media.label || "");
  }, [media.label]);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  function commitLabel() {
    setIsEditing(false);
    const trimmed = draftLabel.trim();
    if (trimmed && trimmed !== (media.label || "")) {
      onLabelSave(media.id, trimmed);
    } else {
      setDraftLabel(media.label || "");
    }
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="group relative overflow-hidden rounded-card border border-border bg-surface-low p-2"
    >
      <div className="relative aspect-[4/3] overflow-hidden rounded-xl">
        {canManage && (
          <button
            type="button"
            {...attributes}
            {...listeners}
            className="absolute left-2 top-2 z-10 flex h-8 w-8 cursor-grab items-center justify-center rounded-md bg-white/90 text-ink-muted shadow-sm transition-opacity max-lg:opacity-100 lg:h-6 lg:w-6 lg:opacity-0 lg:group-hover:opacity-100 active:cursor-grabbing"
            aria-label="Drag to reorder"
          >
            <GripVertical size={13} />
          </button>
        )}
        {canManage && (
          <button
            type="button"
            onClick={() => onDelete(media.id)}
            className="absolute right-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-md bg-white/90 text-danger shadow-sm transition-opacity hover:bg-danger hover:text-white max-lg:opacity-100 lg:h-6 lg:w-6 lg:opacity-0 lg:group-hover:opacity-100"
            aria-label="Remove photo"
          >
            <X size={13} />
          </button>
        )}
        {media.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={media.url} alt={media.label || "Catalog media"} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full flex-col items-center justify-center border border-dashed border-border text-ink-muted">
            <ImageIcon size={26} />
          </div>
        )}
      </div>
      {isEditing ? (
        <input
          autoFocus
          value={draftLabel}
          onChange={(event) => setDraftLabel(event.target.value)}
          onBlur={commitLabel}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              setDraftLabel(media.label || "");
              setIsEditing(false);
            }
          }}
          placeholder="Name this photo..."
          className="mt-2 w-full rounded-md border border-primary px-2 py-1.5 text-center text-xs font-semibold text-ink outline-none"
        />
      ) : (
        <button
          type="button"
          disabled={!canManage}
          onClick={() => canManage && setIsEditing(true)}
          className={cn(
            "mt-2 flex w-full items-center justify-center gap-1.5 truncate rounded-md border px-2 py-1.5 text-xs font-semibold transition-colors disabled:cursor-default",
            media.label
              ? "border-border bg-white text-ink hover:border-primary/40"
              : "border-dashed border-primary/40 bg-primary/5 text-primary hover:bg-primary/10"
          )}
          title={canManage ? "Click to rename this photo" : undefined}
        >
          {canManage && <Pencil size={11} className="shrink-0" />}
          <span className="truncate">{media.label || "Click to name this photo"}</span>
        </button>
      )}
    </div>
  );
}

function MediaItemGroup({
  photos,
  canManage,
  onReorder,
  onLabelSave,
  onDelete,
}: {
  photos: CatalogMedia[];
  canManage: boolean;
  onReorder: (orderedIds: string[]) => void;
  onLabelSave: (id: string, label: string) => void;
  onDelete: (id: string) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = photos.findIndex((p) => p.id === active.id);
    const newIndex = photos.findIndex((p) => p.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    onReorder(arrayMove(photos, oldIndex, newIndex).map((p) => p.id));
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={photos.map((p) => p.id)} strategy={rectSortingStrategy}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {photos.map((photo) => (
            <SortablePhoto key={photo.id} media={photo} canManage={canManage} onLabelSave={onLabelSave} onDelete={onDelete} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}

export function MediaTab({ canManage }: { canManage: boolean }) {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [media, setMedia] = useState<CatalogMedia[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadingItemId, setUploadingItemId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number } | null>(null);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);

  async function loadAll() {
    setIsLoading(true);
    setError(null);
    try {
      const [itemsData, mediaData] = await Promise.all([api.catalog.listItems(), api.catalog.listMedia()]);
      setItems(itemsData);
      setMedia(mediaData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load media");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function handleUploadMultiple(itemId: string, files: FileList) {
    if (!canManage || files.length === 0) return;
    setUploadingItemId(itemId);
    setError(null);
    const fileList = Array.from(files);
    try {
      for (let i = 0; i < fileList.length; i++) {
        setUploadProgress({ current: i + 1, total: fileList.length });
        const uploaded = await api.catalog.uploadMedia(itemId, fileList[i]);
        setMedia((prev) => [...prev, uploaded]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploadingItemId(null);
      setUploadProgress(null);
    }
  }

  async function handleReorder(itemId: string, orderedIds: string[]) {
    setMedia((prev) => {
      const rank = new Map(orderedIds.map((id, index) => [id, index]));
      return prev
        .map((m) => (m.catalog_item_id === itemId && rank.has(m.id) ? { ...m, sort_order: rank.get(m.id)! } : m))
        .slice()
        .sort((a, b) => a.sort_order - b.sort_order);
    });
    try {
      await api.catalog.reorderMedia(itemId, orderedIds);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save photo order");
      loadAll();
    }
  }

  async function handleLabelSave(mediaId: string, label: string) {
    setMedia((prev) => prev.map((m) => (m.id === mediaId ? { ...m, label } : m)));
    try {
      await api.catalog.updateMedia(mediaId, { label });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save photo name");
      loadAll();
    }
  }

  async function handleDelete(mediaId: string) {
    const removed = media.find((m) => m.id === mediaId);
    setMedia((prev) => prev.filter((m) => m.id !== mediaId));
    try {
      await api.catalog.deleteMedia(mediaId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove photo");
      if (removed) setMedia((prev) => [...prev, removed]);
    }
  }

  const mediaCountByItem = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const m of media) {
      counts[m.catalog_item_id] = (counts[m.catalog_item_id] || 0) + 1;
    }
    return counts;
  }, [media]);

  const mediaGroupsByItem = useMemo(() => {
    const groups: Record<string, CatalogMedia[]> = {};
    for (const m of media) {
      (groups[m.catalog_item_id] ||= []).push(m);
    }
    for (const itemId of Object.keys(groups)) {
      groups[itemId].sort((a, b) => a.sort_order - b.sort_order);
    }
    return groups;
  }, [media]);

  const selectedItem = items.find((item) => item.id === selectedItemId) || null;
  const selectedPhotos = selectedItemId ? mediaGroupsByItem[selectedItemId] || [] : [];

  return (
    <div className="space-y-4">
      <ShopFiles canManage={canManage} />
      <h2 className="pt-2 font-display text-lg font-bold text-ink">Item photos</h2>
      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</div>
      )}
      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-card border border-border bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-lg font-bold text-ink">
              Media Library{selectedItem ? ` — ${selectedItem.name}` : ""}
            </h2>
          </div>
          {isLoading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-ink-muted">
              <Loader2 size={16} className="animate-spin" />
              Loading media...
            </div>
          )}
          {!isLoading && !selectedItem && (
            <p className="py-10 text-center text-sm text-ink-muted">Select an item on the right to view its photos.</p>
          )}
          {!isLoading && selectedItem && selectedPhotos.length === 0 && (
            <p className="py-10 text-center text-sm text-ink-muted">No photos yet for {selectedItem.name}. Upload some using the panel on the right.</p>
          )}
          {!isLoading && selectedItem && selectedPhotos.length > 0 && (
            <MediaItemGroup
              photos={selectedPhotos}
              canManage={canManage}
              onReorder={(orderedIds) => handleReorder(selectedItem.id, orderedIds)}
              onLabelSave={handleLabelSave}
              onDelete={handleDelete}
            />
          )}
        </div>
        <div className="rounded-card border border-border bg-white p-5 shadow-sm">
          <h3 className="font-display text-base font-bold text-ink">Attach Media</h3>
          <p className="mt-1 text-sm text-ink-muted">
            Each image belongs to an item so the AI can choose relevant visuals. Click an item to view its photos in
            the library on the left — select multiple photos to upload them all at once, drag to reorder, whoever is
            listed first gets sent first.
          </p>
          <div className="mt-5 space-y-3">
            {items.length === 0 && !isLoading && (
              <p className="text-sm text-ink-muted">Add a catalog item first, then come back here to attach photos.</p>
            )}
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSelectedItemId(item.id)}
                className={cn(
                  "flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left transition-colors",
                  selectedItemId === item.id ? "bg-primary/10 ring-1 ring-primary/40" : "bg-surface-low hover:bg-surface-low/70"
                )}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-ink">{item.name}</p>
                  <p className="text-xs font-medium text-ink-muted">
                    {uploadingItemId === item.id && uploadProgress
                      ? `Uploading ${uploadProgress.current}/${uploadProgress.total}...`
                      : `${mediaCountByItem[item.id] || 0} images`}
                  </p>
                </div>
                <label
                  onClick={(event) => event.stopPropagation()}
                  className={cn("btn-ghost inline-flex shrink-0 items-center gap-2 px-3 py-1.5 text-xs", canManage ? "cursor-pointer" : "cursor-not-allowed opacity-45 blur-[0.5px]")}
                >
                  {uploadingItemId === item.id ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
                  Upload
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    className="hidden"
                    disabled={uploadingItemId === item.id || !canManage}
                    onChange={(event) => {
                      const files = event.target.files;
                      if (files && files.length > 0) {
                        setSelectedItemId(item.id);
                        handleUploadMultiple(item.id, files);
                      }
                      event.target.value = "";
                    }}
                  />
                </label>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
