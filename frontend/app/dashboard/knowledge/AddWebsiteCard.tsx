"use client";

import { useState } from "react";
import { Globe, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { knowledgeWebApi, tidyWebsite } from "@/lib/knowledgeWebApi";

/**
 * v9.2 #168: paste a website link and Anril reads that one page like an uploaded file (it is sorted and
 * goes to review before anything changes). The server only reads public pages.
 */
export default function AddWebsiteCard({ onAdded }: { onAdded: () => Promise<void> | void }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = tidyWebsite(url);
    if (!clean || busy) return;
    setBusy(true);
    setError(null);
    try {
      await knowledgeWebApi.addWebsite(clean);
      setUrl("");
      toast.success("Link added. Anril is reading the page.");
      try {
        await onAdded();
      } catch {
        // The page was added; the list refreshes on the next poll.
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Couldn't read that link. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="bg-surface rounded-2xl border border-surface-mid shadow-sm p-4 sm:p-5">
      <h2 className="font-display font-bold text-base text-on-surface flex items-center gap-2">
        <Globe size={18} className="text-primary" />
        Add a website link
      </h2>
      <p className="font-body text-xs text-on-surface-muted mt-0.5">
        Paste the address of one page (your About or Price page). Anril reads its text like an uploaded file. Only public pages can be read.
      </p>
      <div className="mt-3 flex flex-col sm:flex-row gap-2">
        <input
          type="text"
          inputMode="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://yourshop.com/about"
          aria-label="Website address"
          maxLength={2000}
          className="min-w-0 flex-1 rounded-xl border border-surface-mid bg-white px-3 py-2 font-body text-sm text-on-surface"
        />
        <button type="submit" disabled={busy || !url.trim()} className="btn-primary justify-center disabled:opacity-60">
          {busy ? <Loader2 size={16} className="animate-spin" /> : null}
          {busy ? "Reading…" : "Add link"}
        </button>
      </div>
      {error && <p role="alert" className="mt-2 font-body text-xs text-red-700">{error}</p>}
    </form>
  );
}
