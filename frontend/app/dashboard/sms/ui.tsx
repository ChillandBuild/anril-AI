"use client";

import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type DragEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, FileText, Info, Loader2, UploadCloud, X } from "lucide-react";
import { CheckField } from "@/components/ui/controls";
import { cn } from "@/lib/utils";
import { CONSENT_HINT, CONSENT_LABEL, type Tone } from "./helpers";

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

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function ModalBody({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  // On open: focus the first form field (else the dialog). On close: give focus back to whatever opened it.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = bodyRef.current?.querySelector<HTMLElement>("input:not([type=hidden]):not([type=file]), select, textarea");
    (first ?? dialogRef.current)?.focus({ preventScroll: true });
    return () => opener?.focus?.({ preventScroll: true });
  }, []);

  // Escape closes; Tab and Shift+Tab stay inside the dialog.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === firstEl || active === dialogRef.current)) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && active === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cn("flex max-h-[90vh] w-full flex-col rounded-2xl bg-white shadow-xl focus:outline-none", wide ? "max-w-2xl" : "max-w-md")}
      >
        <div className="flex items-center justify-between gap-3 border-b border-[#e2e8f0] px-5 py-3.5">
          <h3 className="font-display text-base font-bold text-[#0A1528]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="text-[#64748b] hover:text-[#0A1528]">
            <X size={18} />
          </button>
        </div>
        <div ref={bodyRef} className="overflow-y-auto p-5">
          {children}
        </div>
      </div>
    </div>
  );
}

/** Centered dialog over a dimmed page; the body scrolls on short screens. Escape closes it and Tab stays inside. */
export function Modal({ open, title, onClose, children, wide }: { open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  if (!open || typeof document === "undefined") return null;
  // Rendered on <body>, not where the caller placed it: inside a space-y-*
  // list the overlay picked up the list's margin-top and left an undimmed
  // strip along the top of the window (DLT Setup > Add template).
  return createPortal(
    <ModalBody title={title} onClose={onClose} wide={wide}>
      {children}
    </ModalBody>,
    document.body
  );
}

/** The promotional-SMS consent tick (off by default). */
export function ConsentCheck({ checked, onChange }: { checked: boolean; onChange: (next: boolean) => void }) {
  return <CheckField checked={checked} onChange={onChange} label={CONSENT_LABEL} description={CONSENT_HINT} />;
}

/** Hand a CSV string to the browser as a file download. */
export function saveCsv(csv: string, filename: string) {
  const url = window.URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

// ---- FilePicker ----

/** The backend rejects uploads over 20 MB (MAX_UPLOAD_BYTES). */
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** 18432 -> "18 KB", 2.5 MB -> "2.5 MB". */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  const mb = bytes / (1024 * 1024);
  return `${mb >= 10 ? Math.round(mb) : Math.round(mb * 10) / 10} MB`;
}

/** ".xlsx,.csv" -> [".xlsx", ".csv"] (lower-cased, each with its dot). */
export function acceptList(accept: string): string[] {
  return accept
    .split(",")
    .map((x) => x.trim().toLowerCase())
    .filter(Boolean)
    .map((x) => (x.startsWith(".") ? x : `.${x}`));
}

/** Why a file can't be used, or null when it is fine. Checks the extension, then the size. */
export function fileProblem(file: { name: string; size: number }, accept: string, maxBytes: number = MAX_UPLOAD_BYTES): string | null {
  const exts = acceptList(accept);
  const name = file.name.toLowerCase();
  if (exts.length > 0 && !exts.some((x) => name.endsWith(x))) return `"${file.name}" isn't a supported file. Use ${exts.join(" or ")}.`;
  if (file.size > maxBytes) return `"${file.name}" is ${formatFileSize(file.size)}. The limit is ${formatFileSize(maxBytes)}.`;
  return null;
}

/**
 * Drop zone + Browse button for one file. A wrong type or an oversize file is refused with a red line
 * under the box and onChange is not called. After a pick it shows the file's name and size with an X to clear.
 */
export function FilePicker({
  accept,
  file,
  onChange,
  disabled,
  maxBytes = MAX_UPLOAD_BYTES,
  label,
  hint,
}: {
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
  maxBytes?: number;
  label?: string;
  /** Extra text after the built-in "<types>, up to 20 MB" line. */
  hint?: string;
}) {
  const uid = useId();
  const hintId = `${uid}-hint`;
  const errorId = `${uid}-error`;
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  function take(f: File | null | undefined) {
    if (!f) return;
    const problem = fileProblem(f, accept, maxBytes);
    if (problem) {
      setError(problem);
      return;
    }
    setError("");
    onChange(f);
  }

  function clear() {
    setError("");
    if (inputRef.current) inputRef.current.value = "";
    onChange(null);
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    if (disabled) return;
    e.preventDefault();
    setDragging(true);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (!disabled) take(e.dataTransfer.files?.[0]);
  }

  const hintText = `${acceptList(accept).join(", ")}, up to ${formatFileSize(maxBytes)}${hint ? `. ${hint}` : ""}`;

  return (
    <div className="min-w-0">
      {label && <span className="mb-1 block text-xs font-bold text-[#334155]">{label}</span>}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        disabled={disabled}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          take(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      {file ? (
        <div className="flex items-center gap-3 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2.5">
          <FileText size={18} className="shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-[#0A1528]">{file.name}</p>
            <p className="text-xs text-[#64748b]">{formatFileSize(file.size)}</p>
          </div>
          <button
            type="button"
            onClick={clear}
            disabled={disabled}
            aria-label={`Remove ${file.name}`}
            className="rounded-lg p-1.5 text-[#64748b] hover:bg-[#f1f5f9] hover:text-[#0A1528] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X size={16} />
          </button>
        </div>
      ) : (
        <div
          onDragOver={onDragOver}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
          }}
          onDrop={onDrop}
          className={cn(
            "flex flex-col items-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors",
            dragging ? "border-primary bg-primary/5" : "border-[#cbd5e1] bg-[#f8fafc]",
            disabled && "opacity-60",
          )}
        >
          <UploadCloud size={24} className={dragging ? "text-primary" : "text-[#94a3b8]"} aria-hidden="true" />
          <p className="text-sm text-[#334155]">
            Drop your file here or{" "}
            <button
              type="button"
              disabled={disabled}
              onClick={() => inputRef.current?.click()}
              aria-describedby={hintId}
              className="font-bold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed"
            >
              Browse files
            </button>
          </p>
          <p id={hintId} className="text-[11px] text-[#64748b]">
            {hintText}
          </p>
        </div>
      )}
      {error && (
        <p id={errorId} role="alert" className="mt-1.5 text-xs font-semibold text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
