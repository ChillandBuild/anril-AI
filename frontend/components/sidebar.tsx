"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useSubscription } from "@/app/dashboard/contexts/SubscriptionContext";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { ChevronRight, ChevronLeft, ChevronsLeft, Code2, LayoutDashboard, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

import { createClient } from "@/lib/supabase/client";
import { AnrilMarkRow } from "@/components/logo";
import { getVisibleSettingsItems, SETTINGS_GROUP_ORDER, SETTINGS_ITEMS } from "@/components/settingsNavigation";
import { useBrainCount } from "@/hooks/useBrainCount";
import { SidebarSection, inertWhen } from "@/components/nav/SidebarSection";
import { NavCount, navCountLabel } from "@/components/nav/NavCount";
import { ActiveIndicator } from "@/components/nav/ActiveIndicator";
import { useSidebarRail } from "@/components/nav/useSidebarRail";
import {
  ANALYTICS_LINK, NAV_SECTIONS, TC_FEATURE_MAP, TC_PERMISSION_MAP, TELECALLING_ITEMS,
  dashboardEntry, resolveOpenSection, sectionContainsPage, visibleEntries,
  type NavAccess, type NavBadgeKey, type NavEntry, type NavGroup, type NavLeaf,
} from "@/components/nav/navSections";

type NavItem = { href: string; label: string; icon?: LucideIcon };

// Styled to the v2 sidebar study: navy (--navy, #0A1528) with white labels
// (--nav-label) and pale-teal icons. The active row's teal tint wipes in
// (.nav-active in globals.css) as the shared teal square (ActiveIndicator)
// lands on it. Rows inside an open section's box (.nav-children) are smaller,
// their icons look carved into the box (.nav-carved) and light up teal on the
// open page; the square lands in space kept free at the row's right end.
const ROW =
  "group relative isolate z-[2] flex w-full items-center gap-3 rounded-lg text-left text-[var(--nav-label)] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary-400)]";
const ROW_TOP = "min-h-10 p-2.5 text-[13px]";
const ROW_NESTED = "min-h-[35px] gap-2.5 py-2.5 pr-2.5 text-[12px]";
const ICON = "nav-icon shrink-0 text-[#d5f4f4]";
const CARVED = "nav-carved shrink-0";

