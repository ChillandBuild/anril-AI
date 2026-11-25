import { isActive } from "@/lib/utils";

/**
 * Which phone bottom-bar tab to light up. Home ("/dashboard") lights only on an exact match
 * because every page starts with it; other tabs light for their own pages; any other dashboard
 * page was reached through More, so More lights (when the bar has it).
 */
export function pickActiveTab(hrefs: string[], pathname: string, moreHref: string): string | undefined {
  const own = hrefs.find((href) => (href === "/dashboard" ? pathname === href : isActive(pathname, href)));
  if (own) return own;
  return hrefs.includes(moreHref) && pathname.startsWith("/dashboard") ? moreHref : undefined;
}
