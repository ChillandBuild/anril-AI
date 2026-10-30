"use client";
import { useCallback, useEffect, useState } from "react";
import { MessageSquareText, RefreshCw } from "lucide-react";
import { getOperatorSmsStock, type OperatorSmsStock } from "@/lib/operator";

/** Reseller SMS stock (Bulk9). Red when below the low-stock threshold. */
export function SmsStockCard() {
  const [stock, setStock] = useState<OperatorSmsStock | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStock(await getOperatorSmsStock());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load SMS stock");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const low = stock?.low === true;
  const failed = err !== null || (stock?.error ?? null) !== null;
  const tone = low ? "border-danger/30 bg-red-50" : "border-border bg-white";

  return (
    <div className={`rounded-card border p-4 shadow-sm ${tone}`}>
      <div className="flex items-center justify-between gap-3">
        <p className={`flex items-center gap-2 text-xs font-medium uppercase tracking-wider font-label ${low ? "text-danger" : "text-ink-muted"}`}>
          <MessageSquareText size={14} /> SMS stock (Bulk9)
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          aria-label="Refresh SMS stock"
          className="text-ink-muted hover:text-ink disabled:opacity-60"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      {failed ? (
        <p className="mt-2 text-sm text-danger">{err ?? stock?.error}</p>
      ) : stock ? (
        <div className={`mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1`}>
          <p className={`text-2xl font-bold ${low ? "text-danger" : "text-ink"}`}>
            {(stock.sms_count ?? 0).toLocaleString("en-IN")} <span className="text-sm font-medium text-ink-muted">SMS left</span>
          </p>
          {stock.sms_balance !== null && (
            <p className="text-xs text-ink-muted">
              Balance ₹{stock.sms_balance.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
          )}
          <p className={`text-xs ${low ? "font-semibold text-danger" : "text-ink-muted"}`}>
            {low ? "Low — top up Bulk9. " : ""}Alert below {stock.threshold.toLocaleString("en-IN")}
          </p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-ink-muted">Loading…</p>
      )}
    </div>
  );
}
