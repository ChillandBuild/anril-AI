"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { ChevronRight, ChevronLeft, Code2, LayoutDashboard, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

import { createClient } from "@/lib/supabase/client";
import { AnrilMarkRow } from "@/components/logo";
import { getVisibleSettingsItems, SETTINGS_GROUP_ORDER, SETTINGS_ITEMS } from "@/components/settingsNavigation";
import { useBrainCount } from "@/hooks/useBrainCount";
import { BrainNavBadge } from "@/components/brain/BrainNavBadge";
import { SidebarSection, inertWhen } from "@/components/nav/SidebarSection";
import { ActiveIndicator } from "@/components/nav/ActiveIndicator";
import {
  ANALYTICS_LINK, NAV_SECTIONS, TC_FEATURE_MAP, TC_PERMISSION_MAP, TELECALLING_ITEMS,
  dashboardEntry, resolveSectionOpen, sectionContainsPage, visibleEntries,
  type NavAccess, type NavBadgeKey, type NavEntry, type NavGroup, type NavLeaf,
} from "@/components/nav/navSections";

type NavItem = { href: string; label: string };

// Styled to the v2 sidebar study: navy (--navy, #0A1528) with white labels
// (--nav-label) and pale-teal icons. The active row's teal tint wipes in
// (.nav-active in globals.css) as the shared teal square (ActiveIndicator)
// lands on it. Rows inside an open section's box (.nav-children) are smaller,
// have no icon, and step right when active.
const ROW =
  "group relative isolate z-[2] flex w-full items-center gap-3 rounded-lg text-left text-[var(--nav-label)] transition-[padding] duration-300 ease-[cubic-bezier(.16,1,.3,1)] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary-400)]";
const ROW_TOP = "min-h-10 p-2.5 text-[13px]";
const ROW_NESTED = "min-h-[35px] py-2.5 pr-2.5 text-[12px]";
const nestedPad = (active: boolean) => (active ? "pl-[26px]" : "pl-5");
const ICON = "nav-icon shrink-0 text-[#d5f4f4]";
const BADGE = "flex-shrink-0 px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-600 font-bold text-[9px] min-w-[16px] text-center";

function MainNavItem({
  href,
  active,
  icon: Icon,
  label,
  badge,
  nested = false,
  pad,
}: {
  href: string;
  active: boolean;
  icon?: LucideIcon;
  label: string;
  badge?: React.ReactNode;
  nested?: boolean;
  /** Left padding override for rows nested one level deeper (Telecalling pages). */
  pad?: string;
}) {
  const router = useRouter();
  return (
    <Link
      href={href}
      prefetch={true}
      aria-current={active ? "page" : undefined}
      onMouseEnter={() => router.prefetch(href)}
      className={cn(
        ROW,
        nested ? cn(ROW_NESTED, pad ?? nestedPad(active)) : ROW_TOP,
        active && "nav-active font-semibold",
      )}
    >
      {!nested && Icon && <Icon size={17} strokeWidth={1.6} className={ICON} aria-hidden="true" />}
      <span className="min-w-0 flex-1 whitespace-normal leading-5">{label}</span>
      {badge}
    </Link>
  );
}

