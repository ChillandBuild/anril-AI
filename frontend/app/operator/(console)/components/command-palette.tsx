"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, CornerDownLeft, Users, CreditCard, CalendarClock, ScrollText, Bot, Plus, Building2 } from "lucide-react";
import { operatorFetch } from "@/lib/operator";

type Client = {
  id: string;
  name: string;
  status: string;
  enabled_features: string[];
  created_at: string;
  owner_user_id: string | null;
};

type PaletteItem =
  | { kind: "nav"; id: string; label: string; hint: string; icon: typeof Users; href: string }
  | { kind: "client"; id: string; label: string; hint: string; status: string; href: string };

const NAV_ITEMS: { id: string; label: string; hint: string; icon: typeof Users; href: string }[] = [
  { id: "nav-clients", label: "Clients", hint: "Go to Clients", icon: Users, href: "/operator" },
  { id: "nav-subscription", label: "Subscription", hint: "Go to Subscription", icon: CreditCard, href: "/operator/subscription" },
  { id: "nav-scheduler", label: "Schedulers", hint: "Go to Schedulers", icon: CalendarClock, href: "/operator/scheduler" },
  { id: "nav-audit-log", label: "Audit Log", hint: "Go to Audit Log", icon: ScrollText, href: "/operator/audit-log" },
  { id: "nav-claude-access", label: "Claude Access", hint: "Go to Claude Access", icon: Bot, href: "/operator/claude-access" },
  { id: "nav-new-client", label: "New Client", hint: "Create a client", icon: Plus, href: "/operator" },
];

/**
 * Global ⌘K / Ctrl+K command palette for the operator console. Mounted once
 * from the operator layout so it's available on every page. Fetches the
 * client list lazily (once, on first open) and caches it in state.
 */
