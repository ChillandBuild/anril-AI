"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, MessageSquare, Phone, CreditCard } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { cn, getHomeHref, isActive } from "@/lib/utils";
import { API_URL, getAuthHeaders } from "@/lib/api";

type NavTab = {
  href: string;
  icon: typeof Home;
  label: string;
};

export function MobileDashboardNav() {
  const pathname = usePathname() || "/dashboard";
  const { role } = useAuthRole();
  const [subStatus, setSubStatus] = useState<"loading" | "active" | "none" | "pending_approval">("loading");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/subscriptions/me`, { headers: auth });
        if (res.ok && active) {
          const data = await res.json();
          setSubStatus(data.status);
        } else if (active) {
          setSubStatus("active");
        }
      } catch {
        if (active) setSubStatus("active");
      }
    })();
    return () => { active = false; };
  }, []);

  if (subStatus === "loading") return null;

  const isSubscribed = subStatus === "active";

  const tabs: NavTab[] = isSubscribed
    ? [
        { href: getHomeHref(role), icon: Home, label: "Home" },
        { href: "/dashboard/telecalling", icon: Phone, label: "Calls" },
        { href: "/dashboard/conversations", icon: MessageSquare, label: "Inbox" },
      ]
    : [
        { href: getHomeHref(role), icon: Home, label: "Home" },
        { href: "/dashboard/subscription", icon: CreditCard, label: "Subscription" },
      ];

  return (
    <nav className="fixed inset-x-0 bottom-0 z-bottom-nav h-[calc(4.75rem+env(safe-area-inset-bottom))] border-t border-border bg-white/95 px-3 pt-2 shadow-[0_-10px_30px_rgba(28,25,23,0.08)] backdrop-blur lg:hidden">
      <div className={cn(
        "mx-auto grid h-14 max-w-lg gap-0.5 pb-0",
        isSubscribed ? "grid-cols-3" : "grid-cols-2"
      )}>
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const active = isActive(pathname, tab.href);
          return (
            <Link
              key={tab.label}
              href={tab.href}
              className={cn(
                "flex h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-xl px-0.5 text-[9px] font-extrabold leading-none",
                active ? "bg-primary-light text-primary" : "text-ink-secondary"
              )}
            >
              <Icon size={16} strokeWidth={2.1} />
              <span className="max-w-full truncate">{tab.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
