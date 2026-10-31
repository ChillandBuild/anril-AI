"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { CheckCircle2, ChevronDown, Loader2, Save } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { publishHeaderAccordion } from "@/lib/headerAccordion";
import { cn } from "@/lib/utils";

// The binary controls live in one shared place so the dashboard and the
// operator console cannot drift apart. Re-exported here because every
// settings panel already imports from this module.
export { SwitchPill, CheckTick, CheckField, TickMark } from "@/components/ui/controls";

/* ------------------------------------------------------------------ *
 * Accordion group
 *
 * Sections keep their own open state when rendered standalone. Wrapped
 * in <SettingsAccordion>, they hand that state to the group, which
 * publishes the section count and an expand/collapse-all control to the
 * app header (see lib/headerAccordion).
 *
 * Default open state follows the section count: a page with a single
 * section opens it (nothing to choose between, so a closed card would
 * just be an extra click), while a page with two or more starts fully
 * collapsed so you land on the list of topics, not a wall of forms.
 * Seeding waits until every section has registered — they all mount in
 * the same commit, so the first non-empty id list is the full one.
 * ------------------------------------------------------------------ */

type AccordionCtx = {
  isOpen: (id: string) => boolean;
  toggle: (id: string) => void;
  register: (id: string) => () => void;
};

const Ctx = createContext<AccordionCtx | null>(null);

