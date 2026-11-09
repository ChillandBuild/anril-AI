"use client";
import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

export function CopyButton({ text, label = "Copy", className }: { text: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border border-border bg-white px-2.5 py-1 text-xs font-medium text-ink transition-colors hover:bg-surface-mid",
        className,
      )}
    >
      {copied ? <Check size={13} className="text-success" aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
      <span aria-live="polite">{copied ? "Copied" : label}</span>
    </button>
  );
}

export function CodeBlock({ title, code }: { title: string; code: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border-subtle">
      <div className="flex items-center justify-between border-b border-border-subtle bg-surface-mid/60 px-3 py-1.5">
        <span className="font-mono text-[11px] uppercase tracking-wide text-ink-muted">{title}</span>
        <CopyButton text={code} />
      </div>
      <pre className="max-h-80 overflow-auto bg-[#0b1220] p-3 text-xs leading-relaxed text-slate-100">
        <code>{code}</code>
      </pre>
    </div>
  );
}
