"use client";
import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { companionsApi, type CompanionRequestKind, type CompanionRequestLog } from "@/lib/api";
import { formatMs } from "@/components/agents/playground";
import { KIND_LABEL, barMax, dailyBars, errorRate } from "@/components/agents/requestsView";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

const SELECT =
  "rounded-xl border border-border bg-white px-3 py-1.5 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15";
const DAY_OPTIONS = [1, 7, 30];

function timeLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Every call to the public API. Example: "9 Nov 10:42 · Chat (widget) · Jothidar AI · 48213 · 200 · 1.4 s". */
export default function RequestsPage() {
  const [kind, setKind] = useState<CompanionRequestKind | "">("");
  const [status, setStatus] = useState<"ok" | "error" | "">("");
  const [days, setDays] = useState(7);
  const [log, setLog] = useState<CompanionRequestLog | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    setLog(null);
    companionsApi
      .requests({ kind, status, days })
      .then(setLog)
      .catch((e: Error) => setError(e.message || "Could not load requests."));
  }, [kind, status, days]);
  useEffect(load, [load]);

  const bars = log ? dailyBars(log.daily, days) : [];
  const max = barMax(bars);

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-2">
        <label>
          <span className="sr-only">Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as CompanionRequestKind | "")} className={SELECT}>
            <option value="">All kinds</option>
            {(Object.keys(KIND_LABEL) as CompanionRequestKind[]).map((k) => (
              <option key={k} value={k}>{KIND_LABEL[k]}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Result</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as "ok" | "error" | "")} className={SELECT}>
            <option value="">All results</option>
            <option value="ok">Succeeded</option>
            <option value="error">Failed</option>
          </select>
        </label>
        <div role="radiogroup" aria-label="Time range" className="flex gap-1 rounded-xl bg-surface-mid p-1">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={days === d}
              onClick={() => setDays(d)}
              className={cn("rounded-lg px-3 py-1 text-sm font-medium", days === d ? "bg-white text-ink shadow-sm" : "text-ink-secondary hover:text-ink")}
            >
              {d === 1 ? "24 h" : `${d} days`}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <ErrorNote message={error} onRetry={load} />
      ) : !log ? (
        <LoadingRows rows={4} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[
              { label: "Requests", value: log.total.toLocaleString() + (log.capped ? "+" : "") },
              { label: "Failed", value: `${log.errors.toLocaleString()} (${errorRate(log.errors, log.total)})` },
              { label: "Median time", value: log.median_ms === null ? "—" : formatMs(log.median_ms) },
            ].map((t) => (
              <div key={t.label} className={cn(CARD, "p-4")}>
                <div className="text-xs text-ink-muted">{t.label}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{t.value}</div>
              </div>
            ))}
          </div>

          {days > 1 && (
            <section className={CARD} aria-labelledby="per-day">
              <h2 id="per-day" className="mb-3 text-sm font-semibold text-ink">Per day</h2>
              <div className="flex h-32 items-end gap-1" role="img" aria-label={bars.map((b) => `${b.date}: ${b.ok} ok, ${b.error} failed`).join("; ")}>
                {bars.map((b) => (
                  <div key={b.date} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`${b.date}: ${b.ok} ok, ${b.error} failed`}>
                    <div className="w-full rounded-t bg-danger/70" style={{ height: `${(b.error / max) * 100}%` }} />
                    <div className={cn("w-full bg-primary", b.error === 0 && "rounded-t")} style={{ height: `${(b.ok / max) * 100}%` }} />
                  </div>
                ))}
              </div>
              <div className="mt-2 flex justify-between text-xs text-ink-muted">
                <span>{bars[0]?.date}</span>
                <span className="flex gap-3">
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-primary" aria-hidden="true" /> Succeeded</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-danger/70" aria-hidden="true" /> Failed</span>
                </span>
                <span>{bars[bars.length - 1]?.date}</span>
              </div>
            </section>
          )}

          <section className={cn(CARD, "overflow-x-auto p-0")} aria-label="Latest requests">
            {log.requests.length === 0 ? (
              <p className="p-5 text-sm text-ink-secondary">
                No calls yet in this range. They show up here once your site or server talks to a character.
              </p>
            ) : (
              <table className="w-full min-w-[640px] text-sm">
                <thead className="border-b border-border-subtle text-left text-xs text-ink-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Time</th>
                    <th className="px-4 py-2 font-medium">Kind</th>
                    <th className="px-4 py-2 font-medium">Character</th>
                    <th className="px-4 py-2 font-medium">User id</th>
                    <th className="px-4 py-2 font-medium">Result</th>
                    <th className="px-4 py-2 text-right font-medium">Time taken</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {log.requests.map((r) => (
                    <tr key={r.id}>
                      <td className="whitespace-nowrap px-4 py-2 text-ink-secondary">{timeLabel(r.created_at)}</td>
                      <td className="px-4 py-2 text-ink">{KIND_LABEL[r.kind] ?? r.kind}</td>
                      <td className="px-4 py-2 text-ink">{r.companion_name ?? "—"}</td>
                      <td className="px-4 py-2 font-mono text-xs text-ink-secondary">{r.external_user_id ?? "—"}</td>
                      <td className="px-4 py-2">
                        <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium tabular-nums", r.status < 400 ? "bg-success/10 text-success" : "bg-danger/10 text-danger")}>
                          {r.status < 400 ? "OK" : "Failed"} · {r.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-ink-secondary">{formatMs(r.ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {log.requests.length >= 100 && <p className="border-t border-border-subtle px-4 py-2 text-xs text-ink-muted">Showing the newest 100.</p>}
          </section>
        </>
      )}
    </div>
  );
}
