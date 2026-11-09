"use client";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { canSeeAgents, productHref, productOf, readLastPaths, type Product } from "@/components/nav/products";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

/** "Anril | Agents" switch at the top of the phone drawers, where the rail is hidden. */
export function ProductSwitch({ onSwitch }: { onSwitch?: () => void }) {
  const pathname = usePathname() ?? "/dashboard";
  const router = useRouter();
  const current = productOf(pathname);
  const { role, permissions } = useAuthRole();

  // Without Anril Agents there is only one product: no switch.
  if (!canSeeAgents(role, permissions)) return null;

  const go = (target: Product) => {
    onSwitch?.();
    router.push(productHref(target, pathname, readLastPaths()));
  };

  return (
    <div role="group" aria-label="Product" className="mb-3 flex gap-1 rounded-[10px] border border-border-subtle bg-surface-low p-[3px]">
      {(["anril", "agents"] as const).map((product) => (
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
          {product === "anril" ? "Anril" : "Agents"}
        </button>
      ))}
    </div>
  );
}