export function SettingsAccordion({
  children,
  defaultOpenId,
  startClosed = false,
}: {
  children: React.ReactNode;
  defaultOpenId?: string | string[];
  /** Keep every section collapsed even when there is only one. */
  startClosed?: boolean;
}) {
  const [openIds, setOpenIds] = useState<Set<string>>(() => {
    if (!defaultOpenId) return new Set();
    const list = Array.isArray(defaultOpenId) ? defaultOpenId : [defaultOpenId];
    return new Set(list);
  });
  const [ids, setIds] = useState<string[]>([]);
  const seeded = useRef(false);

  const register = useCallback((id: string) => {
    setIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
    return () => setIds((prev) => prev.filter((x) => x !== id));
  }, []);

  useEffect(() => {
    if (seeded.current || ids.length === 0) return;
    seeded.current = true;
    if (typeof window !== "undefined" && window.location.hash) {
      const hash = window.location.hash.replace("#", "");
      if (hash === "business" || hash === "business-details") {
        setOpenIds(new Set(["business-details"]));
        return;
      }
      if (ids.includes(hash)) {
        setOpenIds(new Set([hash]));
        return;
      }
    }
    if (defaultOpenId) {
      const list = Array.isArray(defaultOpenId) ? defaultOpenId : [defaultOpenId];
      setOpenIds(new Set(list));
    } else if (ids.length === 1 && !startClosed) {
      // Lone section opens; two or more stay closed until the user picks one.
      setOpenIds(new Set(ids));
    }
  }, [ids, defaultOpenId, startClosed]);

  const toggle = useCallback((id: string) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const isOpen = useCallback((id: string) => openIds.has(id), [openIds]);

  const value = useMemo<AccordionCtx>(() => ({ isOpen, toggle, register }), [isOpen, toggle, register]);

  const allOpen = ids.length > 0 && ids.every((id) => openIds.has(id));

  const toggleAll = useCallback(() => {
    setOpenIds((prev) => (ids.every((id) => prev.has(id)) ? new Set() : new Set(ids)));
  }, [ids]);

  // The section count and expand/collapse-all live in the app header. Only
  // publish once there's more than one section — a lone section has nothing
  // to expand against.
  useEffect(() => {
    publishHeaderAccordion(
      ids.length > 1 ? { count: ids.length, openCount: openIds.size, allOpen, toggleAll } : null
    );
    return () => publishHeaderAccordion(null);
  }, [ids, openIds, allOpen, toggleAll]);

  return (
    <Ctx.Provider value={value}>
      <div className="space-y-2 sm:space-y-2.5">{children}</div>
    </Ctx.Provider>
  );
}

/* ------------------------------------------------------------------ */

export type SectionAccent = "violet" | "amber" | "sky" | "emerald";

const ACCENTS: Record<SectionAccent, { tile: string; icon: string; rail: string; glow: string }> = {
  violet: {
    tile: "bg-gradient-to-br from-[var(--primary-50)] to-[#e9e2ff] ring-[#ddd4fb]",
    icon: "text-primary",
    rail: "from-primary/70 via-primary-400/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(var(--primary-800-rgb),0.06)]",
  },
  amber: {
    tile: "bg-gradient-to-br from-[#fffbeb] to-[#fdefc8] ring-[#f8e3ae]",
    icon: "text-amber-600",
    rail: "from-amber-500/70 via-amber-300/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(217,119,6,0.06)]",
  },
  sky: {
    tile: "bg-gradient-to-br from-[#f0f9ff] to-[#dcedfd] ring-[#c3e0f8]",
    icon: "text-sky-600",
    rail: "from-sky-500/70 via-sky-300/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(2,132,199,0.06)]",
  },
  emerald: {
    tile: "bg-gradient-to-br from-[#ecfdf5] to-[#d3f5e5] ring-[#b6ecd3]",
    icon: "text-emerald-600",
    rail: "from-emerald-500/70 via-emerald-300/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(5,150,105,0.06)]",
  },
};

export type SectionStatus = {
  label: string;
  tone: "on" | "off" | "warn";
};

const STATUS_STYLES: Record<SectionStatus["tone"], string> = {
  on: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  off: "bg-[#f1f5f9] text-ink-secondary ring-border",
  warn: "bg-amber-50 text-amber-700 ring-amber-200",
};

export function SettingsSection({
  id,
  icon: Icon,
  title,
  description,
  accent = "violet",
  status,
  dirty = false,
  defaultOpen = true,
  children,
}: {
  /** Stable id — required for the group toolbar to drive this section. */
  id: string;
  icon: LucideIcon;
  title: string;
  description: string;
  accent?: SectionAccent;
  status?: SectionStatus;
  /** Shows an "Unsaved" marker on the header so it survives collapsing. */
  dirty?: boolean;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const group = useContext(Ctx);
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const panelId = `${useId()}-panel`;
  const a = ACCENTS[accent];

  // Inside a group the count rule decides the initial state, so only the
  // standalone path reads defaultOpen.
  const register = group?.register;
  useEffect(() => {
    if (!register) return;
    return register(id);
  }, [register, id]);

  const open = group ? group.isOpen(id) : localOpen;
  const onToggle = () => (group ? group.toggle(id) : setLocalOpen((o) => !o));

  return (
    <section
      className={cn(
        "group/section relative overflow-hidden rounded-2xl border bg-white transition-all duration-300 sm:rounded-3xl",
        open
          ? "border-primary/20 shadow-[0_2px_4px_rgba(28,25,23,0.03),0_18px_40px_-24px_rgba(28,25,23,0.28)]"
          : "border-border/70 shadow-[0_1px_2px_rgba(28,25,23,0.03)] hover:border-border hover:shadow-[0_2px_4px_rgba(28,25,23,0.04),0_14px_32px_-24px_rgba(28,25,23,0.25)]"
      )}
    >
      {/* Accent rail — fades in only while the section is open */}
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r transition-opacity duration-300",
          a.rail,
          open ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
        className={cn(
          "flex w-full items-start gap-3.5 p-4 text-left transition-colors duration-200 sm:gap-4 sm:p-6",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/30",
          open ? "bg-white" : "hover:bg-surface-subtle/70"
        )}
      >
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ring-1 transition-all duration-300 sm:h-11 sm:w-11",
            a.tile,
            a.glow
          )}
        >
          <Icon size={18} className={a.icon} strokeWidth={2} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <h2 className="font-display text-[0.9375rem] font-bold tracking-[-0.02em] text-ink sm:text-base">
              {title}
            </h2>
            {status && (
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-label text-[10px] font-bold uppercase tracking-wider ring-1 ring-inset",
                  STATUS_STYLES[status.tone]
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    status.tone === "on"
                      ? "bg-emerald-500"
                      : status.tone === "warn"
                      ? "bg-amber-500"
                      : "bg-ink-muted"
                  )}
                />
                {status.label}
              </span>
            )}
            {dirty && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2 py-0.5 font-label text-[10px] font-bold uppercase tracking-wider text-amber-700 ring-1 ring-inset ring-amber-200">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                Unsaved
              </span>
            )}
          </span>
          <span
            className={cn(
              "mt-1 block max-w-2xl font-body text-[13px] leading-relaxed text-ink-secondary sm:text-sm",
              !open && "line-clamp-2"
            )}
          >
            {description}
          </span>
        </span>

        <span
          className={cn(
            "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition-all duration-300",
            open
              ? "border-primary/25 bg-primary-light text-primary"
              : "border-border/80 bg-surface-subtle text-ink-muted group-hover/section:border-primary/25 group-hover/section:text-primary"
          )}
        >
          <ChevronDown
            size={16}
            className={cn("transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]", open && "rotate-180")}
          />
        </span>
      </button>

      {/* grid-rows 0fr → 1fr animates to the content's natural height */}
      <div
        id={panelId}
        role="region"
        className={cn(
          "grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        )}
      >
        {/* visibility (not display) keeps collapsed content out of the tab
            order without killing the closing animation */}
        <div
          className={cn(
            "overflow-hidden transition-[opacity,visibility] duration-300",
            open ? "visible opacity-100" : "invisible opacity-0"
          )}
        >
          <div className="border-t border-border-subtle px-4 pb-5 pt-5 sm:px-6 sm:pb-6 sm:pt-6">{children}</div>
        </div>
      </div>
    </section>
  );
}

