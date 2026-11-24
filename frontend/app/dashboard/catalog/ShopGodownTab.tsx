"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { ArrowLeftRight, Check, Loader2, Plus, Search, Settings2, Trash2, Truck, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { StockMove, StockOverview, StockPlace, StockPlaceCard, StockPlaceKind, StockPlaceLine } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { useStockOverview } from "@/hooks/useApi";
import { StatCard } from "./ItemsTab";
import { formatPaise } from "./money";

/* Shop & godown (backend services/stock_places.py, migration 309). Stock in each place, moves
 * between them (counted only when the other place taps Received), and suggested moves. */

const KIND_ICON: Record<StockPlaceKind, string> = { shop: "🏬", godown: "🏭", other: "📍" };
const KIND_OPTIONS = [
  { value: "shop", label: "Shop" },
  { value: "godown", label: "Godown" },
  { value: "other", label: "Other" },
];
const DEFAULT_READY = "ready in 1 day";

function lineName(line: Pick<StockPlaceLine, "name" | "label">) {
  return line.label ? `${line.name} · ${line.label}` : line.name;
}

function time(iso: string) {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

type MoveDraft = { from: string; to: string; lines: { key: string; quantity: number }[] };

export function ShopGodownTab({ canManage, toolbarSlot }: { canManage: boolean; toolbarSlot: HTMLElement | null }) {
  const { data, error, mutate, isLoading } = useStockOverview();
  const [query, setQuery] = useState("");
  const [move, setMove] = useState<MoveDraft | null>(null);
  const [editingPlaces, setEditingPlaces] = useState(false);

  const places = data?.places ?? [];
  const bill = places.find((p) => p.bills_from) ?? places[0];
  const online = places.find((p) => p.online_from) ?? bill;
  const name = (id: string) => places.find((p) => p.id === id)?.name ?? "Removed place";
  const many = places.length > 1;

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.lines ?? []).filter((li) => !q || lineName(li).toLowerCase().includes(q));
  }, [data, query]);
  const paged = usePagedList(shown, query);

  function openMove(line?: StockPlaceLine) {
    if (!places.length) return;
    const s = line?.suggestion;
    const other = places.find((p) => p.id !== bill?.id) ?? places[0];
    setMove({
      from: s?.from_place_id ?? other.id,
      to: s?.to_place_id ?? bill?.id ?? places[0].id,
      lines: line ? [{ key: line.key, quantity: s?.quantity ?? 1 }] : [],
    });
  }

  return (
    <div className="space-y-4">
      {toolbarSlot && canManage && createPortal(
        <>
          <button type="button" onClick={() => setEditingPlaces(true)} disabled={!data}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-50">
            <Settings2 size={14} /> Places
          </button>
          {many && (
            <button type="button" onClick={() => openMove()}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-primary px-3.5 text-sm font-bold text-white shadow-sm hover:bg-primary-dark">
              <ArrowLeftRight size={14} /> Move stock
            </button>
          )}
        </>,
        toolbarSlot,
      )}

      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          Couldn&apos;t load stock per place. <button type="button" onClick={() => mutate()} className="font-semibold underline">Try again</button>
        </div>
      )}
      {isLoading && (
        <div className="flex items-center justify-center gap-2 rounded-card border border-border bg-white py-16 text-sm text-ink-muted">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      )}

      {data && !many && (
        <div className="rounded-card border border-border bg-white px-6 py-10 text-center shadow-sm">
          <p className="text-3xl" aria-hidden>🏬 🏭</p>
          <h3 className="mt-3 font-display text-lg font-bold text-ink">All your stock is in one place: {places[0]?.name ?? "Shop"}</h3>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">
            Have a godown or a second branch? Add it, and you&apos;ll see the stock in each place, move stock between them,
            and get told when the shop is running low on something the godown has.
          </p>
          {canManage && (
            <button type="button" onClick={() => setEditingPlaces(true)}
              className="mt-4 inline-flex h-10 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-bold text-white hover:bg-primary-dark">
              <Plus size={15} /> Add a godown or branch
            </button>
          )}
        </div>
      )}

      {data && many && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {places.map((p) => (
              <StatCard key={p.id} icon={KIND_ICON[p.kind]} label={p.name} value={`${p.pieces.toLocaleString("en-IN")} pcs`}
                sub={[formatPaise(p.value_paise), p.bills_from && "counter bills", p.online_from && "online orders"].filter(Boolean).join(" · ")} />
            ))}
            <StatCard icon="🚚" label="On the way" value={`${data.on_the_way.pieces} pcs`}
              sub={data.on_the_way.moves ? `${data.on_the_way.moves} ${data.on_the_way.moves === 1 ? "move" : "moves"} waiting for Received` : "nothing on the way"} />
            <StatCard icon="💡" label="Move suggested" tone={data.suggested ? "amber" : "plain"}
              value={`${data.suggested} ${data.suggested === 1 ? "item" : "items"}`} sub={`${bill?.name} low, another place has it`} />
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="space-y-3">
              <label className="relative block max-w-xs">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search items"
                  className="h-9 w-full rounded-xl border border-border bg-white pl-9 pr-3 text-sm outline-none focus:border-primary" />
              </label>
              <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                      <th className="px-4 py-3">Item</th>
                      {places.map((p) => <th key={p.id} className="px-3 py-3">{p.name}</th>)}
                      <th className="px-3 py-3">Sold {data.sold_days} days</th>
                      <th className="px-3 py-3">Suggestion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.length === 0 && (
                      <tr><td colSpan={places.length + 3} className="px-4 py-10 text-center text-ink-muted">
                        {data.lines.length ? "No item matches that search." : "No items track stock yet. Add stock to an item to see it here."}
                      </td></tr>
                    )}
                    {paged.pageItems.map((line) => (
                      <tr key={line.key} className="border-b border-border-subtle last:border-b-0">
                        <td className="px-4 py-3">
                          <Link href={`/dashboard/catalog/items/${line.item_id}`} className="font-bold text-ink hover:underline">{lineName(line)}</Link>
                        </td>
                        {places.map((p) => {
                          const qty = line.by_place[p.id] ?? 0;
                          const low = p.id === bill?.id && line.suggestion;
                          return (
                            <td key={p.id} className={cn("px-3 py-3 tabular-nums", low ? "font-bold text-rose-700" : qty ? "text-ink" : "text-ink-muted")}>
                              {qty}
                            </td>
                          );
                        })}
                        <td className="px-3 py-3 tabular-nums text-ink">{line.sold}</td>
                        <td className="px-3 py-3">
                          {line.suggestion ? (
                            canManage ? (
                              <button type="button" onClick={() => openMove(line)}
                                className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg border border-border bg-white px-2.5 text-[13px] font-semibold text-ink hover:border-primary/50 hover:bg-primary-50/50">
                                <ArrowLeftRight size={13} /> Move {line.suggestion.quantity} to {name(line.suggestion.to_place_id)}
                              </button>
                            ) : (
                              <span className="text-[13px] text-ink">Move {line.suggestion.quantity} to {name(line.suggestion.to_place_id)}</span>
                            )
                          ) : <span className="text-ink-muted">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <Pagination page={paged.page} total={paged.total} onPageChange={paged.setPage} noun="items" />
              </div>
            </div>

            <div className="space-y-3">
              <MovesCard moves={data.moves} name={name} canManage={canManage} onChanged={() => mutate()} />
              <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
                A move counts only when the other place taps <b>Received</b>, so nothing goes missing on the way. Until then
                it isn&apos;t sold from either place.
              </p>
            </div>
          </div>

          <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
            <span aria-hidden>🧾</span> Counter bills take stock from <b>{bill?.name}</b> first. Online and AI orders are packed from{" "}
            <b>{online?.name}</b> first. If that place runs out, the rest comes from your other places. When an item is only in
            another place, the AI agent tells customers it is available, &ldquo;{places.find((p) => !p.online_from)?.ready_note || DEFAULT_READY}&rdquo;.
            Change this in <button type="button" onClick={() => setEditingPlaces(true)} disabled={!canManage} className="font-semibold underline disabled:no-underline">Places</button>.
          </p>
        </>
      )}

      {move && data && (
        <MoveDialog data={data} draft={move} onClose={() => setMove(null)} onSent={() => { setMove(null); mutate(); }} />
      )}
      {editingPlaces && data && (
        <PlacesDialog places={places} onClose={() => setEditingPlaces(false)} onSaved={() => { setEditingPlaces(false); mutate(); }} />
      )}
    </div>
  );
}

