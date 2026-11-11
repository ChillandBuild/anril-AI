"use client";
import { ArrowUp, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

/** Small pieces both Playground tabs share: the hero, the big input box, a chip. */

/**
 * Arrow-key switching for a row of tabs (roving tabindex: the selected tab is the only tab stop).
 * Example: on "Chat", ArrowRight selects "Search" and moves focus to it. Home / End jump to the ends.
 */
export function tabKeyDown<T extends string>(e: React.KeyboardEvent<HTMLElement>, order: T[], current: T, select: (t: T) => void) {
  const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  const i = order.indexOf(current);
  const next = e.key === "Home" ? 0 : e.key === "End" ? order.length - 1 : step ? (i + step + order.length) % order.length : -1;
  if (next < 0) return;
  e.preventDefault();
  select(order[next]);
  const tabs = e.currentTarget.parentElement?.querySelectorAll<HTMLElement>('[role="tab"]');
  tabs?.[next]?.focus();
}

/** Centered icon + title shown before anything is sent. Example: "See what Maya can do". */
export function Hero({ title }: { title: string }) {
  return (
    <div className="py-9 text-center">
      <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl border border-border bg-white text-primary shadow-sm">
        <Sparkles size={22} aria-hidden="true" />
      </div>
      <h2 className="text-[19px] font-semibold text-ink">{title}</h2>
    </div>
  );
}

/**
 * The big message box: text on top, small chips + Send under it, pickers
 * in the grey strip below. Example: Chat tab -> [model chip] [Auto-search] [Compare] (Send).
 */
export function PromptBox({
  id,
  label,
  value,
  onChange,
  onSubmit,
  placeholder,
  maxLength,
  disabled,
  sendDisabled,
  chips,
  pickers,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  maxLength: number;
  disabled?: boolean;
  sendDisabled?: boolean;
  chips?: React.ReactNode;
  pickers?: React.ReactNode;
}) {
  return (
    <form
      className="mx-auto w-full max-w-[720px] rounded-2xl border border-border bg-surface-mid"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="rounded-2xl border-b border-border bg-white px-3.5 py-3 shadow-sm">
        <label htmlFor={id} className="sr-only">
          {label}
        </label>
        <textarea
          id={id}
          rows={2}
          value={value}
          maxLength={maxLength}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            // Enter that confirms a Tamil / IME word must not send the message.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              onSubmit();
            }
          }}
          className="min-h-12 w-full resize-none bg-transparent text-sm text-ink placeholder:text-ink-muted focus:outline-none disabled:cursor-not-allowed"
        />
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink-secondary">
          {chips}
          <button
            type="submit"
            aria-label="Send"
            disabled={sendDisabled}
            className="ml-auto grid h-[34px] w-[34px] place-items-center rounded-[10px] bg-primary text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ArrowUp size={16} aria-hidden="true" />
          </button>
        </div>
      </div>
      {pickers && <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3.5 py-2.5 text-[13px]">{pickers}</div>}
    </form>
  );
}

/** A small pill in the box's chip row. `on` = highlighted (a switch that is on). */
export const CHIP = "inline-flex items-center gap-1 rounded-lg border border-border bg-white px-2 py-0.5 text-[13px] text-ink-secondary";
export const CHIP_ON = "border-primary/25 bg-primary/5 text-primary";

export function chipClass(on = false): string {
  return cn(CHIP, on && CHIP_ON);
}
