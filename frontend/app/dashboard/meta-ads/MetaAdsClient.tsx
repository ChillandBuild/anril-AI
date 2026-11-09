import Link from "next/link";
import { cn } from "@/lib/utils";
import { AdPerformanceTab } from "./AdPerformanceTab";
import { AllAdsTab } from "./AllAdsTab";
import { InstantFormDetail } from "./InstantFormDetail";
import { InstantFormsTab } from "./InstantFormsTab";

const VIEWS: { view: "whatsapp" | "all" | "forms"; href: string; label: string }[] = [
  { view: "whatsapp", href: "/dashboard/meta-ads", label: "Messaging ads" },
  { view: "all", href: "/dashboard/meta-ads/all-ads", label: "All ads" },
  { view: "forms", href: "/dashboard/meta-ads/instant-forms", label: "Instant forms" },
];

/** The Messaging ads / All ads / Instant forms switch lives in the app header (components/AppHeader.tsx);
 * the header hides its tabs on phones, so a copy shows here below the md breakpoint. */
export function MetaAdsClient({
  view = "whatsapp",
  formId,
}: {
  view?: "whatsapp" | "all" | "forms";
  formId?: string;
}) {
  return (
    <div>
      <nav aria-label="Meta ads views" className="mb-4 flex gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:hidden">
        {VIEWS.map((item) => (
          <Link
            key={item.view}
            href={item.href}
            aria-current={item.view === view ? "page" : undefined}
            className={cn(
              "flex-1 rounded-xl px-3 py-1.5 text-center font-label text-xs font-bold transition-all",
              item.view === view ? "bg-white text-primary shadow-sm" : "text-[#475569]",
            )}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      {view === "forms" ? (
        formId ? <InstantFormDetail formId={formId} /> : <InstantFormsTab />
      ) : view === "all" ? (
        <AllAdsTab />
      ) : (
        <AdPerformanceTab />
      )}
    </div>
  );
}
