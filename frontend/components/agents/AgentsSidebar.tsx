"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { AnrilWordmark } from "@/components/logo";
import { AGENTS_NAV, isAgentsItemActive, type AgentsNavItem } from "@/components/agents/agentsNav";

/**
 * The Anril Agents menu. Same footprint and curved right edge as Anril's
 * navy sidebar (fixed, --sidebar-width wide, right of the product rail), in
 * the light console colours of the Agents product.
 */
export function AgentsSidebar() {
  const pathname = usePathname() ?? "";
  return (
    <aside
      aria-label="Anril Agents menu"
      className="swiss-sidebar fixed left-[var(--product-rail-width)] top-0 z-20 flex h-full w-[var(--sidebar-width)] flex-col overflow-y-auto rounded-r-3xl border-r border-[#ededed] bg-[#f5f5f5] px-3 pb-4 pt-[22px]"
    >
      <AgentsBrand />
      <AgentsNavList pathname={pathname} />
    </aside>
  );
}

export function AgentsBrand() {
  return (
    <Link
      href="/dashboard/agents"
      aria-label="Anril Agents home"
      className="mb-5 flex items-center gap-2 px-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
    >
      <Sparkles size={16} className="shrink-0 text-primary" aria-hidden="true" />
      <AnrilWordmark height={17} className="w-auto shrink-0 text-ink" />
      <span className="rounded-full border border-[#ededed] bg-white px-2 py-px font-mono text-[10px] font-medium uppercase tracking-[.06em] text-ink-secondary">
        Agents
      </span>
    </Link>
  );
}

export function AgentsNavList({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-px">
      {AGENTS_NAV.map((section, i) => (
        <div key={section.title ?? i} className="flex flex-col gap-px">
          {section.title && (
            <div className="px-3 pb-1 pt-3.5 font-mono text-[10px] font-medium uppercase tracking-[.06em] text-[#8a919c]">
              {section.title}
            </div>
          )}
          {section.items.map((item) => (
            <AgentsNavRow key={item.href} item={item} active={isAgentsItemActive(item, pathname)} onNavigate={onNavigate} />
          ))}
        </div>
      ))}
    </nav>
  );
}

const ROW = "flex min-h-[34px] w-full items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm";

function AgentsNavRow({ item, active, onNavigate }: { item: AgentsNavItem; active: boolean; onNavigate?: () => void }) {
  const Icon = item.icon;
  if (item.later) {
    return (
      <div className={cn(ROW, "cursor-default text-[#9ea3ad]")} aria-disabled="true">
        <Icon size={16} strokeWidth={1.7} aria-hidden="true" />
        <span className="truncate">{item.label}</span>
        <span className="ml-auto rounded-full border border-[#ededed] bg-white px-1.5 font-mono text-[9.5px] tracking-[.04em]">Later</span>
      </div>
    );
  }
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        ROW,
        "transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary",
        active ? "bg-primary/10 font-medium text-primary" : "text-ink-secondary hover:bg-ink/5 hover:text-ink",
      )}
    >
      <Icon size={16} strokeWidth={1.7} aria-hidden="true" />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}
