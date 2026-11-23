"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { Phone } from "lucide-react";
import { bookingsApi, type SiteVisit } from "@/lib/bookingsApi";
import { cn } from "@/lib/utils";
import { STATUS_CLASS, STATUS_LABEL, canMarkNoShow, canMarkVisit, customerLabel } from "./bookingsLogic";
import { formatDay, formatTime, istOf, todayIst } from "./bookingsTime";
import { BTN_PRIMARY, BTN_SECONDARY, Notice, errorText } from "./bookingsUi";

const SEGMENT: Record<string, { label: string; cls: string }> = {
  A: { label: "🔥 Hot", cls: "text-[#b42318]" },
  B: { label: "Warm", cls: "text-[#b54708]" },
  C: { label: "Cold", cls: "text-[#475467]" },
};

const REBOOK_WHY: Record<string, string> = {
  outside_24h_no_template: "they haven't messaged in 24 hours. Call them instead",
  opted_out: "they said stop",
  blocked: "they are blocked",
};

function whenLabel(iso: string): string {
  const day = istOf(iso)?.date ?? "";
  const today = todayIst();
  const word = day === today ? "Today" : formatDay(day);
  return `${word} ${formatTime(iso)}`;
}

function Pickup({ v, canEdit, onSaved }: { v: SiteVisit; canEdit: boolean; onSaved: () => void }) {
  const [draft, setDraft] = useState(v.pickup ?? "");
  if (!canEdit) return <span className="text-sm text-ink-secondary">{v.pickup || "—"}</span>;
  return (
    <input
      value={draft}
      maxLength={120}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={async () => {
        if (draft.trim() === (v.pickup ?? "")) return;
        try {
          await bookingsApi.setPickup(v.id, draft);
          onSaved();
        } catch (err) {
          toast.error(errorText(err));
        }
      }}
      placeholder="e.g. Own vehicle"
      aria-label={`Pickup for ${customerLabel(v)}`}
      className="h-8 w-full min-w-[9rem] rounded-lg border border-transparent bg-transparent px-2 text-sm text-ink hover:border-border focus:border-primary focus:outline-none"
    />
  );
}

/**
 * Bookings > Site visits: who is coming, which property, who shows them around, pickup, and one tap after
 * the visit (Token paid / Liked, thinking) or when they didn't come (send a new time).
 */
