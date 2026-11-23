"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { Check, ChevronDown, Loader2, Pause, Play, Plus, Search, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { CountLine, CountReason, StockCountFull, StockCountsView } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { useStockCounts } from "@/hooks/useApi";
import { StatCard } from "./ItemsTab";
import { ScanBox } from "./ScanBox";
import { formatPaise } from "./money";

/* Stock count (backend services/stock_counts.py, migration 312). Count one place in sections by scanning or
 * typing; selling goes on. Finish and fix stock (owner) applies each difference with its reason. */

const LESS: { value: CountReason; label: string }[] = [
  { value: "damaged", label: "Damaged" }, { value: "lost", label: "Lost" }, { value: "count_wrong", label: "Count wrong" },
];
const MORE: { value: CountReason; label: string }[] = [
  { value: "found", label: "Found in shop" }, { value: "count_wrong", label: "Count wrong" },
];

function items(n: number) {
  return `${n} ${n === 1 ? "item" : "items"}`;
}

function time(iso: string) {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

export function StockCountTab({ canCount, isOwner, toolbarSlot }: { canCount: boolean; isOwner: boolean; toolbarSlot: HTMLElement | null }) {
  const { data, error, mutate, isLoading } = useStockCounts();
  const count = data?.count ?? null;

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          Couldn&apos;t load the count. <button type="button" onClick={() => mutate()} className="font-semibold underline">Try again</button>
        </div>
      )}
      {isLoading && (
        <div className="flex items-center justify-center gap-2 rounded-card border border-border bg-white py-16 text-sm text-ink-muted">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      )}
      {data && !count && <StartCount data={data} canCount={canCount} onStarted={() => mutate()} />}
      {count && <OpenCount count={count} canCount={canCount} isOwner={isOwner} toolbarSlot={toolbarSlot} onChanged={() => mutate()} />}
      <div className="grid gap-3 lg:grid-cols-2">
        <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
          <span aria-hidden>📱</span> Staff count on the phone by scanning or typing, each in their own section. Selling can go on:
          bills made during the count are allowed for by themselves.
        </p>
        <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
          <span aria-hidden>🔒</span> &ldquo;Finish and fix stock&rdquo; needs the owner. Every change is saved in each item&apos;s stock
          history with the reason, and the loss shows in Expenses → Real profit as &ldquo;Stock loss&rdquo;.
        </p>
      </div>
    </div>
  );
}

