"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { ChevronDown, ChevronRight, ChevronLeft, Code2, LayoutDashboard, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

import { createClient } from "@/lib/supabase/client";
import { AnrilLogo } from "@/components/logo";
import { getVisibleSettingsItems, SETTINGS_GROUP_ORDER, SETTINGS_ITEMS } from "@/components/settingsNavigation";
import { useBrainCount } from "@/hooks/useBrainCount";
import { BrainNavBadge } from "@/components/brain/BrainNavBadge";
import { SidebarSection } from "@/components/nav/SidebarSection";
import {
  ANALYTICS_LINK, NAV_SECTIONS, TC_FEATURE_MAP, TC_PERMISSION_MAP, TELECALLING_ITEMS,
  dashboardEntry, resolveSectionOpen, sectionContainsPage, visibleEntries,
  type NavAccess, type NavBadgeKey, type NavEntry, type NavGroup, type NavLeaf,
} from "@/components/nav/navSections";

type NavItem = { href: string; label: string };

// The sidebar sits on navy (--navy, #0A1528): idle rows are soft white, the
// active row is a teal tint with a bright teal bar so it reads on dark.
const ACTIVE_BAR =
  "w-1 h-3.5 rounded-full bg-[var(--primary-400)] -ml-0.5 mr-0.5 flex-shrink-0 shadow-[0_0_8px_rgba(var(--primary-400-rgb),0.6)]";
const ACTIVE_LABEL = "text-white font-semibold tracking-tight";
const ROW_ACTIVE = "bg-[rgba(var(--primary-400-rgb),0.14)] border-[rgba(var(--primary-400-rgb),0.28)]";
const ROW_IDLE = "border-transparent text-slate-300 hover:bg-white/[0.06] hover:text-white";
const ICON_ACTIVE = "text-[var(--primary-300)]";
const ICON_IDLE = "text-slate-300 group-hover:text-white";
const GROUP_BUTTON =
  "flex items-center gap-2.5 px-2 py-2.5 w-full rounded-xl text-[13px] font-semibold text-left transition-all group focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary-400)]";