export function SiteVisitsTab({ canManage, myResourceId }: { canManage: boolean; myResourceId: string | null }) {
  const router = useRouter();
  const { data, error, mutate } = useSWR("bookings/site-visits", () => bookingsApi.siteVisits());
  const [busy, setBusy] = useState<string | null>(null);
  const who = { canManage, myResourceId };

  async function act(id: string, fn: () => Promise<unknown>, done: string) {
    setBusy(id);
    try {
      await fn();
      toast.success(done);
      await mutate();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function tokenPaid(v: SiteVisit) {
    setBusy(v.id);
    try {
      await bookingsApi.visitOutcome(v.id, "token_paid");
      await mutate();
      if (v.deal_id) router.push(`/dashboard/deals/orders/${encodeURIComponent(v.deal_id)}`);
      else toast.success("Saved. Record the token in Orders & payments.");
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function rebook(v: SiteVisit) {
    setBusy(v.id);
    try {
      const res = await bookingsApi.rebookMessage(v.id);
      if (res.sent) toast.success("New-time message sent");
      else toast.warning(`Not sent: ${REBOOK_WHY[res.reason] ?? "WhatsApp didn't take it"}.`);
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  if (error && !data) return <Notice tone="red">Site visits could not be loaded. Try again in a moment.</Notice>;
  if (!data) return <div className="h-48 animate-pulse rounded-2xl bg-border-subtle" aria-hidden />;
  if (!data.service_ready) return <Notice>Add a property in Commerce › Properties and the Site visit service is set up for you.</Notice>;

  const rows = data.data.filter((v) => v.status !== "cancelled");
  return (
    <div className="space-y-4">
      {rows.length === 0 ? (
        <Notice>No site visits from 2 days ago to 2 weeks ahead.</Notice>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border bg-white shadow-card">
          <table className="w-full min-w-[960px] text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-low text-left text-[11px] font-bold uppercase tracking-wider text-ink-muted">
                <th className="px-4 py-2.5">Buyer</th>
                <th className="px-3 py-2.5">Property</th>
                <th className="px-3 py-2.5">When</th>
                <th className="px-3 py-2.5">Shown by</th>
                <th className="px-3 py-2.5">Pickup</th>
                <th className="px-3 py-2.5">Status</th>
                <th className="px-4 py-2.5">After the visit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {rows.map((v) => {
                const seg = v.segment ? SEGMENT[v.segment] : null;
                // Same people as Came / Didn't come: a manager, or the person on this column.
                const canAct = canManage || (myResourceId !== null && myResourceId === v.resource_id);
                const open = v.status === "booked" || v.status === "held";
                return (
                  <tr key={v.id}>
                    <td className="px-4 py-2.5">
                      {v.lead_id ? (
                        <Link href={`/dashboard/conversations?lead=${encodeURIComponent(v.lead_id)}`} className="font-bold text-ink hover:text-primary">{customerLabel(v)}</Link>
                      ) : (
                        <span className="font-bold text-ink">{customerLabel(v)}</span>
                      )}
                      {seg && <p className={cn("text-xs font-semibold", seg.cls)}>{seg.label}</p>}
                    </td>
                    <td className="px-3 py-2.5 text-ink">{v.property_name || <span className="text-ink-muted">Not linked</span>}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 font-semibold text-ink">{whenLabel(v.start_at)}</td>
                    <td className="px-3 py-2.5 text-ink-secondary">{v.shown_by || "—"}</td>
                    <td className="px-3 py-2.5"><Pickup v={v} canEdit={canAct} onSaved={() => void mutate()} /></td>
                    <td className="px-3 py-2.5">
                      <span className={cn("rounded-full border px-2 py-0.5 text-xs font-bold", STATUS_CLASS[v.status])}>
                        {open && !v.confirmed_at && v.call_now ? "No reply yet" : open && v.confirmed_at ? "Confirmed" : STATUS_LABEL[v.status]}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        {v.status === "came" && canAct && v.visit_outcome !== "token_paid" && v.visit_outcome !== "liked_thinking" && (
                          <>
                            <button type="button" disabled={busy === v.id} onClick={() => void tokenPaid(v)} className={cn(BTN_PRIMARY, "min-h-8 px-3 py-1 text-xs")}>🪙 Token paid</button>
                            <button type="button" disabled={busy === v.id} onClick={() => void act(v.id, () => bookingsApi.visitOutcome(v.id, "liked_thinking"), "Saved. Loan help goes in 2 days.")} className={cn(BTN_SECONDARY, "min-h-8 px-3 py-1 text-xs")}>Liked, thinking</button>
                          </>
                        )}
                        {v.visit_outcome === "token_paid" && <span className="text-xs font-semibold text-[#067647]">🪙 Token paid</span>}
                        {v.visit_outcome === "liked_thinking" && <span className="text-xs text-ink-secondary">Loan help in 2 days ✓</span>}
                        {open && canMarkVisit(v, who) && canMarkNoShow(v, who) && (
                          <>
                            <button type="button" disabled={busy === v.id} onClick={() => void act(v.id, () => bookingsApi.came(v.id), "Marked as came")} className={cn(BTN_SECONDARY, "min-h-8 px-3 py-1 text-xs")}>✓ Came</button>
                            <button type="button" disabled={busy === v.id} onClick={() => void act(v.id, () => bookingsApi.noShow(v.id), "Marked as didn't come")} className={cn(BTN_SECONDARY, "min-h-8 px-3 py-1 text-xs text-ink-secondary")}>Didn&apos;t come</button>
                          </>
                        )}
                        {open && !canMarkNoShow(v, who) && v.call_now && (
                          <a href={`tel:${v.phone}`} className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline"><Phone size={12} /> Call to confirm ›</a>
                        )}
                        {v.status === "no_show" && canAct && (
                          <button type="button" disabled={busy === v.id} onClick={() => void rebook(v)} className="text-xs font-bold text-primary hover:underline">Send a new time ›</button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="rounded-2xl border border-border bg-white px-5 py-4 text-sm text-ink-secondary shadow-card">
        <p className="font-display text-[15px] font-bold text-ink">After each visit <span className="font-body text-xs font-normal text-ink-muted">one tap, the rest goes by itself</span></p>
        <p className="mt-1.5">🪙 <b className="text-ink">Token paid</b>: opens the order to take the token; when it&apos;s paid the unit comes off Properties.</p>
        <p>🤔 <b className="text-ink">Liked, thinking</b>: loan help goes on WhatsApp after 2 days.</p>
        <p>✕ <b className="text-ink">Didn&apos;t come</b>: send them a new time, or call.</p>
      </div>
    </div>
  );
}
