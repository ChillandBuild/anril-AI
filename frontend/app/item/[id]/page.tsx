"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2, MessageCircle } from "lucide-react";
import { fetchPublicItem, type PublicItem } from "@/lib/api";

// The item page a Meta (WhatsApp / Facebook / Instagram) catalogue product links to. No sign-in;
// only Ready items load. "Order on WhatsApp" opens a chat with the shop, the item already typed.

function rupees(paise: number): string {
  return "₹" + Math.round(paise / 100).toLocaleString("en-IN");
}

export default function PublicItemPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<PublicItem | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const [photo, setPhoto] = useState(0);
  const [pick, setPick] = useState<number | null>(null);

  useEffect(() => {
    fetchPublicItem(id).then(setItem).catch(() => setFailed(true));
  }, [id]);

  useEffect(() => {
    if (item) document.title = `${item.name}${item.shop.name ? ` · ${item.shop.name}` : ""}`;
  }, [item]);

  const colours = useMemo(() => (item?.options ?? []).map((o) => o.colour).filter((c, i, all): c is string => !!c && all.indexOf(c) === i), [item]);

  if (failed) return <Shell><p className="py-24 text-center text-sm text-slate-500">This item couldn&apos;t be loaded. Check your connection and open the link again.</p></Shell>;
  if (item === undefined) return <Shell><div className="flex justify-center py-24"><Loader2 className="animate-spin text-slate-400" /></div></Shell>;
  if (item === null) return <Shell><p className="py-24 text-center text-sm text-slate-500">This item isn&apos;t available any more.</p></Shell>;

  const chosen = pick != null ? item.options[pick] : null;
  const price = chosen?.price_paise ?? item.price_paise;
  const label = chosen ? [chosen.colour, chosen.size].filter(Boolean).join(" · ") : "";
  const message = `Hi! I'd like to order ${item.name}${label ? ` (${label})` : ""}${price != null ? ` · ${rupees(price)}` : ""}`;
  const chat = item.whatsapp ? `https://wa.me/${item.whatsapp}?text=${encodeURIComponent(message)}` : null;

  return (
    <Shell>
      <article className="mx-auto max-w-[760px] overflow-hidden rounded-3xl bg-white shadow-sm ring-1 ring-slate-200">
        <div className="grid gap-0 sm:grid-cols-2">
          <div className="bg-slate-100">
            {item.photos.length ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={item.photos[photo]} alt={item.name} className="aspect-square w-full object-cover" />
                {item.photos.length > 1 && (
                  <div className="flex gap-2 overflow-x-auto p-3">
                    {item.photos.map((url, i) => (
                      <button key={url} type="button" onClick={() => setPhoto(i)} aria-label={`Photo ${i + 1}`}
                        className={`h-14 w-14 shrink-0 overflow-hidden rounded-lg ring-2 ${i === photo ? "ring-emerald-600" : "ring-transparent"}`}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={url} alt="" className="h-full w-full object-cover" />
                      </button>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="flex aspect-square items-center justify-center text-5xl text-slate-300">🛍️</div>
            )}
          </div>
          <div className="flex flex-col gap-4 p-5 sm:p-6">
            <div>
              {item.shop.name && <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{item.shop.name}{item.shop.city ? ` · ${item.shop.city}` : ""}</p>}
              <h1 className="mt-1 text-2xl font-bold text-slate-900">{item.name}</h1>
              {price != null && (
                <p className="mt-1 text-xl font-bold text-slate-900">{rupees(price)}{item.price_note && !chosen ? <span className="ml-1.5 text-sm font-normal text-slate-500">{item.price_note}</span> : null}</p>
              )}
            </div>
            {item.description && <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">{item.description}</p>}

            {item.options.length > 0 && (
              <div className="space-y-3">
                {(colours.length ? colours : [null]).map((c) => (
                  <div key={c ?? "_"}>
                    {c && <p className="mb-1.5 text-sm font-semibold text-slate-800">{c}</p>}
                    <div className="flex flex-wrap gap-2">
                      {item.options.map((o, i) => (o.colour ?? null) !== c ? null : (
                        <button key={i} type="button" disabled={!o.in_stock} onClick={() => setPick(i)} aria-pressed={pick === i}
                          className={`min-w-11 rounded-xl border px-3 py-1.5 text-sm font-semibold ${!o.in_stock ? "cursor-not-allowed border-slate-200 text-slate-300 line-through" : pick === i ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-300 text-slate-800 hover:border-slate-400"}`}>
                          {o.size ?? o.colour}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!item.in_stock && <p className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">Out of stock right now. Message the shop to know when it&apos;s back.</p>}

            {chat && (
              <a href={chat} className="mt-auto inline-flex h-12 items-center justify-center gap-2 rounded-2xl bg-emerald-600 px-5 text-base font-bold text-white hover:bg-emerald-700">
                <MessageCircle size={18} /> {item.in_stock ? "Order on WhatsApp" : "Ask on WhatsApp"}
              </a>
            )}
          </div>
        </div>
      </article>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="min-h-screen bg-slate-50 px-4 py-6 sm:py-10">{children}</main>;
}
