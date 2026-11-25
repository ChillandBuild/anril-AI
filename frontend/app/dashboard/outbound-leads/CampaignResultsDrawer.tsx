"use client";
import { useEffect, useState } from "react";
import { BarChart3, Hand, IndianRupee, Loader2, Send, ShoppingBag, Sparkles, User, X, type LucideIcon } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { cn } from "@/lib/utils";

// From GET /upload/broadcast/{id}/results. The rupee fields are missing without the deals.view permission.
export type CampaignResults = {
  broadcast_id: string;
  sent: number;
  said_stop: number | null;
  paid_count: number | null;
  paid_window_open: boolean;
  paid_people: { lead_id: string; name: string | null; phone: string | null; paid_at: string; paid_inr?: number }[];
  paid_amount_inr?: number | null;
  cost_inr?: number;
  rate_inr?: number;
  back_per_rupee?: number | null;
};

const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const share = (part: number | null | undefined, whole: number) =>
  part == null || whole <= 0 ? null : `${Math.round((part / whole) * 1000) / 10}% of sent`;
const initials = (s: string) => s.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";

export function CampaignResultsDrawer({ broadcastId, title, onClose }: { broadcastId: string; title: string; onClose: () => void }) {
  const [data, setData] = useState<CampaignResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/upload/broadcast/${broadcastId}/results`, { headers: await getAuthHeaders() });
        if (!res.ok) throw new Error();
        const body: CampaignResults = await res.json();
        if (live) setData(body);
      } catch {
        if (live) setError("Could not load the results. Try again.");
      }
    })();
    return () => { live = false; };
  }, [broadcastId]);

  // Slide in on open; Escape closes.
  useEffect(() => {
    const t = requestAnimationFrame(() => setShown(true));
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { cancelAnimationFrame(t); window.removeEventListener("keydown", onKey); };
  }, [onClose]);

  const showMoney = data?.cost_inr !== undefined;
  return (
    <div
      className={cn("fixed inset-0 z-50 flex justify-end bg-gray-900/30 backdrop-blur-[2px] transition-opacity duration-200", shown ? "opacity-100" : "opacity-0")}
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-label={`Results for ${title}`}
        className={cn(
          "flex h-full w-full max-w-[440px] flex-col bg-white shadow-2xl transition-transform duration-300 ease-out",
          shown ? "translate-x-0" : "translate-x-full"
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="border-b border-primary-100/70 bg-gradient-to-br from-primary-50 via-white to-white px-5 pb-4 pt-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-primary-200/70 bg-white shadow-xs">
              <BarChart3 size={18} className="text-[var(--primary-800)]" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-label text-[10px] font-bold uppercase tracking-[0.12em] text-primary-700/80">Campaign results</p>
              <h2 className="break-all font-display text-[15px] font-bold leading-snug text-gray-900">{title}</h2>
            </div>
            <button onClick={onClose} aria-label="Close" className="-mr-1 rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {error ? (
            <p className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 font-body text-sm text-red-700">{error}</p>
          ) : !data ? (
            <div className="flex justify-center py-16"><Loader2 className="animate-spin text-gray-400" size={22} /></div>
          ) : (
            <div className="space-y-5">
              {/* Return on the campaign */}
              {showMoney && (() => {
                // Green once money came back; a calm neutral card while it's still ₹0.
                const earned = (data.back_per_rupee ?? 0) > 0;
                return (
                  <div className={cn(
                    "relative overflow-hidden rounded-2xl p-4",
                    earned
                      ? "bg-gradient-to-br from-emerald-600 to-emerald-700 text-white shadow-[0_8px_24px_-8px_rgba(5,150,105,0.55)]"
                      : "border border-gray-200 bg-gradient-to-br from-gray-50 to-white text-gray-900"
                  )}>
                    <Sparkles size={64} className={cn("absolute -right-3 -top-3", earned ? "text-white/10" : "text-gray-200/70")} />
                    <p className={cn("font-label text-[11px] font-semibold uppercase tracking-wider", earned ? "text-emerald-100" : "text-gray-500")}>
                      Back for every ₹1 spent · estimated
                    </p>
                    <p className="mt-1 font-display text-3xl font-bold tabular-nums">
                      {data.back_per_rupee == null ? "—" : `₹${data.back_per_rupee.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`}
                    </p>
                    <p className={cn("mt-2 font-body text-xs leading-relaxed", earned ? "text-emerald-50/90" : "text-gray-600")}>
                      {rupees(data.paid_amount_inr ?? 0)} paid ÷ about {rupees(data.cost_inr ?? 0)} of messages
                      <span className={earned ? "text-emerald-100/70" : "text-gray-400"}> ({data.sent.toLocaleString("en-IN")} sent × ₹{data.rate_inr} each, before tax)</span>
                    </p>
                  </div>
                );
              })()}

              {/* The numbers */}
              <div className="grid grid-cols-2 gap-2.5">
                <Stat icon={Send} tone="blue" label="Sent" value={data.sent.toLocaleString("en-IN")} />
                <Stat
                  icon={Hand}
                  tone="rose"
                  label="Said stop"
                  value={data.said_stop === null ? "—" : data.said_stop.toLocaleString("en-IN")}
                  note={share(data.said_stop, data.sent) ?? undefined}
                />
                <Stat
                  icon={ShoppingBag}
                  tone="emerald"
                  label="Paid within 7 days"
                  value={data.paid_count === null ? "—" : data.paid_count.toLocaleString("en-IN")}
                  note={share(data.paid_count, data.sent) ?? undefined}
                  badge={data.paid_window_open ? "Still counting" : undefined}
                />
                {showMoney && (
                  <Stat icon={IndianRupee} tone="emerald" label="Paid, in rupees" value={data.paid_amount_inr == null ? "—" : rupees(data.paid_amount_inr)} />
                )}
              </div>

              {/* Who paid */}
              <div>
                <div className="mb-2.5 flex items-center justify-between">
                  <p className="font-label text-[11px] font-bold uppercase tracking-wider text-gray-500">Who paid</p>
                  {data.paid_people.length > 0 && (
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 font-label text-[11px] font-semibold text-gray-600">{data.paid_people.length}</span>
                  )}
                </div>
                {data.paid_people.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-gray-200 bg-gray-50/50 px-4 py-7 text-center">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-xs ring-1 ring-gray-100">
                      <ShoppingBag size={17} className="text-gray-400" />
                    </div>
                    <p className="font-body text-sm font-medium text-gray-600">
                      {data.paid_count === null ? "Could not load this list." : "Nobody has paid yet"}
                    </p>
                    {data.paid_count !== null && data.paid_window_open && (
                      <p className="font-body text-xs text-gray-400">Orders in the next few days will show up here.</p>
                    )}
                  </div>
                ) : (
                  <ul className="divide-y divide-gray-100 overflow-hidden rounded-2xl border border-gray-100">
                    {data.paid_people.map((p) => {
                      const who = p.name || p.phone || "Customer";
                      return (
                        <li key={p.lead_id} className="flex items-center gap-3 px-3.5 py-2.5 transition-colors hover:bg-gray-50/70">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-50 font-label text-[11px] font-bold text-emerald-700 ring-1 ring-emerald-100">
                            {p.name ? initials(p.name) : <User size={14} />}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-body text-sm font-semibold text-gray-900">{who}</p>
                            <p className="font-body text-xs text-gray-500">
                              {p.name && p.phone ? `${p.phone} · ` : ""}
                              {new Date(p.paid_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                            </p>
                          </div>
                          {p.paid_inr !== undefined && <span className="shrink-0 font-display text-sm font-bold tabular-nums text-gray-900">{rupees(p.paid_inr)}</span>}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>

        <p className="border-t border-gray-100 px-5 py-3 font-body text-[11px] leading-relaxed text-gray-400">
          Each person counts once, for their first order within 7 days of getting the message.
        </p>
      </aside>
    </div>
  );
}

const TONES = {
  blue: "bg-blue-50 text-blue-600 ring-blue-100",
  rose: "bg-rose-50 text-rose-500 ring-rose-100",
  emerald: "bg-emerald-50 text-emerald-600 ring-emerald-100",
} as const;

function Stat({ icon: Icon, tone, label, value, note, badge }: {
  icon: LucideIcon;
  tone: keyof typeof TONES;
  label: string;
  value: string;
  note?: string;
  badge?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white px-3 py-2.5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex items-center gap-1.5">
        <span className={cn("flex h-6 w-6 items-center justify-center rounded-md ring-1", TONES[tone])}>
          <Icon size={12} />
        </span>
        <p className="font-label text-[11px] font-semibold text-gray-500">{label}</p>
      </div>
      <p className="mt-1.5 font-display text-xl font-bold leading-tight tabular-nums text-gray-900">{value}</p>
      <div className="flex min-h-[16px] flex-wrap items-center gap-1.5">
        {note && <span className="font-body text-[11px] text-gray-400">{note}</span>}
        {badge && (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-1.5 py-px font-label text-[10px] font-semibold text-emerald-700">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />{badge}
          </span>
        )}
      </div>
    </div>
  );
}
