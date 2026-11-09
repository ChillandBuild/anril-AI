"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** [label, explanation] — one line in the "how the Total is worked out" box. */
export type TotalRule = [string, string];

export const ALL_ADS_TOTAL_RULES: TotalRule[] = [
  ["Added up", "Spend, impressions, clicks, leads and other counts."],
  ["Reach", "People reached across all ads, each counted once, not added up."],
  ["Worked out again", "CPM, CTR, CPC, cost per result, frequency and ROAS use the totals, not an average."],
  ["—", "Can't be totalled, e.g. ads with different result types."],
];

export const MESSAGING_TOTAL_RULES: TotalRule[] = [
  ["Added up", "Spend, impressions, clicks, messages, conversations, hot leads and other counts."],
  ["Reach", "People reached across all ads, each counted once, not added up."],
  ["Worked out again", "CPM, CTR, CPC, frequency, costs per message / conversation / hot lead and the rates use the totals, not an average."],
  ["—", "Status and budget can't be totalled."],
];

/** The "Total" label; clicking it shows how the row is worked out. */
export function TotalLabel({ rules }: { rules: TotalRule[] }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  // Portalled with fixed coordinates: the table scrolls inside overflow containers
  // that would clip it. Opens above the label (the row sits at the table's bottom).
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const rect = btnRef.current?.getBoundingClientRect();
      if (!rect) return;
      const h = panelRef.current?.offsetHeight ?? 180;
      const w = panelRef.current?.offsetWidth ?? 300;
      const top = rect.top - h - 6 >= 8 ? rect.top - h - 6 : rect.bottom + 6;
      setPos({ top, left: Math.max(8, Math.min(rect.left, window.innerWidth - w - 8)) });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="cursor-pointer font-label text-sm font-bold text-on-surface underline decoration-dotted decoration-[#94a3b8] underline-offset-4 hover:text-primary"
      >
        Total
      </button>
      {open &&
        createPortal(
          <div
            ref={panelRef}
            role="dialog"
            aria-label="How the Total is worked out"
            style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
            className="fixed z-50 w-[300px] rounded-xl border border-[#e2e8f0] bg-white p-3 text-left shadow-lg"
          >
            <ul className="space-y-1.5">
              {rules.map(([label, text]) => (
                <li key={label} className="font-body text-xs font-normal leading-snug text-[#475569]">
                  <span className="font-bold text-[#0A1528]">{label}:</span> {text}
                </li>
              ))}
            </ul>
          </div>,
          document.body,
        )}
    </>
  );
}