function StartCount({ data, canCount, onStarted }: { data: StockCountsView; canCount: boolean; onStarted: () => void }) {
  const [place, setPlace] = useState(data.places.find((p) => p.bills_from)?.id ?? data.places[0]?.id ?? "");
  const [sections, setSections] = useState<string[]>([]);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);

  function addSection() {
    const s = typed.trim();
    if (s && !sections.includes(s)) setSections([...sections, s]);
    setTyped("");
  }

  async function start() {
    setBusy(true);
    try {
      await api.catalog.startCount(place, sections);
      toast.success("Count started. Staff can count now.");
      onStarted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't start the count.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="rounded-card border border-border bg-white p-5 shadow-sm">
        <h3 className="font-display text-lg font-bold text-ink">Start a stock count</h3>
        <p className="mt-1 text-sm text-ink-muted">Count one place. Add sections (racks, shelves) so each person counts their own part.</p>
        <label className="mt-4 block text-sm font-semibold text-ink">Place
          <Select value={place} onChange={setPlace} className="mt-1 w-full" aria-label="Place"
            options={data.places.map((p) => ({ value: p.id, label: p.name }))} />
        </label>
        <div className="mt-3">
          <p className="text-sm font-semibold text-ink">Sections <span className="font-normal text-ink-muted">(optional)</span></p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {sections.map((s) => (
              <span key={s} className="inline-flex items-center gap-1 rounded-full bg-surface-low px-2.5 py-1 text-sm text-ink">
                {s}<button type="button" onClick={() => setSections(sections.filter((x) => x !== s))} aria-label={`Remove ${s}`}><X size={12} /></button>
              </span>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <input value={typed} onChange={(e) => setTyped(e.target.value)} maxLength={60} placeholder="e.g. Saree rack 1"
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSection(); } }}
              className="h-10 flex-1 rounded-xl border border-border px-3 text-sm outline-none focus:border-primary" />
            <button type="button" onClick={addSection} className="inline-flex h-10 items-center gap-1 rounded-xl border border-border px-3 text-sm font-semibold text-ink hover:bg-surface-low">
              <Plus size={14} /> Add
            </button>
          </div>
        </div>
        <button type="button" onClick={start} disabled={!canCount || !place || busy}
          className="mt-4 inline-flex h-10 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-bold text-white hover:bg-primary-dark disabled:opacity-50">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />} Start count
        </button>
      </section>
      <section className="rounded-card border border-border bg-white p-5 shadow-sm">
        <h3 className="font-display text-base font-bold text-ink">Last counts</h3>
        {data.finished.length === 0 ? <p className="mt-3 text-sm text-ink-muted">No count finished yet.</p> : (
          <ul className="mt-2 divide-y divide-border-subtle">
            {data.finished.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 py-2.5 text-sm">
                <span className="text-ink"><b>{c.place}</b> · {c.finished_at ? new Date(c.finished_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : ""}
                  {c.finished_by_name ? ` · ${c.finished_by_name}` : ""}</span>
                <span className={cn("font-semibold tabular-nums", (c.loss_paise ?? 0) > (c.gain_paise ?? 0) ? "text-rose-700" : "text-emerald-700")}>
                  {c.loss_paise === undefined && c.gain_paise === undefined ? "finished" : (c.loss_paise ?? 0) || (c.gain_paise ?? 0) ? `${(c.loss_paise ?? 0) ? `−${formatPaise(c.loss_paise ?? 0)}` : ""}${(c.gain_paise ?? 0) ? ` +${formatPaise(c.gain_paise ?? 0)}` : ""}` : "all matched"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function OpenCount({ count, canCount, isOwner, toolbarSlot, onChanged }: {
  count: StockCountFull; canCount: boolean; isOwner: boolean; toolbarSlot: HTMLElement | null; onChanged: () => void;
}) {
  const [section, setSection] = useState<string>(count.sections[0] ?? "");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"finish" | "cancel" | null>(null);
  const [showMissing, setShowMissing] = useState(false);
  const paused = count.status === "paused";
  const c = count.cards;

  const candidates = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const all = [...count.lines.map((l) => ({ catalog_item_id: l.catalog_item_id, variant_id: l.variant_id, name: l.name, variant_label: l.variant_label })),
      ...count.not_counted];
    return all.filter((r) => `${r.name} ${r.variant_label}`.toLowerCase().includes(q)).slice(0, 8);
  }, [query, count]);

  async function run(key: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(key);
    try {
      await fn();
      if (done) toast.success(done);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setBusy(null);
    }
  }

  async function finish() {
    setBusy("finish");
    try {
      const out = await api.catalog.countAction(count.id, "finish");
      toast.success(`Stock fixed: ${out.changed ?? 0} ${out.changed === 1 ? "item" : "items"} changed${out.loss_paise ? `, ${formatPaise(out.loss_paise)} stock loss` : ""}.`);
      if (out.not_applied) toast.error(`${out.not_applied} ${out.not_applied === 1 ? "change" : "changes"} couldn't be applied (the stock moved meanwhile). Check those items and correct them by hand.`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't finish. Try again.");
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  }

  useEffect(() => { if (!count.sections.includes(section) && section) setSection(count.sections[0] ?? ""); }, [count.sections, section]);

  return (
    <>
      {toolbarSlot && canCount && createPortal(
        <>
          <button type="button" disabled={busy !== null}
            onClick={() => run("pause", () => api.catalog.countAction(count.id, paused ? "resume" : "pause"), paused ? "Count resumed." : "Count paused.")}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low">
            {paused ? <Play size={14} /> : <Pause size={14} />} {paused ? "Resume count" : "Pause count"}
          </button>
          {isOwner && (
            <button type="button" onClick={() => setConfirm("finish")} disabled={busy !== null || c.counted === 0}
              title={count.missing_reasons ? "Give a reason for every difference first" : undefined}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-primary px-3.5 text-sm font-bold text-white shadow-sm hover:bg-primary-dark disabled:opacity-50">
              <Check size={14} /> Finish and fix stock
            </button>
          )}
        </>,
        toolbarSlot,
      )}

      {confirm && (
        <div className="flex flex-wrap items-center gap-3 rounded-card border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {confirm === "finish" ? (
            count.missing_reasons ? <span>Give a reason for the {count.missing_reasons} {count.missing_reasons === 1 ? "difference" : "differences"} without one first.</span> : (
              <span>Fix stock at {count.place}: {c.less.items} {c.less.items === 1 ? "item goes" : "items go"} down ({formatPaise(c.less.value_paise)} at cost),{" "}
                {c.more.items} up. {c.not_counted} not counted {c.not_counted === 1 ? "stays" : "stay"} as {c.not_counted === 1 ? "it is" : "they are"}.</span>
            )
          ) : <span>Cancel this count? Nothing in stock changes; the counted numbers are dropped.</span>}
          <span className="ml-auto flex gap-2">
            {!(confirm === "finish" && count.missing_reasons) && (
              <button type="button" disabled={busy !== null} onClick={confirm === "finish" ? finish : () => run("cancel", () => api.catalog.countAction(count.id, "cancel"), "Count cancelled.")}
                className="inline-flex h-9 items-center gap-1 rounded-xl bg-primary px-3 font-bold text-white hover:bg-primary-dark disabled:opacity-60">
                {busy === "finish" && <Loader2 size={14} className="animate-spin" />} {confirm === "finish" ? "Yes, fix stock" : "Yes, cancel count"}
              </button>
            )}
            <button type="button" onClick={() => setConfirm(null)} className="h-9 rounded-xl border border-amber-300 bg-white px-3 font-semibold">Back</button>
          </span>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard icon="🔢" label="Counted" value={`${c.counted} of ${items(c.total)}`}
          sub={`${c.counters.length ? `by ${c.counters.join(" and ")} · ` : ""}${count.place} · started ${time(count.started_at)}${paused ? " · paused" : ""}`} />
        <StatCard icon="✅" label="Match" value={items(c.match)} sub="no change" />
        <StatCard icon="➖" label="Less than system" tone={c.less.items ? "red" : "plain"} value={`${items(c.less.items)} · ${c.less.pieces} pcs`} sub={c.less.value_paise === undefined ? "pieces only" : `${formatPaise(c.less.value_paise)} at cost`} />
        <StatCard icon="➕" label="More than system" value={`${items(c.more.items)} · ${c.more.pieces} pcs`} sub={c.more.value_paise === undefined ? "pieces only" : formatPaise(c.more.value_paise)} />
        <StatCard icon="⏳" label="Not counted yet" tone={c.not_counted ? "amber" : "plain"} value={items(c.not_counted)}
          sub="tap to see them" onClick={() => setShowMissing((v) => !v)} active={showMissing} />
      </div>

      {canCount && !paused && (
        <section className="grid gap-3 rounded-card border border-border bg-white p-4 shadow-sm lg:grid-cols-[200px_minmax(0,1fr)_minmax(0,1fr)]">
          {count.sections.length > 0 ? (
            <Select value={section} onChange={setSection} aria-label="Section" options={count.sections.map((s) => ({ value: s, label: s }))} />
          ) : <span className="self-center text-sm text-ink-muted">{count.place}</span>}
          <ScanBox placeholder="Scan each piece (adds 1)" onFound={(f) => run("scan", () => api.catalog.countLine(count.id, {
            item_id: f.catalog_item_id, variant_id: f.variant_id, section, add: 1 }), `+1 ${f.name}${f.variant_label ? ` · ${f.variant_label}` : ""}`)} />
          <div className="relative">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Or find an item to type its count"
              className="h-10 w-full rounded-xl border border-border pl-9 pr-3 text-sm outline-none focus:border-primary" />
            {candidates.length > 0 && (
              <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-xl border border-border bg-white shadow-lg">
                {candidates.map((r) => (
                  <li key={`${r.catalog_item_id}:${r.variant_id ?? ""}`}>
                    <TypeCount label={`${r.name}${r.variant_label ? ` · ${r.variant_label}` : ""}`}
                      onSave={(qty) => run("type", () => api.catalog.countLine(count.id, { item_id: r.catalog_item_id, variant_id: r.variant_id, section, qty }))
                        .then(() => setQuery(""))} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {showMissing && (
        <section className="rounded-card border border-border bg-white p-4 shadow-sm">
          <h3 className="flex items-center gap-1 font-display text-base font-bold text-ink"><ChevronDown size={15} /> Not counted yet</h3>
          {count.not_counted.length === 0 ? <p className="mt-2 text-sm text-ink-muted">Everything with stock here is counted.</p> : (
            <ul className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
              {count.not_counted.map((r) => (
                <li key={`${r.catalog_item_id}:${r.variant_id ?? ""}`} className="flex justify-between gap-2">
                  <span className="truncate text-ink">{r.name}{r.variant_label ? ` · ${r.variant_label}` : ""}</span>
                  <span className="shrink-0 text-ink-muted">system {r.system_qty}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
        <table className="w-full min-w-[920px] text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-4 py-3">Item</th>
              <th className="px-3 py-3">Section</th>
              <th className="px-3 py-3">System says</th>
              <th className="px-3 py-3">Counted</th>
              <th className="px-3 py-3">Difference</th>
              <th className="px-3 py-3">Counted by</th>
              <th className="px-3 py-3">Why</th>
            </tr>
          </thead>
          <tbody>
            {count.lines.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-ink-muted">Nothing counted yet. Scan a piece or find an item above.</td></tr>
            )}
            {count.lines.map((l) => <CountRow key={l.id} line={l} countId={count.id} canCount={canCount && !paused} onChanged={onChanged} />)}
          </tbody>
        </table>
      </div>
      {canCount && <p className="text-right text-xs text-ink-muted">
        <button type="button" onClick={() => setConfirm("cancel")} className="font-semibold hover:text-ink">Cancel this count</button>
        {" · "}<Link href="/dashboard/catalog/labels" className="font-semibold hover:text-ink">Print barcode labels</Link>
      </p>}
    </>
  );
}

function TypeCount({ label, onSave }: { label: string; onSave: (qty: number) => Promise<unknown> | void }) {
  const [qty, setQty] = useState("");
  return (
    <div className="flex items-center gap-2 px-3 py-1.5">
      <span className="min-w-0 flex-1 truncate text-ink">{label}</span>
      <input value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" placeholder="count" aria-label={`Count of ${label}`}
        onKeyDown={(e) => { if (e.key === "Enter" && qty !== "") onSave(Number(qty)); }}
        className="h-8 w-20 rounded-lg border border-border px-2 text-right tabular-nums outline-none focus:border-primary" />
      <button type="button" disabled={qty === ""} onClick={() => onSave(Number(qty))}
        className="h-8 rounded-lg bg-primary px-2.5 text-xs font-bold text-white disabled:opacity-50">Save</button>
    </div>
  );
}

function CountRow({ line: l, countId, canCount, onChanged }: { line: CountLine; countId: string; canCount: boolean; onChanged: () => void }) {
  const [qty, setQty] = useState(String(l.counted_qty));
  useEffect(() => setQty(String(l.counted_qty)), [l.counted_qty]);
  const reasons = l.difference < 0 ? LESS : l.difference > 0 ? MORE : [];

  async function save(next: Partial<{ qty: number; reason: CountReason | null }>) {
    try {
      if (next.qty !== undefined) await api.catalog.countLine(countId, { item_id: l.catalog_item_id, variant_id: l.variant_id, qty: next.qty });
      if (next.reason !== undefined) await api.catalog.countReason(l.id, next.reason);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    }
  }

  return (
    <tr className="border-b border-border-subtle last:border-b-0">
      <td className="px-4 py-3 font-bold text-ink">{l.name}{l.variant_label ? ` · ${l.variant_label}` : ""}</td>
      <td className="px-3 py-3 text-ink">{l.section ?? <span className="text-ink-muted">—</span>}</td>
      <td className="px-3 py-3 tabular-nums text-ink">{l.system_qty}</td>
      <td className="px-3 py-3">
        {canCount ? (
          <input value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" aria-label={`Counted ${l.name}`}
            onBlur={() => { if (qty !== "" && Number(qty) !== l.counted_qty) save({ qty: Number(qty) }); }}
            className="h-8 w-16 rounded-lg border border-border px-2 text-right font-bold tabular-nums outline-none focus:border-primary" />
        ) : <b className="tabular-nums">{l.counted_qty}</b>}
      </td>
      <td className="px-3 py-3">
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold tabular-nums",
          l.difference < 0 ? "bg-rose-50 text-rose-700" : l.difference > 0 ? "bg-emerald-50 text-emerald-700" : "bg-emerald-50 text-emerald-700")}>
          {l.difference > 0 ? `+${l.difference}` : l.difference}
        </span>
      </td>
      <td className="px-3 py-3 text-ink">{l.counted_by_name ?? "—"}</td>
      <td className="px-3 py-3">
        {reasons.length === 0 ? <span className="text-ink-muted">—</span> : (
          <span className="flex flex-wrap gap-1.5">
            {reasons.map((r) => (
              <button key={r.value} type="button" disabled={!canCount} onClick={() => save({ reason: l.reason === r.value ? null : r.value })}
                className={cn("rounded-full border px-2.5 py-0.5 text-xs font-semibold",
                  l.reason === r.value ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink-secondary hover:bg-surface-low",
                  !l.reason && "border-amber-300")}>
                {r.label}
              </button>
            ))}
          </span>
        )}
      </td>
    </tr>
  );
}
