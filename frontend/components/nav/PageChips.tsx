"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { useNavAccess } from "./useNavAccess";
import { chipRowFor } from "./chipRow";

/**
 * The second-level chips under the module tab bar, for the pages that share one
 * tab (Auto-Messages, Replies & handover, OTP Setup, Calling, Leads to call).
 * Reads ?tab= too, because Scripts, Uploads and Who got which lead are views of
 * the Upload and Team pages. Teal filled = the one you are on. The row scrolls
 * sideways instead of wrapping. Renders nothing when the page has no siblings
 * or the user can open fewer than two of them.
 */
export function PageChips() {
  const pathname = usePathname() ?? "";
  const tab = useSearchParams()?.get("tab") ?? "";
  const { access } = useNavAccess();
  const row = chipRowFor(pathname, access, tab);
  if (!row) return null;

  return (
    <nav
      aria-label="Page views"
      className="flex w-full gap-2 overflow-x-auto border-b border-[#e2e8f0] bg-white px-3 py-2 sm:px-4 md:px-7 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {row.chips.map((chip) => {
        const active = chip.href === row.activeHref;
        return (
          <Link
            key={chip.key}
            href={chip.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-3.5 py-1.5 font-label text-xs font-bold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
              active
                ? "border-primary bg-primary text-white"
                : "border-[#cbd5e1] bg-white text-[#475569] hover:border-primary hover:text-primary",
            )}
          >
            {chip.label}
          </Link>
        );
      })}
    </nav>
  );
}