function TelecallingGroup({
  group,
  items,
  alertCount,
  open,
  onToggle,
  pathname,
}: {
  group: NavGroup;
  items: readonly NavItem[];
  alertCount: number;
  open: boolean;
  onToggle: () => void;
  pathname: string;
}) {
  const active = group.isActive(pathname);
  // Most specific (longest href) match wins, so Dialer at /dashboard/telecalling
  // does not also light up on /dashboard/telecalling/scheduled.
  const bestHref = items
    .filter((i) => pathname === i.href || pathname.startsWith(i.href + "/"))
    .reduce<string | null>((best, i) => (!best || i.href.length > best.length ? i.href : best), null);
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={cn(ROW, ROW_NESTED, "pl-5 font-semibold")}
      >
        <span className="min-w-0 flex-1">{group.label}</span>
        <span className={cn("nav-held-dot", !open && active && "is-on")} aria-hidden="true" />
        <ChevronRight size={13} strokeWidth={1.6} className="nav-chevron shrink-0" aria-hidden="true" />
      </button>
      <div className={cn("nav-expander", open && "open")} {...inertWhen(!open)}>
        <div>
          <div className="nav-children-flat">
            {items.map((item) => {
              const isActive = bestHref === item.href;
              return (
                <MainNavItem
                  key={item.href}
                  nested
                  pad={isActive ? "pl-[38px]" : "pl-8"}
                  href={item.href}
                  active={isActive}
                  label={item.label}
                  badge={item.href === "/dashboard/telecalling" && alertCount > 0 ? (
                    <span className={BADGE}>{alertCount > 9 ? "9+" : alertCount}</span>
                  ) : undefined}
                />
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingsGroupButton({ group, onOpen }: { group: NavGroup; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className={cn(ROW, ROW_NESTED, "pl-5")}>
      <span className="min-w-0 flex-1">{group.label}</span>
      <ChevronRight size={13} strokeWidth={1.6} className="shrink-0" aria-hidden="true" />
    </button>
  );
}

interface SidebarProps {
  /** Accepted so existing callers compile. The sidebar always renders the full desktop layout. */
  collapsed?: boolean;
  /** Accepted so existing callers compile. The logo always renders. */
  hideLogo?: boolean;
}

// Props are accepted for caller compatibility only; the layout ignores them.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function Sidebar(_props: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { role, permissions, enabledFeatures, loading: roleLoading } = useAuthRole();
  const [inboxCount, setInboxCount] = useState(0);
  const [alertCount, setAlertCount] = useState(0);
  const [subStatus, setSubStatus] = useState<"loading" | "active" | "none" | "pending_approval">("loading");
  const [purchasedFeatures, setPurchasedFeatures] = useState<string[]>([]);
  // The logo's squares drop in on first show, then wave on each page change.
  const markAnim = useRef<{ path: string; cls: string } | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/subscriptions/me`, { headers: auth });
        if (res.ok && active) {
          const data = await res.json();
          setSubStatus(data.status);
          setPurchasedFeatures((data.items ?? []).map((item: { feature_key: string }) => item.feature_key));
        } else if (active) {
          setSubStatus("active");
        }
      } catch {
        if (active) setSubStatus("active");
      }
    })();
    return () => { active = false; };
  }, []);

  // Nested group open state (Telecalling, Settings), unchanged from before.
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    Telecalling: false,
    Settings: false,
  });
  // Per-section explicit choice. undefined = not set, so the default or active page decides.
  const [sectionChoice, setSectionChoice] = useState<Record<string, boolean | undefined>>({});

  const toggleGroup = (groupName: string) => {
    setExpandedGroups(prev => ({ ...prev, [groupName]: !prev[groupName] }));
  };

  const fetchCount = useCallback(async () => {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/chat-handovers/count`, { headers: auth });
      if (res.ok) setInboxCount((await res.json()).count ?? 0);
    } catch {}
  }, []);

  const waEnabled = enabledFeatures.includes("whatsapp");
  const outboundOn = enabledFeatures.includes("outbound_messaging");
  const inboundOn = enabledFeatures.includes("inbound_messaging");
  const messagingOn = outboundOn || inboundOn;
  // Telecalling is purchased as a SIM or Tele-CMI bundle (each pulls in its own
  // telecalling.* sub-features); there is no bare "telecalling" key anymore.
  const telecallingOn = enabledFeatures.some(
    (f) => f === "telecalling_sim" || f === "telecalling_telecmi" || f.startsWith("telecalling.")
  );
  const canManageTeam = role === "owner" || permissions.includes("team.manage");
  // Brain has its own Roles toggle (brain.view). Computed up here so the count
  // hook stays above the early return and hook order never changes.
  const brainGate =
    subStatus === "active" &&
    messagingOn &&
    (role === "owner" || permissions.includes("brain.view"));
  const brainCount = useBrainCount(brainGate);

  useEffect(() => {
    if (!telecallingOn || !canManageTeam) return;
    let stopped = false;
    const poll = async () => {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/calls/alerts/count`, { headers: auth });
        if (res.ok && !stopped) setAlertCount((await res.json()).count ?? 0);
      } catch {}
    };
    void poll();
    const id = setInterval(poll, 60_000);
    return () => { stopped = true; clearInterval(id); };
  }, [telecallingOn, canManageTeam]);

  useEffect(() => {
    if (!waEnabled) return;
    fetchCount();

    const supabase = createClient();
    const channel = supabase
      .channel("inbox-count-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "chat_handovers" }, () => {
        fetchCount();
      })
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [waEnabled, fetchCount]);

  if (roleLoading || subStatus === "loading") {
    return (
      <aside className="swiss-sidebar fixed left-0 top-0 h-full overflow-hidden rounded-r-3xl bg-[var(--navy)] z-20 w-[var(--sidebar-width)]" />
    );
  }

  const isSubscribed = subStatus === "active";
  const can = (permission: string) => role === "owner" || permissions.includes(permission);
  const canAny = (items: string[]) => role === "owner" || items.some((permission) => permissions.includes(permission));

  // Gate telecalling sub-items by sub-feature flags with backwards compatibility
  const hasTcSubFeatures = enabledFeatures.some(f => f.startsWith("telecalling."));
  const visibleTcItems = hasTcSubFeatures
    ? TELECALLING_ITEMS.filter(item => {
        const featureKey = TC_FEATURE_MAP[item.href];
        return !featureKey || enabledFeatures.includes(featureKey);
      })
    : TELECALLING_ITEMS;

  const tcGroupItems = visibleTcItems.filter((item) => {
    const permissionKeys = TC_PERMISSION_MAP[item.href];
    return !permissionKeys || canAny(permissionKeys);
  });

  const showTc = Boolean(expandedGroups.Telecalling);
  const canSettings = canAny(["settings.view", "settings.manage"]);
  const visibleSettingsItems = getVisibleSettingsItems(purchasedFeatures);
  const canServices = canAny(["services.view", "services.manage"]);
  const isSettingsActive = SETTINGS_ITEMS.some(item => pathname.startsWith(item.href));
  const showSettings = expandedGroups.Settings || isSettingsActive;

  const access: NavAccess = {
    isSubscribed,
    messagingOn,
    inboundOn,
    outboundOn,
    smsOn: enabledFeatures.includes("sms"),
    canServices,
    canSettings,
    brainGate,
    telecallingVisible: isSubscribed && telecallingOn && tcGroupItems.length > 0,
    can,
    canAny,
  };
  const dashboard = dashboardEntry(access);

  const renderBadge = (key: NavBadgeKey | undefined) => {
    if (key === "conversations") {
      return inboxCount > 0 ? (
        <span className={BADGE}>
          {inboxCount}
        </span>
      ) : undefined;
    }
    if (key === "brain") {
      return brainCount ? <BrainNavBadge count={brainCount} variant="row" /> : undefined;
    }
    return undefined;
  };

  const renderLeaf = (leaf: NavLeaf, nested = false) => (
    <MainNavItem
      key={leaf.key}
      nested={nested}
      href={leaf.href}
      active={leaf.isActive(pathname)}
      icon={leaf.icon}
      label={leaf.label}
      badge={renderBadge(leaf.badge)}
    />
  );

  const renderGroup = (group: NavGroup) => {
    if (group.key === "telecalling") {
      return (
        <TelecallingGroup
          key={group.key}
          group={group}
          items={tcGroupItems}
          alertCount={alertCount}
          open={showTc}
          onToggle={() => toggleGroup("Telecalling")}
          pathname={pathname}
        />
      );
    }
    return (
      <SettingsGroupButton
        key={group.key}
        group={group}
        onOpen={() => toggleGroup("Settings")}
      />
    );
  };

  const renderEntry = (entry: NavEntry) => (entry.kind === "link" ? renderLeaf(entry, true) : renderGroup(entry));

  const renderSection = (section: (typeof NAV_SECTIONS)[number]) => {
    const entries = visibleEntries(section, access);
    if (entries.length === 0) return null;
    const holdsActive = sectionContainsPage(section, pathname);
    const open = resolveSectionOpen(sectionChoice[section.key], section.defaultOpen, holdsActive);
    return (
      <SidebarSection
        key={section.key}
        title={section.title}
        icon={section.icon}
        open={open}
        holdsActive={holdsActive}
        onToggle={() => setSectionChoice((prev) => ({ ...prev, [section.key]: !open }))}
      >
        {entries.map(renderEntry)}
      </SidebarSection>
    );
  };

  if (markAnim.current?.path !== pathname) {
    markAnim.current = { path: pathname, cls: markAnim.current ? "anril-mark-wave" : "anril-mark-in" };
  }

  return (
    <aside className="swiss-sidebar fixed left-0 top-0 h-full overflow-hidden rounded-r-3xl bg-[var(--navy)] [--nav-label:#fff] [color-scheme:dark] flex flex-col z-20 select-none w-[var(--sidebar-width)] pt-[22px] pb-[18px] text-white">
      <div className="shrink-0 px-3.5">
        {/* Keyed on the page so the squares replay their wave on every navigation. */}
        <Link
          key={pathname}
          href={dashboard.href}
          aria-label="anril AI home"
          className={cn("anril-mark mb-[26px] block w-max px-2.5 pt-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary-400)]", markAnim.current.cls)}
        >
          <AnrilMarkRow height={15} accent="#3fbcbf" className="block w-auto overflow-visible text-white" />
        </Link>
      </div>

      {showSettings ? (
        <div className="relative min-h-0 flex-grow overflow-y-auto px-3.5 scrollbar-thin">
          <button
            type="button"
            onClick={() => {
              setExpandedGroups((prev) => ({ ...prev, Settings: false }));
              router.push("/dashboard");
            }}
            className={cn(ROW, ROW_TOP, "mb-2 font-semibold")}
          >
            <ChevronLeft size={17} strokeWidth={1.6} className={ICON} aria-hidden="true" />
            <span>Settings</span>
          </button>

          {SETTINGS_GROUP_ORDER.map((group) => {
            const groupItems = visibleSettingsItems.filter((i) => i.group === group);
            if (groupItems.length === 0) return null;
            return (
              <div key={group} className="pt-3 first:pt-0">
                <div className="mb-2 px-2.5 text-[9px] uppercase tracking-[.14em] text-[#78d6d8]">
                  {group}
                </div>
                {groupItems.map((item) => {
                  const matches = visibleSettingsItems.filter(
                    (i) => pathname === i.href || pathname.startsWith(i.href + "/")
                  );
                  const bestMatch = matches.reduce<NavItem | null>(
                    (best, i) => (!best || i.href.length > best.href.length ? i : best), null
                  );
                  return (
                    <MainNavItem
                      key={item.href}
                      href={item.href}
                      active={bestMatch?.href === item.href}
                      label={item.label}
                    />
                  );
                })}
              </div>
            );
          })}
          <ActiveIndicator pathname={pathname} />
        </div>
      ) : (
        <>
          <div className="mb-2 shrink-0 px-6 text-[9px] tracking-[.14em] text-[#78d6d8]">WORKSPACE</div>
          <nav aria-label="Main" className="relative min-h-0 flex-grow overflow-y-auto px-3.5 scrollbar-thin">
            <MainNavItem
              href={dashboard.href}
              active={pathname === dashboard.href}
              icon={LayoutDashboard}
              label={dashboard.label}
            />
            {renderLeaf(ANALYTICS_LINK)}
            <div className="mx-2 my-3.5 h-px bg-[var(--navy-800)]" />
            {NAV_SECTIONS.map((section) => renderSection(section))}
            <ActiveIndicator pathname={pathname} />
          </nav>
        </>
      )}

      {/* Pinned footer: Developer. Stays out of the scrolling list, as before. */}
      {isSubscribed && canSettings && (
        <div className="relative mx-3.5 mt-auto shrink-0 border-t border-[var(--navy-800)] pt-3.5">
          <MainNavItem
            href="/dashboard/developer"
            active={pathname.startsWith("/dashboard/developer")}
            icon={Code2}
            label="Developer"
          />
          <ActiveIndicator pathname={pathname} />
        </div>
      )}
    </aside>
  );
}
