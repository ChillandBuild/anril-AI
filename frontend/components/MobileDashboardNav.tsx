"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { CreditCard, Home, LayoutGrid, MessageSquare, Phone, Users } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useNavAccess } from "@/components/nav/useNavAccess";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { cn, getHomeHref, isActive } from "@/lib/utils";
import { useIsPhone } from "@/hooks/useIsPhone";

type NavTab = {
  href: string;
  icon: typeof Home;
  label: string;
  /** Extra paths that also light this tab up. */
  also?: string[];
  badge?: number;
};

export const MORE_HREF = "/dashboard/more";

/** Chats that a person must answer (Anril handed them over). Polled, so the badge stays roughly live. */
function useHandoverCount(enabled: boolean) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/chat-handovers/count`, { headers: await getAuthHeaders() });
        if (res.ok && !stopped) setCount((await res.json()).count ?? 0);
      } catch {}
    };
    void load();
    const id = setInterval(load, 60_000);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      stopped = true;
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [enabled]);
  return count;
}

/**
 * The phone (< lg) bottom bar: Home, Chats, Calls, Customers, More. A tab shows only when the
 * person may open its page (same rules as the sidebar). Height matches --mobile-nav-h in globals.css.
 */
export function MobileDashboardNav() {
  const pathname = usePathname() || "/dashboard";
  const { role } = useAuthRole();
  const { access, waEnabled } = useNavAccess();
  const isSubscribed = access.isSubscribed;

  const chatsOn = isSubscribed && access.messagingOn && access.canAny(["conversations.view", "conversations.reply"]);
  const callsOn = access.telecallingVisible && access.telecallingPages.includes("/dashboard/telecalling");
  const customersOn = isSubscribed && access.messagingOn && access.can("leads.view");
  // The bar is phone-only (lg:hidden); the desktop sidebar already counts these, so only poll on a phone.
  const isPhone = useIsPhone();
  const handovers = useHandoverCount(isPhone && chatsOn && waEnabled);

  const tabs: NavTab[] = isSubscribed
    ? [
        { href: getHomeHref(role), icon: Home, label: "Home" },
        ...(chatsOn ? [{ href: "/dashboard/conversations", icon: MessageSquare, label: "Chats", badge: handovers }] : []),
        ...(callsOn ? [{ href: "/dashboard/telecalling", icon: Phone, label: "Calls" }] : []),
        ...(customersOn ? [{ href: "/dashboard/leads", icon: Users, label: "Customers" }] : []),
        { href: MORE_HREF, icon: LayoutGrid, label: "More" },
      ]
    : [
        { href: getHomeHref(role), icon: Home, label: "Home" },
        { href: "/dashboard/subscription", icon: CreditCard, label: "Subscription" },
      ];

  // Home is "/dashboard", which every page starts with: only an exact match lights it.
  const activeHref = tabs
    .filter((t) => (t.href === "/dashboard" ? pathname === t.href : isActive(pathname, t.href)))
    .map((t) => t.href)[0];

  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-bottom-nav border-t border-border bg-white/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgba(10,21,40,0.06)] backdrop-blur lg:hidden"
    >
      <div
        className="mx-auto grid h-[var(--mobile-nav-h)] max-w-lg px-1.5"
        style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
      >
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const active = tab.href === activeHref;
          return (
            <Link
              key={tab.label}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-w-0 flex-col items-center justify-center gap-1 font-label text-[11px] font-bold leading-none",
                active ? "text-primary-900" : "text-ink-secondary",
              )}
            >
              <span
                className={cn(
                  "relative flex h-8 w-14 items-center justify-center rounded-full transition-colors",
                  active && "bg-primary-light",
                )}
              >
                <Icon size={20} strokeWidth={2} aria-hidden />
                {tab.badge ? (
                  <span className="absolute -top-1 right-2 flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-white bg-rose-700 px-1 text-[10px] font-extrabold text-white">
                    {tab.badge > 99 ? "99+" : tab.badge}
                    <span className="sr-only"> waiting for you</span>
                  </span>
                ) : null}
              </span>
              <span className="max-w-full truncate">{tab.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
