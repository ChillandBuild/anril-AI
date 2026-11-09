"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";

/** A small download icon beside a lead count. Inside clickable rows, so it
 * keeps its click to itself. `download` reads live from Meta, so every click
 * includes the newest leads. */
export function LeadsDownloadButton({ label, download }: { label: string; download: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={busy}
      onClick={async (event) => {
        event.stopPropagation();
        setBusy(true);
        try {
          await download();
        } catch (error) {
          toast.error(error instanceof Error ? error.message : "Couldn't download the leads.");
        } finally {
          setBusy(false);
        }
      }}
      onKeyDown={(event) => event.stopPropagation()}
      className="ml-1.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md align-middle text-[#94a3b8] transition-colors hover:bg-primary-50 hover:text-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-200 disabled:cursor-wait"
    >
      {busy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
    </button>
  );
}