/* Moves still on the way, and today's received / cancelled ones. */
function MovesCard({ moves, name, canManage, onChanged }: {
  moves: StockMove[]; name: (id: string) => string; canManage: boolean; onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);

  async function finish(m: StockMove, received: boolean) {
    setBusy(m.id);
    try {
      await api.catalog.finishStockMove(m.id, received);
      toast.success(received ? `Received at ${name(m.to_place_id)}. Stock updated.` : `Cancelled. The stock is back in ${name(m.from_place_id)}.`);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
      onChanged();
    } finally {
      setBusy(null);
      setCancelling(null);
    }
  }

  return (
    <div className="rounded-card border border-border bg-white px-4 py-3 shadow-sm">
      <h3 className="flex items-center gap-1.5 font-display text-base font-bold text-ink"><ArrowLeftRight size={15} /> Moves today</h3>
      {moves.length === 0 && <p className="py-6 text-center text-sm text-ink-muted">No moves today.</p>}
      <ul className="divide-y divide-border-subtle">
        {moves.map((m) => (
          <li key={m.id} className="py-3">
            <div className="flex items-start justify-between gap-2">
              <p className="font-bold text-ink">{name(m.from_place_id)} → {name(m.to_place_id)}</p>
              {m.status === "on_the_way" && <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-sky-700"><Truck size={13} /> On the way</span>}
              {m.status === "received" && <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-emerald-700"><Check size={13} /> Received{m.done_by_name ? ` by ${m.done_by_name}` : ""}</span>}
              {m.status === "cancelled" && <span className="shrink-0 text-xs font-semibold text-ink-muted">Cancelled</span>}
            </div>
            <p className="text-sm text-ink">{m.lines.map((li) => `${li.name} × ${li.quantity}`).join(", ")}</p>
            <p className="text-xs text-ink-muted">
              {[m.sent_by_name, time(m.created_at)].filter(Boolean).join(" · ")}{m.note ? ` · ${m.note}` : ""}
            </p>
            {m.status === "on_the_way" && canManage && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {cancelling === m.id ? (
                  <>
                    <span className="text-xs text-ink-muted">Put it back in {name(m.from_place_id)}?</span>
                    <button type="button" onClick={() => finish(m, false)} disabled={busy !== null}
                      className="inline-flex h-8 items-center gap-1 rounded-lg border border-danger/40 bg-white px-2.5 text-xs font-semibold text-danger hover:bg-danger/5 disabled:opacity-60">
                      {busy === m.id && <Loader2 size={12} className="animate-spin" />} Yes, cancel move
                    </button>
                    <button type="button" onClick={() => setCancelling(null)} className="text-xs font-semibold text-ink-muted hover:text-ink">Keep</button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => finish(m, true)} disabled={busy !== null}
                      className="inline-flex h-8 items-center gap-1 rounded-lg bg-primary px-3 text-xs font-bold text-white hover:bg-primary-dark disabled:opacity-60">
                      {busy === m.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={13} />} Received
                    </button>
                    <button type="button" onClick={() => setCancelling(m.id)} disabled={busy !== null}
                      className="text-xs font-semibold text-ink-muted hover:text-ink">Cancel move</button>
                  </>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Dialog({ title, children, onClose, footer }: {
  title: string; children: React.ReactNode; onClose: () => void; footer: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-dialog flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
        className="flex max-h-[92vh] w-full max-w-2xl flex-col rounded-t-2xl bg-white shadow-xl sm:rounded-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="font-display text-lg font-bold text-ink">{title}</h3>
          <button type="button" onClick={onClose} className="text-ink-muted hover:text-ink" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>
      </div>
    </div>
  );
}

function MoveDialog({ data, draft, onClose, onSent }: {
  data: StockOverview; draft: MoveDraft; onClose: () => void; onSent: () => void;
}) {
  const [from, setFrom] = useState(draft.from);
  const [to, setTo] = useState(draft.to);
  const [lines, setLines] = useState(draft.lines);
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [sending, setSending] = useState(false);
  const byKey = useMemo(() => new Map(data.lines.map((li) => [li.key, li])), [data]);
  const placeOptions = data.places.map((p) => ({ value: p.id, label: p.name }));
  const toName = data.places.find((p) => p.id === to)?.name ?? "";
  const fromName = data.places.find((p) => p.id === from)?.name ?? "";
  const have = (key: string) => byKey.get(key)?.by_place[from] ?? 0;
  const picked = new Set(lines.map((l) => l.key));
  const matches = query.trim()
    ? data.lines.filter((li) => !picked.has(li.key) && have(li.key) > 0 && lineName(li).toLowerCase().includes(query.trim().toLowerCase())).slice(0, 8)
    : [];
  const problems = [
    from === to && "Pick two different places.",
    !lines.length && "Add at least one item.",
    ...lines.filter((l) => l.quantity < 1 || l.quantity > have(l.key))
      .map((l) => `${fromName} has ${have(l.key)} of ${lineName(byKey.get(l.key)!)}.`),
  ].filter(Boolean) as string[];

  async function send() {
    setSending(true);
    try {
      await api.catalog.sendStockMove({
        from_place_id: from, to_place_id: to, note: note.trim() || undefined,
        lines: lines.map((l) => ({ item_id: byKey.get(l.key)!.item_id, variant_id: byKey.get(l.key)!.variant_id, quantity: l.quantity })),
      });
      toast.success(`On the way to ${toName}. It counts there when someone taps Received.`);
      onSent();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't send. Try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <Dialog title="Move stock" onClose={onClose} footer={
      <>
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-semibold text-ink hover:bg-surface-low">Cancel</button>
        <button type="button" onClick={send} disabled={sending || problems.length > 0}
          className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-bold text-white hover:bg-primary-dark disabled:opacity-50">
          {sending ? <Loader2 size={15} className="animate-spin" /> : <Truck size={15} />} Send
        </button>
      </>
    }>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
        <label className="block text-sm font-semibold text-ink">From
          <Select value={from} onChange={setFrom} options={placeOptions} className="mt-1 w-full" aria-label="From" />
        </label>
        <button type="button" onClick={() => { setFrom(to); setTo(from); }} aria-label="Swap places"
          className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl border border-border text-ink-muted hover:bg-surface-low hover:text-ink">
          <ArrowLeftRight size={15} />
        </button>
        <label className="block text-sm font-semibold text-ink">To
          <Select value={to} onChange={setTo} options={placeOptions} className="mt-1 w-full" aria-label="To" />
        </label>
      </div>

      <div className="mt-4 space-y-2">
        <p className="text-sm font-semibold text-ink">Items</p>
        {lines.map((l) => {
          const line = byKey.get(l.key)!;
          const max = have(l.key);
          return (
            <div key={l.key} className="flex items-center gap-3 rounded-xl border border-border px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold text-ink">{lineName(line)}</p>
                <p className={cn("text-xs", l.quantity > max ? "text-danger" : "text-ink-muted")}>{fromName} has {max}</p>
              </div>
              <input type="number" inputMode="numeric" min={1} max={max} value={l.quantity || ""} aria-label="Quantity"
                onChange={(e) => setLines(lines.map((x) => x.key === l.key ? { ...x, quantity: Math.max(0, Math.floor(Number(e.target.value) || 0)) } : x))}
                className="h-9 w-20 rounded-lg border border-border px-2 text-right tabular-nums outline-none focus:border-primary" />
              <button type="button" onClick={() => setLines(lines.filter((x) => x.key !== l.key))} aria-label="Remove item"
                className="text-ink-muted hover:text-danger"><Trash2 size={15} /></button>
            </div>
          );
        })}
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Add an item from ${fromName}`}
            className="h-10 w-full rounded-xl border border-dashed border-border bg-white pl-9 pr-3 text-sm outline-none focus:border-primary" />
          {matches.length > 0 && (
            <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-xl border border-border bg-white shadow-lg">
              {matches.map((li) => (
                <li key={li.key}>
                  <button type="button" onClick={() => { setLines([...lines, { key: li.key, quantity: 1 }]); setQuery(""); }}
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-surface-low">
                    <span className="truncate text-ink">{lineName(li)}</span>
                    <span className="shrink-0 text-xs text-ink-muted">{have(li.key)} in {fromName}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {query.trim() && !matches.length && <p className="mt-1 text-xs text-ink-muted">Nothing in {fromName} matches.</p>}
        </div>
      </div>

      <label className="mt-4 block text-sm font-semibold text-ink">Note <span className="font-normal text-ink-muted">(optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} placeholder="e.g. Sent with Bala in the auto"
          className="mt-1 h-10 w-full rounded-xl border border-border px-3 text-sm outline-none focus:border-primary" />
      </label>

      {problems.length > 0 && lines.length > 0 && <p className="mt-3 text-sm text-danger">{problems[0]}</p>}
      <p className="mt-3 text-xs text-ink-muted">
        The stock leaves {fromName || "this place"} now and shows as On the way. It is added to {toName || "the other place"} when someone there taps Received.
      </p>
    </Dialog>
  );
}

function PlacesDialog({ places, onClose, onSaved }: { places: StockPlaceCard[]; onClose: () => void; onSaved: () => void }) {
  const [rows, setRows] = useState<(StockPlace & { tempKey: string; pieces?: number })[]>(
    places.map((p) => ({ id: p.id, name: p.name, kind: p.kind, bills_from: p.bills_from, online_from: p.online_from,
      ready_note: p.ready_note, archived: false, tempKey: p.id, pieces: p.pieces })),
  );
  const [saving, setSaving] = useState(false);
  // Who works where (Team: staff tied to a place). Hidden when the viewer can't see the team.
  const [staff, setStaff] = useState<{ user_id: string; name: string; owner: boolean; place_id: string | null }[] | null>(null);
  const [staffPlace, setStaffPlace] = useState<Record<string, string>>({});
  useEffect(() => {
    api.catalog.placeStaff()
      .then((res) => { setStaff(res.data); setStaffPlace(Object.fromEntries(res.data.map((m) => [m.user_id, m.place_id ?? ""]))); })
      .catch(() => setStaff(null));
  }, []);
  const live = rows.filter((r) => !r.archived);
  const set = (key: string, patch: Partial<StockPlace>) => setRows(rows.map((r) => (r.tempKey === key ? { ...r, ...patch } : r)));
  const only = (key: string, flag: "bills_from" | "online_from") => setRows(rows.map((r) => ({ ...r, [flag]: r.tempKey === key })));
  const names = live.map((r) => r.name.trim().toLowerCase());
  const problem = !live.length ? "Keep at least one place."
    : names.some((n) => !n) ? "Every place needs a name."
    : new Set(names).size !== names.length ? "Two places have the same name."
    : !live.some((r) => r.bills_from) ? "Pick where counter bills take stock from."
    : !live.some((r) => r.online_from) ? "Pick where online orders are packed from." : null;

  function remove(key: string) {
    const r = rows.find((x) => x.tempKey === key)!;
    if (!r.id) { setRows(rows.filter((x) => x.tempKey !== key)); return; }
    const next = rows.map((x) => (x.tempKey === key ? { ...x, archived: true, bills_from: false, online_from: false } : x));
    const first = next.find((x) => !x.archived);
    setRows(next.map((x) => (x === first ? { ...x, bills_from: x.bills_from || !next.some((y) => !y.archived && y.bills_from),
      online_from: x.online_from || !next.some((y) => !y.archived && y.online_from) } : x)));
  }

  async function save() {
    setSaving(true);
    try {
      await api.catalog.saveStockPlaces(rows.map((r) => ({
        id: r.id, name: r.name.trim(), kind: r.kind, bills_from: r.bills_from, online_from: r.online_from,
        ready_note: r.ready_note?.trim() || null, archived: r.archived,
      })));
      for (const m of staff ?? []) {
        const next = staffPlace[m.user_id] ?? "";
        if (next !== (m.place_id ?? "") && (!next || rows.some((r) => r.id === next && !r.archived))) {
          await api.catalog.setPlaceStaff(m.user_id, next || null);
        }
      }
      toast.success("Places saved.");
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog title="Places" onClose={onClose} footer={
      <>
        <button type="button" onClick={onClose} className="h-10 rounded-xl border border-border bg-white px-4 text-sm font-semibold text-ink hover:bg-surface-low">Cancel</button>
        <button type="button" onClick={save} disabled={saving || !!problem}
          className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-bold text-white hover:bg-primary-dark disabled:opacity-50">
          {saving && <Loader2 size={15} className="animate-spin" />} Save
        </button>
      </>
    }>
      <p className="text-sm text-ink-muted">Your shop, godowns and branches. Nothing changes until you save.</p>
      <div className="mt-3 space-y-3">
        {live.map((r) => (
          <div key={r.tempKey} className="rounded-xl border border-border p-3">
            <div className="flex flex-wrap items-end gap-2">
              <label className="min-w-[180px] flex-1 text-xs font-semibold text-ink-muted">Name
                <input value={r.name} maxLength={60} onChange={(e) => set(r.tempKey, { name: e.target.value })} placeholder="e.g. Gandhipuram godown"
                  className="mt-1 h-10 w-full rounded-xl border border-border px-3 text-sm font-normal text-ink outline-none focus:border-primary" />
              </label>
              <label className="w-36 text-xs font-semibold text-ink-muted">Kind
                <Select value={r.kind} onChange={(v) => set(r.tempKey, { kind: v as StockPlaceKind })} options={KIND_OPTIONS} className="mt-1 w-full" aria-label="Kind" />
              </label>
              <button type="button" onClick={() => remove(r.tempKey)} disabled={live.length === 1 || (r.pieces ?? 0) > 0}
                title={(r.pieces ?? 0) > 0 ? `It has ${r.pieces} pcs. Move them to another place first.` : "Remove this place"}
                aria-label="Remove place" className="flex h-10 w-10 items-center justify-center rounded-xl border border-border text-ink-muted hover:text-danger disabled:cursor-not-allowed disabled:opacity-40">
                <Trash2 size={15} />
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink">
              <label className="inline-flex items-center gap-2">
                <input type="radio" name="bills_from" checked={r.bills_from} onChange={() => only(r.tempKey, "bills_from")} className="accent-primary" />
                Counter bills take stock from here
              </label>
              <label className="inline-flex items-center gap-2">
                <input type="radio" name="online_from" checked={r.online_from} onChange={() => only(r.tempKey, "online_from")} className="accent-primary" />
                Online orders are packed here
              </label>
            </div>
            {!r.online_from && (
              <label className="mt-2 block text-xs font-semibold text-ink-muted">
                When an item is only here, the AI agent tells customers it is available,
                <input value={r.ready_note ?? ""} maxLength={80} onChange={(e) => set(r.tempKey, { ready_note: e.target.value })} placeholder={DEFAULT_READY}
                  className="mt-1 h-10 w-full rounded-xl border border-border px-3 text-sm font-normal text-ink outline-none focus:border-primary" />
                <span className="mt-1 block font-normal">It says this in the customer&apos;s own language (English, Tamil or Tanglish).</span>
              </label>
            )}
          </div>
        ))}
      </div>
      <button type="button" disabled={live.length >= 20}
        onClick={() => setRows([...rows, { name: "", kind: "godown", bills_from: false, online_from: false, ready_note: null, tempKey: `new-${rows.length}-${Date.now()}` }])}
        className="mt-3 inline-flex h-10 items-center gap-1.5 rounded-xl border border-dashed border-border px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-50">
        <Plus size={15} /> Add a place
      </button>
      {problem && <p className="mt-3 text-sm text-danger">{problem}</p>}
      {staff && staff.some((m) => !m.owner) && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="font-display text-sm font-bold text-ink">Who works where</p>
          <p className="text-xs text-ink-muted">Their counter bills take stock from their place first, and only they can tap Received for stock coming to it. Owners can do everything.</p>
          <div className="mt-2 space-y-1.5">
            {staff.filter((m) => !m.owner).map((m) => (
              <div key={m.user_id} className="flex items-center gap-3">
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{m.name}</span>
                <Select size="sm" value={staffPlace[m.user_id] ?? ""} onChange={(v) => setStaffPlace((s) => ({ ...s, [m.user_id]: v }))}
                  aria-label={`Place of ${m.name}`} className="w-52"
                  options={[{ value: "", label: "All places" }, ...live.filter((r) => r.id).map((r) => ({ value: r.id as string, label: r.name }))]} />
              </div>
            ))}
          </div>
        </div>
      )}
    </Dialog>
  );
}
