"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, MetaCatalogueStatus } from "@/lib/api";

/** The line above the Items list: is the Catalogue copied to the shop's Meta (WhatsApp) catalogue? */
export function MetaCatalogueBar({ canManage, onChanged }: { canManage: boolean; onChanged?: () => void }) {
  const [status, setStatus] = useState<MetaCatalogueStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.catalog.metaStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  async function act(action: "on" | "off" | "again") {
    if (action === "on" && !window.confirm(
      "Show your Ready items in your WhatsApp catalogue?\n\nEvery Ready product with a price and a photo goes to Meta, with its sizes, colours and stock. After that, every sale and change goes by itself within a minute."
    )) return;
    if (action === "off" && !window.confirm("Stop sending changes to your WhatsApp catalogue? Meta keeps what it has now.")) return;
    setBusy(true);
    try {
      setStatus(await api.catalog.metaAction(action));
      onChanged?.();
      toast.success(action === "off" ? "WhatsApp catalogue paused" : "Sending your items to Meta");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't reach Meta");
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;

  if (!status.connected) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-white px-4 py-3 text-sm shadow-sm">
        <p className="text-ink">
          <span className="font-bold">🛍️ WhatsApp catalogue</span>
          <span className="text-ink-muted"> · Let customers browse your items inside WhatsApp. Connect Meta and pick your catalogue first.</span>
        </p>
        {canManage && (
          <Link href="/dashboard/settings/connect-channels" className="inline-flex h-8 items-center rounded-xl border border-border px-3 font-semibold text-ink hover:bg-surface-low">
            Connect Meta
          </Link>
        )}
      </div>
    );
  }

  if (!status.sync_on) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-primary/30 bg-primary-50/60 px-4 py-3 text-sm">
        <p className="text-ink">
          <span className="font-bold">🛍️ WhatsApp catalogue</span>
          <span className="text-ink-muted"> · {status.catalog_name ?? "Your Meta catalogue"} is connected. Turn it on to show your Ready items there, with live stock.</span>
        </p>
        {canManage && (
          <button type="button" onClick={() => act("on")} disabled={busy} className="btn-primary inline-flex h-8 items-center gap-1.5 !py-0">
            {busy && <Loader2 size={14} className="animate-spin" />} Show on WhatsApp
          </button>
        )}
      </div>
    );
  }

  const c = status.counts;
  const moving = c.sending + c.waiting;
  const needFix = c.error + c.skipped;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-emerald-200 bg-emerald-50/60 px-4 py-3 text-sm">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ink">
        <span className="font-bold">🛍️ WhatsApp catalogue · {status.catalog_name ?? "on"}</span>
        <span className="text-emerald-800">✓ {c.synced} on WhatsApp</span>
        {moving > 0 && <span className="text-ink-muted">{moving} sending</span>}
        {needFix > 0 && <span className="font-semibold text-rose-700">{needFix} need a fix (open the item to see why)</span>}
      </p>
      {canManage && (
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => act("again")} disabled={busy}
            className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-border bg-white px-3 font-semibold text-ink hover:bg-surface-low disabled:opacity-60">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Send all again
          </button>
          <button type="button" onClick={() => act("off")} disabled={busy}
            className="inline-flex h-8 items-center rounded-xl px-2 font-semibold text-ink-muted hover:text-ink disabled:opacity-60">
            Turn off
          </button>
        </div>
      )}
    </div>
  );
}
