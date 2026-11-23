"use client";
import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";

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

export function CampaignResultsDrawer({ broadcastId, title, onClose }: { broadcastId: string; title: string; onClose: () => void }) {
  const [data, setData] = useState<CampaignResults | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const showMoney = data?.cost_inr !== undefined;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        role="dialog"
        aria-label={`Results for ${title}`}
        className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-label text-[11px] font-bold uppercase tracking-wider text-gray-400">Campaign results</p>
            <h2 className="truncate font-display text-base font-bold text-gray-900">{title}</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        {error ? (
          <p className="font-body text-sm text-red-600">{error}</p>
        ) : !data ? (
          <div className="flex justify-center py-12"><Loader2 className="animate-spin text-gray-400" size={20} /></div>
        ) : (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Sent" value={data.sent.toLocaleString("en-IN")} />
              <Stat label="Said stop" value={data.said_stop === null ? "—" : data.said_stop.toLocaleString("en-IN")} />
              <Stat
                label="Paid within 7 days"
                value={data.paid_count === null ? "—" : data.paid_count.toLocaleString("en-IN")}
                note={data.paid_window_open ? "still counting" : undefined}
              />
              {showMoney && (
                <Stat label="Paid, in rupees" value={data.paid_amount_inr == null ? "—" : rupees(data.paid_amount_inr)} />
              )}
            </div>

            {showMoney && (
              <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                <p className="font-label text-xs font-semibold text-green-800">₹ back per ₹1 (estimated)</p>
                <p className="font-display text-2xl font-bold text-green-900">
                  {data.back_per_rupee == null ? "—" : `₹${data.back_per_rupee.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`}
                </p>
                <p className="mt-1 font-body text-xs text-green-800/80">
                  {rupees(data.paid_amount_inr ?? 0)} paid ÷ about {rupees(data.cost_inr ?? 0)} of messages ({data.sent.toLocaleString("en-IN")} sent × ₹{data.rate_inr} each, before tax).
                </p>
              </div>
            )}

            <div>
              <p className="mb-2 font-label text-xs font-bold uppercase tracking-wider text-gray-500">Who paid</p>
              {data.paid_people.length === 0 ? (
                <p className="font-body text-sm text-gray-500">{data.paid_count === null ? "Could not load this list." : "Nobody has paid yet."}</p>
              ) : (
                <ul className="divide-y divide-gray-100 rounded-xl border border-gray-100">
                  {data.paid_people.map((p) => (
                    <li key={p.lead_id} className="flex items-center justify-between gap-3 px-3 py-2">
                      <div className="min-w-0">
                        <p className="truncate font-body text-sm font-semibold text-gray-900">{p.name || p.phone || "Customer"}</p>
                        <p className="font-body text-xs text-gray-500">
                          {p.name && p.phone ? `${p.phone} · ` : ""}
                          {new Date(p.paid_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                        </p>
                      </div>
                      {p.paid_inr !== undefined && <span className="shrink-0 font-display text-sm font-bold text-gray-900">{rupees(p.paid_inr)}</span>}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 font-body text-[11px] text-gray-400">Each person counts once, for their first order within 7 days of getting the message.</p>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-gray-50/60 p-3">
      <p className="font-label text-[11px] font-semibold text-gray-500">{label}</p>
      <p className="font-display text-lg font-bold text-gray-900">{value}</p>
      {note && <p className="font-body text-[11px] text-green-700">{note}</p>}
    </div>
  );
}
