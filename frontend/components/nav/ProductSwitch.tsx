"use client";
import { usePathname, useRouter } from "next/navigation";
import { MessageCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PRODUCT_LABEL,
  canSeeAgents,
  productHref,
  productOf,
  readLastPaths,
  startProductSwitch,
  type Product,
} from "@/components/nav/products";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

const PRODUCTS = ["anril", "agents"] as const;
const ICON = { anril: MessageCircle, agents: Sparkles } as const;

function useProductSwitch(onSwitch?: () => void) {
  const pathname = usePathname() ?? "/dashboard";
  const router = useRouter();
  const current = productOf(pathname);
  const { role, permissions } = useAuthRole();
  const go = (target: Product) => {
    onSwitch?.();
    if (target !== current) startProductSwitch(target);
    router.push(productHref(target, pathname, readLastPaths()));
  };
  return { current, go, visible: canSeeAgents(role, permissions) };
}

/**
 * "Sales | Agents" at the top of both desktop sidebars, in the same spot, so
 * the pill slides while the sidebar fades between navy and light grey
 * (globals.css, "Sales | Agents switch"). Folded to 64px, it stacks to two icons.
 */
export function SidebarProductSwitch({ className }: { className?: string }) {
  const { current, go, visible } = useProductSwitch();
  // Without Anril Agents there is only one product: no switch.
  if (!visible) return null;
  return (
    <div className={cn("product-switch-row mb-5 shrink-0 px-3.5", className)}>
      <div role="group" aria-label="Product" className="product-switch" data-on={current}>
        <span className="ps-pill" aria-hidden="true" />
        {PRODUCTS.map((product) => {
          const Icon = ICON[product];
          return (
            <button
              key={product}
              type="button"
              data-product={product}
              onClick={() => go(product)}
              aria-pressed={current === product}
              title={PRODUCT_LABEL[product]}
              className="ps-btn flex min-h-8 items-center justify-center gap-1.5 rounded-[9px] text-[13px] font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#3fbcbf]"
            >
              <Icon size={14} strokeWidth={2} aria-hidden="true" className="shrink-0" />
              <span className="ps-lbl">{PRODUCT_LABEL[product]}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** "Sales | Agents" switch at the top of the phone drawers. */
export function ProductSwitch({ onSwitch }: { onSwitch?: () => void }) {
  const { current, go, visible } = useProductSwitch(onSwitch);
  if (!visible) return null;
  return (
    <div role="group" aria-label="Product" className="mb-3 flex gap-1 rounded-[10px] border border-border-subtle bg-surface-low p-[3px]">
      {PRODUCTS.map((product) => (
        <button
          key={product}
          type="button"
          onClick={() => go(product)}
          aria-pressed={current === product}
          className={cn(
            "min-h-9 flex-1 rounded-lg text-[13px] font-semibold transition-colors",
            current === product ? "bg-white text-ink shadow-sm" : "text-ink-muted hover:text-ink",
          )}
        >
          {PRODUCT_LABEL[product]}
        </button>
      ))}
    </div>
  );
}
