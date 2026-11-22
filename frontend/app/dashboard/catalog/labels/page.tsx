"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import useSWR from "swr";
import { Check, ChevronLeft, Loader2, Minus, Plus, Printer, ScanLine, Search } from "lucide-react";
import { toast } from "sonner";
import { api, type LabelLine, type PrintLabel } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import { Barcode } from "../ScanBox";
import { formatPaise } from "../money";

/* Barcode labels (backend services/barcodes.py): Anril's own short code per item and size/colour,
 * printed from the browser on a label printer roll or A4 sheets; a company barcode is kept, not printed. */

type Source = "stock_in" | "pick" | "no_code";
type Size = "38x25" | "50x25" | "a4_65";
type Show = "shop" | "item" | "variant" | "price" | "barcode";

const SIZES: { value: Size; label: string }[] = [
  { value: "38x25", label: "38 × 25 mm · roll" },
  { value: "50x25", label: "50 × 25 mm · roll" },
  { value: "a4_65", label: "A4 sheet · 65 per page" },
];
const SHOWS: { value: Show; label: string }[] = [
  { value: "shop", label: "Shop name" },
  { value: "item", label: "Item" },
  { value: "variant", label: "Size / colour" },
  { value: "price", label: "Price (MRP)" },
  { value: "barcode", label: "Barcode" },
];

const PRINT_CSS: Record<Size, string> = {
  "38x25": "@page { size: 38mm 25mm; margin: 0 } .lbl { width: 38mm; height: 25mm } .lbl:not(:last-child) { break-after: page }",
  "50x25": "@page { size: 50mm 25mm; margin: 0 } .lbl { width: 50mm; height: 25mm } .lbl:not(:last-child) { break-after: page }",
  a4_65: "@page { size: A4; margin: 10.7mm 4.7mm } #anril-labels-print { display: grid !important; grid-template-columns: repeat(5, 38.1mm); column-gap: 2.5mm; grid-auto-rows: 21.2mm } .lbl { width: 38.1mm; height: 21.2mm }",
};

