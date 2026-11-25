"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, FileSpreadsheet, Loader2, RefreshCw, Upload } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api, getAuthHeaders } from "@/lib/api";
import type { PriceListPreview, PriceListRow, PriceListRowInput } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MobileRecordCard, MobileRecordHeader } from "@/components/MobileRecord";
import { CatalogueTabs } from "../CatalogueTabs";

/* Upload price list (backend services/price_list.py): Excel/CSV read directly, a PDF or photo read
 * by Anril. Every row is shown as New / New size / Update / Same; nothing changes until Save. */

const STATUS: Record<PriceListRow["status"], { text: string; cls: string }> = {
  new: { text: "New item", cls: "bg-emerald-50 text-emerald-700" },
  new_size: { text: "New size / colour", cls: "bg-emerald-50 text-emerald-700" },
  update: { text: "Update", cls: "bg-blue-50 text-blue-700" },
  same: { text: "Same", cls: "bg-surface-mid text-ink-muted" },
  problem: { text: "Fix this", cls: "bg-amber-50 text-amber-800" },
};

function toInput(row: PriceListRow): PriceListRowInput {
  return {
    name: row.name, size: row.size, colour: row.colour,
    price: row.price_paise != null ? String(row.price_paise / 100) : "", gst_rate: row.gst_rate != null ? String(row.gst_rate) : "",
    hsn: row.hsn ?? "", stock: row.stock != null ? String(row.stock) : "", group: row.group,
  };
}

