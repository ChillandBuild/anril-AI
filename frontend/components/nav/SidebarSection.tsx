"use client";
import type { ReactNode } from "react";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface SidebarSectionProps {
  title: string;
  icon: LucideIcon;
  open: boolean;
  /** The current page lives in this section: a closed section shows a small teal square. */
  holdsActive?: boolean;
  onToggle: () => void;
  children: ReactNode;
}

/** React 18 has no `inert` prop; an empty-string attribute turns it on. */
export const inertWhen = (on: boolean) => (on ? ({ inert: "" } as Record<string, string>) : {});

/**
 * A product row that folds its items open and shut. The items stay mounted and
 * the box animates its height (.nav-expander in globals.css); a closed box is
 * inert so its links leave the tab order. The parent renders it only when it
 * has visible items.
 */
export function SidebarSection({ title, icon: Icon, open, holdsActive = false, onToggle, children }: SidebarSectionProps) {
  return (
    <section>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="group relative z-[2] flex min-h-[42px] w-full items-center gap-3 rounded-lg p-2.5 text-left text-[12px] font-semibold text-[var(--nav-label)] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary-400)]"
      >
        <Icon
          size={17}
          strokeWidth={1.6}
          className={cn("nav-icon shrink-0", open ? "text-[#78d6d8]" : "text-[#d5f4f4]")}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1">{title}</span>
        <span className={cn("nav-held-dot", !open && holdsActive && "is-on")} aria-hidden="true" />
        <ChevronRight size={13} strokeWidth={1.6} className="nav-chevron shrink-0" aria-hidden="true" />
      </button>
      <div className={cn("nav-expander", open && "open")} {...inertWhen(!open)}>
        <div>
          <div className="nav-children">{children}</div>
        </div>
      </div>
    </section>
  );
}
