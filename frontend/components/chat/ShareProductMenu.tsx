"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Package, Search, ShoppingBag } from "lucide-react";
import { toast } from "sonner";
import { api, type CatalogItem } from "@/lib/api";
import { cn } from "@/lib/utils";

function price(paise: number | null): string | null {
  if (!paise) return null;
  const rupees = paise / 100;
  return `₹${rupees.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

/**
 * Quick-action chip + popover: pick a ready product and send its photo, name and
 * price to this WhatsApp lead. Disabled (with the reason) outside the 24-hour window.
 */
export function ShareProductMenu({
  leadId,
  disabledReason,
  className,
  onSent,
}: {
  leadId: string;
  disabledReason?: string | null;
  className: string;
  onSent: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [sendingId, setSendingId] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    if (items === null) {
      api.catalog.listItems().then((rows) => setItems(rows.filter((r) => r.status === "ready"))).catch(() => setItems([]));
    }
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, items]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items ?? []).filter((i) => !q || i.name.toLowerCase().includes(q));
  }, [items, query]);

  async function send(item: CatalogItem) {
    setSendingId(item.id);
    try {
      await api.leads.shareProduct(leadId, item.id);
      toast.success(`Sent ${item.name}`);
      setOpen(false);
      onSent();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't send the product");
    } finally {
      setSendingId(null);
    }
  }

  return (
    // Phone: the wrapper fills its share of the action row and is not positioned, so the list opens
    // across the whole row (the row is `relative`) instead of running off the screen edge.
    <div className="relative max-md:static max-md:flex max-md:min-w-0 max-md:flex-1" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={!!disabledReason}
        title={disabledReason ?? "Send a product's photo, name and price"}
        className={cn(className, "max-md:w-full disabled:cursor-not-allowed disabled:opacity-50")}
      >
        <ShoppingBag size={13} />
        Share product
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-40 mb-2 w-[300px] overflow-hidden max-md:right-0 max-md:w-auto rounded-xl border border-[#e2e8f0] bg-white shadow-xl">
          <div className="border-b border-[#f1f5f9] p-2">
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search products"
                className="h-8 w-full rounded-lg border border-[#e2e8f0] pl-8 pr-2 text-[12px] focus:border-primary focus:outline-none"
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {items === null ? (
              <p className="flex items-center gap-2 px-3 py-4 text-[12px] text-[#64748b]">
                <Loader2 size={13} className="animate-spin" /> Loading products…
              </p>
            ) : shown.length === 0 ? (
              <p className="px-3 py-4 text-[12px] text-[#64748b]">
                {items.length === 0 ? "No ready products yet. Add them on the Catalogue page." : "No product matches that."}
              </p>
            ) : (
              shown.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  disabled={sendingId !== null}
                  onClick={() => void send(item)}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-[#f8fafc] disabled:opacity-60"
                >
                  {item.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={item.thumbnail_url} alt="" className="h-9 w-9 shrink-0 rounded-lg object-cover" />
                  ) : (
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#f1f5f9] text-[#94a3b8]">
                      <Package size={15} />
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] font-semibold text-[#0A1528]">{item.name}</span>
                    {price(item.price_paise) && <span className="block text-[11px] text-[#64748b]">{price(item.price_paise)}</span>}
                  </span>
                  {sendingId === item.id && <Loader2 size={13} className="animate-spin text-primary" />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
