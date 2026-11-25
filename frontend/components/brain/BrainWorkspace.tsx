"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface BrainSection {
  id: string;
  label: string;
  description: string;
  count?: number;
  content: ReactNode;
  scrollable?: boolean;
}

export function BrainWorkspace({ sections, activeId, onSelect }: {
  sections: BrainSection[];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  const instanceId = useId();
  const [visited, setVisited] = useState<Set<string>>(() => new Set([activeId]));
  const active = sections.find((section) => section.id === activeId) ?? sections[0];

  useEffect(() => {
    setVisited((previous) => previous.has(activeId) ? previous : new Set([...Array.from(previous), activeId]));
  }, [activeId]);

  function select(id: string) {
    setVisited((previous) => new Set([...Array.from(previous), id]));
    onSelect(id);
  }

  return (
    <div className="grid min-w-0 gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label="Anril Brain sections" className="min-w-0">
        <div className="flex flex-nowrap gap-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:flex-col lg:flex-wrap lg:gap-1 lg:overflow-visible">
          {sections.map((section) => {
            const selected = section.id === active.id;
            return (
              <button
                key={section.id}
                type="button"
                aria-current={selected ? "page" : undefined}
                aria-controls={`${instanceId}-${section.id}`}
                onClick={() => select(section.id)}
                className={cn(
                  "flex h-8 shrink-0 items-center gap-2 whitespace-nowrap rounded-xl px-3 text-left font-label text-xs transition-colors lg:h-auto lg:min-h-11 lg:shrink lg:whitespace-normal lg:py-2 lg:text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                  selected ? "bg-primary text-white" : "text-ink-secondary hover:bg-surface-mid hover:text-ink",
                )}
              >
                <span className="flex-1 font-bold">{section.label}</span>
                {section.count !== undefined && section.count > 0 && (
                  <span className={cn("rounded-full px-2 py-0.5 text-xs", selected ? "bg-white/20 text-white" : "bg-amber-50 text-warning")}>
                    {section.count}
                  </span>
                )}
                <ChevronRight size={14} aria-hidden className="hidden shrink-0 lg:block" />
              </button>
            );
          })}
        </div>
      </nav>
      <div className="min-w-0">
        <div className="mb-4">
          <h1 className="font-display text-xl font-extrabold text-ink">{active.label}</h1>
          <p className="mt-1 font-body text-sm text-ink-secondary">{active.description}</p>
        </div>
        {sections.map((section) => (
          <div
            key={section.id}
            id={`${instanceId}-${section.id}`}
            hidden={section.id !== active.id}
            role="region"
            aria-label={section.label}
            tabIndex={0}
            className={cn("min-w-0 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary", section.scrollable !== false && "overscroll-contain pr-2 lg:max-h-[calc(100dvh-300px)] lg:overflow-y-auto")}
          >
            {(visited.has(section.id) || section.id === active.id) && <div className="flex min-w-0 flex-col gap-4 pb-2">{section.content}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
