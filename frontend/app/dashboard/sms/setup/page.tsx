"use client";

import { Suspense } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { AddEntityTab } from "../AddEntityTab";
import { DltManagerTab } from "../DltManagerTab";
import { PeTmTab } from "../PeTmTab";
import { setupTabFor, type SetupTab } from "../dltSetup";
import { useSms } from "../SmsShell";
import { Skeleton } from "../ui";

const TABS: { key: SetupTab; label: string }[] = [
  { key: "entity", label: "Add Entity" },
  { key: "manager", label: "DLT Manager" },
  { key: "petm", label: "PE-TM Binding" },
];

function SetupTabs() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { status } = useSms();
  const tab = setupTabFor(params.get("tab"), status.connected);
  const tabs = status.connected ? TABS : TABS.filter((t) => t.key === "petm");

  function go(next: SetupTab) {
    router.replace(`${pathname}?tab=${next}`, { scroll: false });
  }

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="DLT Setup" className="flex flex-wrap gap-2 border-b border-[#e2e8f0] pb-3">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => go(t.key)}
            className={cn(
              "h-10 rounded-xl px-4 text-sm font-bold transition-colors",
              tab === t.key ? "bg-primary text-white" : "bg-white text-[#64748b] ring-1 ring-[#e2e8f0] hover:text-[#0A1528]",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "entity" && <AddEntityTab />}
      {tab === "manager" && <DltManagerTab />}
      {tab === "petm" && <PeTmTab />}
    </div>
  );
}

export default function SmsSetupPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      <SetupTabs />
    </Suspense>
  );
}
