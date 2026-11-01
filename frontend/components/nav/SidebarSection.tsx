"use client";
import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, type LucideIcon } from "lucide-react";

interface SidebarSectionProps {
  title: string;
  icon?: LucideIcon;
  open: boolean;
  /** The current page lives in this section: a closed section shows a small teal square. */
  holdsActive?: boolean;
  onToggle: () => void;
  children: ReactNode;
}

/** A product heading that folds its items open and shut. The parent renders it only when it has visible items. */
export function SidebarSection({ title, icon: Icon, open, holdsActive = false, onToggle, children }: SidebarSectionProps) {
  // Slide the items in only when the user opens the section, not on page load.
  const [kidsIn, setKidsIn] = useState(false);
  return (
    <div className="">
      <button
        type="button"
        onClick={() => { setKidsIn(!open); onToggle(); }}
        aria-expanded={open}
        className="group flex min-h-12 items-center gap-4 w-full px-4 py-3 rounded-md text-left font-label text-[11px] font-bold uppercase tracking-wider text-slate-300 hover:text-white transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary-400)]"
      >
        {Icon && (
          <Icon
            size={16}
            className="shrink-0 transition-transform duration-300 ease-[cubic-bezier(.34,1.56,.64,1)] group-hover:translate-x-0.5 motion-reduce:transition-none"
            aria-hidden="true"
          />
        )}
        <span className="min-w-0 flex-1">{title}</span>
        {!open && holdsActive && <span className="size-1.5 shrink-0 rounded-[2px] bg-[var(--primary-400)]" aria-hidden="true" />}
        {open ? <ChevronDown size={12} aria-hidden="true" /> : <ChevronRight size={12} aria-hidden="true" />}
      </button>
      {open && <div className={kidsIn ? "nav-kids-in space-y-1" : "space-y-1"}>{children}</div>}
    </div>
  );
}
