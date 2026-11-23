"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { useNavAccess } from "./useNavAccess";
import { moduleTabsFor } from "./navSections";

/**
 * The module tab bar under the page header: one tab per page of the module the
 * page belongs to (WhatsApp, Anril Setup, Engage, Anril OTP, Anril SMS,
 * Commerce, Call IQ), only the ones this user may open. Bold label, teal
 * underline on the one you are on. Mounted once in the dashboard shell
 * (AppHeader), so no module page needs to render it. The bar scrolls sideways
 * on a phone instead of wrapping or widening the page. Renders nothing outside
 * a module, or when the user may open fewer than two of its tabs.
 */
export function ModuleTabBar() {
  const pathname = usePathname() ?? "";
  const tab = useSearchParams()?.get("tab") ?? "";
  const { access } = useNavAccess();
  const bar = moduleTabsFor(pathname, access, tab);
  if (!bar) return null;

  return (
    <nav
      aria-label={`${bar.section.title} tabs`}
      className="flex w-full gap-0.5 overflow-x-auto border-b border-[#e2e8f0] bg-white px-2 sm:px-3 md:px-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {bar.tabs.map((item) => (
        <Link
          key={item.key}
          href={item.href}
          aria-current={item.active ? "page" : undefined}
          className={cn(
            "-mb-px shrink-0 whitespace-nowrap border-b-[3px] px-3.5 pb-[11px] pt-3 font-label text-[13px] font-extrabold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary",
            item.active
              ? "border-primary text-[#13284A]"
              : "border-transparent text-[#556274] hover:text-[#13284A]",
          )}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
