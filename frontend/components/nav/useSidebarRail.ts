"use client";
import { useEffect, useLayoutEffect, useRef, useState, type FocusEvent } from "react";
import { sidebarFoldsOn } from "@/components/nav/navSections";

// Pause before a hover over the folded strip opens the full menu, so a
// pointer passing over it on the way somewhere else doesn't pop it open.
const PEEK_DELAY_MS = 150;

/**
 * Desktop sidebar fold state. Wide pages (sidebarFoldsOn) fold it to the
 * 64px icon strip; every other page opens it. The collapse button overrides
 * that for the current page only: the next page follows the rule again.
 * While folded, hovering or keyboard focus "peeks" the full menu over the
 * page without moving it.
 *
 * The fold is published as data-sidebar-rail on <html>, which switches
 * --sidebar-width (globals.css) for the layout, header and inbox at once.
 */
export function useSidebarRail(pathname: string) {
  const [override, setOverride] = useState<{ path: string; rail: boolean } | null>(null);
  const [peek, setPeek] = useState(false);
  const rail = override?.path === pathname ? override.rail : sidebarFoldsOn(pathname);
  const timer = useRef<number | undefined>(undefined);
  // When the sidebar folds under the pointer, hover must not peek again
  // until the pointer has left, or it would spring straight back open.
  const armed = useRef(true);
  const lastRail = useRef(rail);

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.toggleAttribute("data-sidebar-rail", rail);
    if (lastRail.current !== rail) {
      lastRail.current = rail;
      armed.current = false;
      window.clearTimeout(timer.current);
      setPeek(false);
    }
    // Cleared here, not in the passive cleanup below: the inbox and the other
    // pages mount separate sidebars, and a passive cleanup would run after the
    // new sidebar had set the attribute, leaving the page at 256px.
    return () => root.removeAttribute("data-sidebar-rail");
  }, [rail]);

  // Touch screens never send mouseleave, so close a peek on navigation there.
  useEffect(() => {
    if (window.matchMedia("(hover: none)").matches) setPeek(false);
  }, [pathname]);

  useEffect(() => {
    const root = document.documentElement;
    // Animate width changes only from the second frame on, so a page that
    // opens folded doesn't slide in on load.
    const frame = requestAnimationFrame(() => root.setAttribute("data-sidebar-anim", ""));
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer.current);
      root.removeAttribute("data-sidebar-anim");
    };
  }, []);

  const handlers = {
    onMouseEnter: () => {
      if (!rail || !armed.current) return;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setPeek(true), PEEK_DELAY_MS);
    },
    onMouseLeave: () => {
      armed.current = true;
      window.clearTimeout(timer.current);
      setPeek(false);
    },
    onFocus: (e: FocusEvent<HTMLElement>) => {
      if (rail && e.target.matches(":focus-visible")) setPeek(true);
    },
    onBlur: (e: FocusEvent<HTMLElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setPeek(false);
    },
  };

  return {
    rail,
    peek: rail && peek,
    /** Folded and not peeking: only the icons show. */
    folded: rail && !peek,
    toggle: () => setOverride({ path: pathname, rail: !rail }),
    openPeek: () => setPeek(true),
    handlers,
  };
}
