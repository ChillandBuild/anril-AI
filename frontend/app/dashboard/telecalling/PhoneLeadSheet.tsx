"use client";
import { useEffect, type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";

/** Full-screen lead profile for phones. z-[65]: above the bottom bar, below the call modals (z-70). */
export default function PhoneLeadSheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[65] flex flex-col bg-white lg:hidden" role="dialog" aria-modal="true">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-2 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
        <button
          type="button"
          onClick={onClose}
          aria-label="Back to the list"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-ink active:bg-surface-mid"
        >
          <ArrowLeft size={22} />
        </button>
        <p className="min-w-0 flex-1 truncate font-display text-base font-extrabold text-ink">{title}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden pb-[env(safe-area-inset-bottom)]">{children}</div>
    </div>
  );
}