function MainNavItem({
  href,
  active,
  icon: Icon,
  label,
  count = 0,
  nested = false,
  pad,
}: {
  href: string;
  active: boolean;
  icon?: LucideIcon;
  label: string;
  /** Waiting items (unanswered chats, call alerts), drawn on the icon's corner. */
  count?: number;
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
        nested ? cn(ROW_NESTED, "pr-7", pad ?? "pl-4") : ROW_TOP,
        active && "nav-active font-semibold",
      )}
    >
      {Icon && (
        <span className="relative flex shrink-0">
          <Icon size={nested ? 15 : 17} strokeWidth={1.6} className={nested ? CARVED : ICON} aria-hidden="true" />
          <NavCount count={count} />
        </span>
      )}
      <span className="nav-lbl min-w-0 flex-1 truncate leading-5">
        {label}
        <span className="sr-only">{navCountLabel(count)}</span>
      </span>
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
        className={cn(ROW, ROW_NESTED, "pl-4 font-semibold")}
      >
        <span className="relative flex shrink-0">
          <group.icon size={15} strokeWidth={1.6} className={CARVED} aria-hidden="true" />
          <NavCount count={alertCount} group shown={!open} />
        </span>
        <span className="nav-lbl min-w-0 flex-1 truncate">{group.label}</span>
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
                  pad="pl-[34px]"
                  href={item.href}
                  active={isActive}
                  icon={item.icon}
                  label={item.label}
                  count={item.href === "/dashboard/telecalling" ? alertCount : 0}
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
    <button type="button" onClick={onOpen} className={cn(ROW, ROW_NESTED, "pl-4")}>
      <group.icon size={15} strokeWidth={1.6} className={CARVED} aria-hidden="true" />
      <span className="nav-lbl min-w-0 flex-1 truncate">{group.label}</span>
      <ChevronRight size={13} strokeWidth={1.6} className="nav-chevron shrink-0" aria-hidden="true" />
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
  const { status: subStatus, purchasedFeatures } = useSubscription();
  // The logo's squares drop in on first show, then wave on each page change.
  const markAnim = useRef<{ path: string; cls: string } | null>(null);
  const fold = useSidebarRail(pathname);

  // Nested group open state (Telecalling, Settings), unchanged from before.
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    Telecalling: false,
    Settings: false,
  });
  // The section the user clicked open (null = all shut), for this page only:
  // a new page reopens the section that holds it. One open at a time.
  const [sectionChoice, setSectionChoice] = useState<{ path: string; key: string | null } | null>(null);
  const openSection = resolveOpenSection(
    sectionChoice?.path === pathname ? sectionChoice.key : undefined,
    NAV_SECTIONS,
    pathname,
  );

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

  if (roleLoading) {
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

  const badgeCount = (key: NavBadgeKey | undefined) =>
    key === "conversations" ? inboxCount : key === "brain" ? (brainCount ?? 0) : 0;
  // What a menu heading shows on its icon while its rows are hidden.
  const entryCount = (entry: NavEntry) =>
    entry.kind === "link" ? badgeCount(entry.badge) : entry.key === "telecalling" ? alertCount : 0;

  const renderLeaf = (leaf: NavLeaf, nested = false) => (
    <MainNavItem
      key={leaf.key}
      nested={nested}
      href={leaf.href}
      active={leaf.isActive(pathname)}
      icon={leaf.icon}
      label={leaf.label}
      count={badgeCount(leaf.badge)}
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
    const open = openSection === section.key;
    return (
      <SidebarSection
        key={section.key}
        title={section.title}
        icon={section.icon}
        open={open}
        holdsActive={holdsActive}
        count={entries.reduce((sum, entry) => sum + entryCount(entry), 0)}
        onToggle={() => {
          // On the folded strip a group icon peeks the menu with that group open.
          if (fold.folded) {
            fold.openPeek();
            setSectionChoice({ path: pathname, key: section.key });
            return;
          }
          setSectionChoice({ path: pathname, key: open ? null : section.key });
        }}
      >
        {entries.map(renderEntry)}
      </SidebarSection>
    );
  };

  if (markAnim.current?.path !== pathname) {
    markAnim.current = { path: pathname, cls: markAnim.current ? "anril-mark-wave" : "anril-mark-in" };
  }

  return (
    <aside
      data-rail={fold.rail || undefined}
      data-peek={fold.peek || undefined}
      {...fold.handlers}
      className="swiss-sidebar sidebar-shell fixed left-0 top-0 h-full overflow-hidden rounded-r-3xl bg-[var(--navy)] [--nav-label:#fff] [color-scheme:dark] flex flex-col z-20 select-none pt-[22px] pb-[18px] text-white"
    >
      {/* Flex centring keeps the logo centred even on the 64px strip, where it is wider than the space. */}
      <div className="flex shrink-0 justify-center px-3.5">
        {/* Keyed on the page so the squares replay their wave on every navigation. */}
        <Link
          key={pathname}
          href={dashboard.href}
          aria-label="anril AI home"
          className={cn("anril-mark mx-auto mb-[26px] block w-max shrink-0 px-2.5 pt-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary-400)]", markAnim.current.cls)}
        >
          <AnrilMarkRow height={15} accent="#3fbcbf" className="block w-auto overflow-visible text-white" />
        </Link>
      </div>

      {showSettings ? (
        <GlowScroll className="px-3.5">
          <button
            type="button"
            onClick={() => {
              setExpandedGroups((prev) => ({ ...prev, Settings: false }));
              router.push("/dashboard");
            }}
            className={cn(ROW, ROW_TOP, "mb-2 font-semibold")}
          >
            <ChevronLeft size={17} strokeWidth={1.6} className={ICON} aria-hidden="true" />
            <span className="nav-lbl truncate">Settings</span>
          </button>

          {SETTINGS_GROUP_ORDER.map((group) => {
            const groupItems = visibleSettingsItems.filter((i) => i.group === group);
            if (groupItems.length === 0) return null;
            return (
              <div key={group} className="pt-3 first:pt-0">
                <div className="nav-ws mb-2 truncate px-2.5 text-[9px] uppercase tracking-[.14em] text-[#78d6d8]">
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
        </GlowScroll>
      ) : (
        <>
          <div className="nav-ws mb-2 shrink-0 px-6 text-[9px] tracking-[.14em] text-[#78d6d8]">WORKSPACE</div>
          <GlowScroll as="nav" label="Main" className="px-3.5">
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
          </GlowScroll>
        </>
      )}

      {/* Pinned footer: Developer, and the button that folds the sidebar. Stays out of the scrolling list. */}
      <div className="relative mx-3.5 mt-auto shrink-0 border-t border-[var(--navy-800)] pt-3.5">
        {isSubscribed && canSettings && (
          <MainNavItem
            href="/dashboard/developer"
            active={pathname.startsWith("/dashboard/developer")}
            icon={Code2}
            label="Developer"
          />
        )}
        <button
          type="button"
          onClick={fold.toggle}
          aria-label={fold.rail ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(ROW, ROW_TOP)}
        >
          <ChevronsLeft size={17} strokeWidth={1.6} className={cn(ICON, "nav-fold-icon")} aria-hidden="true" />
          <span className="nav-lbl min-w-0 flex-1 truncate">{fold.rail ? "Expand" : "Collapse"}</span>
        </button>
        <ActiveIndicator pathname={pathname} />
      </div>
    </aside>
  );
}

// Scroll area for the navy sidebar. The browser's own scrollbar is hidden (its
// light-grey thumb looked like tape on navy). In its place: a teal pill that is
// invisible at rest, faint while the sidebar is hovered and bright while
// scrolling or dragging, plus navy fades at the top and bottom edges that show
// only when more menu sits past that edge. The pill can be dragged like a
// normal thumb. All updates are direct style writes, so scrolling never
// re-renders the menu.
const PILL_MIN = 28;

function GlowScroll({
  as: Tag = "div",
  label,
  className,
  children,
}: {
  as?: "div" | "nav";
  label?: string;
  className?: string;
  children: React.ReactNode;
}) {
  const scrollRef = useRef<HTMLElement | null>(null);
  const pillRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const liveTimer = useRef<number | undefined>(undefined);

  const measure = useCallback(() => {
    const el = scrollRef.current;
    const pill = pillRef.current;
    if (!el || !pill) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    const room = scrollHeight - clientHeight;
    const overflows = room > 1;
    topRef.current?.style.setProperty("opacity", scrollTop > 2 ? "1" : "0");
    bottomRef.current?.style.setProperty("opacity", scrollTop < room - 2 ? "1" : "0");
    pill.style.display = overflows ? "" : "none";
    if (!overflows) return;
    const h = Math.max(PILL_MIN, (clientHeight / scrollHeight) * clientHeight);
    const y = (scrollTop / room) * (clientHeight - h);
    pill.style.height = `${h}px`;
    pill.style.transform = `translateY(${y}px)`;
  }, []);

  const flashLive = useCallback(() => {
    const pill = pillRef.current;
    if (!pill) return;
    pill.dataset.live = "true";
    window.clearTimeout(liveTimer.current);
    liveTimer.current = window.setTimeout(() => {
      if (pill.dataset.drag !== "true") delete pill.dataset.live;
    }, 800);
  }, []);

  // Sections open and close with an animation, which changes the content
  // height without the scroller itself resizing. Watch every direct child too,
  // and re-attach when React adds or removes children.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(measure);
    const watch = () => {
      ro.disconnect();
      ro.observe(el);
      Array.from(el.children).forEach((c) => ro.observe(c));
      measure();
    };
    const mo = new MutationObserver(watch);
    mo.observe(el, { childList: true });
    watch();
    return () => {
      ro.disconnect();
      mo.disconnect();
      window.clearTimeout(liveTimer.current);
    };
  }, [measure]);

  const onPillDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = scrollRef.current;
    const pill = pillRef.current;
    if (!el || !pill) return;
    e.preventDefault();
    pill.setPointerCapture(e.pointerId);
    pill.dataset.drag = "true";
    pill.dataset.live = "true";
    const startY = e.clientY;
    const startTop = el.scrollTop;
    const ratio = (el.scrollHeight - el.clientHeight) / Math.max(1, el.clientHeight - pill.offsetHeight);
    const move = (ev: PointerEvent) => {
      el.scrollTop = startTop + (ev.clientY - startY) * ratio;
    };
    const up = () => {
      delete pill.dataset.drag;
      flashLive();
      pill.removeEventListener("pointermove", move);
      pill.removeEventListener("pointerup", up);
      pill.removeEventListener("pointercancel", up);
    };
    pill.addEventListener("pointermove", move);
    pill.addEventListener("pointerup", up);
    pill.addEventListener("pointercancel", up);
  };

  const fade = "pointer-events-none absolute inset-x-0 z-10 h-7 opacity-0 transition-opacity duration-200 motion-reduce:transition-none";

  return (
    <div className="group/scroll relative flex min-h-0 flex-grow flex-col">
      <Tag
        ref={(node: HTMLElement | null) => { scrollRef.current = node; }}
        aria-label={label}
        onScroll={() => { measure(); flashLive(); }}
        className={cn(
          "relative min-h-0 flex-grow overflow-y-auto overflow-x-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
          className,
        )}
      >
        {children}
      </Tag>
      <div ref={topRef} aria-hidden="true" className={cn(fade, "top-0 bg-gradient-to-b from-[var(--navy)] to-transparent")} />
      <div ref={bottomRef} aria-hidden="true" className={cn(fade, "bottom-0 bg-gradient-to-t from-[var(--navy)] to-transparent")} />
      {/* 10px-wide grab area; the visible pill is the 4px bar inside it. */}
      <div
        ref={pillRef}
        aria-hidden="true"
        onPointerDown={onPillDown}
        className="group/pill absolute right-0.5 top-0 z-20 flex w-2.5 cursor-grab touch-none justify-center opacity-0 transition-opacity duration-300 group-hover/scroll:opacity-50 data-[live=true]:!opacity-100 data-[drag=true]:cursor-grabbing motion-reduce:transition-none"
      >
        <div className="h-full w-1 rounded-full bg-[var(--navy-accent)] transition-[width] duration-150 group-data-[live=true]/pill:w-[5px]" />
      </div>
    </div>
  );
}
