"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowUp, CheckCircle2, Lightbulb } from "lucide-react";
import type { Blocker } from "../template-rules";

/** Auto-fix notes ("Removed emoji…") show for a few seconds, then fade. */
export function useFixNotes(ms = 6000) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const show = useCallback(
    (key: string, note: string | null) => {
      if (!note) return;
      clearTimeout(timers.current[key]);
      setNotes((prev) => ({ ...prev, [key]: note }));
      timers.current[key] = setTimeout(() => {
        setNotes((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
      }, ms);
    },
    [ms],
  );

  /** Drop every note, e.g. after the fields they point at changed position. */
  const clearAll = useCallback(() => {
    Object.values(timers.current).forEach(clearTimeout);
    setNotes({});
  }, []);

  useEffect(() => {
    const t = timers.current;
    return () => Object.values(t).forEach(clearTimeout);
  }, []);

  return { notes, show, clearAll };
}

type FieldMessagesProps = {
  id: string;
  note?: string | null;
  blockers?: Blocker[];
  tip?: string | null;
  onFix?: (fix: NonNullable<Blocker["fix"]>) => void;
};

/**
 * Messages under one field: green when we fixed something, red when the client must,
 * grey for advice. Linked to the field with aria-describedby={id}.
 */
export default function FieldMessages({ id, note, blockers = [], tip, onFix }: FieldMessagesProps) {
  const inline = blockers.filter((b) => b.inline);
  return (
    <div id={id} aria-live="polite" className="space-y-0.5 mt-1 empty:hidden">
      {note && (
        <p className="flex items-start gap-1.5 font-body text-[11px] text-emerald-700">
          <CheckCircle2 size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{note}</span>
        </p>
      )}
      {inline.map((b) => (
        <p key={b.message} className="flex items-start gap-1.5 font-body text-[11px] text-red-600">
          <AlertCircle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            {b.message}
            {b.fix && onFix && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => onFix(b.fix!)}
                  className="font-semibold underline underline-offset-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300"
                >
                  Fix numbering
                </button>
              </>
            )}
          </span>
        </p>
      ))}
      {tip && (
        <p className="flex items-start gap-1.5 font-body text-[11px] text-ink-muted">
          <Lightbulb size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{tip}</span>
        </p>
      )}
    </div>
  );
}

/** Sample-value rows for the variables in a piece of text. Input ids are `${idPrefix}${n}`. */
export function SampleInputs({
  variables,
  samples,
  onChange,
  idPrefix,
  label = "Example values",
  chipLabel = (n: number) => `{{${n}}}`,
}: {
  variables: number[];
  samples: Record<number, string>;
  onChange: (next: Record<number, string>) => void;
  idPrefix: string;
  label?: string;
  chipLabel?: (n: number) => string;
}) {
  if (!variables.length) return null;
  return (
    <div className="mt-2 rounded-xl border border-border-subtle bg-surface-subtle p-3 space-y-2">
      <div className="space-y-0.5">
        <p className="font-body text-xs font-semibold text-ink">{label}</p>
        <p className="font-body text-[11px] leading-relaxed text-ink-muted">
          Add a sample for each variable so that Meta can review your template. Samples are only used for
          review and won&apos;t be sent to your customers. Don&apos;t include real customer details, to protect
          their privacy.
        </p>
      </div>
      {variables.map((n) => {
        const value = samples[n] ?? "";
        return (
          <div key={n} className="grid grid-cols-[minmax(52px,max-content)_minmax(0,1fr)] items-center gap-2">
            <span
              className="justify-self-start whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold"
              style={{ background: "var(--primary-50)", color: "var(--primary-900)" }}
            >
              {chipLabel(n)}
            </span>
            <input
              id={`${idPrefix}${n}`}
              value={value}
              onChange={(e) => onChange({ ...samples, [n]: e.target.value })}
              maxLength={200}
              placeholder="e.g. Priya, 14 Oct, ORD-2291"
              aria-label={`Sample value for ${chipLabel(n)}`}
              aria-invalid={!value.trim()}
              className={`input text-sm ${value.trim() ? "" : "border-red-300"}`}
            />
          </div>
        );
      })}
    </div>
  );
}

/** Scroll to and focus the first field at fault. */
export function focusFirst(blockers: Blocker[]) {
  const el = blockers.length ? document.getElementById(blockers[0].fieldId) : null;
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  (el as HTMLElement).focus({ preventScroll: true });
}

/** Beside a disabled Continue/Submit button: what is left to fix; clicking jumps to the first one. */
export function BlockedReason({ blockers }: { blockers: Blocker[] }) {
  if (!blockers.length) return null;
  const single = blockers.length === 1 && !blockers[0].inline;
  const text = single ? blockers[0].message : `${blockers.length === 1 ? "thing" : "things"} to fix`;
  return (
    <button
      type="button"
      onClick={() => focusFirst(blockers)}
      aria-live="polite"
      title="Show me"
      className="group inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-50 py-1.5 pl-1.5 pr-3 font-body text-xs font-semibold text-red-700 transition-colors hover:border-red-300 hover:bg-red-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300"
    >
      {single ? (
        <AlertCircle size={16} className="shrink-0 text-red-600" aria-hidden="true" />
      ) : (
        <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-600 px-1.5 text-[11px] font-bold tabular-nums text-white">
          {blockers.length}
        </span>
      )}
      <span>{text}</span>
      <ArrowUp
        size={13}
        className="shrink-0 opacity-60 transition-transform group-hover:-translate-y-0.5 group-hover:opacity-100 motion-reduce:transition-none"
        aria-hidden="true"
      />
    </button>
  );
}
