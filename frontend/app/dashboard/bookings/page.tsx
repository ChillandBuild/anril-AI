"use client";
import { Suspense, useCallback, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { isDateString, mondayOf, todayIst } from "./bookingsTime";
import { DayTab } from "./DayTab";
import { LinkTab } from "./LinkTab";
import { ServicesTab } from "./ServicesTab";
import { StaffTab } from "./StaffTab";
import { WeekTab } from "./WeekTab";
import { Notice, useBookingsAccess, useBookingsSetup } from "./bookingsUi";

type TabId = "day" | "week" | "staff" | "link" | "services";

const TABS: { id: TabId; label: string }[] = [
  { id: "day", label: "Day" },
  { id: "week", label: "Week" },
  { id: "staff", label: "By staff / chair" },
  { id: "link", label: "Booking link" },
  { id: "services", label: "Services & timings" },
];

function BookingsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const access = useBookingsAccess();
  const { data: setup, error, isLoading, mutate } = useBookingsSetup();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const rawTab = params.get("tab");
  const tab: TabId = (TABS.find((t) => t.id === rawTab)?.id ?? "day") as TabId;
  const rawDate = params.get("date");
  const date = isDateString(rawDate) ? rawDate : todayIst();
  const bookingId = params.get("booking");

  const go = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(changes)) {
        if (v === null) next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  if (access.loading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  if (!access.view) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-ink-muted">You do not have access to bookings.</p>
      </div>
    );
  }

  const canManage = access.manage && (setup?.can_manage ?? true);

  function onTabKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const n = (i + (e.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length;
    tabRefs.current[n]?.focus();
    go({ tab: TABS[n].id });
  }

  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-xl font-extrabold text-ink">Bookings</h1>
      </div>

      <div role="tablist" aria-label="Bookings" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[i] = el;
            }}
            id={`bk-tab-${t.id}`}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            aria-controls="bk-panel"
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => go({ tab: t.id })}
            onKeyDown={(e) => onTabKey(e, i)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-lg px-3.5 py-2 text-sm font-bold transition-colors",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
              tab === t.id ? "bg-white text-ink shadow-sm ring-1 ring-[#e2e8f0]" : "text-[#64748b] hover:text-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div id="bk-panel" role="tabpanel" aria-labelledby={`bk-tab-${tab}`}>
        {isLoading && !setup && <div className="h-48 animate-pulse rounded-2xl bg-border-subtle" aria-hidden />}
        {error && !setup && <Notice tone="red">Bookings could not be loaded. Try again in a moment.</Notice>}
        {setup && tab === "day" && (
          <DayTab
            setup={setup}
            date={date}
            onDate={(d) => go({ date: d, booking: null })}
            openId={bookingId}
            onOpenId={(id) => go({ booking: id })}
            canManage={canManage}
            canSeeMoney={access.money}
          />
        )}
        {setup && tab === "week" && (
          <WeekTab weekStart={mondayOf(date)} onWeek={(m) => go({ date: m })} onPickDay={(d) => go({ tab: "day", date: d })} />
        )}
        {setup && tab === "staff" && <StaffTab setup={setup} canManage={canManage} onChanged={() => void mutate()} />}
        {setup && tab === "link" && <LinkTab setup={setup} canManage={canManage} onChanged={() => void mutate()} />}
        {setup && tab === "services" && <ServicesTab setup={setup} canManage={canManage} canSeeMoney={access.money} onChanged={() => void mutate()} />}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />}>
      <BookingsPage />
    </Suspense>
  );
}