/**
 * Footer used inside a section body: status text on the left, save button
 * on the right, separated by a hairline. Keeps every panel's save row
 * identical instead of five near-copies.
 */
export function SectionFooter({
  children,
  status,
}: {
  children: React.ReactNode;
  status?: React.ReactNode;
}) {
  return (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-5">
      <div className="min-h-[20px] flex items-center">{status}</div>
      {children}
    </div>
  );
}

export type SaveState = "idle" | "dirty" | "saving" | "saved";

/** The one Save button every settings panel uses. */
export function SaveButton({
  state,
  dirty,
  disabled = false,
  onClick,
}: {
  state: SaveState;
  dirty: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  const active = !disabled && dirty && state !== "saving" && state !== "saved";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!active}
      className={cn(
        "inline-flex items-center gap-2 rounded-xl px-4 py-2 font-label text-sm font-semibold transition-all duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
        state === "saved"
          ? "cursor-default bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200"
          : active
          ? "bg-gradient-to-br from-[var(--primary-950)] to-primary text-white shadow-[0_6px_16px_-8px_rgba(var(--primary-800-rgb),0.7)] hover:shadow-[0_10px_22px_-8px_rgba(var(--primary-800-rgb),0.75)] hover:brightness-110 active:scale-[0.98]"
          : "cursor-default bg-surface-subtle text-ink-muted ring-1 ring-inset ring-border/70"
      )}
    >
      {state === "saving" ? (
        <>
          <Loader2 size={14} className="animate-spin" />
          Saving…
        </>
      ) : state === "saved" ? (
        <>
          <CheckCircle2 size={14} />
          Saved
        </>
      ) : (
        <>
          <Save size={14} />
          Save Changes
        </>
      )}
    </button>
  );
}

/** Left-hand status line in a SectionFooter: "Unsaved changes" / "Saved" / resting hint. */
export function SaveStatus({
  state,
  dirty,
  idleLabel,
}: {
  state: SaveState;
  dirty: boolean;
  idleLabel?: string;
}) {
  if (state === "saved") {
    return (
      <span className="inline-flex items-center gap-1.5 font-body text-sm font-medium text-emerald-600">
        <CheckCircle2 size={15} /> Saved successfully
      </span>
    );
  }
  if (dirty) {
    return (
      <span className="inline-flex items-center gap-1.5 font-body text-[11px] font-semibold text-amber-600">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
        Unsaved changes
      </span>
    );
  }
  return idleLabel ? <span className="font-body text-[11px] text-ink-muted">{idleLabel}</span> : null;
}
