"use client";

import { useEffect, useState } from "react";
import { Type } from "lucide-react";
import { SwitchPill } from "@/components/ui/controls";
import { cn } from "@/lib/utils";
import {
  type TextSize,
  readDarkerText,
  readTextSize,
  saveDarkerText,
  saveTextSize,
} from "@/lib/textSize";

const CARD = "rounded-2xl border border-border/70 bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,0.03)]";

const CHOICES: { size: TextSize; label: string; sample: string; sampleClass: string }[] = [
  { size: "normal", label: "Normal", sample: "Aa", sampleClass: "text-lg" },
  { size: "big", label: "Big", sample: "Aa", sampleClass: "text-2xl" },
  { size: "bigger", label: "Bigger", sample: "Aa", sampleClass: "text-3xl" },
];

/**
 * Text size: open to everyone who is logged in (telecallers too), so no permission gate.
 * The choice lives on this phone or laptop only (localStorage) and applies the moment it is picked.
 */
export default function TextSizePage() {
  const [size, setSize] = useState<TextSize>("normal");
  const [darker, setDarker] = useState(false);

  // Read the saved choice after mount: the server has no localStorage.
  useEffect(() => {
    setSize(readTextSize());
    setDarker(readDarkerText());
  }, []);

  function pickSize(next: TextSize) {
    setSize(next);
    saveTextSize(next);
  }

  function toggleDarker(next: boolean) {
    setDarker(next);
    saveDarkerText(next);
  }

  return (
    <div className="w-full space-y-4 pb-10">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary">
          <Type size={18} strokeWidth={1.6} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="text-sm text-ink-muted">Make the words easier to read. It changes the whole app.</p>
        </div>
      </div>

      <section className={CARD} aria-labelledby="text-size-heading">
        <h2 id="text-size-heading" className="text-sm font-semibold text-ink">How big should the text be?</h2>
        <div role="radiogroup" aria-labelledby="text-size-heading" className="mt-3 grid grid-cols-3 gap-2 sm:gap-3">
          {CHOICES.map((choice) => {
            const selected = size === choice.size;
            return (
              <button
                key={choice.size}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => pickSize(choice.size)}
                className={cn(
                  "flex min-h-11 flex-col items-center justify-center gap-1 rounded-xl border-2 px-2 py-3 text-sm font-semibold text-ink transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
                  selected ? "border-primary bg-primary-50" : "border-border bg-white hover:bg-surface-mid",
                )}
              >
                <span aria-hidden="true" className={cn("font-bold leading-none", choice.sampleClass)}>{choice.sample}</span>
                <span>{choice.label}</span>
              </button>
            );
          })}
        </div>

        <div className="mt-5 flex items-center justify-between gap-4 border-t border-border/70 pt-4">
          <div className="min-w-0">
            <p id="darker-text-label" className="text-sm font-semibold text-ink">Darker text</p>
            <p className="mt-0.5 text-sm text-ink-muted">Turns the light grey words darker, so they are easier to see.</p>
          </div>
          <SwitchPill on={darker} onChange={toggleDarker} aria-label="Darker text" />
        </div>
      </section>

      <section className={CARD} aria-labelledby="preview-heading">
        <h2 id="preview-heading" className="text-sm font-semibold text-ink">How it will look</h2>
        <div className="mt-3 flex items-center gap-3 rounded-xl border border-border/70 p-3">
          <span aria-hidden="true" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-bold text-primary-800">KS</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-sm font-semibold text-ink">Kavitha S</span>
              <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs font-semibold text-ink">Hot</span>
            </div>
            <p className="mt-0.5 truncate text-sm text-ink-secondary">Discount kidaikkuma?</p>
            <p className="mt-0.5 text-xs text-ink-muted">Waiting 2m</p>
          </div>
          <span className="inline-flex min-h-11 shrink-0 items-center rounded-lg bg-primary px-4 text-sm font-semibold text-white">Reply</span>
        </div>
        <p className="mt-3 text-sm text-ink-muted">
          Changes text on this phone or laptop only. Each person picks their own.
        </p>
      </section>
    </div>
  );
}
