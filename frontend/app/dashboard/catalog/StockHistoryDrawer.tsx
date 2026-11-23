"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink, Loader2, X } from "lucide-react";
import { api, StockMovement } from "@/lib/api";
import { STOCK_REASON_LABEL, formatDateTime } from "./money";

/** Slide-over listing every stock movement for one item, newest first. */
export function StockHistoryDrawer({
  itemId,
  itemName,
  onClose,
}: {
  itemId: string;
  itemName: string;
  onClose: () => void;
}) {
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    api.catalog
      .stockMovements(itemId)
      .then((data) => {
        if (!cancelled) setMovements(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load stock history");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [itemId]);

  return (
    <div className="fixed inset-0 z-dialog flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-sm flex-col bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h3 className="font-display text-base font-bold text-ink">Stock history</h3>
            <p className="truncate text-xs text-ink-muted" title={itemName}>{itemName}</p>
          </div>
          <button type="button" onClick={onClose} className="text-ink-muted hover:text-ink" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-ink-muted">
              <Loader2 size={16} className="animate-spin" />
              Loading history...
            </div>
          )}
          {!isLoading && error && (
            <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</div>
          )}
          {!isLoading && !error && movements.length === 0 && (
            <p className="py-10 text-center text-sm text-ink-muted">No stock movements yet.</p>
          )}
          {!isLoading && !error && movements.length > 0 && (
            <ul className="space-y-3">
              {movements.map((movement) => (
                <li key={movement.id} className="rounded-xl border border-border bg-surface-low p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={
                        movement.delta >= 0
                          ? "font-display text-sm font-bold text-success"
                          : "font-display text-sm font-bold text-danger"
                      }
                    >
                      {movement.delta >= 0 ? "+" : ""}
                      {movement.delta}
                    </span>
                    <span className="font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">
                      {STOCK_REASON_LABEL[movement.reason]}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-ink-muted">
                    <span>{formatDateTime(movement.created_at)}</span>
                    <span>{movement.quantity_after} after</span>
                  </div>
                  {movement.note && <p className="mt-1.5 text-xs text-ink">{movement.note}</p>}
                  {movement.photo_url && (
                    <a href={movement.photo_url} target="_blank" rel="noreferrer" className="mt-2 block w-fit" title="Open the photo">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={movement.photo_url} alt="Damaged pieces" className="h-16 w-16 rounded-lg border border-border object-cover" />
                    </a>
                  )}
                  {movement.deal_id && (
                    <Link
                      href={`/dashboard/deals/${movement.deal_id}`}
                      className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
                    >
                      Deal
                      <ExternalLink size={11} />
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