export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [clients, setClients] = useState<Client[] | null>(null);
  const [loadingClients, setLoadingClients] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const fetchedOnce = useRef(false);

  const loadClients = useCallback(async () => {
    if (fetchedOnce.current) return;
    fetchedOnce.current = true;
    setLoadingClients(true);
    setLoadError(null);
    try {
      const res = await operatorFetch<{ data: Client[] }>("/api/v1/operator/clients");
      setClients(res.data);
    } catch (e) {
      fetchedOnce.current = false; // allow retry on next open
      setLoadError(e instanceof Error ? e.message : "Failed to load clients");
    } finally {
      setLoadingClients(false);
    }
  }, []);

  const openPalette = useCallback(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    setOpen(true);
    setQuery("");
    setHighlight(0);
    loadClients();
  }, [loadClients]);

  const closePalette = useCallback(() => {
    setOpen(false);
    previouslyFocused.current?.focus?.();
  }, []);

  // Keep a live ref of `open` so the global listener (mounted once) always
  // sees the current state without needing to re-bind on every toggle.
  const openRef = useRef(open);
  useEffect(() => {
    openRef.current = open;
  }, [open]);

  // Global shortcut listener — mounted once, cleaned up on unmount.
  useEffect(() => {
    function handleGlobalKeyDown(e: KeyboardEvent) {
      const isMod = e.metaKey || e.ctrlKey;
      if (isMod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (!openRef.current) openPalette();
      }
    }
    document.addEventListener("keydown", handleGlobalKeyDown);
    return () => document.removeEventListener("keydown", handleGlobalKeyDown);
  }, [openPalette]);

  // Focus the input when the dialog opens.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const navMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return NAV_ITEMS.filter((item) => q === "" || item.label.toLowerCase().includes(q));
  }, [query]);

  const clientMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!clients) return [];
    if (q === "") return clients;
    return clients.filter(
      (c) => c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q)
    );
  }, [clients, query]);

  const items: PaletteItem[] = useMemo(() => {
    const navPart: PaletteItem[] = navMatches.map((n) => ({
      kind: "nav",
      id: n.id,
      label: n.label,
      hint: n.hint,
      icon: n.icon,
      href: n.href,
    }));
    const clientPart: PaletteItem[] = clientMatches.map((c) => ({
      kind: "client",
      id: c.id,
      label: c.name,
      hint: c.id,
      status: c.status,
      href: `/operator/client/${c.id}`,
    }));
    return [...navPart, ...clientPart];
  }, [navMatches, clientMatches]);

  // Keep highlight within bounds as results change.
  useEffect(() => {
    if (highlight >= items.length) setHighlight(items.length > 0 ? items.length - 1 : 0);
  }, [items.length, highlight]);

  // Scroll the highlighted item into view.
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector(`[data-index="${highlight}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [highlight, open]);

  const selectItem = useCallback(
    (item: PaletteItem) => {
      closePalette();
      router.push(item.href);
    },
    [closePalette, router]
  );

  function handleDialogKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (items.length === 0 ? 0 : (h + 1) % items.length));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (items.length === 0 ? 0 : (h - 1 + items.length) % items.length));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const item = items[highlight];
      if (item) selectItem(item);
      return;
    }
    if (e.key === "Tab") {
      // Trap focus within the dialog — only the search input is tabbable.
      e.preventDefault();
      inputRef.current?.focus();
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) closePalette();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onKeyDown={handleDialogKeyDown}
        className="w-full max-w-xl bg-white rounded-card shadow-xl overflow-hidden motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:duration-150"
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <Search size={16} className="text-ink-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setHighlight(0);
            }}
            placeholder="Jump to a client or page…"
            aria-label="Search clients and pages"
            className="flex-1 bg-transparent text-sm text-ink placeholder:text-ink-muted focus:outline-none"
          />
          <kbd className="hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-border text-[10px] font-mono text-ink-muted">
            Esc
          </kbd>
        </div>

        <ul ref={listRef} role="listbox" aria-label="Results" className="max-h-96 overflow-y-auto py-2">
          {loadingClients && clients === null ? (
            <li className="px-4 py-6 text-center text-sm text-ink-muted">Loading clients…</li>
          ) : items.length === 0 ? (
            <li className="px-4 py-6 text-center text-sm text-ink-muted">
              {loadError ? loadError : "No results"}
            </li>
          ) : (
            <>
              {navMatches.length > 0 && (
                <li className="px-4 pt-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-muted" role="presentation">
                  Navigate
                </li>
              )}
              {items.map((item, index) => {
                if (item.kind === "nav") {
                  const Icon = item.icon;
                  const isHighlighted = index === highlight;
                  return (
                    <li key={`nav-${item.id}`} data-index={index} role="presentation">
                      <div
                        role="option"
                        aria-selected={isHighlighted}
                        onMouseEnter={() => setHighlight(index)}
                        onClick={() => selectItem(item)}
                        className={`mx-2 flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-colors ${
                          isHighlighted ? "bg-primary-light text-primary" : "text-ink hover:bg-surface-mid"
                        }`}
                      >
                        <Icon size={15} className={isHighlighted ? "text-primary" : "text-ink-muted"} />
                        <span className="flex-1 text-sm font-medium">{item.label}</span>
                        {isHighlighted && <CornerDownLeft size={13} className="text-primary" />}
                      </div>
                    </li>
                  );
                }

                const isHighlighted = index === highlight;
                const isFirstClient = index === navMatches.length;
                return (
                  <li key={`client-${item.id}`} data-index={index} role="presentation">
                    {isFirstClient && (
                      <div className="px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-muted" role="presentation">
                        Clients
                      </div>
                    )}
                    <div
                      role="option"
                      aria-selected={isHighlighted}
                      onMouseEnter={() => setHighlight(index)}
                      onClick={() => selectItem(item)}
                      className={`mx-2 flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-colors ${
                        isHighlighted ? "bg-primary-light text-primary" : "text-ink hover:bg-surface-mid"
                      }`}
                    >
                      <Building2 size={15} className={isHighlighted ? "text-primary" : "text-ink-muted"} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{item.label}</p>
                        <p className="text-[11px] text-ink-muted font-mono truncate">{item.hint}</p>
                      </div>
                      <span
                        className={`shrink-0 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          item.status === "active" ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
                        }`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${item.status === "active" ? "bg-success" : "bg-danger"}`} />
                        {item.status}
                      </span>
                      {isHighlighted && <CornerDownLeft size={13} className="text-primary shrink-0" />}
                    </div>
                  </li>
                );
              })}
            </>
          )}
        </ul>

        <div className="flex items-center gap-4 px-4 py-2 border-t border-border text-[11px] text-ink-muted">
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded border border-border font-mono">&uarr;</kbd>
            <kbd className="px-1.5 py-0.5 rounded border border-border font-mono">&darr;</kbd>
            navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded border border-border font-mono">Enter</kbd>
            select
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 rounded border border-border font-mono">Esc</kbd>
            close
          </span>
        </div>
      </div>
    </div>
  );
}
