"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { ArrowRightLeft, Check, Copy, Info, Layers, MessageCircle, MessageSquareText, X, type LucideIcon } from "lucide-react";
import type { OtpHistoryItem, OtpMode, OtpView } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Tone } from "../sms/helpers";
import { Skeleton } from "../sms/ui";
import { MODE_OPTIONS, channelBadge, resultLabel } from "./otpShared";

// ---------------------------------------------------------------- status

const PILL: Record<Tone, { box: string; dot: string }> = {
  success: { box: "bg-[#ecfdf3] text-[#067647]", dot: "#12b76a" },
  danger: { box: "bg-[#fef3f2] text-[#b42318]", dot: "#f04438" },
  warn: { box: "bg-[#fffaeb] text-[#b54708]", dot: "#f79009" },
  info: { box: "bg-[#eff8ff] text-[#175cd3]", dot: "#2e90fa" },
  neutral: { box: "bg-[#f2f4f7] text-[#475467]", dot: "#98a2b3" },
};

/** Coloured pill for a status. Shows a 6px dot, or the `icon` (12px) in place of the dot. */
export function StatusPill({ tone, children, icon: Icon }: { tone: Tone; children: ReactNode; icon?: LucideIcon }) {
  const p = PILL[tone];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold", p.box)}>
      {Icon ? <Icon size={12} aria-hidden="true" /> : <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: p.dot }} aria-hidden="true" />}
      {children}
    </span>
  );
}

/** One channel's delivery state as a pill. "none" (channel not used) is a muted em dash. */
export function ChannelStatus({ status }: { status: OtpView["sms"]["status"] | OtpView["whatsapp"]["status"] }) {
  if (status === "none") return <span className="text-[#94a3b8]">—</span>;
  const b = channelBadge(status);
  return <StatusPill tone={b.tone}>{b.label}</StatusPill>;
}

/** An OTP's overall result as a pill. */
export function ResultStatus({ status }: { status: OtpHistoryItem["status"] }) {
  const r = resultLabel(status);
  return <StatusPill tone={r.tone}>{r.label}</StatusPill>;
}

// ---------------------------------------------------------------- channel icon

const CHANNEL_BOX: Record<"sms" | "whatsapp", { icon: LucideIcon; box: string }> = {
  sms: { icon: MessageSquareText, box: "bg-[#eff8ff] text-[#175cd3]" },
  whatsapp: { icon: MessageCircle, box: "bg-[#ecfdf3] text-[#067647]" },
};

/** SMS or WhatsApp glyph in a 32px tinted square. `size` sets the glyph size (default 16). */
export function ChannelIcon({ channel, size = 16 }: { channel: "sms" | "whatsapp"; size?: number }) {
  const { icon: Icon, box } = CHANNEL_BOX[channel];
  return (
    <span className={cn("inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", box)} aria-hidden="true">
      <Icon size={size} />
    </span>
  );
}

// ---------------------------------------------------------------- KPI tile

