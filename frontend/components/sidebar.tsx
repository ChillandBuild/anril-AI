"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { ChevronLeft, ChevronsLeft, Code2, LayoutDashboard, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

import { createClient } from "@/lib/supabase/client";
import { AnrilMarkRow } from "@/components/logo";
import { activeSettingsItem, groupSettingsItems, isSettingsPath, settingsItemsFor, type SettingsNavItem } from "@/components/settingsNavigation";
import { useBrainCount } from "@/hooks/useBrainCount";
import { NavCount, navCountLabel } from "@/components/nav/NavCount";
import { ActiveIndicator } from "@/components/nav/ActiveIndicator";
import { useSidebarRail } from "@/components/nav/useSidebarRail";
import { useNavAccess } from "@/components/nav/useNavAccess";
import { SidebarProductSwitch } from "@/components/nav/ProductSwitch";
import {
  NAV_ROWS,
  dashboardEntry, leafHref,
  type NavBadgeKey, type NavLeaf,
} from "@/components/nav/navSections";

// Styled to the v2 sidebar study: navy (--navy, #0A1528) with white labels
// (--nav-label) and pale-teal icons. The active row's teal tint wipes in
// (.nav-active in globals.css) as the shared teal square (ActiveIndicator)
// lands on it. Every module is one flat row (no fold-out groups): its pages are
// the tab bar under the page header (ModuleTabBar); the square lands in space
// kept free at the row's right end.
const ROW =
  "group relative isolate z-[2] flex w-full items-center gap-3 rounded-lg text-left text-[var(--nav-label)] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--primary-400)]";
const ROW_TOP = "min-h-10 p-2.5 text-[13px]";
const ICON = "nav-icon shrink-0 text-[#d5f4f4]";

function MainNavItem({
  href,
  active,
  icon: Icon,
  label,
  count = 0,
}: {
  href: string;
  active: boolean;
  icon?: LucideIcon;
  label: string;
  /** Waiting items (unanswered chats, call alerts), drawn on the icon's corner. */
  count?: number;
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
        ROW_TOP,
        active && "nav-active font-semibold",
      )}
    >
      {Icon && (
        <span className="relative flex shrink-0">
          <Icon size={17} strokeWidth={1.6} className={ICON} aria-hidden="true" />
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

interface SidebarProps {
  /** Accepted so existing callers compile. The sidebar always renders the full desktop layout. */
  collapsed?: boolean;
  /** Accepted so existing callers compile. The logo always renders. */
  hideLogo?: boolean;
}

const SIDEBAR_BLANK = "swiss-sidebar sb-anril fixed left-0 top-0 h-full overflow-hidden rounded-r-3xl z-20 w-[var(--sidebar-width)]";

// Props are accepted for caller compatibility only; the layout ignores them.
// The menu reads ?tab= (Calling and Leads to call split the Upload and Team pages by it), and
// useSearchParams needs a Suspense boundary the sidebar's parents do not provide, so it brings its own.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function Sidebar(_props: SidebarProps) {
  return (
    <Suspense fallback={<aside className={SIDEBAR_BLANK} />}>
      <SidebarMenu />
    </Suspense>
  );
}

function SidebarMenu() {
  const pathname = usePathname();
  // The ?tab= of the page ("" when none): lets one path light up different rows.
  const tab = useSearchParams()?.get("tab") ?? "";
  // Changes with the page or its tab, so the teal square hops on a tab change too.
  const pageKey = tab ? `${pathname}?tab=${tab}` : pathname;
  const router = useRouter();
  const { access, waEnabled, telecallingOn, canManageTeam, roleLoading, purchasedFeatures, claudeOn } = useNavAccess();
  const [inboxCount, setInboxCount] = useState(0);
  const [alertCount, setAlertCount] = useState(0);
  // The logo's squares drop in on first show, then wave on each page change.
  const markAnim = useRef<{ path: string; cls: string } | null>(null);
  const fold = useSidebarRail(pathname);

  const fetchCount = useCallback(async () => {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/chat-handovers/count`, { headers: auth });
      if (res.ok) setInboxCount((await res.json()).count ?? 0);
    } catch {}
  }, []);

  // Above the early return so hook order never changes.
  const brainCount = useBrainCount(access.brainGate);

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
    return <aside className={SIDEBAR_BLANK} />;
  }

  const { isSubscribed, canSettings } = access;
  // The Settings row opens /dashboard/settings, so the sidebar swaps to the Settings list
  // exactly when the page is a Settings page (home, its pages, Team & roles, Plans & subscription).
  const showSettings = isSettingsPath(pathname);
  const visibleSettingsItems = settingsItemsFor(access, purchasedFeatures, claudeOn);
  const settingsList = groupSettingsItems(visibleSettingsItems);
  const activeSettings = activeSettingsItem(visibleSettingsItems, pathname);
  const renderSettingsItem = (item: SettingsNavItem) => (
    <MainNavItem key={item.href} href={item.href} active={activeSettings?.href === item.href} label={item.label} />
  );

  const dashboard = dashboardEntry(access);

  // Counts ride on the module rows: Chats, Anril Setup (Brain) and Call IQ (call alerts).
  const badgeCount = (key: NavBadgeKey | undefined) =>
    key === "conversations" ? inboxCount : key === "brain" ? (brainCount ?? 0) : key === "alerts" ? alertCount : 0;

  const renderLeaf = (leaf: NavLeaf) => (
    <MainNavItem
      key={leaf.key}
      href={leafHref(leaf, access)}
      active={leaf.isActive(pathname, tab)}
      icon={leaf.icon}
      label={leaf.label}
      count={badgeCount(leaf.badge)}
    />
  );

  if (markAnim.current?.path !== pathname) {
    markAnim.current = { path: pathname, cls: markAnim.current ? "anril-mark-wave" : "anril-mark-in" };
  }

  return (
    <aside
      data-rail={fold.rail || undefined}
      data-peek={fold.peek || undefined}
      {...fold.handlers}
      className="swiss-sidebar sidebar-shell sb-anril fixed left-0 top-0 h-full overflow-hidden rounded-r-3xl [--nav-label:#fff] [color-scheme:dark] flex flex-col z-20 select-none pt-[22px] pb-[18px] text-white"
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

      <SidebarProductSwitch />

      {showSettings ? (
        <GlowScroll className="px-3.5">
          <button
            type="button"
            onClick={() => router.push("/dashboard")}
            className={cn(ROW, ROW_TOP, "mb-2 font-semibold")}
          >
            <ChevronLeft size={17} strokeWidth={1.6} className={ICON} aria-hidden="true" />
            <span className="nav-lbl truncate">Settings</span>
          </button>

          {settingsList.groups.map(({ group, items }) => (
            <div key={group} className="pt-3 first:pt-0">
              <div className="nav-ws mb-2 truncate px-2.5 text-[9px] uppercase tracking-[.14em] text-[#78d6d8]">
                {group}
              </div>
              {items.map(renderSettingsItem)}
            </div>
          ))}
          {settingsList.loose.length > 0 && (
            <div className="pt-3 first:pt-0">{settingsList.loose.map(renderSettingsItem)}</div>
          )}
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
            {NAV_ROWS.map((leaf) => (leaf.visible(access) ? renderLeaf(leaf) : null))}
            <ActiveIndicator pathname={pageKey} />
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
