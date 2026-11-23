"use client";
import { useEffect, useRef, useState } from "react";
import { Archive, Ban, X } from "lucide-react";

export type ReasonKind = "archive" | "block";

const COPY: Record<ReasonKind, { title: string; sub: string; chips: string[]; button: string; placeholder: string }> = {
  archive: {
    title: "Archive this chat",
    sub: "It comes back to the Inbox by itself when they write again.",
    chips: ["Not now", "Done", "Order delivered", "Bought elsewhere", "Just asking"],
    button: "Archive",
    placeholder: "Or type why (optional)",
  },
  block: {
    title: "Block this contact",
    sub: "Nothing goes in or out, and the AI agent stays quiet. You can unblock any time.",
    chips: ["Spam links", "Abuse", "Sales calls", "Wrong number"],
    button: "Block",
    placeholder: "Or type why (optional)",
  },
};

/** Ask "Why?" before Archive or Block: a few one-tap reasons or the teammate's own words. Optional. */
export function ReasonDialog({
  kind,
  name,
  onCancel,
  onConfirm,
}: {
  kind: ReasonKind;
  name: string;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const c = COPY[kind];
  const [reason, setReason] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const Icon = kind === "block" ? Ban : Archive;
  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-[#0A1528]/45 p-4" onMouseDown={onCancel}>
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="reason-title"
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); onConfirm(reason.trim()); }}
        className="w-full max-w-[440px] rounded-2xl bg-white p-5 shadow-[0_30px_80px_-20px_rgba(10,21,40,0.45)]"
      >
        <div className="flex items-start gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${kind === "block" ? "bg-red-50 text-red-600" : "bg-primary-light text-primary"}`}>
            <Icon size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="reason-title" className="truncate font-display text-[17px] font-bold text-[#0A1528]">{c.title}: {name}</h2>
            <p className="mt-0.5 text-[12.5px] leading-snug text-[#64748b]">{c.sub}</p>
          </div>
          <button type="button" onClick={onCancel} aria-label="Close" className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        <p className="mb-2 mt-4 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Why?</p>
        <div className="flex flex-wrap gap-1.5">
          {c.chips.map((chip) => (
            <button
              key={chip}
              type="button"
              aria-pressed={reason === chip}
              onClick={() => setReason(reason === chip ? "" : chip)}
              className={`rounded-full border px-3 py-1 text-[12.5px] font-semibold transition ${
                reason === chip ? "border-primary bg-primary/10 text-primary" : "border-border text-ink-secondary hover:border-ink-muted"
              }`}
            >
              {chip}
            </button>
          ))}
        </div>
        <input
          ref={inputRef}
          value={reason}
          maxLength={120}
          onChange={(e) => setReason(e.target.value)}
          placeholder={c.placeholder}
          aria-label="Why"
          className="mt-3 h-10 w-full rounded-xl border border-border px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="h-9 rounded-xl px-4 text-sm font-semibold text-ink-secondary hover:bg-slate-100">
            Cancel
          </button>
          <button
            type="submit"
            className={`h-9 rounded-xl px-4 text-sm font-bold text-white ${kind === "block" ? "bg-red-600 hover:bg-red-700" : "bg-primary hover:bg-primary/90"}`}
          >
            {c.button}
          </button>
        </div>
      </form>
    </div>
  );
}
