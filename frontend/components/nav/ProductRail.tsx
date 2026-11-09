"use client";
import { usePathname, useRouter } from "next/navigation";
import { MessageCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { productHref, productOf, readLastPaths, type Product } from "@/components/nav/products";

/**
 * The thin strip at the far left of every dashboard page (lg and up): one
 * button per product. Its width is --product-rail-width (globals.css), which
 * the sidebars, header and inbox add to their left offset.
 */
export function ProductRail({ showAgents = true }: { showAgents?: boolean }) {
  const pathname = usePathname() ?? "/dashboard";
  const router = useRouter();
  const current = productOf(pathname);

  const go = (target: Product) => router.push(productHref(target, pathname, readLastPaths()));

  return (
    <nav
      aria-label="Products"
      className="fixed left-0 top-0 z-30 flex h-full w-[var(--product-rail-width)] flex-col items-center gap-1.5 border-r border-white/[0.08] bg-[#050b16] pb-3.5 pt-5"
    >
      <RailButton label="Anril" ariaLabel="Anril, WhatsApp sales" active={current === "anril"} onClick={() => go("anril")}>
        <MessageCircle size={18} strokeWidth={1.8} aria-hidden="true" />
      </RailButton>
      {showAgents && (
        <RailButton label="Agents" ariaLabel="Anril Agents, AI characters" active={current === "agents"} accent onClick={() => go("agents")}>
          <Sparkles size={18} strokeWidth={1.8} aria-hidden="true" />
        </RailButton>
      )}
    </nav>
  );
}

function RailButton({
  label,
  ariaLabel,
  active,
  accent = false,
  onClick,
  children,
}: {
  label: string;
  ariaLabel: string;
  active: boolean;
  accent?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group flex w-12 flex-col items-center gap-1 rounded-[10px] py-1.5 text-[10.5px] font-medium transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5fd4d6]",
        active ? "text-white" : "text-white/60 hover:text-white",
      )}
    >
      <span
        className={cn(
          "grid h-9 w-9 place-items-center rounded-[10px] transition-colors",
          active ? (accent ? "bg-[#2fb3b6] text-white" : "bg-white text-[var(--navy)]") : "group-hover:bg-white/[0.08]",
        )}
      >
        {children}
      </span>
      {label}
    </button>
  );
}
