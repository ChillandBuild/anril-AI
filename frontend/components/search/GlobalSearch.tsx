"use client";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Search, X } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { cn } from "@/lib/utils";
import { SearchPanel, optionId } from "./SearchPanel";
import { MAX_QUERY, PLACEHOLDER, canUseSearch, flatRows, isFreshAnswer, isSlashShortcut, nextFocusIndex, nextIndex, type SearchRow } from "./searchLogic";
import { useSearchResults } from "./useSearchResults";

/**
 * The search in the top bar. On wide screens a box with a "/" hint and a dropdown; on phones a magnifier
 * that opens a full-screen sheet. "/" from any page focuses the box, or opens the sheet where the box is
 * not showing.
 */
export function GlobalSearch() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const enabled = canUseSearch(role, permissions);
  const listId = useId().replace(/:/g, "");

  const [query, setQuery] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const inlineRef = useRef<HTMLInputElement>(null);
  const sheetRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const state = useSearchResults(query);
  const rows = useMemo(() => flatRows(state.sections), [state.sections]);
  // The highlighted row belongs to the answer it was chosen in; a new answer starts with none.
  const [picked, setPicked] = useState<{ sections: unknown; index: number }>({ sections: null, index: -1 });
  const activeIndex = picked.sections === state.sections ? picked.index : -1;
  const setActive = useCallback((index: number) => setPicked({ sections: state.sections, index }), [state.sections]);

  const reset = useCallback(() => {
    setQuery("");
    setDropdownOpen(false);
    setSheetOpen(false);
  }, []);

  const open = useCallback((row: SearchRow) => {
    reset();
    inlineRef.current?.blur();
    router.push(row.href);
  }, [reset, router]);

  // "/" from any page.
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (!isSlashShortcut(e)) return;
      e.preventDefault();
      const inline = inlineRef.current;
      if (inline && inline.offsetParent !== null) {
        inline.focus();
        inline.select();
        setDropdownOpen(true);
      } else {
        setSheetOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);

  // Click outside the box closes the dropdown.
  useEffect(() => {
    if (!dropdownOpen) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setDropdownOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [dropdownOpen]);

  // The sheet: focus the box, keep the page behind it still, Esc closes, focus goes back to the magnifier.
  useEffect(() => {
    if (!sheetOpen) return;
    sheetRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setSheetOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    const trigger = iconRef.current;
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
      trigger?.focus();
    };
  }, [sheetOpen]);

  useEffect(() => {
    if (activeIndex < 0) return;
    document.getElementById(optionId(listId, activeIndex))?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, listId]);

  if (!enabled) return null;

  const onInputKey = (e: React.KeyboardEvent<HTMLInputElement>, inSheet: boolean) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!inSheet) setDropdownOpen(true);
      setActive(nextIndex(activeIndex, e.key === "ArrowDown" ? 1 : -1, rows.length));
    } else if (e.key === "Enter") {
      // Only act on an answer to what is typed now; otherwise Enter would open a row from an older search.
      if (!isFreshAnswer(state.status, state.forQuery, query)) {
        e.preventDefault();
        return;
      }
      const row = rows[activeIndex] ?? (rows.length > 0 ? rows[0] : undefined);
      if (row) {
        e.preventDefault();
        open(row);
      }
    } else if (e.key === "Escape" && !inSheet) {
      e.preventDefault();
      setDropdownOpen(false);
      inlineRef.current?.blur();
    }
  };

  // Tab and Shift+Tab stay inside the open sheet (the page behind it is not reachable).
  const trapTab = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'),
    );
    const at = focusable.indexOf(document.activeElement as HTMLElement);
    const next = nextFocusIndex(at, focusable.length, e.shiftKey);
    if (next < 0) return;
    e.preventDefault();
    focusable[next].focus();
  };

  const inputProps = (inSheet: boolean) => ({
    role: "combobox" as const,
    "aria-label": "Search name, phone, order number or item",
    "aria-autocomplete": "list" as const,
    "aria-expanded": inSheet ? true : dropdownOpen,
    "aria-controls": listId,
    "aria-activedescendant": activeIndex >= 0 ? optionId(listId, activeIndex) : undefined,
    autoComplete: "off",
    spellCheck: false,
    maxLength: MAX_QUERY,
    value: query,
    placeholder: PLACEHOLDER,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => {
      setQuery(e.target.value);
      if (!inSheet) setDropdownOpen(true);
    },
    onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => onInputKey(e, inSheet),
  });

  const panel = (
    <SearchPanel listId={listId} query={query} state={state} rows={rows} activeIndex={activeIndex} onActive={setActive} onPick={open} />
  );

  return (
    <>
      <div ref={boxRef} className="relative hidden lg:block">
        <div
          className={cn(
            "flex h-[34px] items-center gap-2 rounded-lg border border-[#e2e8f0] bg-white px-2.5 transition-[width] duration-150",
            "lg:w-48 xl:w-72 lg:focus-within:w-80 focus-within:border-primary",
          )}
        >
          <Search size={14} className="shrink-0 text-ink-muted" aria-hidden="true" />
          <input
            ref={inlineRef}
            type="text"
            {...inputProps(false)}
            onFocus={() => setDropdownOpen(true)}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-muted"
          />
          {query === "" && (
            <kbd className="shrink-0 rounded border border-[#e2e8f0] px-1.5 text-[12px] font-semibold leading-5 text-ink-muted" aria-hidden="true">/</kbd>
          )}
        </div>
        {dropdownOpen && !sheetOpen && (
          <div className="absolute right-0 top-full z-50 mt-2 max-h-[70vh] w-[440px] max-w-[90vw] overflow-y-auto overscroll-contain rounded-xl border border-[#e2e8f0] bg-white shadow-xl">
            {panel}
          </div>
        )}
      </div>

      <button
        ref={iconRef}
        type="button"
        onClick={() => setSheetOpen(true)}
        aria-label="Search"
        aria-haspopup="dialog"
        className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full border border-[#e2e8f0] bg-white text-ink transition-transform hover:scale-105 lg:hidden"
      >
        <Search size={16} aria-hidden="true" />
      </button>

      {sheetOpen &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Search"
            className="fixed inset-0 z-[100] flex flex-col bg-background md:items-center md:bg-black/40 md:px-6 md:pt-20"
            ref={dialogRef}
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setSheetOpen(false);
            }}
            onKeyDown={trapTab}
          >
            <div className="flex min-h-0 flex-1 flex-col bg-background md:w-full md:max-w-xl md:flex-none md:rounded-2xl md:shadow-xl">
              <div className="flex shrink-0 items-center gap-2 border-b border-[#e2e8f0] px-4 pb-3 pt-[calc(0.75rem+env(safe-area-inset-top))]">
                <Search size={18} className="shrink-0 text-ink-muted" aria-hidden="true" />
                <input
                  ref={sheetRef}
                  type="text"
                  {...inputProps(true)}
                  className="h-10 min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-muted"
                />
                <button
                  type="button"
                  onClick={() => setSheetOpen(false)}
                  aria-label="Close search"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-ink-muted hover:bg-[#f1f5f9]"
                >
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain md:max-h-[60vh]">{panel}</div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
