"use client";

// The two Business Kit shortcuts under the drop zone. Full row while the client has no
// documents; one quiet link afterwards, so returning clients aren't shown setup help.

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, ChevronDown, Copy, Download } from "lucide-react";
import { KIT_AI_PROMPT, KIT_INDUSTRIES, kitTemplateUrl } from "./kitContent";

const COPIED_RESET_MS = 2500;

export default function KitStarter({ compact }: { compact: boolean }) {
  const [open, setOpen] = useState(!compact);
  const [copied, setCopied] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => setOpen(!compact), [compact]);

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(KIT_AI_PROMPT);
      setCopied(true);
      toast.success("Copied. Paste it into ChatGPT, Gemini or Claude.");
      setTimeout(() => setCopied(false), COPIED_RESET_MS);
    } catch {
      toast.error("Could not copy. Please try again.");
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 inline-flex min-h-8 items-center font-label text-xs font-semibold text-primary hover:underline"
      >
        Need the template or AI prompt?
      </button>
    );
  }

  return (
    <div className="mt-4 flex flex-wrap items-center justify-center gap-2.5">
      <span className="font-body text-xs text-on-surface-muted">Nothing written yet?</span>
      <button
        type="button"
        onClick={copyPrompt}
        className="flex items-center gap-1.5 rounded-xl border border-primary-200 bg-white px-3.5 py-2 font-label text-xs font-semibold text-primary shadow-sm transition-colors hover:bg-primary/5"
      >
        {copied ? <Check size={13} strokeWidth={3} /> : <Copy size={13} />}
        {copied ? "Copied" : "Copy AI prompt"}
      </button>
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        aria-expanded={menuOpen}
        aria-controls="kit-industries"
        className="flex items-center gap-1.5 rounded-xl border border-surface-mid bg-white px-3.5 py-2 font-label text-xs font-semibold text-on-surface shadow-sm transition-colors hover:bg-surface-low"
      >
        <Download size={13} />
        Download template
        <ChevronDown size={13} className={menuOpen ? "rotate-180 transition-transform" : "transition-transform"} />
      </button>
      {/* Inline, not a floating menu: the upload card is overflow-hidden and clips it. */}
      {menuOpen && (
        <div id="kit-industries" className="w-full">
          <p className="mb-2 mt-1 font-label text-[10.5px] font-bold uppercase tracking-wider text-on-surface-muted">
            Pick your business type
          </p>
          <div className="flex flex-wrap justify-center gap-1.5">
            {KIT_INDUSTRIES.map((ind) => (
              <a
                key={ind.slug}
                href={kitTemplateUrl(ind.slug)}
                download
                className="rounded-lg border border-surface-mid bg-white px-2.5 py-1.5 font-body text-xs text-on-surface transition-colors hover:border-primary-200 hover:bg-primary/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                {ind.label}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