export function KpiTile({
  label,
  value,
  sub,
  hint,
  loading,
}: {
  label: string;
  value: string | number;
  sub?: string;
  hint?: string;
  loading?: boolean;
}) {
  return (
    <div className="relative rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.08em] text-[#64748b]">
        {label}
        {hint && (
          <span title={hint} className="inline-flex text-[#94a3b8]">
            <Info size={13} aria-hidden="true" />
            <span className="sr-only">{hint}</span>
          </span>
        )}
      </p>
      {loading ? (
        <Skeleton className="mt-3 h-7 w-24" />
      ) : (
        <p className="mt-2 font-display text-[28px] font-bold leading-none tabular-nums text-[#0A1528]">{value}</p>
      )}
      {sub && <p className="mt-2 text-[13px] text-[#64748b]">{sub}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- section card

export function SectionCard({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-2xl border border-[#e2e8f0] bg-white shadow-[0_1px_2px_rgba(16,24,40,0.04)]", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <h2 className="font-display text-[15px] font-bold text-[#0A1528]">{title}</h2>
          {description && <p className="mt-1 text-[13px] text-[#64748b]">{description}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      <div className="p-5 pt-4">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------- settings row

export function SettingsRow({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <div className="grid gap-4 border-t border-[#eef2f6] py-6 first:border-t-0 first:pt-0 lg:grid-cols-[280px_1fr] lg:gap-10">
      <div className="min-w-0">
        <p className="text-sm font-bold text-[#0A1528]">{title}</p>
        <p className="mt-1 text-[13px] leading-relaxed text-[#64748b]">{description}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------- mode cards

const MODE_ICON: Record<OtpMode, LucideIcon> = {
  sms: MessageSquareText,
  whatsapp: MessageCircle,
  both: Layers,
  sms_then_whatsapp: ArrowRightLeft,
};

/**
 * Radio cards for the four send modes. Arrow keys (and Home/End) move the selection and focus;
 * only the selected card sits in the tab order. Nothing happens while `disabled`.
 */
export function ModeCards({
  value,
  onChange,
  disabled,
  compact,
}: {
  value: OtpMode;
  onChange: (mode: OtpMode) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const selectedIndex = Math.max(
    0,
    MODE_OPTIONS.findIndex((o) => o.value === value),
  );

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (disabled) return;
    const count = MODE_OPTIONS.length;
    let next: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (index + 1) % count;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (index - 1 + count) % count;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = count - 1;
    if (next === null) return;
    e.preventDefault();
    onChange(MODE_OPTIONS[next].value);
    buttons.current[next]?.focus();
  }

  return (
    <div role="radiogroup" aria-label="How to send the code" className="grid gap-3 sm:grid-cols-2">
      {MODE_OPTIONS.map((opt, i) => {
        const selected = i === selectedIndex;
        const Icon = MODE_ICON[opt.value];
        return (
          <button
            key={opt.value}
            ref={(el) => {
              buttons.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              "relative flex flex-col justify-start rounded-xl border p-3.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-60",
              selected ? "border-primary bg-primary/[0.04] ring-1 ring-primary" : "border-[#e2e8f0] bg-white hover:border-[#cbd5e1]",
            )}
          >
            <span className="absolute right-3 top-3">
              {selected ? (
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary text-white">
                  <Check size={10} strokeWidth={3} aria-hidden="true" />
                </span>
              ) : (
                <span className="block h-4 w-4 rounded-full border border-[#cbd5e1]" aria-hidden="true" />
              )}
            </span>
            <span className="flex items-start gap-3 pr-6">
              <span
                className={cn(
                  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                  selected ? "bg-primary/10 text-primary" : "bg-[#f1f5f9] text-[#475569]",
                )}
                aria-hidden="true"
              >
                <Icon size={16} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-bold text-[#0A1528]">{opt.label}</span>
                {!compact && <span className="mt-0.5 block text-xs text-[#64748b]">{opt.hint}</span>}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- timeline

/** Vertical event list, newest first as the caller orders it. */
export function Timeline({
  items,
}: {
  items: { key: string; title: string; time?: string; detail?: string; tone: Tone }[];
}) {
  return (
    <ol className="space-y-0">
      {items.map((item, i) => (
        <li key={item.key} className="relative pb-5 pl-6 last:pb-0">
          <span
            className="absolute left-0 top-[5px] h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: PILL[item.tone].dot }}
            aria-hidden="true"
          />
          {i < items.length - 1 && <span className="absolute bottom-0 left-[4px] top-[18px] w-px bg-[#e2e8f0]" aria-hidden="true" />}
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <p className="text-sm font-semibold text-[#0A1528]">{item.title}</p>
            {item.time && <p className="text-xs tabular-nums text-[#64748b]">{item.time}</p>}
          </div>
          {item.detail && (
            <p className={cn("mt-0.5 break-words text-xs", item.tone === "danger" ? "text-[#b42318]" : "text-[#64748b]")}>{item.detail}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------- drawer

/**
 * Right-hand slide-over, portalled to <body>. Renders nothing while closed. On open it mounts at
 * translate-x-full and slides to translate-x-0 on the next frame. Esc, the X and a click on the
 * overlay close it. Focus moves into the panel and goes back to the opener on close. Body scroll is locked while open.
 */
export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  const [entered, setEntered] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    setMounted(true);
  }, []);

  // Two frames: the first lets the browser paint translate-x-full, the second starts the slide.
  useEffect(() => {
    if (!open) {
      setEntered(false);
      return;
    }
    let inner = 0;
    const outer = window.requestAnimationFrame(() => {
      inner = window.requestAnimationFrame(() => setEntered(true));
    });
    return () => {
      window.cancelAnimationFrame(outer);
      window.cancelAnimationFrame(inner);
    };
  }, [open]);

  // Body scroll lock.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // Focus in on open, Esc to close, focus back to the opener on close.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.focus({ preventScroll: true });
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") closeRef.current();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.({ preventScroll: true });
    };
  }, [open]);

  if (!mounted || !open || typeof document === "undefined") return null;

  return createPortal(
    <>
      <div className="fixed inset-0 z-[60] bg-[#0A1528]/30" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cn(
          "fixed inset-y-0 right-0 z-[61] flex w-full max-w-[480px] flex-col bg-white shadow-2xl transition-transform duration-200 focus:outline-none",
          entered ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-[#e2e8f0] px-5 py-4">
          <div className="min-w-0">
            <h2 className="font-display text-base font-bold text-[#0A1528]">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[13px] text-[#64748b]">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-lg p-1.5 text-[#64748b] transition-colors hover:bg-[#f1f5f9] hover:text-[#0A1528] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
          >
            <X size={16} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
        {footer && <div className="border-t border-[#e2e8f0] px-5 py-3">{footer}</div>}
      </div>
    </>,
    document.body,
  );
}

// ---------------------------------------------------------------- copy button

/** Small ghost button that copies `text`, then shows a tick for 1.5 s. `label={null}` makes it icon-only. */
export function CopyButton({ text, label = "Copy", className }: { text: string; label?: string | null; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    return () => window.clearTimeout(timer.current);
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy. Select the text and copy it yourself.");
    }
  }

  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label ? undefined : "Copy"}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-lg text-xs font-semibold text-[#475569] transition-colors hover:bg-[#f1f5f9] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
        label ? "px-2.5" : "w-8 justify-center",
        className,
      )}
    >
      <Icon size={14} aria-hidden="true" />
      {label}
    </button>
  );
}

// ---------------------------------------------------------------- code panel

export type CodeTab = { id: string; label: string; code: string };

/**
 * Dark code block for the API docs. With more than one tab it shows a tab bar, otherwise the title.
 * Copy copies the active tab. Pass `value` and `onChange` to drive the tab from outside, e.g. to keep
 * several panels on the same language.
 */
export function CodePanel({
  tabs,
  title,
  className,
  value,
  onChange,
}: {
  tabs: CodeTab[];
  title?: string;
  className?: string;
  value?: string;
  onChange?: (id: string) => void;
}) {
  const [inner, setInner] = useState(tabs[0]?.id ?? "");
  const selectedId = value ?? inner;
  const active = tabs.find((t) => t.id === selectedId) ?? tabs[0];

  if (!active) return null;

  function select(id: string) {
    setInner(id);
    onChange?.(id);
  }

  return (
    <div className={cn("overflow-hidden rounded-xl border border-[#1e293b] bg-[#0b1220]", className)}>
      <div className="flex h-10 items-center justify-between gap-3 border-b border-white/10 px-3">
        {tabs.length > 1 ? (
          <div role="tablist" className="flex h-full items-stretch gap-4 overflow-x-auto">
            {tabs.map((t) => {
              const selected = t.id === active.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => select(t.id)}
                  className={cn(
                    "relative flex items-center whitespace-nowrap text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
                    selected
                      ? "text-white after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-[#2dd4bf]"
                      : "text-slate-400 hover:text-slate-200",
                  )}
                >
                  {t.label}
                </button>
              );
            })}
          </div>
        ) : (
          <span className="text-xs font-semibold text-slate-400">{title ?? active.label}</span>
        )}
        <CopyButton text={active.code} className="text-slate-300 hover:bg-white/10" />
      </div>
      <pre className="max-h-[480px] overflow-auto p-4 font-mono text-[12.5px] leading-6 text-slate-200">
        <code>{active.code}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------- method badge

/** HTTP method chip: POST teal, GET blue, anything else neutral. */
export function MethodBadge({ method }: { method: string }) {
  const cls =
    method === "POST"
      ? "bg-primary/10 text-primary"
      : method === "GET"
        ? "bg-[#eff8ff] text-[#175cd3]"
        : "bg-[#f2f4f7] text-[#475467]";
  return <span className={cn("rounded-md px-1.5 py-0.5 font-mono text-[11px] font-bold", cls)}>{method}</span>;
}

// ---------------------------------------------------------------- percent

/** 0.8734 -> "87.3%", 0.5 -> "50%", null -> "—". */
export function percent(rate: number | null): string {
  if (rate === null || !Number.isFinite(rate)) return "—";
  return `${(rate * 100).toFixed(1).replace(/\.0$/, "")}%`;
}
