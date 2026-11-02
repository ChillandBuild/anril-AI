"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Tone } from "./helpers";

export const inputCls =
  "h-10 w-full rounded-xl border border-[#e2e8f0] bg-white px-3 text-sm text-[#0A1528] placeholder:text-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:bg-[#f8fafc] disabled:text-[#94a3b8]";
export const textareaCls =
  "w-full rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 text-sm text-[#0A1528] placeholder:text-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-primary/20";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cn("rounded-2xl border border-[#e2e8f0] bg-white shadow-sm", className)}>{children}</section>;
}

export function CardHeader({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-[#e2e8f0] px-4 py-3 sm:px-5">
      <div className="min-w-0">
        <h2 className="font-display text-base font-bold text-[#0A1528]">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-[#64748b]">{hint}</p>}
      </div>
      {action}
    </div>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: "primary" | "outline" | "danger" | "link" };

export function Btn({ busy, variant = "primary", className, children, disabled, type = "button", ...rest }: BtnProps) {
  const styles = {
    primary: "bg-primary text-white hover:bg-primary-dark",
    outline: "border border-primary text-primary hover:bg-primary/5",
    danger: "border border-danger text-danger hover:bg-danger/5",
    link: "text-primary hover:underline px-1",
  }[variant];
  return (
    <button
      type={type}
      disabled={disabled || busy}
      className={cn(
        "inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 text-sm font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        variant === "link" && "h-auto",
        styles,
        className,
      )}
      {...rest}
    >
      {busy && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  );
}

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-[#eef2f6] text-[#475569]",
  info: "bg-[#e8f5fd] text-[#0369a1]",
  success: "bg-[#ecfdf3] text-[#15803d]",
  danger: "bg-[#fff1f2] text-[#be123c]",
  warn: "bg-[#fff7e6] text-[#b45309]",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex w-fit items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11.5px] font-bold", TONE_CLASS[tone])}>
      {children}
    </span>
  );
}

export function Notice({ tone = "info", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "danger" || tone === "warn" ? AlertTriangle : Info;
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex items-start gap-2 rounded-xl px-3 py-2.5 text-sm", TONE_CLASS[tone], className)}>
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 break-words">{children}</div>
    </div>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block min-w-0", className)}>
      <span className="mb-1 block text-xs font-bold text-[#334155]">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-[#64748b]">{hint}</span>}
    </label>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-2xl bg-border-subtle", className)} />;
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-sm font-semibold text-[#0A1528]">{title}</p>
      {hint && <p className="mt-1 text-xs text-[#64748b]">{hint}</p>}
    </div>
  );
}

export function LoadError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-sm font-semibold text-[#0A1528]">{"Couldn't load this."}</p>
      <p className="mt-1 text-xs text-[#64748b]">{message}</p>
      {onRetry && (
        <Btn variant="outline" className="mt-4 h-9" onClick={onRetry}>
          Try again
        </Btn>
      )}
    </div>
  );
}

/** Horizontal scroll wrapper so wide tables never push the page sideways on a phone. */
export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto">{children}</div>;
}

export const thCls = "whitespace-nowrap px-4 py-2.5 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]";
export const tdCls = "px-4 py-3 align-top text-sm text-[#334155]";
