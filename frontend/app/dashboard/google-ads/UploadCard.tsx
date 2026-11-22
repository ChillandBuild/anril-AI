"use client";

import { useEffect, useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { toast } from "sonner";
import { googleAdsApi } from "@/lib/googleAdsApi";
import type { GoogleAdsRow, UnmatchedRow, UploadResult } from "@/lib/googleAdsApi";
import { monthLabel, formatRupees } from "./googleAdsLogic";

const MAX_BYTES = 1_048_576;

/** Upload Google's campaign report; rows we can't match are paired with a campaign once. */
export function UploadCard({
  month,
  campaigns,
  showMoney,
  onChanged,
}: {
  month: string;
  campaigns: GoogleAdsRow[];
  showMoney: boolean;
  onChanged: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [unmatched, setUnmatched] = useState<UnmatchedRow[]>([]);
  // The month the file was saved for. Pairing must use it, not whatever month the picker shows now.
  const [uploadMonth, setUploadMonth] = useState<string | null>(null);

  // Rows left over from another month's upload no longer apply once the picker moves.
  useEffect(() => {
    setUnmatched([]);
    setResult(null);
    setUploadMonth(null);
  }, [month]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      toast.error("That file is too big (limit 1 MB). Download just the campaign report.");
      return;
    }
    setBusy(true);
    try {
      const res = await googleAdsApi.upload(month, file);
      setResult(res);
      setUnmatched(res.unmatched);
      setUploadMonth(res.month);
      if (res.matched.length === 0) toast.info("No campaigns matched yet — pick them below");
      else toast.success(`Saved ${res.matched.length} campaign${res.matched.length === 1 ? "" : "s"} for ${monthLabel(res.month)}`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function pair(row: UnmatchedRow, campaignId: string) {
    if (!campaignId || !uploadMonth) return;
    try {
      await googleAdsApi.pair({
        google_campaign_name: row.google_campaign_name,
        campaign_id: campaignId,
        month: uploadMonth,
        spend_paise: row.spend_paise,
        clicks: row.clicks,
      });
      setUnmatched((rows) => rows.filter((r) => r.google_campaign_name !== row.google_campaign_name));
      toast.success("Saved. Next time this name matches by itself.");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    }
  }

  return (
    <section className="card rounded-2xl p-4" aria-labelledby="upload-title">
      <h2 id="upload-title" className="font-display text-base font-bold text-on-surface">Upload Google Ads report</h2>
      <p className="mt-1 text-sm text-on-surface-muted">
        Google can&apos;t send us your spend yet, so download the report from Google and drop it here.
      </p>
      <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-on-surface">
        <li>In Google Ads, open <strong>Campaigns</strong> and pick the month at the top right.</li>
        <li>Click the <strong>Download</strong> icon and choose <strong>.csv</strong>.</li>
        <li>Come back here and choose that file below.</li>
      </ol>
      <div className="mt-3">
        <input
          ref={fileRef}
          id="gads-report-file"
          type="file"
          accept=".csv,text/csv,.tsv,text/tab-separated-values"
          className="peer sr-only"
          onChange={(e) => void onFile(e.target.files?.[0])}
        />
        <label
          htmlFor="gads-report-file"
          className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-bold text-white peer-focus-visible:ring-2 peer-focus-visible:ring-primary-300 peer-focus-visible:ring-offset-2"
        >
          <FileUp size={14} aria-hidden />
          {busy ? "Reading…" : `Choose report for ${monthLabel(month)}`}
        </label>
      </div>

      {result && result.skipped_other_months > 0 && (
        <p className="mt-3 text-sm text-on-surface-muted">
          {result.skipped_other_months} row{result.skipped_other_months === 1 ? "" : "s"} from other months {result.skipped_other_months === 1 ? "was" : "were"} left out.
        </p>
      )}

      {unmatched.length > 0 && (
        <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-3" role="region" aria-label="Campaigns we could not match">
          <p className="text-sm font-bold text-amber-900">Which campaign is this? ({monthLabel(uploadMonth ?? month)})</p>
          <p className="text-sm text-amber-900">
            We could not match these names from Google. Pick the campaign once and we will remember it.
          </p>
          <ul className="mt-2 space-y-2">
            {unmatched.map((row) => (
              <li key={row.google_campaign_name} className="flex flex-col gap-2 rounded-lg bg-white p-2 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold text-on-surface">{row.google_campaign_name}</p>
                  <p className="text-xs text-on-surface-muted">
                    {showMoney && row.spend_paise !== null ? `${formatRupees(row.spend_paise)} · ` : ""}
                    {row.clicks !== null ? `${row.clicks.toLocaleString("en-IN")} clicks` : "no clicks column"}
                  </p>
                </div>
                <select
                  aria-label={`Campaign for ${row.google_campaign_name}`}
                  defaultValue=""
                  onChange={(e) => void pair(row, e.target.value)}
                  className="rounded-lg border border-surface-mid bg-white px-2 py-2 text-sm"
                >
                  <option value="" disabled>Pick a campaign…</option>
                  {campaigns.map((c) => (
                    <option key={c.campaign_id} value={c.campaign_id}>{c.name}</option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
          {campaigns.length === 0 && (
            <p className="mt-2 text-sm text-amber-900">Make a tracked link first, then pick it here.</p>
          )}
        </div>
      )}
    </section>
  );
}
