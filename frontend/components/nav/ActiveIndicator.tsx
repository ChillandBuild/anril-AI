"use client";
import { useLayoutEffect, useRef } from "react";

const SIZE = 7;

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

    const place = (navigated: boolean) => {
      const row = box.querySelector<HTMLElement>('[aria-current="page"]');
      if (!row) {
        square.style.opacity = "0";
        last.current = null;
        return;
      }
      const at = offsetWithin(row, box);
      const x = at.x - 4;
      const y = at.y + row.offsetHeight / 2 - SIZE / 2;
      const from = last.current;
      if (from && from.x === x && from.y === y) return;
      square.style.transform = `translate(${x}px, ${y}px)`;
      square.style.opacity = "1";
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
          { duration: 420 + Math.min(240, Math.abs(y - from.y) * 0.4), easing: "ease-in-out" },
        );
      } else if (!from) {
        square.animate(
          [{ opacity: 0, transform: `translate(${x}px, ${y}px) scale(0)` }, { opacity: 1, transform: `translate(${x}px, ${y}px)` }],
          { duration: 320, delay: 120, easing: "cubic-bezier(.34,1.56,.64,1)", fill: "backwards" },
        );
      }
    };

    place(lastPath.current !== null && lastPath.current !== pathname);
    lastPath.current = pathname;

    // Sections opening/closing and badges arriving move rows without a navigation.
    const sync = () => place(false);
    const mutations = new MutationObserver(sync);
    mutations.observe(box, { childList: true, subtree: true });
    const resize = new ResizeObserver(sync);
    resize.observe(box);
    return () => {
      mutations.disconnect();
      resize.disconnect();
    };
  }, [pathname]);

  return <span ref={ref} aria-hidden="true" className="nav-hop-square" />;
}
