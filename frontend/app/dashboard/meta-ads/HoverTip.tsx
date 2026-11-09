"use client";

import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * A short explanation shown while the cursor is on `children` (or it has focus).
 * Portalled with fixed coordinates: the tables scroll inside overflow containers
 * that would clip it.
 */
export function HoverTip({
  text,
  side = "top",
  focusable = true,
  children,
}: {
  text: string | null | undefined;
  side?: "top" | "bottom";
  /** Set false when the trigger lives inside a button. */
  focusable?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const rect = anchorRef.current?.getBoundingClientRect();
      if (!rect) return;
      const h = tipRef.current?.offsetHeight ?? 40;
      const w = tipRef.current?.offsetWidth ?? 240;
      const above = rect.top - h - 6;
      const below = rect.bottom + 6;
      const fitsAbove = above >= 8;
      const fitsBelow = below + h <= window.innerHeight - 8;
      const top = side === "top" ? (fitsAbove || !fitsBelow ? above : below) : (fitsBelow || !fitsAbove ? below : above);
      const centred = rect.left + rect.width / 2 - w / 2;
      setPos({ top, left: Math.max(8, Math.min(centred, window.innerWidth - w - 8)) });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, side]);

  if (!text) return <>{children}</>;

  return (
    <>
      <span
        ref={anchorRef}
        tabIndex={focusable ? 0 : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="cursor-help rounded-sm outline-none decoration-dotted decoration-[#94a3b8] underline-offset-4 hover:underline focus-visible:underline"
      >
        {children}
      </span>
      {open &&
        createPortal(
          <div
            ref={tipRef}
            role="tooltip"
            style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
            className="pointer-events-none fixed z-50 max-w-[260px] rounded-lg bg-[#0A1528] px-2.5 py-1.5 text-left font-body text-xs font-normal normal-case leading-snug tracking-normal text-white shadow-lg"
          >
            {text}
          </div>,
          document.body,
        )}
    </>
  );
}