function MainNavItem({
  href,
  active,
  icon: Icon,
  label,
  badge,
}: {
  href: string;
  active: boolean;
  icon: LucideIcon;
  label: string;
  badge?: React.ReactNode;
}) {
  const router = useRouter();
  return (
    <Link
      href={href}
      prefetch={true}
      aria-current={active ? "page" : undefined}
      onMouseEnter={() => router.prefetch(href)}
      className={cn(
        "flex min-h-10 items-center gap-2 px-2 py-2 rounded-xl text-[13px] transition-all duration-150 border group focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary-400)]",
        active
          ? ROW_ACTIVE
          : ROW_IDLE
      )}
    >
      {active && <span className={ACTIVE_BAR} />}
      <Icon
        size={16}
        className={cn("flex-shrink-0", active ? ICON_ACTIVE : ICON_IDLE)}
      />
      <span className={cn("min-w-0 flex-grow whitespace-normal leading-5", active ? ACTIVE_LABEL : "font-medium")}>{label}</span>
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
  const router = useRouter();
  const Icon = group.icon;
  const active = group.isActive(pathname);
  // Most specific (longest href) match wins, so Dialer at /dashboard/telecalling
  // does not also light up on /dashboard/telecalling/scheduled.
  const bestHref = items
    .filter((i) => pathname === i.href || pathname.startsWith(i.href + "/"))
    .reduce<string | null>((best, i) => (!best || i.href.length > best.length ? i.href : best), null);
  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={cn(GROUP_BUTTON, active ? "text-[var(--primary-300)]" : "text-slate-300 hover:bg-white/[0.06] hover:text-white")}
      >
        <Icon size={16} className={active ? ICON_ACTIVE : ICON_IDLE} />
        <span className="flex-1">{group.label}</span>
        {open ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronRight size={14} className="text-slate-400" />}
      </button>
      {open && (
        <div className="space-y-0.5">
          {items.map((item, idx) => {
            const isActive = bestHref === item.href;
            const isLast = idx === items.length - 1;
            return (
              <div key={item.href} className="relative pl-4 flex min-h-9 items-center">
                <div className={cn("absolute left-3 w-px bg-white/15", isLast ? "top-0 h-[18px]" : "-top-1 bottom-0")} />
                <div className="absolute left-3 top-1/2 -translate-y-1 w-3.5 h-3.5 border-l border-b border-white/15 rounded-bl-lg" />
                <Link
                  href={item.href}
                  prefetch={true}
                  onMouseEnter={() => router.prefetch(item.href)}
                  className={cn(
                    "flex min-w-0 flex-1 items-center gap-2 ml-1 px-2 py-1.5 rounded-xl text-xs transition-all duration-150 group border focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary-400)]",
                    isActive
                      ? ROW_ACTIVE
                      : ROW_IDLE
                  )}
                >
                  {isActive && <span className="w-1 h-3 rounded-full bg-[var(--primary-400)] mr-1 flex-shrink-0 shadow-[0_0_8px_rgba(var(--primary-400-rgb),0.6)]" />}
                  <span className={cn("min-w-0 flex-1 whitespace-normal leading-5", isActive ? ACTIVE_LABEL : "font-medium")}>{item.label}</span>
                  {item.href === "/dashboard/telecalling" && alertCount > 0 && (
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-600 font-bold text-[9px] min-w-[16px] text-center">
                      {alertCount > 9 ? "9+" : alertCount}
                    </span>
                  )}
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SettingsGroupButton({ group, active, onOpen }: { group: NavGroup; active: boolean; onOpen: () => void }) {
  const Icon = group.icon;
  return (
    <button type="button" onClick={onOpen} className={cn(GROUP_BUTTON, active ? "text-[var(--primary-300)]" : "text-slate-300 hover:bg-white/[0.06] hover:text-white")}>
      <Icon size={16} className={active ? ICON_ACTIVE : ICON_IDLE} />
      <span className="flex-1">{group.label}</span>
      <ChevronRight size={14} className="text-slate-400" />
    </button>
  );
}

interface SidebarProps {
  /** Accepted so existing callers compile. The sidebar always renders the full 220px layout. */
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
      <aside className="swiss-sidebar fixed left-0 top-0 h-full overflow-hidden rounded-r-[28px] bg-[var(--navy)] border-r border-white/[0.06] z-20 w-[220px]" />
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
        <span className="flex-shrink-0 px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-600 font-bold text-[9px] min-w-[16px] text-center">
          {inboxCount}
        </span>
      ) : undefined;
    }
    if (key === "brain") {
      return brainCount ? <BrainNavBadge count={brainCount} variant="row" /> : undefined;
    }
    return undefined;
  };

  const renderLeaf = (leaf: NavLeaf) => (
    <MainNavItem
      key={leaf.key}
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
        active={isSettingsActive}
        onOpen={() => toggleGroup("Settings")}
      />
    );
  };

  const renderEntry = (entry: NavEntry) => (entry.kind === "link" ? renderLeaf(entry) : renderGroup(entry));

  return (
    <aside className="swiss-sidebar fixed left-0 top-0 h-full overflow-hidden rounded-r-[28px] bg-[var(--navy)] border-r border-white/[0.06] [color-scheme:dark] flex flex-col z-20 select-none w-[220px]">
      {/* Brand: h-16 matches the header so the divider lines up. shrink-0 keeps it from compressing. */}
      <div className="h-16 shrink-0 flex items-center border-b border-white/[0.08] px-5">
        <AnrilLogo className="h-6 w-auto text-white" />
      </div>

      {showSettings ? (
        <div className="flex-grow overflow-y-auto px-3 py-4 space-y-1 scrollbar-thin">
          <button
            type="button"
            onClick={() => {
              setExpandedGroups((prev) => ({ ...prev, Settings: false }));
              router.push("/dashboard");
            }}
            className="flex items-center gap-2 px-2 py-2 mb-2 w-full rounded-xl text-left text-sm font-bold text-white transition-all hover:bg-white/[0.06]"
          >
            <ChevronLeft size={16} />
            <span>Settings</span>
          </button>

          {SETTINGS_GROUP_ORDER.map((group) => {
            const groupItems = visibleSettingsItems.filter((i) => i.group === group);
            if (groupItems.length === 0) return null;
            return (
              <div key={group} className="pt-2 first:pt-0">
                <div className="px-3 pb-1 font-label text-[10px] font-bold uppercase tracking-wider text-slate-300">
                  {group}
                </div>
                {groupItems.map((item) => {
                  const matches = visibleSettingsItems.filter(
                    (i) => pathname === i.href || pathname.startsWith(i.href + "/")
                  );
                  const bestMatch = matches.reduce<NavItem | null>(
                    (best, i) => (!best || i.href.length > best.href.length ? i : best), null
                  );
                  const active = bestMatch?.href === item.href;

                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      prefetch={true}
                      onMouseEnter={() => router.prefetch(item.href)}
                      className={cn(
                        "flex items-center px-3 py-1.5 rounded-xl text-sm transition-all duration-150 border",
                        active
                          ? ROW_ACTIVE
                          : ROW_IDLE
                      )}
                    >
                      {active && (
                        <span className="w-1 h-3.5 rounded-full bg-[var(--primary-400)] mr-2 flex-shrink-0 shadow-[0_0_8px_rgba(var(--primary-400-rgb),0.6)]" />
                      )}
                      <span className={cn("truncate", active ? ACTIVE_LABEL : "font-medium")}>{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex-grow min-h-0 overflow-y-auto px-3 py-4 space-y-3 scrollbar-thin">
          <div className="rounded-2xl bg-navy-800 p-1.5 space-y-1">
            <MainNavItem
              href={dashboard.href}
              active={pathname === dashboard.href}
              icon={LayoutDashboard}
              label={dashboard.label}
            />
            {renderLeaf(ANALYTICS_LINK)}
          </div>

          {NAV_SECTIONS.map((section) => {
            const entries = visibleEntries(section, access);
            if (entries.length === 0) return null;
            const open = resolveSectionOpen(
              sectionChoice[section.key],
              section.defaultOpen,
              sectionContainsPage(section, pathname),
            );
            return (
              <div key={section.key} className="rounded-2xl bg-navy-800 p-1.5 [&>div]:pt-0 [&>div>button]:py-3 [&>div>button]:px-2 [&>div>button]:gap-2 [&>div>button]:focus-visible:outline [&>div>button]:focus-visible:outline-2 [&>div>button]:focus-visible:outline-[var(--primary-400)] [&>div>button>span]:whitespace-normal [&>div>button>span]:leading-4 [&>div>button>svg]:shrink-0 [&>div>div]:ml-2 [&>div>div]:border-l [&>div>div]:border-white/15 [&>div>div]:pl-1 [&>div>div]:pb-1">
                <SidebarSection
                  title={section.title}
                  open={open}
                  onToggle={() => setSectionChoice((prev) => ({ ...prev, [section.key]: !open }))}
                >
                  {entries.map(renderEntry)}
                </SidebarSection>
              </div>
            );
          })}
        </div>
      )}

      {/* Pinned footer: Developer. Stays out of the scrolling list, as before. */}
      {isSubscribed && canSettings && (
        <div className="shrink-0 border-t border-white/[0.08] px-3 py-2">
          <MainNavItem
            href="/dashboard/developer"
            active={pathname.startsWith("/dashboard/developer")}
            icon={Code2}
            label="Developer"
          />
        </div>
      )}
    </aside>
  );
}
