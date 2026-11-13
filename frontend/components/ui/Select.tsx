"use client";
import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The dashboard's dropdown menu (design "A"). Use it for long lists and lists that come from data.
 * Fixed lists of 4 or fewer choices use SegmentedControl instead.
 *
 * Example: <Select value={templateId} onChange={setTemplateId} placeholder="Pick a template"
 *            options={templates.map((t) => ({ value: t.id, label: t.name }))} />
 * The menu floats above the page (portal), so it is never cut off inside a popup.
 */
export type SelectOption = {
  value: string;
  label: ReactNode;
  /** Plain text for type-to-jump when the label is not a string. */
  text?: string;
  disabled?: boolean;
  /** Options with the same group are shown under that heading, in the order they appear. */
  group?: string;
  /** A small coloured dot before the label, e.g. green for Live. */
  dot?: string;
};

// Radix reserves "" for "nothing picked", but many of our lists use "" for "All" or "None".
const EMPTY = "__anril_empty__";
const enc = (v: string) => (v === "" ? EMPTY : v);
const dec = (v: string) => (v === EMPTY ? "" : v);

export function Select({
  value,
  onChange,
  options,
  placeholder = "Select…",
  disabled,
  id,
  name,
  className,
  size = "md",
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  name?: string;
  className?: string;
  /** sm = 32px tall, for filter bars and table rows. md = 40px, for forms. */
  size?: "sm" | "md";
  "aria-label"?: string;
  "aria-labelledby"?: string;
}) {
  // Data can repeat a value (two templates both named "welcome", in English and Tamil). The native
  // select shrugged that off; Radix would tick both rows, so keep the first of each.
  const unique = options.filter((o, i) => options.findIndex((x) => x.value === o.value) === i);
  const hasValue = unique.some((o) => o.value === value);
  const groups: { name: string | undefined; items: SelectOption[] }[] = [];
  for (const o of unique) {
    const last = groups[groups.length - 1];
    if (last && last.name === o.group) last.items.push(o);
    else groups.push({ name: o.group, items: [o] });
  }

  return (
    <RadixSelect.Root
      // "" keeps Radix controlled and shows the placeholder. undefined would make it uncontrolled, so an
      // "Add a product" picker that always resets to "" would keep showing the last pick.
      value={hasValue ? enc(value) : ""}
      onValueChange={(v) => onChange(dec(v))}
      disabled={disabled}
      name={name}
    >
      <RadixSelect.Trigger
        id={id}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        className={cn(
          "group inline-flex w-full min-w-0 items-center justify-between gap-3 rounded-[10px] border border-border bg-white text-left text-ink transition-colors",
          "hover:border-slate-300 focus:outline-none focus-visible:border-primary focus-visible:ring-[3px] focus-visible:ring-primary/15",
          "data-[state=open]:border-primary data-[state=open]:ring-[3px] data-[state=open]:ring-primary/15",
          "data-[placeholder]:text-ink-muted disabled:cursor-not-allowed disabled:bg-surface-mid disabled:opacity-60",
          size === "sm" ? "h-8 pl-3 pr-2.5 text-[13px]" : "h-10 pl-3.5 pr-3 text-sm",
          className,
        )}
      >
        <span className="flex min-w-0 items-center gap-2 truncate">
          <RadixSelect.Value placeholder={placeholder} />
        </span>
        <RadixSelect.Icon asChild>
          <ChevronDown
            aria-hidden
            className="h-4 w-4 shrink-0 text-ink-muted transition-transform duration-150 group-data-[state=open]:rotate-180 group-data-[state=open]:text-primary"
          />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>

      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={6}
          // Escape closes just this menu. Radix listens on document (capture) and only prevents default,
          // so without this the SMS modal and the auto-message editor around it closed too.
          onEscapeKeyDown={(e) => e.stopPropagation()}
          collisionPadding={12}
          className={cn(
            "z-[1000] max-h-[min(320px,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] max-w-[min(420px,calc(100vw-24px))]",
            "overflow-hidden rounded-xl border border-border bg-white p-1.5 shadow-[0_8px_24px_rgba(10,21,40,0.10)]",
          )}
        >
          <RadixSelect.Viewport>
            {groups.map((g, gi) => (
              <RadixSelect.Group key={`${g.name ?? ""}-${gi}`}>
                {g.name && (
                  <RadixSelect.Label className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                    {g.name}
                  </RadixSelect.Label>
                )}
                {g.items.map((o) => (
                  <RadixSelect.Item
                    key={o.value}
                    value={enc(o.value)}
                    disabled={o.disabled}
                    textValue={o.text ?? (typeof o.label === "string" ? o.label : undefined)}
                    className={cn(
                      "relative flex cursor-pointer select-none items-center gap-2.5 rounded-lg py-2 pl-2.5 pr-8 text-sm text-ink outline-none",
                      "data-[highlighted]:bg-primary-50 data-[state=checked]:font-medium data-[state=checked]:text-primary-900",
                      "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40",
                    )}
                  >
                    <RadixSelect.ItemText>
                      <span className="flex min-w-0 items-center gap-2">
                        {o.dot && <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: o.dot }} />}
                        <span className="truncate">{o.label}</span>
                      </span>
                    </RadixSelect.ItemText>
                    <RadixSelect.ItemIndicator className="absolute right-2.5 inline-flex items-center text-primary">
                      <Check aria-hidden className="h-4 w-4" />
                    </RadixSelect.ItemIndicator>
                  </RadixSelect.Item>
                ))}
              </RadixSelect.Group>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
