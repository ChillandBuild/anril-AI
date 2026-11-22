"use client";

import { useState } from "react";
import { toast } from "sonner";
import { googleAdsApi } from "@/lib/googleAdsApi";
import type { GoogleAdsRow } from "@/lib/googleAdsApi";
import { parseWholeNumber, rupeesToPaise } from "./googleAdsLogic";

/** Type a month's spend and clicks by hand for one campaign. */
export function SpendEditor({
  row,
  month,
  onSaved,
  onCancel,
}: {
  row: GoogleAdsRow;
  month: string;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [spend, setSpend] = useState(row.spent_paise != null ? String(row.spent_paise / 100) : "");
  const [clicks, setClicks] = useState(row.clicks != null ? String(row.clicks) : "");
  const [busy, setBusy] = useState(false);

  async function save() {
    const spendPaise = rupeesToPaise(spend);
    const clickCount = clicks.trim() === "" ? 0 : parseWholeNumber(clicks);
    if (spendPaise === null) {
      toast.error("Type the spend in rupees, like 1200 or 1200.50.");
      return;
    }
    if (clickCount === null) {
      toast.error("Clicks must be a whole number.");
      return;
    }
    setBusy(true);
    try {
      await googleAdsApi.setSpend(row.campaign_id, { month, spend_paise: spendPaise, clicks: clickCount });
      toast.success("Saved");
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-lg border border-surface-mid bg-white px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-300";
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-surface-low p-3 sm:flex-row sm:items-end">
      <label className="flex-1 text-xs font-bold text-on-surface-muted">
        Spent (₹)
        <input className={field} inputMode="decimal" value={spend} onChange={(e) => setSpend(e.target.value)} />
      </label>
      <label className="flex-1 text-xs font-bold text-on-surface-muted">
        Clicks
        <input className={field} inputMode="numeric" value={clicks} onChange={(e) => setClicks(e.target.value)} />
      </label>
      <div className="flex gap-2">
        <button type="button" onClick={save} disabled={busy} className="rounded-lg bg-primary px-4 py-2 text-sm font-bold text-white disabled:opacity-40">
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onCancel} className="rounded-lg border border-surface-mid px-4 py-2 text-sm font-bold text-on-surface">
          Cancel
        </button>
      </div>
    </div>
  );
}
