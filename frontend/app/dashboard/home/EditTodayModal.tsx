"use client";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronUp, GripVertical, RotateCcw, Search, X } from "lucide-react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api, type HomeLayout, type HomeListKey, type HomeToday } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  BOX_KEYS,
  BOX_META,
  COMING_SOON_BOXES,
  GROUPS,
  LIST_KEYS,
  LIST_LABELS,
  MAX_BOXES,
  addBox,
  buildSavePayload,
  canAddBox,
  listsFromLayout,
  moveBox,
  removeBox,
  resolveBoxes,
  type BoxGroup,
  type BoxKey,
} from "./todayLayout";

function Switch({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange?: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={cn(
        "relative h-6 w-10 shrink-0 rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        checked ? "bg-primary" : "bg-slate-300",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all",
          checked ? "left-[18px]" : "left-0.5",
        )}
      />
    </button>
  );
}

function SortableRow({
  boxKey,
  index,
  count,
  onMove,
  onRemove,
}: {
  boxKey: BoxKey;
  index: number;
  count: number;
  onMove: (key: BoxKey, delta: -1 | 1) => void;
  onRemove: (key: BoxKey) => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: boxKey });
  const meta = BOX_META[boxKey];
  const Icon = meta.icon;
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex items-center gap-2 rounded-xl border border-primary/40 bg-white px-2 py-1.5",
        isDragging && "relative z-10 shadow-lg",
      )}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Drag ${meta.label} to change its place. With the keyboard, press space, then the arrow keys.`}
        className="flex h-9 w-7 shrink-0 cursor-grab touch-none items-center justify-center rounded text-ink-muted hover:text-ink active:cursor-grabbing"
      >
        <GripVertical size={16} aria-hidden />
      </button>
      <span className="w-5 shrink-0 text-center font-label text-xs font-bold text-ink-muted tabular-nums">{index + 1}</span>
      <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px]", meta.tint)} aria-hidden>
        <Icon size={15} />
      </span>
      <span className="min-w-0 flex-1 truncate font-label text-sm font-bold text-ink">{meta.label}</span>
      <span className="hidden shrink-0 font-label text-xs text-ink-muted sm:inline">{meta.module}</span>
      <span className="flex shrink-0 flex-col">
        <button
          type="button"
          onClick={() => onMove(boxKey, -1)}
          disabled={index === 0}
          aria-label={`Move ${meta.label} up`}
          className="flex h-5 w-6 items-center justify-center rounded text-ink-muted hover:bg-slate-100 hover:text-ink disabled:opacity-30"
        >
          <ChevronUp size={14} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => onMove(boxKey, 1)}
          disabled={index === count - 1}
          aria-label={`Move ${meta.label} down`}
          className="flex h-5 w-6 items-center justify-center rounded text-ink-muted hover:bg-slate-100 hover:text-ink disabled:opacity-30"
        >
          <ChevronDown size={14} aria-hidden />
        </button>
      </span>
      <Switch checked label={`Show ${meta.label}`} onChange={() => onRemove(boxKey)} />
    </li>
  );
}

export function EditTodayModal({
  today,
  layout,
  onClose,
  onSaved,
}: {
  today: HomeToday;
  layout: HomeLayout | null | undefined;
  onClose: () => void;
  /** Called with the layout the server returned, after a save or a reset. */
  onSaved: (layout: HomeLayout) => void;
}) {
  const [selected, setSelected] = useState<BoxKey[]>(() => resolveBoxes(layout, today));
  const [lists, setLists] = useState<Record<HomeListKey, boolean>>(() => listsFromLayout(layout));
  const [group, setGroup] = useState<"all" | BoxGroup>("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Latest values for the Escape handler, so the effect below runs once.
  const live = useRef({ busy, onClose });
  live.current = { busy, onClose };

  useEffect(() => {
    closeRef.current?.focus();
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !live.current.busy) live.current.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const atMax = !canAddBox(selected);
  const q = query.trim().toLowerCase();
  const matches = (label: string, g: BoxGroup) => (group === "all" || group === g) && (!q || label.toLowerCase().includes(q));

  const canAdd = BOX_KEYS.filter(
    (k) => (today.available as readonly string[]).includes(k) && !selected.includes(k) && matches(BOX_META[k].label, BOX_META[k].group),
  );
  const comingSoon = COMING_SOON_BOXES.filter((b) => matches(b.label, b.group));
  const totalBoxes = today.available.length + COMING_SOON_BOXES.length;

  function onDragEnd(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return;
    const from = selected.indexOf(e.active.id as BoxKey);
    const to = selected.indexOf(e.over.id as BoxKey);
    if (from < 0 || to < 0) return;
    setSelected(arrayMove(selected, from, to));
  }

  async function save() {
    setBusy("save");
    try {
      const saved = await api.home.saveLayout(buildSavePayload(selected, lists));
      onSaved(saved);
      toast.success("Today saved");
      onClose();
    } catch (err) {
      // 503 = layouts not ready on the server yet; the old layout stays on screen.
      const status = (err as { status?: number }).status;
      toast.error("Couldn't save yet", {
        description: status === 422 ? (err as Error).message : "Your Today is unchanged. Try again in a little while.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    setBusy("reset");
    try {
      const fresh = await api.home.resetLayout();
      onSaved(fresh);
      toast.success("Back to the suggested set");
      onClose();
    } catch {
      toast.error("Couldn't reset yet", { description: "Your Today is unchanged. Try again in a little while." });
    } finally {
      setBusy(null);
    }
  }

  // A list can be switched only when the server sends it to this person.
  const listAvailable: Record<HomeListKey, boolean> = {
    waiting: today.waiting !== null,
    low_stock: today.low_stock !== null,
    todays_feedback: !!today.todays_feedback,
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-today-title"
        className="flex max-h-[92vh] w-full max-w-5xl flex-col rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl"
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-5 sm:px-7 sm:pt-6">
          <div className="min-w-0">
            <h2 id="edit-today-title" className="font-display text-2xl font-bold text-ink">
              Edit Today
            </h2>
            <p className="mt-1 font-body text-sm text-ink-muted">
              Pick the boxes you want to see first. Only for you; each staff member sets their own.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            disabled={busy !== null}
            aria-label="Close"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-ink-muted hover:bg-slate-100 hover:text-ink"
          >
            <X size={18} aria-hidden />
          </button>
        </div>

        <div className="grid flex-1 grid-cols-1 gap-6 overflow-y-auto px-5 py-5 sm:px-7 lg:grid-cols-[1.15fr_1fr_0.8fr]">
          {/* On Today */}
          <section aria-labelledby="on-today-h" className="min-w-0">
            <h3 id="on-today-h" className="font-label text-xs font-bold uppercase tracking-wider text-ink-muted">
              On Today · {selected.length} of {MAX_BOXES} · drag to change order
            </h3>
            {selected.length === 0 ? (
              <p className="mt-3 rounded-xl border border-dashed border-slate-300 px-3 py-4 font-body text-sm text-ink-muted">
                No boxes picked. Today will show the suggested set.
              </p>
            ) : (
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                <SortableContext items={selected} strategy={verticalListSortingStrategy}>
                  <ol className="mt-3 space-y-2">
                    {selected.map((k, i) => (
                      <SortableRow
                        key={k}
                        boxKey={k}
                        index={i}
                        count={selected.length}
                        onMove={(key, d) => setSelected((cur) => moveBox(cur, key, d))}
                        onRemove={(key) => setSelected((cur) => removeBox(cur, key))}
                      />
                    ))}
                  </ol>
                </SortableContext>
              </DndContext>
            )}
            <p className="mt-3 font-body text-xs text-ink-muted">
              More boxes = more rows. Laptop: 6 per row. Phone: 2 per row.
            </p>
          </section>

          {/* Can add */}
          <section aria-labelledby="can-add-h" className="min-w-0">
            <h3 id="can-add-h" className="font-label text-xs font-bold uppercase tracking-wider text-ink-muted">
              Can add · {totalBoxes} boxes in all
            </h3>
            <div className="relative mt-3">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" aria-hidden />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search boxes"
                aria-label="Search boxes"
                className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 font-body text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none"
              />
            </div>
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filter boxes">
              {GROUPS.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  aria-pressed={group === g.id}
                  onClick={() => setGroup(g.id)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 font-label text-xs font-bold",
                    group === g.id ? "border-primary bg-primary/10 text-primary-800" : "border-slate-200 bg-white text-ink hover:border-slate-300",
                  )}
                >
                  {g.label}
                </button>
              ))}
            </div>
            {atMax && (
              <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 font-body text-xs text-amber-900" role="status">
                You have {MAX_BOXES} boxes, the most Today can hold. Turn one off to add another.
              </p>
            )}
            <ul className="mt-3 space-y-2">
              {canAdd.map((k) => {
                const meta = BOX_META[k];
                const Icon = meta.icon;
                return (
                  <li key={k} className="flex items-center gap-2.5 rounded-xl border border-slate-200 bg-white px-3 py-2">
                    <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px]", meta.tint)} aria-hidden>
                      <Icon size={15} />
                    </span>
                    <span className="min-w-0 flex-1 truncate font-label text-sm font-semibold text-ink">{meta.label}</span>
                    <span className="hidden shrink-0 font-label text-xs text-ink-muted sm:inline">{meta.module}</span>
                    <Switch
                      checked={false}
                      disabled={atMax}
                      label={`Add ${meta.label}`}
                      onChange={() => setSelected((cur) => addBox(cur, k))}
                    />
                  </li>
                );
              })}
              {comingSoon.map((b) => {
                const Icon = b.icon;
                return (
                  <li key={b.key} className="flex items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 opacity-70">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px] bg-slate-200 text-slate-600" aria-hidden>
                      <Icon size={15} />
                    </span>
                    <span className="min-w-0 flex-1 truncate font-label text-sm font-semibold text-ink">{b.label}</span>
                    <span className="shrink-0 rounded-full bg-slate-200 px-2 py-0.5 font-label text-xs font-bold text-slate-700">Coming soon</span>
                    <Switch checked={false} disabled label={`${b.label} (coming soon)`} />
                  </li>
                );
              })}
              {canAdd.length === 0 && comingSoon.length === 0 && (
                <li className="font-body text-sm text-ink-muted">No box matches.</li>
              )}
            </ul>
          </section>

          {/* Lists */}
          <section aria-labelledby="lists-h" className="min-w-0">
            <h3 id="lists-h" className="font-label text-xs font-bold uppercase tracking-wider text-ink-muted">
              Lists below the boxes
            </h3>
            <ul className="mt-3 space-y-2">
              {LIST_KEYS.filter((k) => listAvailable[k]).map((k) => (
                <li key={k} className="flex items-center gap-2.5 rounded-xl border border-slate-200 bg-white px-3 py-2.5">
                  <span className="min-w-0 flex-1 font-label text-sm font-semibold text-ink">{LIST_LABELS[k]}</span>
                  <Switch checked={lists[k]} label={`Show ${LIST_LABELS[k]}`} onChange={(v) => setLists((cur) => ({ ...cur, [k]: v }))} />
                </li>
              ))}
            </ul>
            <p className="mt-3 font-body text-xs leading-relaxed text-ink-muted">
              Boxes only show for modules you use. Staff only see boxes their role allows (no money for chat staff).
            </p>
          </section>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-5 py-4 sm:px-7">
          <button
            type="button"
            onClick={reset}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 font-label text-sm font-bold text-primary-700 hover:text-primary-900 disabled:opacity-50"
          >
            <RotateCcw size={15} aria-hidden />
            {busy === "reset" ? "Resetting…" : "Back to the suggested set"}
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy !== null}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 font-label text-sm font-bold text-ink shadow-sm hover:border-slate-300 disabled:opacity-50"
            >
              Cancel
            </button>
            <button type="button" onClick={save} disabled={busy !== null} className="btn-primary justify-center">
              {busy === "save" ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
