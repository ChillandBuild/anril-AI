"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronRight, LogOut, Search, TrendingUp, UserCircle, X } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useSubscription } from "@/app/dashboard/contexts/SubscriptionContext";
import { MORE_SECTIONS, getVisibleMoreItems } from "@/components/MoreMenu";
import { ProductSwitch } from "@/components/nav/ProductSwitch";
import { BrainNavBadge } from "@/components/brain/BrainNavBadge";
import { claudeSettingsOn, groupSettingsItems, settingsItemsForMember } from "@/components/settingsNavigation";
import { useNavAccess } from "@/components/nav/useNavAccess";
import { useBrainCount } from "@/hooks/useBrainCount";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useLogout } from "@/hooks/useLogout";

/** Big cards at the top, in this order, when the person may open them. */
const USED_MOST: Record<string, string> = {
  deals: "Bills and money in",
  bookings: "Who is coming, when",
  reach: "Message many customers",
  analytics: "How the business is doing",
};

/** Headings for the sections the drawer showed without one. */
const FALLBACK_TITLE: Partial<Record<string, string>> = { customers: "Customers", reach: "Reach", reports: "Reports" };

/**
 * The phone "More" tab: everything that is not Home, Chats, Calls or Customers.
 * Uses the same gated list as the old drawer (MORE_ITEMS), so nobody sees a page they cannot open.
 */
