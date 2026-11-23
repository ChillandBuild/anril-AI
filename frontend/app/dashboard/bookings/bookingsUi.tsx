"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import useSWR from "swr";
import { Download, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { bookingsApi, type BookingSetup } from "@/lib/bookingsApi";

export const INPUT_CLS =
  "h-10 w-full rounded-lg border border-[#e2e8f0] bg-white px-3 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15 disabled:bg-slate-50 disabled:text-ink-muted";
export const BTN_PRIMARY =
  "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-bold text-white shadow-sm hover:bg-[var(--primary-900)] disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_SECONDARY =
  "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-[#e2e8f0] bg-white px-4 py-2 text-sm font-bold text-ink shadow-sm hover:bg-[#f8fafc] disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_DANGER =
  "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-lg border border-rose-200 bg-white px-4 py-2 text-sm font-bold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50";

export function errorText(err: unknown, fallback = "Could not save that. Try again."): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** The setup (services, columns, rules, who am I). Shared by every tab through one SWR key. */
export function useBookingsSetup() {
  const swr = useSWR<BookingSetup>("bookings/setup", () => bookingsApi.setup(), {
    revalidateOnFocus: false,
    dedupingInterval: 10_000,
  });
  return swr;
}

/** What this person may do with Bookings. The server still enforces every one of these. */
export function useBookingsAccess() {
  const { role, permissions, loading } = useAuthRole();
  const owner = role === "owner";
  const download = owner || permissions.includes("leads.download");
  const manage = owner || permissions.includes("bookings.manage");
  const view = manage || permissions.includes("bookings.view");
  const money = owner || permissions.includes("deals.view") || permissions.includes("deals.manage");
  return { loading, view, manage, money, download };
}

/** "Download the list" for the day or week on screen. The server checks the permission again. */
export function DownloadListButton({ start, end, disabled }: { start: string; end?: string; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      await bookingsApi.exportCsv(start, end);
    } catch (err) {
      toast.error(errorText(err, "Could not prepare the download. Try again."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <button type="button" className={BTN_SECONDARY} onClick={() => void go()} disabled={busy || disabled} title="Download this list">
      <Download size={16} aria-hidden /> Download the list
    </button>
  );
}

export function Field({ label, children, hint, htmlFor }: { label: string; children: ReactNode; hint?: string; htmlFor?: string }) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="mb-1 block font-label text-xs font-bold text-ink-muted">
        {label}
      </label>
      {children}
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );
}

/** Open sheets, last = top-most. Only the top one answers Escape and Tab. */
const SHEET_STACK: object[] = [];

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null || el === document.activeElement);
}

/** A centred sheet on a laptop, a full-width bottom sheet on a phone. Escape closes the top one; Tab stays inside it. */
export function Sheet({
  title,
  onClose,
  children,
  footer,
  wide,
  labelId = "sheet-title",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  labelId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const prevFocus = document.activeElement as HTMLElement | null;
    const token = {};
    SHEET_STACK.push(token);
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      // Only the top-most sheet reacts, so Escape never closes the sheet underneath too.
      if (SHEET_STACK[SHEET_STACK.length - 1] !== token) return;
      if (e.defaultPrevented) return; // a dropdown inside already used this key
      if (e.key === "Escape") {
        e.preventDefault();
        closeRef.current();
        return;
      }
      if (e.key === "Tab" && ref.current) {
        const items = focusables(ref.current);
        if (items.length === 0) {
          e.preventDefault();
          ref.current.focus();
          return;
        }
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        if (e.shiftKey && (active === first || active === ref.current)) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        } else if (!ref.current.contains(active)) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const i = SHEET_STACK.indexOf(token);
      if (i >= 0) SHEET_STACK.splice(i, 1);
      // Back to whatever opened the sheet, if it is still on the page.
      if (prevFocus && prevFocus.isConnected) prevFocus.focus?.();
    };
  }, []);

  return (
    <div className="fixed inset-0 z-dialog flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        className={cn(
          "flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-white shadow-xl outline-none sm:rounded-2xl",
          wide ? "sm:max-w-2xl" : "sm:max-w-md",
        )}
      >
        <div className="flex items-center justify-between gap-3 border-b border-[#eef2f6] px-4 py-3 sm:px-5">
          <h2 id={labelId} className="font-display text-base font-bold text-ink">
            {title}
          </h2>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">{children}</div>
        {footer ? <div className="flex flex-wrap justify-end gap-2 border-t border-[#eef2f6] px-4 py-3 sm:px-5">{footer}</div> : null}
      </div>
    </div>
  );
}

/** A yes/no question. Used for moves, cancels and "new link". */
export function ConfirmSheet({
  title,
  body,
  confirmLabel,
  tone = "primary",
  busy,
  onConfirm,
  onClose,
}: {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  tone?: "primary" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Sheet
      title={title}
      onClose={onClose}
      labelId="confirm-title"
      footer={
        <>
          <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>
            Not now
          </button>
          <button type="button" className={tone === "danger" ? BTN_DANGER : BTN_PRIMARY} onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm text-ink-secondary">{body}</div>
    </Sheet>
  );
}

export function Notice({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "amber" | "red" }) {
  const cls = tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-900" : tone === "red" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-[#e2e8f0] bg-[#f8fafc] text-ink-secondary";
  return (
    <p role="status" className={cn("rounded-xl border px-3 py-2 text-sm", cls)}>
      {children}
    </p>
  );
}
