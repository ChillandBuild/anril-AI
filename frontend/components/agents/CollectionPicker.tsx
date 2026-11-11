"use client";
import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, Plus, Tag } from "lucide-react";
import { cn } from "@/lib/utils";
import { companionKbApi, type ApiError, type KbCollection } from "@/lib/api";
import { INPUT } from "@/components/agents/ui";
import { canCreateCollection, defaultIndex, filterCollections, moveIndex } from "@/components/agents/uploadQueue";

/**
 * Pick a collection, or type a new name and create it.
 * A button opens a box with a search field (a combobox) and a list of options.
 * Arrows move, Enter picks, Escape closes and puts focus back on the button.
 * The list comes from the page; the only call made here is createCollection.
 *
 * Example: type "Vastu" with no match, press Enter: "Vastu" is created and picked.
 * A 409 means the name exists: the server's sentence shows under the field.
 */
export function CollectionPicker({
  value,
  onChange,
  collections,
  onCreated,
  invalid = false,
  describedBy,
  open: openProp,
  onOpenChange,
  triggerId,
}: {
  value: string | null;
  onChange: (id: string | null) => void;
  collections: KbCollection[];
  onCreated: (c: KbCollection) => void;
  invalid?: boolean;
  describedBy?: string;
  /** Give both to control it from outside (the page opens it when Import is pressed with nothing picked). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  triggerId?: string;
}) {
  const uid = useId();
  const listId = `${uid}-list`;
  const optionId = (i: number) => `${uid}-opt-${i}`;
  const [innerOpen, setInnerOpen] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : innerOpen;
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const refocusTrigger = useRef(false);

  const setOpen = (next: boolean) => {
    if (!controlled) setInnerOpen(next);
    onOpenChange?.(next);
  };

  const matches = filterCollections(collections, query);
  const createOffered = canCreateCollection(collections, query);
  const optionCount = matches.length + (createOffered ? 1 : 0);
  const selected = collections.find((c) => c.id === value) ?? null;

  // Opening: clear the search, start on the right option, focus the search field.
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCreateError("");
    setActive(defaultIndex(collections.length, false));
    input.current?.focus();
    // Only when it opens; the list changing while open must not reset what was typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Closing by Escape or a pick puts focus back on the button.
  useEffect(() => {
    if (open || !refocusTrigger.current) return;
    refocusTrigger.current = false;
    trigger.current?.focus();
  }, [open]);

  // A click outside closes it.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const close = (andFocusButton: boolean) => {
    refocusTrigger.current = andFocusButton;
    setOpen(false);
    // Already closed from outside and nothing re-rendered: focus now.
    if (andFocusButton && !open) trigger.current?.focus();
  };

  const pick = (id: string) => {
    onChange(id);
    close(true);
  };

  const create = async () => {
    const name = query.trim();
    if (!name || creating) return;
    setCreating(true);
    setCreateError("");
    try {
      const made = await companionKbApi.createCollection(name);
      onCreated(made);
      onChange(made.id);
      setCreating(false);
      close(true);
    } catch (e) {
      setCreating(false);
      const err = e as ApiError;
      setCreateError(err.message || "Could not create the collection.");
    }
  };

  const choose = (index: number) => {
    if (index < 0) return;
    if (index < matches.length) pick(matches[index].id);
    else if (createOffered) void create();
  };

  const onInputKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => moveIndex(a, 1, optionCount));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => moveIndex(a, -1, optionCount));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(active);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    } else if (e.key === "Tab") {
      close(false);
    }
  };

  const onType = (text: string) => {
    setQuery(text);
    setCreateError("");
    setActive(defaultIndex(filterCollections(collections, text).length, canCreateCollection(collections, text)));
  };

  // Keep the highlighted option in view.
  useEffect(() => {
    if (!open || active < 0) return;
    document.getElementById(optionId(active))?.scrollIntoView?.({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, open]);

  return (
    <div ref={wrap} className="relative w-full sm:w-72">
      <button
        ref={trigger}
        id={triggerId}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-describedby={describedBy}
        onClick={() => (open ? close(false) : setOpen(true))}
        className={cn(
          INPUT,
          "flex min-h-10 items-center gap-2 text-left",
          selected ? "text-ink" : "text-ink-secondary",
          invalid && "border-danger ring-2 ring-danger/20",
        )}
      >
        <Tag size={16} className="shrink-0 text-ink-muted" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{selected ? selected.name : "Select collection"}</span>
        <ChevronDown size={16} className="shrink-0 text-ink-muted" aria-hidden="true" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 rounded-xl border border-border bg-white p-2 shadow-lg">
          <input
            ref={input}
            type="text"
            role="combobox"
            aria-label="Search or create a collection"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={active >= 0 && active < optionCount ? optionId(active) : undefined}
            value={query}
            placeholder="Search or create…"
            autoComplete="off"
            maxLength={80}
            onChange={(e) => onType(e.target.value)}
            onKeyDown={onInputKey}
            className={INPUT}
          />
          <ul id={listId} role="listbox" aria-label="Collections" className="mt-2 max-h-56 overflow-y-auto">
            {matches.map((c, i) => (
              <li
                key={c.id}
                id={optionId(i)}
                role="option"
                aria-selected={c.id === value}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(c.id)}
                onMouseMove={() => setActive(i)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-ink",
                  i === active && "bg-surface-mid outline outline-2 -outline-offset-2 outline-primary/40",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                {c.book_count > 0 && (
                  <span className="text-xs text-ink-secondary">
                    {c.book_count} {c.book_count === 1 ? "book" : "books"}
                  </span>
                )}
                {c.id === value && <Check size={14} className="text-primary" aria-label="Picked" />}
              </li>
            ))}
            {createOffered && (
              <li
                id={optionId(matches.length)}
                role="option"
                aria-selected={false}
                aria-disabled={creating || undefined}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => void create()}
                onMouseMove={() => setActive(matches.length)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium text-primary",
                  active === matches.length && "bg-surface-mid outline outline-2 -outline-offset-2 outline-primary/40",
                )}
              >
                <Plus size={14} aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">
                  {creating ? "Creating…" : `Create "${query.trim()}"`}
                </span>
              </li>
            )}
          </ul>
          {optionCount === 0 && (
            <p className="px-2.5 py-2 text-sm text-ink-secondary">No collections yet. Type a name to create one.</p>
          )}
          {createError && (
            <p role="alert" className="px-2.5 pt-1 text-xs text-danger">
              {createError}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