export function MoreClient() {
  const { role, roleName, enabledFeatures, permissions, tenantName } = useAuthRole();
  const { purchasedFeatures } = useSubscription();
  const { fullName, email } = useCurrentUser();
  const logout = useLogout();
  const [query, setQuery] = useState("");
  const { access } = useNavAccess();
  // Customers moves to the bottom bar only when that tab shows (same rule as MobileDashboardNav);
  // someone who may open Customers but gets no tab still finds it here.
  const customersTab = access.isSubscribed && access.messagingOn && access.can("leads.view");

  const items = useMemo(
    () => getVisibleMoreItems(role, enabledFeatures, permissions).filter((item) => !(item.key === "leads" && customersTab)),
    [role, enabledFeatures, permissions, customersTab],
  );
  const brainCount = useBrainCount(items.some((item) => item.key === "brain"));
  // Each Settings page is its own row, with the gate it had in the old drawer: Team & roles or
  // Plans & subscription stay reachable for people who cannot open the main Settings page.
  const settingsItems = settingsItemsForMember(role, permissions, purchasedFeatures, claudeSettingsOn(role, enabledFeatures));

  const q = query.trim().toLowerCase();
  const matches = (label: string) => !q || label.toLowerCase().includes(q);

  const top = Object.keys(USED_MOST)
    .map((key) => items.find((item) => item.key === key))
    .filter((item): item is (typeof items)[number] => !!item && matches(item.label));
  const topKeys = new Set(top.map((item) => item.key));
  const sections = MORE_SECTIONS.map((section) => ({
    key: section.key,
    title: section.title ?? FALLBACK_TITLE[section.key] ?? null,
    items: items.filter((item) => item.section === section.key && !topKeys.has(item.key) && matches(item.label)),
  })).filter((section) => section.items.length > 0);
  const settingsShown = settingsItems.filter((item) => matches(item.label) || matches("Settings"));
  const settingsList = groupSettingsItems(settingsShown);
  const settingsRows = [...settingsList.groups.flatMap((g) => g.items), ...settingsList.loose];
  const nothingFound = q && top.length === 0 && sections.length === 0 && settingsRows.length === 0;

  const initial = (fullName || email || "?").charAt(0).toUpperCase();

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-5">
      <div className="sticky top-14 md:top-16 z-20 -mx-3 bg-background px-3 pb-2 pt-1 sm:-mx-4 sm:px-4 lg:static lg:mx-0 lg:p-0">
      <label className="flex h-10 items-center gap-2 rounded-xl border border-border bg-white px-3.5 text-ink-muted focus-within:border-primary-300">
        <Search size={16} aria-hidden className="shrink-0" />
        <span className="sr-only">Find a page</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a page, e.g. templates"
          className="min-w-0 flex-1 bg-transparent font-body text-[15px] text-ink outline-none placeholder:text-ink-muted"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear search"
            className="-mr-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-full hover:bg-surface-mid"
          >
            <X size={18} aria-hidden />
          </button>
        )}
      </label>
      </div>

      {!q && (
        <section aria-label="Your account" className="flex flex-col gap-3 rounded-3xl bg-navy p-4 text-white">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-navy-accent font-display text-base font-extrabold text-navy">
              {initial}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-display text-base font-extrabold">{fullName || "You"}</p>
              <p className="truncate font-body text-[13px] text-slate-300">
                {[roleName || (role === "owner" ? "Owner" : null), tenantName].filter(Boolean).join(" · ") || email}
              </p>
            </div>
            <Link
              href={role === "caller" ? "/dashboard/profile" : "/dashboard/settings/your-account"}
              className="flex min-h-11 shrink-0 items-center gap-1 rounded-xl px-2 font-label text-sm font-bold text-navy-accent"
            >
              {role === "caller" ? <TrendingUp size={16} aria-hidden /> : <UserCircle size={16} aria-hidden />}
              {role === "caller" ? "My performance" : "Account"}
            </Link>
          </div>
          <div className="rounded-xl bg-white/95 px-1 pt-1">
            <ProductSwitch />
          </div>
        </section>
      )}

      {nothingFound && (
        <p className="rounded-2xl border border-border bg-white px-4 py-6 text-center font-body text-sm text-ink-muted">
          No page called &ldquo;{query.trim()}&rdquo;. Try another word.
        </p>
      )}

      {top.length > 0 && (
        <section aria-labelledby="more-top">
          <h2 id="more-top" className="mb-2 px-1 font-label text-xs font-extrabold uppercase tracking-wider text-ink-secondary">
            Used most
          </h2>
          <div className="grid grid-cols-2 gap-2.5">
            {top.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.key}
                  href={item.href}
                  className="flex min-w-0 flex-col gap-2 rounded-2xl border border-border bg-white p-3.5 text-ink transition-colors hover:border-primary-200 active:bg-surface-mid"
                >
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-light text-primary-900">
                    <Icon size={22} aria-hidden />
                  </span>
                  <span className="font-display text-[15px] font-extrabold leading-tight">{item.label}</span>
                  <span className="font-body text-xs leading-snug text-ink-muted">{USED_MOST[item.key]}</span>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {sections.map((section) => (
        <section key={section.key} aria-label={section.title ?? undefined}>
          {section.title && (
            <h2 className="mb-2 px-1 font-label text-xs font-extrabold uppercase tracking-wider text-ink-secondary">
              {section.title}
            </h2>
          )}
          <div className="grid grid-cols-3 gap-0.5 rounded-2xl border border-border bg-white p-1 min-[380px]:grid-cols-4">
            {section.items.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.key}
                  href={item.href}
                  className="flex min-w-0 flex-col items-center gap-2 rounded-xl px-1 pb-2.5 pt-3 text-center text-ink active:bg-surface-mid"
                >
                  <span className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-light text-primary-900">
                    <Icon size={21} aria-hidden />
                    {item.key === "brain" && (
                      <span className="absolute -right-1.5 -top-1.5">
                        <BrainNavBadge count={brainCount} variant="menu" />
                      </span>
                    )}
                  </span>
                  <span className="line-clamp-2 w-full font-label text-xs font-bold leading-tight [overflow-wrap:normal] [word-break:normal]">{item.label}</span>
                </Link>
              );
            })}
          </div>
        </section>
      ))}

      {settingsRows.length > 0 && (
        <section aria-labelledby="more-settings">
          <h2 id="more-settings" className="mb-2 px-1 font-label text-xs font-extrabold uppercase tracking-wider text-ink-secondary">
            Settings
          </h2>
          <div className="overflow-hidden rounded-2xl border border-border bg-white">
            {settingsRows.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="flex min-h-11 items-center gap-3 border-b border-border-subtle px-4 font-body text-[15px] font-bold text-ink last:border-b-0 active:bg-surface-mid"
                >
                  <Icon size={19} aria-hidden className="shrink-0 text-primary-900" />
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  <ChevronRight size={18} aria-hidden className="shrink-0 text-ink-muted" />
                </Link>
              );
            })}
          </div>
        </section>
      )}

      <button
        type="button"
        onClick={() => void logout()}
        className="flex min-h-12 w-full items-center gap-3 rounded-2xl border border-border bg-white px-4 text-left font-body text-[15px] font-bold text-rose-700 active:bg-rose-50"
      >
        <LogOut size={20} aria-hidden />
        Sign out
      </button>
    </div>
  );
}
