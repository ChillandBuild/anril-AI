"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useNavAccess } from "./useNavAccess";
import { chipRowFor } from "./chipRow";

/**
 * Chips for the pages that share one menu row (Auto-Messages, Replies &
 * handover, OTP Setup). Same look as the Meta Ads view switch in AppHeader.
 * "header" sits in the desktop header; "strip" is the phone row under it, which
 * scrolls sideways instead of wrapping. Renders nothing when the page has no
 * siblings or the user can open fewer than two of them.
 */
export function PageChips({ placement }: { placement: "header" | "strip" }) {
  const pathname = usePathname() ?? "";
  const { access } = useNavAccess();
  const row = chipRowFor(pathname, access);
  if (!row) return null;

  const nav = (
    <nav
      aria-label="Page views"
      className={cn(
        "gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1",
        placement === "header" ? "mr-2 hidden md:flex" : "flex w-max max-w-full overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
      )}
    >
      {row.chips.map((chip) => {
        const active = chip.href === row.activeHref;
        return (
          <Link
            key={chip.key}
            href={chip.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "shrink-0 whitespace-nowrap px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
              active ? "bg-white text-primary shadow-sm" : "text-[#475569] hover:text-[#13284A]",
            )}
          >
            {chip.label}
          </Link>
        );
      })}
    </nav>
  );

  if (placement === "header") return nav;
  return <div className="min-w-0 px-3 pt-3 sm:px-4 md:hidden">{nav}</div>;
}
