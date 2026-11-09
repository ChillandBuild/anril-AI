"use client";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import { ProductSwitch } from "@/components/nav/ProductSwitch";
import { AgentsBrand, AgentsNavList } from "@/components/agents/AgentsSidebar";

/** Phone (< lg) drawer for Anril Agents pages, in place of Anril's MoreMenu. */
export function AgentsMenu() {
  const pathname = usePathname() ?? "";
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setIsOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen]);

  return (
    <div className="relative lg:hidden">
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        aria-label="Menu"
        aria-expanded={isOpen}
        className="flex h-[34px] w-[34px] items-center justify-center rounded-full text-white transition-transform hover:scale-105"
        style={{ background: "linear-gradient(135deg, var(--primary-950), var(--primary-800))" }}
      >
        <Menu size={16} />
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-[70] lg:hidden" role="dialog" aria-modal="true" aria-label="Anril Agents menu">
          <button type="button" aria-label="Close navigation" className="absolute inset-0 bg-black/35" onClick={() => setIsOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[80vw] max-w-xs overflow-y-auto rounded-r-3xl bg-[#f5f5f5] p-4 pt-[calc(1rem+env(safe-area-inset-top))] pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-2xl animate-in fade-in slide-in-from-left duration-200">
            <div className="mb-3 flex items-center justify-end">
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="flex h-9 w-9 items-center justify-center rounded-full text-ink-secondary hover:bg-black/5"
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>
            <ProductSwitch onSwitch={() => setIsOpen(false)} />
            <AgentsBrand />
            <AgentsNavList pathname={pathname} onNavigate={() => setIsOpen(false)} />
          </div>
        </div>
      )}
    </div>
  );
}
