"use client";
import { useLayoutEffect, useRef } from "react";

const SIZE = 8;
// How long to keep re-placing the square while a menu animates open or shut.
const FOLLOW_MS = 520;

// Position of `el` inside `box`, from offsetLeft/offsetTop so CSS transforms
// (the slide-in on freshly opened sections) don't skew the measurement.
function offsetWithin(el: HTMLElement, box: HTMLElement) {
  let x = 0;
  let y = 0;
  let node: HTMLElement | null = el;
  while (node && node !== box) {
    x += node.offsetLeft;
    y += node.offsetTop;
    node = node.offsetParent as HTMLElement | null;
  }
  return { x, y };
}

/**
 * The teal square that marks the current page and hops from the old row to the
 * new one on navigation. Render it as the LAST child of a `relative` scroll
 * container; it finds the row with aria-current="page" inside that container.
 */
export function ActiveIndicator({ pathname }: { pathname: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef<{ x: number; y: number } | null>(null);
  const lastPath = useRef<string | null>(null);

  // Layout effect: it must disconnect the old observers before their queued
  // records fire, or a silent re-place would eat the hop.
  useLayoutEffect(() => {
    const square = ref.current;
    const box = square?.parentElement;
    if (!square || !box) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const aside = box.closest("aside");

    const place = (navigated: boolean) => {
      const current = box.querySelector<HTMLElement>('[aria-current="page"]');
      // On the folded strip only the group icons show: mark the group holding the page.
      const row = aside?.matches("[data-rail]:not([data-peek])")
        ? (current?.closest("section")?.querySelector<HTMLElement>(":scope > button") ?? current)
        : current;
      if (!row) {
        square.style.opacity = "0";
        last.current = null;
        return;
      }
      const at = offsetWithin(row, box);
      // Top-level rows: the square sits just left of the row. Rows inside an
      // open menu's box: just inside the row's left edge.
      const nested = row.closest(".nav-children, .nav-children-flat") !== null;
      const x = at.x + (nested ? 12 : -11);
      const y = at.y + row.offsetHeight / 2 - SIZE / 2;
      // A closed menu still holds its rows; hide the square there.
      square.style.opacity = row.closest(".nav-expander:not(.open)") ? "0" : "1";
      const from = last.current;
      if (from && from.x === x && from.y === y) return;
      square.style.transform = `translate(${x}px, ${y}px)`;
      last.current = { x, y };
      if (still) return;
      if (navigated && from) {
        // Squash, arc out over the rows while spinning, land with a squash.
        const midX = (from.x + x) / 2 + 18;
        const midY = (from.y + y) / 2;
        const t = (px: number, py: number, rest = "") => ({ transform: `translate(${px}px, ${py}px) ${rest}` });
        square.animate(
          [
            t(from.x, from.y),
            { ...t(from.x, from.y, "scale(1.3, 0.7)"), offset: 0.12 },
            { ...t(midX, midY, "rotate(135deg) scale(0.85, 1.5)"), offset: 0.5 },
            { ...t(x, y, "rotate(180deg) scale(1.5, 0.6)"), offset: 0.82 },
            t(x, y, "rotate(180deg)"),
          ],
          { duration: 460, easing: "ease-in-out" },
        );
        // The row gives a small nudge as the square lands.
        row.animate(
          [{ transform: "none" }, { transform: "none", offset: 0.75 }, { transform: "translateX(3px)", offset: 0.88 }, { transform: "none" }],
          { duration: 560 },
        );
      }
    };

    place(lastPath.current !== null && lastPath.current !== pathname);
    lastPath.current = pathname;

    // Menus opening/closing and badges arriving move rows without a navigation.
    // A menu animates its height, so follow the row frame by frame for a moment.
    let frame = 0;
    const follow = () => {
      cancelAnimationFrame(frame);
      const t0 = performance.now();
      const step = (t: number) => {
        place(false);
        if (t - t0 < FOLLOW_MS) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };
    const mutations = new MutationObserver(follow);
    mutations.observe(box, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "aria-expanded"] });
    // Folding or peeking the sidebar moves the square between a group and its row.
    if (aside) mutations.observe(aside, { attributes: true, attributeFilter: ["data-rail", "data-peek"] });
    const resize = new ResizeObserver(() => place(false));
    resize.observe(box);
    return () => {
      cancelAnimationFrame(frame);
      mutations.disconnect();
      resize.disconnect();
    };
  }, [pathname]);

  return <span ref={ref} aria-hidden="true" className="nav-hop-square" />;
}
