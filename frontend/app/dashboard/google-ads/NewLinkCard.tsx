"use client";

import { useState } from "react";
import { Check, Copy, Link2 } from "lucide-react";
import { toast } from "sonner";
import { googleAdsApi } from "@/lib/googleAdsApi";

/** Name a campaign, get the WhatsApp link to paste into Google Ads. */
export function NewLinkCard({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function make() {
    const campaign = name.trim();
    if (!campaign) {
      toast.error("Type a campaign name first.");
      return;
    }
    setBusy(true);
    try {
      const res = await googleAdsApi.makeLink(campaign);
      setLink(res.link);
      setCopied(false);
      onCreated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not make the link");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      toast.success("Link copied. Paste it into your Google ad.");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy. Select the link and copy it by hand.");
    }
  }

  return (
    <section className="card rounded-2xl p-4" aria-labelledby="new-link-title">
      <h2 id="new-link-title" className="font-display text-base font-bold text-on-surface">New tracked link</h2>
      <p className="mt-1 text-sm text-on-surface-muted">
        Use this link as the &quot;Final URL&quot; of your Google ad. Every chat that starts from it is counted for this campaign.
      </p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="gads-campaign-name">Campaign name</label>
        <input
          id="gads-campaign-name"
          value={name}
          maxLength={80}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void make(); }}
          placeholder="Campaign name, e.g. Diwali offer"
          className="min-w-0 flex-1 rounded-xl border border-surface-mid bg-surface-low px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-300"
        />
        <button
          type="button"
          onClick={make}
          disabled={busy}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
        >
          <Link2 size={14} aria-hidden />
          {busy ? "Making…" : link ? "Make another" : "Make link"}
        </button>
      </div>
      {link && (
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-surface-low p-3">
          <p className="min-w-0 flex-1 break-all font-mono text-xs text-on-surface" data-testid="gads-link">{link}</p>
          <button
            type="button"
            onClick={copy}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-surface-mid px-3 py-1.5 text-xs font-bold text-primary"
          >
            {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}
    </section>
  );
}