export default function LabelsPage() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("catalog.manage");
  const { data: opts, error, mutate: mutateOpts } = useSWR("stock/labels/options", () => api.catalog.labelOptions());
  const [source, setSource] = useState<Source>("stock_in");
  const [size, setSize] = useState<Size>("38x25");
  const [show, setShow] = useState<Set<Show>>(new Set(SHOWS.map((s) => s.value)));
  const [picked, setPicked] = useState<Record<string, { line: LabelLine; qty: number }>>({});
  const [query, setQuery] = useState("");
  const [labels, setLabels] = useState<PrintLabel[] | null>(null);
  const [kept, setKept] = useState(0);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  useEffect(() => {
    if (opts && !opts.stock_in && source === "stock_in") setSource(opts.no_code ? "no_code" : "pick");
  }, [opts, source]);

  const pickedLines = useMemo(() => Object.values(picked), [picked]);
  const request = useCallback((save: boolean) => (source === "pick"
    ? { source, save, lines: pickedLines.map((p) => ({ item_id: p.line.item_id, variant_id: p.line.variant_id, qty: p.qty })) }
    : source === "stock_in" ? { source, save, stock_in_id: opts?.stock_in?.id } : { source, save }), [source, pickedLines, opts]);
  const load = useCallback(async () => {
    if (!canManage || !opts) return;
    if (source === "pick" && pickedLines.length === 0) { setLabels([]); setKept(0); return; }
    setLoading(true);
    try {
      const out = await api.catalog.labels(request(false));
      setLabels(out.labels);
      setKept(out.kept_company);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't make the labels.");
      setLabels([]);
    } finally {
      setLoading(false);
    }
  }, [canManage, opts, source, pickedLines, request]);
  useEffect(() => { load(); }, [load]);

  // Print saves the codes first (the preview only shows what they will be), then opens the print window.
  async function print() {
    setLoading(true);
    try {
      const out = await api.catalog.labels(request(true));
      setLabels(out.labels);
      setKept(out.kept_company);
      mutateOpts();
      window.setTimeout(() => window.print(), 50);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't make the labels.");
    } finally {
      setLoading(false);
    }
  }

  const total = (labels ?? []).reduce((n, l) => n + l.qty, 0);
  const shopName = opts?.shop_name || "";
  const matches = query.trim()
    ? (opts?.lines ?? []).filter((l) => `${l.name} ${l.variant_label}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 8)
    : [];

  if (!canManage) {
    return <p className="py-20 text-center text-sm text-ink-muted">Printing labels needs permission to manage the catalogue.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href="/dashboard/catalog" className="inline-flex items-center gap-1 text-sm font-semibold text-ink-muted hover:text-ink">
          <ChevronLeft size={16} /> Catalogue
        </Link>
        <button type="button" onClick={print} disabled={!total || loading}
          className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-bold text-white shadow-sm hover:bg-primary-dark disabled:opacity-50">
          <Printer size={15} /> Print {total} {total === 1 ? "label" : "labels"}
        </button>
      </div>
      {error && <p className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">Couldn&apos;t load. Refresh to try again.</p>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="space-y-3">
          <section className="rounded-card border border-border bg-white p-4 shadow-sm">
            <h2 className="font-display text-base font-bold text-ink">1 · What to print</h2>
            <div className="mt-2 divide-y divide-border-subtle">
              {([
                ["stock_in", opts?.stock_in ? `From today's stock in${opts.stock_in.bill_no ? ` (${opts.stock_in.bill_no})` : ""}` : "From today's stock in", opts?.stock_in ? `${opts.stock_in.labels} labels` : "none today", !opts?.stock_in],
                ["pick", "Pick items", pickedLines.length ? `${pickedLines.length} picked` : "", false],
                ["no_code", "Items with no barcode yet", opts ? `${opts.no_code} items` : "", !opts?.no_code],
              ] as [Source, string, string, boolean][]).map(([value, text, count, off]) => (
                <label key={value} className={cn("flex cursor-pointer items-center gap-3 py-2.5", off && "cursor-not-allowed opacity-50")}>
                  <input type="radio" name="source" checked={source === value} disabled={off} onChange={() => setSource(value)} className="h-4 w-4 accent-[var(--primary)]" />
                  <span className="flex-1 text-sm text-ink">{text}</span>
                  <span className="text-sm font-bold text-ink">{count}</span>
                </label>
              ))}
            </div>
            {source === "pick" && (
              <div className="mt-2 space-y-2">
                {pickedLines.map(({ line, qty }) => {
                  const key = `${line.item_id}:${line.variant_id ?? ""}`;
                  const set = (n: number) => setPicked((p) => (n <= 0 ? Object.fromEntries(Object.entries(p).filter(([k]) => k !== key)) : { ...p, [key]: { line, qty: Math.min(n, 500) } }));
                  return (
                    <div key={key} className="flex items-center gap-2 rounded-xl border border-border px-3 py-1.5">
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">{line.name}{line.variant_label ? ` · ${line.variant_label}` : ""}</span>
                      {line.company && <span className="rounded-full bg-surface-low px-2 py-0.5 text-[11px] text-ink-muted">company barcode</span>}
                      <span className="flex items-center rounded-lg border border-border">
                        <button type="button" onClick={() => set(qty - 1)} aria-label="One less" className="px-1.5 py-1 text-ink-muted"><Minus size={12} /></button>
                        <span className="w-8 text-center text-xs font-bold tabular-nums">{qty}</span>
                        <button type="button" onClick={() => set(qty + 1)} aria-label="One more" className="px-1.5 py-1 text-ink-muted"><Plus size={12} /></button>
                      </span>
                    </div>
                  );
                })}
                <div className="relative">
                  <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Add an item"
                    className="h-10 w-full rounded-xl border border-dashed border-border pl-9 pr-3 text-sm outline-none focus:border-primary" />
                  {matches.length > 0 && (
                    <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-xl border border-border bg-white shadow-lg">
                      {matches.map((l) => (
                        <li key={`${l.item_id}:${l.variant_id ?? ""}`}>
                          <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-surface-low"
                            onClick={() => { setPicked((p) => ({ ...p, [`${l.item_id}:${l.variant_id ?? ""}`]: { line: l, qty: 1 } })); setQuery(""); }}>
                            {l.name}{l.variant_label ? ` · ${l.variant_label}` : ""}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </section>

          <section className="rounded-card border border-border bg-white p-4 shadow-sm">
            <h2 className="font-display text-base font-bold text-ink">2 · Label size</h2>
            <div className="mt-2 flex flex-wrap gap-2">
              {SIZES.map((s) => (
                <button key={s.value} type="button" onClick={() => setSize(s.value)} aria-pressed={size === s.value}
                  className={cn("h-9 rounded-xl border px-3 text-sm font-semibold", size === s.value ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink hover:bg-surface-low")}>
                  {s.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-sm text-ink-muted">Works with any label printer (TSC, Zebra, TVS) or a normal printer for A4. In the print window, pick the label printer and set margins to none.</p>
          </section>

          <section className="rounded-card border border-border bg-white p-4 shadow-sm">
            <h2 className="font-display text-base font-bold text-ink">3 · Show on label</h2>
            <div className="mt-2 flex flex-wrap gap-2">
              {SHOWS.map((s) => {
                const on = show.has(s.value);
                return (
                  <button key={s.value} type="button" aria-pressed={on} disabled={s.value === "barcode"}
                    onClick={() => setShow((cur) => { const n = new Set(cur); if (on) n.delete(s.value); else n.add(s.value); return n; })}
                    className={cn("inline-flex h-9 items-center gap-1 rounded-xl border px-3 text-sm font-semibold disabled:cursor-not-allowed",
                      on ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink-muted hover:bg-surface-low")}>
                    {on && <Check size={13} />} {s.label}
                  </button>
                );
              })}
            </div>
          </section>

          <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm text-ink">
            Items that already have a company barcode (EAN) keep it, so nothing is printed for them{kept ? ` (${kept} left out here)` : ""}. Type it on the item&apos;s page.
          </p>
        </div>

        <div className="space-y-3">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">Preview</p>
          {loading ? (
            <div className="flex items-center justify-center gap-2 rounded-card border border-border bg-white py-16 text-sm text-ink-muted"><Loader2 size={16} className="animate-spin" /> Making labels…</div>
          ) : labels && labels.length ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {labels.slice(0, 9).map((l) => (
                <div key={l.code} className="rounded-xl border border-dashed border-border bg-white p-3">
                  <LabelFace label={l} shop={shopName} show={show} />
                  {l.qty > 1 && <p className="mt-1 text-center text-[11px] text-ink-muted">× {l.qty}</p>}
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-card border border-border bg-white px-4 py-10 text-center text-sm text-ink-muted">
              {source === "pick" ? "Add items to print labels for them." : "Nothing to print here."}
            </p>
          )}
          {labels && labels.length > 9 && <p className="text-xs text-ink-muted">and {labels.length - 9} more items</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Link href="/dashboard/deals/new-bill" className="rounded-card border border-border bg-white p-4 shadow-sm hover:border-primary/40">
              <p className="font-display font-bold text-ink"><ScanLine size={15} className="mr-1 inline" /> Scan to bill <span className="text-sm font-normal text-ink-muted">New bill</span></p>
              <p className="mt-1 text-sm text-ink-muted">Phone camera or a USB scanner adds the item with the right size and colour.</p>
            </Link>
            <Link href="/dashboard/purchases/stock-in" className="rounded-card border border-border bg-white p-4 shadow-sm hover:border-primary/40">
              <p className="font-display font-bold text-ink"><ScanLine size={15} className="mr-1 inline" /> Scan to stock in <span className="text-sm font-normal text-ink-muted">Stock in · Count</span></p>
              <p className="mt-1 text-sm text-ink-muted">Scan each piece to add stock or to count the shop.</p>
            </Link>
          </div>
        </div>
      </div>

      {mounted && labels && createPortal(
        <>
          <style>{`#anril-labels-print { display: none }
@media print {
  body > *:not(#anril-labels-print) { display: none !important }
  #anril-labels-print { display: block !important }
  .lbl { box-sizing: border-box; padding: 1.2mm 1.5mm; overflow: hidden; display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: Arial, sans-serif; color: #000 }
  ${PRINT_CSS[size]}
}`}</style>
          <div id="anril-labels-print">
            {labels.flatMap((l) => Array.from({ length: l.qty }, (_, i) => (
              <div key={`${l.code}-${i}`} className="lbl"><LabelFace label={l} shop={shopName} show={show} print /></div>
            )))}
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}

function LabelFace({ label, shop, show, print }: { label: PrintLabel; shop: string; show: Set<Show>; print?: boolean }) {
  const s = (px: number, mm: number) => (print ? `${mm}mm` : `${px}px`);
  return (
    <div className="flex w-full flex-col items-center text-center leading-tight text-black">
      {show.has("shop") && shop && <p className="w-full truncate font-bold uppercase" style={{ fontSize: s(11, 2.2) }}>{shop}</p>}
      {(show.has("item") || show.has("variant")) && (
        <p className="w-full truncate font-semibold" style={{ fontSize: s(12, 2.4) }}>
          {[show.has("item") ? label.name : "", show.has("variant") ? label.variant_label : ""].filter(Boolean).join(" · ")}
        </p>
      )}
      <div className="w-full" style={{ height: s(38, 8) }}><Barcode code={label.code} className="h-full w-full" /></div>
      <p className="font-mono tracking-wide" style={{ fontSize: s(11, 2.1) }}>{label.code}</p>
      {show.has("price") && label.price_paise != null && <p className="font-bold" style={{ fontSize: s(15, 3) }}>{formatPaise(label.price_paise)}</p>}
    </div>
  );
}
