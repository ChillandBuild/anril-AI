"use client";
import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Buttons side by side for a FIXED list of 2–4 choices (design "B"). One tap picks.
 * Lists that come from data, or have more than 4 choices, use Select instead.
 *
 * Example: <SegmentedControl aria-label="Status" value={status} onChange={setStatus}
 *            options={[{ value: "draft", label: "Draft", dot: "#94a3b8" }, { value: "live", label: "Live", dot: "#15803d" }]} />
 * Keyboard: Tab lands on the picked button, arrow keys move and pick, like radio buttons.
 */
export type SegmentOption<T extends string> = { value: T; label: ReactNode; dot?: string; disabled?: boolean };

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  disabled,
  size = "md",
  className,
  id,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SegmentOption<T>[];
  disabled?: boolean;
  /** sm = 30px tall, for filter bars. md = 36px, for forms. */
  size?: "sm" | "md";
  className?: string;
  id?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const enabled = options.map((o, i) => (!disabled && !o.disabled ? i : -1)).filter((i) => i >= 0);
  const current = options.findIndex((o) => o.value === value);
  // The button that Tab lands on: the picked one, or the first one that can be picked.
  const tabStop = current >= 0 && enabled.includes(current) ? current : enabled[0];

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step || enabled.length === 0) return;
    e.preventDefault();
    const at = enabled.indexOf(i);
    const next = enabled[(at + step + enabled.length) % enabled.length];
    refs.current[next]?.focus();
    onChange(options[next].value);
  };

  return (
    <div
      id={id}
      role="radiogroup"
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      aria-disabled={disabled || undefined}
      className={cn("inline-flex max-w-full flex-wrap gap-0.5 rounded-[10px] bg-surface-mid p-[3px]", className)}
    >
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={i === tabStop ? 0 : -1}
            disabled={disabled || o.disabled}
            onClick={() => !on && onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
              "disabled:cursor-not-allowed disabled:opacity-50",
              size === "sm" ? "h-[26px] px-2.5 text-[13px]" : "h-[30px] px-3.5 text-sm",
              on
                ? "bg-white font-medium text-ink shadow-[0_1px_3px_rgba(10,21,40,0.12)]"
                : "text-ink-secondary hover:text-ink",
            )}
          >
            {o.dot && <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: o.dot }} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
