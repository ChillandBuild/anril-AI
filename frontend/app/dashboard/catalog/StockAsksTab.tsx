"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { BellRing, Download, Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api, getAuthHeaders } from "@/lib/api";
import type { BackInStockLanguage, StockAskRow, StockAsks } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { useStockAsks } from "@/hooks/useApi";
import { StatCard } from "./ItemsTab";
import { formatPaise } from "./money";

/* Asked but out of stock (backend services/stock_asks.py). Customers who asked for something sold
 * out: the AI notes them in chat, staff add them from Orders. "Mark back in stock" tells everyone
 * who said yes, once. */

const DAYS = 30;
const LANGUAGES: { value: BackInStockLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "ta", label: "தமிழ்" },
  { value: "tanglish", label: "Tanglish" },
];

function lastAsked(iso: string | null): string {
  if (!iso) return "—";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  const weeks = Math.floor(days / 7);
  return weeks < 5 ? `${weeks} ${weeks === 1 ? "week" : "weeks"} ago` : `${Math.floor(days / 30)} months ago`;
}

function rowKey(row: StockAskRow) {
  return `${row.catalog_item_id}:${row.variant_id ?? ""}`;
}

export function StockAsksTab({ canManage, canSubmitTemplate, toolbarSlot }: {
  canManage: boolean; canSubmitTemplate: boolean; toolbarSlot: HTMLElement | null;
}) {
  const { data, error, mutate, isLoading } = useStockAsks(DAYS);
  const [downloading, setDownloading] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const paged = usePagedList(data?.rows ?? []);

  async function download() {
    setDownloading(true);
    try {
      const res = await fetch(`${API_URL}${api.catalog.stockAsksCsvPath(DAYS)}`, { headers: await getAuthHeaders() });
      if (!res.ok) throw new Error("Couldn't download the list. Try again.");
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "asked-but-out-of-stock.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't download the list.");
    } finally {
      setDownloading(false);
    }
  }

  async function markBack(row: StockAskRow) {
    const key = rowKey(row);
    setSending(key);
    try {
      const result = await api.catalog.backInStock({ catalog_item_id: row.catalog_item_id, variant_id: row.variant_id });
      const parts = [];
      if (result.sent) parts.push(`Told ${result.sent} ${result.sent === 1 ? "person" : "people"} on WhatsApp.`);
      if (result.not_reachable) {
        parts.push(`${result.not_reachable} can't be reached until WhatsApp approves your back-in-stock message. They stay on the list.`);
      }
      if (!parts.length) parts.push("Nobody was waiting for a message.");
      (result.not_reachable ? toast.message : toast.success)(parts.join(" "));
      await mutate();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't send. Try again.");
    } finally {
      setSending(null);
      setConfirming(null);
    }
  }

  return (
    <div className="space-y-4">
      {toolbarSlot && createPortal(
        <button type="button" onClick={download} disabled={downloading || !data?.rows.length}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-50">
          {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} Excel
        </button>,
        toolbarSlot,
      )}

      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          Couldn&apos;t load the list. <button type="button" onClick={() => mutate()} className="font-semibold underline">Try again</button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard icon="🙋" label="People asked" value={data ? String(data.people_asked) : "…"} sub={`last ${DAYS} days`} />
        <StatCard icon="💸" label="Sales missed" tone={data?.missed_paise ? "red" : "plain"}
          value={data ? formatPaise(data.missed_paise) : "…"} sub="if all had bought, at the price when they asked" />
        <StatCard icon="🔔" label="Waiting for “back in stock”" value={data ? String(data.waiting) : "…"} sub="will get a WhatsApp" />
      </div>

      {data && <MessageCard data={data} canManage={canManage} canSubmit={canSubmitTemplate} onChanged={() => mutate()} />}

      <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-4 py-3">Item</th>
              <th className="px-3 py-3">Asked</th>
              <th className="px-3 py-3">Sales missed</th>
              <th className="px-3 py-3">Want a message</th>
              <th className="px-3 py-3">Last asked</th>
              <th className="px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted">
                <Loader2 size={16} className="mr-2 inline animate-spin" />Loading…
              </td></tr>
            )}
            {data && data.rows.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted">
                Nobody has asked for anything out of stock in the last {DAYS} days.
              </td></tr>
            )}
            {paged.pageItems.map((row) => {
              const key = rowKey(row);
              return (
                <tr key={key} className="border-b border-border-subtle last:border-b-0">
                  <td className="px-4 py-3">
                    <Link href={`/dashboard/catalog/items/${row.catalog_item_id}`} className="font-bold text-ink hover:underline">
                      {row.name}{row.variant_label ? ` · ${row.variant_label}` : ""}
                    </Link>
                    <p className={cn("text-xs", row.in_stock ? "text-emerald-700" : "text-ink-muted")}>
                      {row.in_stock ? (row.stock == null ? "Available" : `${row.stock} in stock now`) : "Still out of stock"}
                    </p>
                  </td>
                  <td className="px-3 py-3 text-ink"><b className="tabular-nums">{row.asked}</b> {row.asked === 1 ? "person" : "people"}</td>
                  <td className="px-3 py-3 font-semibold tabular-nums text-rose-700">{formatPaise(row.missed_paise)}</td>
                  <td className="px-3 py-3 tabular-nums text-ink">{row.waiting}</td>
                  <td className="px-3 py-3 text-ink-muted">{lastAsked(row.last_asked_at)}</td>
                  <td className="px-3 py-3 text-right">
                    {canManage && row.waiting > 0 && (
                      confirming === key ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="text-xs text-ink-muted">Message {row.waiting} {row.waiting === 1 ? "person" : "people"}?</span>
                          <button type="button" onClick={() => markBack(row)} disabled={sending !== null}
                            className="inline-flex h-8 items-center gap-1 rounded-lg bg-primary px-3 text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-60">
                            {sending === key ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Send
                          </button>
                          <button type="button" onClick={() => setConfirming(null)} className="text-xs font-semibold text-ink-muted hover:text-ink">Cancel</button>
                        </span>
                      ) : (
                        <button type="button" onClick={() => setConfirming(key)} disabled={!row.in_stock || sending !== null}
                          title={row.in_stock ? undefined : "Add the new stock first, then mark it back in stock"}
                          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:cursor-not-allowed disabled:opacity-50">
                          <BellRing size={14} /> Mark back in stock
                        </button>
                      )
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Pagination page={paged.page} total={paged.total} onPageChange={paged.setPage} noun="asks" />
      </div>

      <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
        <span aria-hidden>🤖</span> How it fills: when something is out of stock, Anril says so, offers a close match, and asks{" "}
        <b>&ldquo;Stock vandha message pannava?&rdquo;</b> in the customer&apos;s language. Each ask is counted here; staff can add people from
        Orders too. When you mark it back in stock, everyone who said yes gets one WhatsApp.
      </p>
    </div>
  );
}

/* The message everyone gets: one text for the 24-hour message and the WhatsApp template. */
function MessageCard({ data, canManage, canSubmit, onChanged }: {
  data: StockAsks; canManage: boolean; canSubmit: boolean; onChanged: () => void;
}) {
  const status = data.template_status;
  const locked = status === "PENDING" || status === "APPROVED";
  const [language, setLanguage] = useState<BackInStockLanguage>(data.message.language);
  const [body, setBody] = useState(data.message.body);
  const [busy, setBusy] = useState<"save" | "submit" | null>(null);
  const [open, setOpen] = useState(!locked);

  useEffect(() => {
    setLanguage(data.message.language);
    setBody(data.message.body);
  }, [data.message.language, data.message.body]);

  const dirty = language !== data.message.language || body.trim() !== data.message.body.trim();
  const missing = ["{{1}}", "{{2}}", "{{3}}", "{{4}}"].filter((box) => !body.includes(box));
  const preview = body.replace("{{1}}", "Priya").replace("{{2}}", "your shop").replace("{{3}}", "Kanchi pattu (Red · XL)").replace("{{4}}", "₹10,500");

  function pickLanguage(next: BackInStockLanguage) {
    // Untouched words follow the language; words you changed stay.
    if (body.trim() === data.starting_bodies[language].trim()) setBody(data.starting_bodies[next]);
    setLanguage(next);
  }

  async function save(): Promise<boolean> {
    setBusy("save");
    try {
      const isStarting = body.trim() === data.starting_bodies[language].trim();
      await api.catalog.saveBackInStockMessage({ language, body: isStarting ? null : body.trim() });
      onChanged();
      return true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function submit() {
    if (dirty && !(await save())) return;
    setBusy("submit");
    try {
      await api.catalog.submitBackInStockTemplate();
      toast.success("Sent to WhatsApp for approval. It usually takes a few minutes to a day.");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't send it to WhatsApp. Try again.");
    } finally {
      setBusy(null);
    }
  }

  const chip = status === "APPROVED"
    ? { text: "Approved", cls: "bg-emerald-50 text-emerald-700" }
    : status === "PENDING"
      ? { text: "With WhatsApp for approval", cls: "bg-blue-50 text-blue-700" }
      : status === "REJECTED"
        ? { text: "Not approved", cls: "bg-amber-50 text-amber-800" }
        : { text: "Not set up yet", cls: "bg-surface-mid text-ink-secondary" };

  return (
    <section className="rounded-card border border-border bg-white px-4 py-3 shadow-sm" aria-labelledby="bis-message">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="bis-message" className="text-sm font-bold text-ink">Back-in-stock message</h2>
          <span className={cn("rounded-full px-2.5 py-0.5 text-[11px] font-semibold", chip.cls)}>{chip.text}</span>
        </div>
        <button type="button" onClick={() => setOpen((v) => !v)} className="text-xs font-semibold text-primary hover:underline">
          {open ? "Hide" : locked ? "See the words" : "Set up"}
        </button>
      </div>
      {!open && status !== "APPROVED" && (
        <p className="mt-1 text-xs text-ink-muted">
          Customers who messaged in the last 24 hours get it right away. Everyone else needs this message approved by WhatsApp first.
        </p>
      )}
      {open && (
        <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="space-y-3">
            <SegmentedControl aria-label="Message language" value={language} disabled={!canManage || locked}
              onChange={pickLanguage} options={LANGUAGES} />
            <textarea value={body} onChange={(e) => setBody(e.target.value)} disabled={!canManage || locked} rows={3} maxLength={1024}
              aria-label="Back-in-stock message"
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-ink focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15 disabled:bg-surface-low" />
            <p className={cn("text-xs", missing.length ? "font-semibold text-amber-800" : "text-ink-muted")}>
              {missing.length
                ? `Keep ${missing.join(", ")} in the message.`
                : "{{1}} name · {{2}} your shop · {{3}} the item and size · {{4}} its price. Filled in for each customer."}
            </p>
            {locked ? (
              <p className="text-xs text-ink-muted">
                WhatsApp {status === "APPROVED" ? "approved" : "is checking"} these exact words. To change them, delete
                anril_back_in_stock in Templates, then send the new words.
              </p>
            ) : canManage && (
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={save} disabled={!dirty || busy !== null || missing.length > 0}
                  className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-40">
                  {busy === "save" && <Loader2 size={14} className="animate-spin" />} Save
                </button>
                {canSubmit && (
                  <button type="button" onClick={submit} disabled={busy !== null || missing.length > 0}
                    className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-primary px-3 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-40">
                    {busy === "submit" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                    {dirty ? "Save & send for approval" : "Send to WhatsApp for approval"}
                  </button>
                )}
                {dirty && <span className="text-xs font-semibold text-amber-700">Unsaved changes</span>}
              </div>
            )}
          </div>
          <div className="rounded-xl bg-[#efeae2] p-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">Customer sees</p>
            <p className="whitespace-pre-line rounded-lg rounded-tl-none bg-white px-2.5 py-2 text-[13px] leading-snug text-[#111b21] shadow-sm">{preview}</p>
          </div>
        </div>
      )}
    </section>
  );
}