function rupees(paise: number | null | undefined) {
  return paise == null ? "—" : `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export default function PriceListPage() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);
  const [preview, setPreview] = useState<PriceListPreview | null>(null);
  const [rows, setRows] = useState<PriceListRowInput[]>([]);
  const [edited, setEdited] = useState(false);
  const [busy, setBusy] = useState<"check" | "save" | null>(null);

  function show(next: PriceListPreview) {
    setPreview(next);
    setRows(next.rows.map(toInput));
    setEdited(false);
  }

  async function read(file: File | undefined) {
    if (!file) return;
    setReading(true);
    try {
      show(await api.catalog.priceListRead(file));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't read the file.");
    } finally {
      setReading(false);
      if (input.current) input.current.value = "";
    }
  }

  async function check() {
    setBusy("check");
    try {
      show(await api.catalog.priceListCheck(rows));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't check it. Try again.");
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("save");
    try {
      const out = await api.catalog.priceListApply(rows);
      const parts = [
        out.new_items && `${out.new_items} new ${out.new_items === 1 ? "item" : "items"}`,
        out.new_sizes && `${out.new_sizes} new ${out.new_sizes === 1 ? "size" : "sizes"}`,
        out.updated && `${out.updated} updated`,
      ].filter(Boolean);
      toast.success(`Saved: ${parts.join(", ") || "nothing changed"}.${out.skipped ? ` ${out.skipped} rows to fix were left out.` : ""}`);
      router.push("/dashboard/catalog");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
      setBusy(null);
    }
  }

  async function downloadSample() {
    try {
      const res = await fetch(`${API_URL}${api.catalog.priceListSamplePath}`, { headers: await getAuthHeaders() });
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "price-list-sample.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Couldn't download the sample.");
    }
  }

  const edit = (i: number, patch: Partial<PriceListRowInput>) => {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    setEdited(true);
  };
  const counts = preview?.counts;
  const toSave = counts ? counts.new + counts.new_size + counts.update : 0;

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 pb-28">
      <CatalogueTabs />
      <Link href="/dashboard/catalog" className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-secondary hover:text-ink">
        <ArrowLeft size={14} /> Products
      </Link>

      <input ref={input} type="file" hidden accept=".xlsx,.xlsm,.csv,application/pdf,image/jpeg,image/png" onChange={(e) => read(e.target.files?.[0])} />
      {!preview ? (
        <div className="rounded-card border border-dashed border-border bg-white px-6 py-12 text-center shadow-sm">
          <FileSpreadsheet size={28} className="mx-auto text-primary" aria-hidden />
          <p className="mx-auto mt-3 max-w-lg text-sm text-ink-muted">
            An Excel or CSV sheet is read as it is. A PDF or a photo of a printed list is read by Anril. You see every row before
            anything changes: new items, new sizes, and price or stock updates.
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <button type="button" onClick={() => input.current?.click()} disabled={reading} className="btn-primary inline-flex h-10 items-center gap-2 !py-0 disabled:opacity-60">
              {reading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />} {reading ? "Reading…" : "Choose file"}
            </button>
            <button type="button" onClick={downloadSample} className="inline-flex h-10 items-center gap-2 rounded-xl border border-border px-4 text-sm font-semibold text-ink hover:bg-surface-low">
              <Download size={15} /> Sample sheet
            </button>
          </div>
          <p className="mt-3 text-xs text-ink-muted">Columns: Item name, Size, Colour, Price, GST %, HSN, Stock, Group. Only Item name is needed.</p>
        </div>
      ) : (
        <>
          {/* Phones: the price cards run long, so Check and Save stay pinned under the header. */}
          <div className="flex flex-wrap items-center justify-between gap-3 max-md:sticky max-md:top-14 max-md:z-20 max-md:-mx-3 max-md:border-b max-md:border-border max-md:bg-background max-md:px-3 max-md:py-2">
            <div className="flex flex-wrap gap-2 text-sm">
              {(["new", "new_size", "update", "same", "problem"] as const).map((s) => counts && counts[s] > 0 && (
                <span key={s} className={cn("rounded-full px-2.5 py-0.5 font-semibold", STATUS[s].cls)}>{counts[s]} {STATUS[s].text.toLowerCase()}</span>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => input.current?.click()} disabled={reading || busy !== null}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-50">
                <Upload size={14} /> Another file
              </button>
              {edited && (
                <button type="button" onClick={check} disabled={busy !== null}
                  className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-primary/40 px-3 text-sm font-semibold text-primary hover:bg-primary-50 disabled:opacity-50">
                  {busy === "check" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Check my changes
                </button>
              )}
              <button type="button" onClick={save} disabled={busy !== null || edited || toSave === 0}
                title={edited ? "Check your changes first" : undefined} className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0 disabled:opacity-50">
                {busy === "save" && <Loader2 size={14} className="animate-spin" />} Save {toSave} {toSave === 1 ? "change" : "changes"}
              </button>
            </div>
          </div>

          <div className="space-y-3 md:hidden">
            {preview.rows.map((row, i) => {
              const r = rows[i];
              const field = (key: keyof PriceListRowInput, label: string, opts?: { changed?: boolean; numeric?: boolean; wide?: boolean }) => (
                <label key={key} className={cn("block min-w-0", opts?.wide && "col-span-2")}>
                  <span className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">{label}</span>
                  <input value={r?.[key] ?? ""} onChange={(e) => edit(i, { [key]: e.target.value })} aria-label={`${key} on row ${row.row}`}
                    inputMode={opts?.numeric ? "decimal" : undefined}
                    className={cn("mt-1 min-h-10 w-full rounded-lg border px-2 text-base", opts?.changed ? "border-blue-300 bg-blue-50/50" : "border-border focus:border-primary/40")} />
                </label>
              );
              return (
                <MobileRecordCard key={`${row.row}-${i}`} className={cn("p-3", row.status === "same" && "opacity-60")}>
                  <MobileRecordHeader
                    title={`Row ${row.row}`}
                    aside={<span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", STATUS[row.status].cls)}>{STATUS[row.status].text}</span>}
                  />
                  {row.problems.length > 0 && <p className="mt-1 text-xs text-amber-800">{row.problems.join(" · ")}</p>}
                  {row.status === "update" && row.current && (
                    <p className="mt-1 text-xs text-ink-muted">
                      {row.changes.includes("price") && `Price ${rupees(row.current.price_paise)} → ${rupees(row.price_paise)} `}
                      {row.changes.includes("stock") && `Stock ${row.current.stock ?? "—"} → ${row.stock}`}
                    </p>
                  )}
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    {field("name", "Item name", { wide: true })}
                    {field("size", "Size")}
                    {field("colour", "Colour")}
                    {field("price", "Price ₹", { changed: row.changes.includes("price"), numeric: true })}
                    {field("gst_rate", "GST %", { changed: row.changes.includes("gst"), numeric: true })}
                    {field("hsn", "HSN", { changed: row.changes.includes("hsn") })}
                    {field("stock", "Stock", { changed: row.changes.includes("stock"), numeric: true })}
                  </div>
                </MobileRecordCard>
              );
            })}
          </div>
          <div className="hidden overflow-x-auto rounded-card border border-border bg-white shadow-sm md:block">
            <table className="w-full min-w-[1000px] text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                  <th className="px-3 py-3">#</th>
                  <th className="px-2 py-3">Item name</th>
                  <th className="px-2 py-3">Size</th>
                  <th className="px-2 py-3">Colour</th>
                  <th className="px-2 py-3">Price ₹</th>
                  <th className="px-2 py-3">GST %</th>
                  <th className="px-2 py-3">HSN</th>
                  <th className="px-2 py-3">Stock</th>
                  <th className="px-3 py-3">What happens</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, i) => {
                  const r = rows[i];
                  const cell = (key: keyof PriceListRowInput, w: string, changed?: boolean) => (
                    <input value={r?.[key] ?? ""} onChange={(e) => edit(i, { [key]: e.target.value })} aria-label={`${key} on row ${row.row}`}
                      className={cn("h-8 rounded-md border px-2 text-sm", w, changed ? "border-blue-300 bg-blue-50/50" : "border-transparent hover:border-border focus:border-primary/40")} />
                  );
                  return (
                    <tr key={`${row.row}-${i}`} className={cn("border-b border-border-subtle last:border-b-0", row.status === "same" && "opacity-60")}>
                      <td className="px-3 py-1.5 text-xs tabular-nums text-ink-muted">{row.row}</td>
                      <td className="px-2 py-1.5">{cell("name", "w-48")}</td>
                      <td className="px-2 py-1.5">{cell("size", "w-20")}</td>
                      <td className="px-2 py-1.5">{cell("colour", "w-24")}</td>
                      <td className="px-2 py-1.5">{cell("price", "w-24", row.changes.includes("price"))}</td>
                      <td className="px-2 py-1.5">{cell("gst_rate", "w-16", row.changes.includes("gst"))}</td>
                      <td className="px-2 py-1.5">{cell("hsn", "w-24", row.changes.includes("hsn"))}</td>
                      <td className="px-2 py-1.5">{cell("stock", "w-20", row.changes.includes("stock"))}</td>
                      <td className="px-3 py-1.5">
                        <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", STATUS[row.status].cls)}>{STATUS[row.status].text}</span>
                        {row.problems.length > 0 && <p className="mt-0.5 text-xs text-amber-800">{row.problems.join(" · ")}</p>}
                        {row.status === "update" && row.current && (
                          <p className="mt-0.5 text-xs text-ink-muted">
                            {row.changes.includes("price") && `Price ${rupees(row.current.price_paise)} → ${rupees(row.price_paise)} `}
                            {row.changes.includes("stock") && `Stock ${row.current.stock ?? "—"} → ${row.stock}`}
                          </p>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm text-ink">
            Rows marked &ldquo;Fix this&rdquo; and &ldquo;Same&rdquo; are left out. New items are ready for Anril to recommend; stock changes show in
            each item&apos;s Stock history as &ldquo;Price list upload&rdquo;.
          </p>
        </>
      )}
    </div>
  );
}
