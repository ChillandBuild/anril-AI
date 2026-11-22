"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { ConflictsLink } from "@/components/brain/ConflictsLink";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { CatalogueTabs } from "./CatalogueTabs";
import { ItemsTab } from "./ItemsTab";
import { MediaTab } from "./MediaTab";
import { AiRulesTab } from "./AiRulesTab";
import { StockAsksTab } from "./StockAsksTab";
import { ShopGodownTab } from "./ShopGodownTab";
import { BatchesTab } from "./BatchesTab";
import { StockCountTab } from "./StockCountTab";

type CatalogTab = "items" | "media" | "batches" | "count" | "places" | "ai-rules" | "asked";

const TABS: { id: CatalogTab; label: string; icon: string }[] = [
  { id: "items", label: "Items", icon: "🏷️" },
  { id: "media", label: "Media", icon: "🖼️" },
  { id: "batches", label: "Batches & expiry", icon: "⏳" },
  { id: "count", label: "Stock count", icon: "🔢" },
  { id: "places", label: "Shop & godown", icon: "🏬" },
  { id: "ai-rules", label: "AI rules", icon: "🤖" },
  { id: "asked", label: "Asked but out of stock", icon: "📉" },
];

export default function CatalogPage() {
  const { role, permissions, loading } = useAuthRole();
  const canViewCatalog = role === "owner" || permissions.includes("catalog.view") || permissions.includes("catalog.manage");
  const canManageCatalog = role === "owner" || permissions.includes("catalog.manage");
  const canManageTemplates = role === "owner" || permissions.includes("templates.manage");
  const router = useRouter();
  const searchParams = useSearchParams();
  // The Items tab portals its search / reindex / add controls into this slot, so tabs and controls share one row.
  const [toolbarSlot, setToolbarSlot] = useState<HTMLDivElement | null>(null);
  const rawTab = searchParams.get("tab");
  const tab = (TABS.some((item) => item.id === rawTab) ? rawTab : "items") as CatalogTab;

  // The Catalogue nav entry links here for services-only users too; send them to what they can open.
  const canViewServices = role === "owner" || permissions.includes("services.view") || permissions.includes("services.manage");
  const shouldRedirectToServices = !loading && !canViewCatalog && canViewServices;
  useEffect(() => {
    if (shouldRedirectToServices) router.replace("/dashboard/services");
  }, [shouldRedirectToServices, router]);

  function setTab(nextTab: CatalogTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", nextTab);
    router.replace(`/dashboard/catalog?${params.toString()}`, { scroll: false });
  }

  if (loading || shouldRedirectToServices) {
    return <div className="min-h-[320px] animate-pulse rounded-card bg-surface-low" />;
  }

  if (!canViewCatalog) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-on-surface-muted">You do not have access to the catalog.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <CatalogueTabs />
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex w-full flex-wrap gap-2 sm:w-fit">
          {TABS.map((item) => {
            const active = tab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                aria-pressed={active}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 rounded-xl border px-3.5 text-sm font-bold transition-colors",
                  active ? "border-primary bg-primary text-white shadow-sm" : "border-border bg-white text-ink hover:bg-surface-low"
                )}
              >
                <span aria-hidden>{item.icon}</span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
        <div ref={setToolbarSlot} className="flex min-w-0 flex-wrap items-center gap-2" />
      </div>

      {tab === "items" && <ConflictsLink />}
      {tab === "items" && <ItemsTab canManage={canManageCatalog} toolbarSlot={toolbarSlot} />}
      {tab === "media" && <MediaTab canManage={canManageCatalog} />}
      {tab === "count" && (
        <StockCountTab toolbarSlot={toolbarSlot} isOwner={role === "owner"}
          canCount={role === "owner" || ["catalog.manage", "purchases.manage", "deals.manage"].some((p) => permissions.includes(p))} />
      )}
      {tab === "batches" && <BatchesTab canManage={canManageCatalog} toolbarSlot={toolbarSlot} />}
      {tab === "places" && <ShopGodownTab canManage={canManageCatalog} toolbarSlot={toolbarSlot} />}
      {tab === "ai-rules" && <AiRulesTab canManage={canManageCatalog} />}
      {tab === "asked" && <StockAsksTab canManage={canManageCatalog} canSubmitTemplate={canManageTemplates} toolbarSlot={toolbarSlot} />}
    </div>
  );
}
