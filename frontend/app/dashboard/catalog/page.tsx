"use client";

import { useEffect, useState } from "react";
import { BarChart3, Image as ImageIcon, Package, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { ConflictsLink } from "@/components/brain/ConflictsLink";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { CatalogueTabs } from "./CatalogueTabs";
import { ItemsTab } from "./ItemsTab";
import { MediaTab } from "./MediaTab";
import { AiRulesTab } from "./AiRulesTab";
import { InsightsTab } from "./InsightsTab";

type CatalogTab = "items" | "media" | "ai-rules" | "insights";

const TABS: { id: CatalogTab; label: string; icon: typeof Package }[] = [
  { id: "items", label: "Items", icon: Package },
  { id: "media", label: "Media", icon: ImageIcon },
  { id: "ai-rules", label: "AI Rules", icon: Sparkles },
  { id: "insights", label: "Insights", icon: BarChart3 },
];

export default function CatalogPage() {
  const { role, permissions, loading } = useAuthRole();
  const canViewCatalog = role === "owner" || permissions.includes("catalog.view") || permissions.includes("catalog.manage");
  const canManageCatalog = role === "owner" || permissions.includes("catalog.manage");
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
        <div className="flex w-full flex-wrap gap-1 rounded-xl border border-border bg-white p-1 shadow-sm sm:w-fit">
          {TABS.map((item) => {
            const Icon = item.icon;
            const active = tab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={cn(
                  "inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm font-semibold transition-colors",
                  active ? "bg-primary text-white" : "text-ink-muted hover:bg-surface-low hover:text-ink"
                )}
              >
                <Icon size={15} />
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
      {tab === "ai-rules" && <AiRulesTab canManage={canManageCatalog} />}
      {tab === "insights" && <InsightsTab />}
    </div>
  );
}
