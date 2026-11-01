"use client";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { AiraLoader } from "@/components/AiraLoader";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { NewDealDialog } from "@/components/deals/NewDealDialog";
import { DealDetailDrawer } from "@/components/deals/DealDetailDrawer";
import { DealsTab } from "./DealsTab";
import { InsightsTab } from "./InsightsTab";
import { FormAnswersTab } from "./FormAnswersTab";

type PageTab = "deals" | "insights" | "forms";

const TABS: { id: PageTab; label: string }[] = [
  { id: "deals", label: "Deals" },
  { id: "insights", label: "Insights" },
  { id: "forms", label: "Form answers" },
];

export default function DealsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { role, permissions, loading: roleLoading } = useAuthRole();
  const rawTab = searchParams.get("tab");
  const [intakeEnabled, setIntakeEnabled] = useState(false);
  const [intakeLoaded, setIntakeLoaded] = useState(false);
  const [openDealId, setOpenDealId] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const canManage = role === "owner" || permissions.includes("deals.manage");
  const canView = role === "owner" || permissions.includes("deals.view") || canManage;

  const visibleTabs = TABS.filter((t) => t.id !== "forms" || intakeEnabled);
  const tab = (visibleTabs.some((t) => t.id === rawTab) ? rawTab : "deals") as PageTab;
  // A ?tab=forms link can't be honoured until the intake config says forms exist;
  // wait for it rather than mounting the Deals tab and swapping.
  const tabPending = rawTab === "forms" && !intakeLoaded;

  const showNewDeal = canManage && searchParams.get("new") === "1";

  function openNewDeal() {
    const params = new URLSearchParams(searchParams.toString());
    params.set("new", "1");
    router.replace(`/dashboard/deals?${params.toString()}`, { scroll: false });
  }

  function closeNewDeal() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("new");
    const qs = params.toString();
    router.replace(`/dashboard/deals${qs ? `?${qs}` : ""}`, { scroll: false });
  }

  function setTab(next: PageTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", next);
    router.replace(`/dashboard/deals?${params.toString()}`, { scroll: false });
  }

  useEffect(() => {
    (async () => {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/settings/intake-config`, { headers: auth });
        if (res.ok) {
          const config = await res.json();
          setIntakeEnabled(Boolean(config.enabled));
        }
      } catch {
        setIntakeEnabled(false);
      } finally {
        setIntakeLoaded(true);
      }
    })();
  }, []);

  function handleCreated() {
    setReloadToken((n) => n + 1);
  }

  function handleDealChanged() {
    setReloadToken((n) => n + 1);
  }

  if (roleLoading) {
    return <div className="min-h-[320px] animate-pulse rounded-2xl bg-border-subtle m-6" />;
  }

  if (!canView) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-ink-muted">You do not have access to deals.</p>
      </div>
    );
  }

  return (
    // Pulled up into the layout's top padding: the tabs sit in the app header, so the
    // full 28px gap above the first row read as empty space.
    <div className="min-w-0 md:-mt-3">
      {/* The tabs live in the app header from md up; phones get them here. */}
      <div className="mb-4 flex items-center justify-between gap-2 md:hidden">
        <div className="flex w-max gap-1 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-1">
          {visibleTabs.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-all ${
                tab === id ? "bg-white text-[#0A1528] shadow-sm" : "text-[#64748b] hover:text-[#0A1528]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {canManage && tab === "deals" && (
          <button
            type="button"
            onClick={openNewDeal}
            className="inline-flex items-center gap-1 rounded-xl bg-primary px-3 py-2 text-xs font-bold text-white shadow-sm hover:bg-primary/90"
          >
            <Plus size={14} /> New deal
          </button>
        )}
      </div>

      {tabPending && <AiraLoader inline className="min-h-[200px]" />}
      {!tabPending && tab === "deals" && <DealsTab onOpenDeal={setOpenDealId} reloadToken={reloadToken} />}
      {!tabPending && tab === "insights" && <InsightsTab />}
      {!tabPending && tab === "forms" && intakeEnabled && <FormAnswersTab />}

      {showNewDeal && (
        <NewDealDialog
          open={showNewDeal}
          onClose={closeNewDeal}
          onCreated={handleCreated}
        />
      )}

      {openDealId && (
        <DealDetailDrawer
          dealId={openDealId}
          canManage={canManage}
          onClose={() => setOpenDealId(null)}
          onChanged={handleDealChanged}
        />
      )}
    </div>
  );
}
