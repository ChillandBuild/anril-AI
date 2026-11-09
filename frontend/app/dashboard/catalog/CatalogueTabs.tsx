"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuthRole } from "../contexts/AuthRoleContext";

function useCatalogueTabLinks() {
  const pathname = usePathname();
  const { role, permissions } = useAuthRole();
  const canViewProducts = role === "owner" || permissions.includes("catalog.view") || permissions.includes("catalog.manage");
  const canViewServices = role === "owner" || permissions.includes("services.view") || permissions.includes("services.manage");

  return [
    {
      href: "/dashboard/catalog",
      label: "Products",
      visible: canViewProducts,
      active: pathname.startsWith("/dashboard/catalog"),
    },
    {
      href: "/dashboard/services",
      label: "Services",
      visible: canViewServices,
      active: pathname.startsWith("/dashboard/services"),
    },
  ].filter((tab) => tab.visible);
}

/**
 * Products | Services switch inside the page body. It now only shows on phones:
 * from md up the same switch lives in the top header (CatalogueHeaderSwitch).
 */
export function CatalogueTabs() {
  const tabs = useCatalogueTabLinks();
  if (tabs.length === 0) return null;

  return (
    <div className="flex w-full flex-wrap gap-1 rounded-xl border border-border bg-white p-1 shadow-sm md:hidden">
      {tabs.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          aria-current={tab.active ? "page" : undefined}
          className={cn(
            "inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm font-semibold transition-colors",
            tab.active ? "bg-primary text-white" : "text-ink-muted hover:bg-surface-low hover:text-ink"
          )}
        >
          <span>{tab.label}</span>
        </Link>
      ))}
    </div>
  );
}

/** The same switch, styled like the other header switchers (meta-ads, numbers). Desktop only. */
export function CatalogueHeaderSwitch() {
  const tabs = useCatalogueTabLinks();
  if (tabs.length === 0) return null;

  return (
    <nav aria-label="Catalogue views" className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
      {tabs.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          aria-current={tab.active ? "page" : undefined}
          className={cn(
            "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
            tab.active ? "bg-white text-primary shadow-sm" : "text-[#475569] hover:text-[#13284A]"
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
