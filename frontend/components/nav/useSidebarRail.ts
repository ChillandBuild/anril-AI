"use client";
import { useEffect, useLayoutEffect, useRef, useState, type FocusEvent } from "react";
import { sidebarFoldsOn } from "@/components/nav/navSections";

// Pause before a hover over the folded strip opens the full menu, so a
// pointer passing over it on the way somewhere else doesn't pop it open.
const PEEK_DELAY_MS = 150;
// How long a wide page waits before folding, so the square's hop to the new
// row plays out first, and the grace after the pointer leaves the sidebar.
const FOLD_DELAY_MS = 3000;
const LEAVE_DELAY_MS = 400;

// The fold last shown, kept outside React: the inbox and the other pages
// mount separate sidebars, and the new one must start where the old one was
// so it can fold after the delay instead of appearing folded.
let lastShownRail: boolean | null = null;

/**
 * Desktop sidebar fold state. Wide pages (sidebarFoldsOn) fold it to the
 * 64px icon strip, FOLD_DELAY_MS after arriving (never while the pointer is
 * on the sidebar); every other page opens it at once. The collapse button overrides
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
  const pinned = override?.path === pathname;
  const target = pinned ? override.rail : sidebarFoldsOn(pathname);
  const [rail, setRail] = useState(() => lastShownRail ?? target);
  const hovering = useRef(false);
  // The fold came due while the pointer was on the sidebar: fold on leave.
  const due = useRef(false);
  const foldTimer = useRef<number | undefined>(undefined);
  const timer = useRef<number | undefined>(undefined);
  // When the sidebar folds under the pointer, hover must not peek again
  // until the pointer has left, or it would spring straight back open.
  const armed = useRef(true);
  const lastRail = useRef(rail);

  useLayoutEffect(() => {
    window.clearTimeout(foldTimer.current);
    due.current = false;
    if (target === rail) return;
    // Opening, or the collapse button: no wait.
    if (!target || pinned) {
      setRail(target);
      return;
    }
    foldTimer.current = window.setTimeout(() => {
      if (hovering.current) due.current = true;
      else setRail(true);
    }, FOLD_DELAY_MS);
    return () => window.clearTimeout(foldTimer.current);
  }, [target, rail, pinned]);

  useLayoutEffect(() => {
    lastShownRail = rail;
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
      window.clearTimeout(foldTimer.current);
      root.removeAttribute("data-sidebar-anim");
    };
  }, []);

  const handlers = {
    onMouseEnter: () => {
      hovering.current = true;
      if (!rail || !armed.current) return;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setPeek(true), PEEK_DELAY_MS);
    },
    onMouseLeave: () => {
      hovering.current = false;
      if (due.current) {
        due.current = false;
        foldTimer.current = window.setTimeout(() => {
          if (hovering.current) due.current = true;
          else setRail(true);
        }, LEAVE_DELAY_MS);
      }
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
