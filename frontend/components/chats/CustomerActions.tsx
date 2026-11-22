"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CalendarCheck, ChevronDown, ChevronRight, Loader2, Receipt, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import useSWR from "swr";
import { api, DealSummary, Lead } from "@/lib/api";
import { bookingsApi } from "@/lib/bookingsApi";
import { NewBookingDialog } from "@/app/dashboard/bookings/NewBookingDialog";
import { istOf } from "@/app/dashboard/bookings/bookingsTime";
import { cn } from "@/lib/utils";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { formatRupees } from "@/components/deals/money";
import { RecordPaymentDialog } from "./RecordPaymentDialog";
import type { Option } from "./inboxFilters";

const NOT_BUYING_REASONS = ["Price too high", "Bought somewhere else", "Just looking", "Not reachable", "Wrong number"];

const SEGMENT_CHIP: Record<string, { label: string; className: string }> = {
  A: { label: "🔥 Hot", className: "bg-orange-50 text-orange-600" },
  B: { label: "Warm", className: "bg-amber-50 text-amber-700" },
  C: { label: "Cold", className: "bg-blue-50 text-blue-600" },
  D: { label: "Not interested", className: "bg-slate-100 text-slate-600" },
};

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata",
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
}

function humanKey(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** datetime-local value (IST wall time) -> ISO with the India offset. */
function istToIso(local: string): string | null {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(local) ? new Date(`${local}:00+05:30`).toISOString() : null;
}

/**
 * Top of the customer panel: the three things you do from a chat (book a visit, record a payment,
 * mark not buying), what the chat has told us about them, and what they've bought before.
 */
export function CustomerActions({
  lead,
  team,
  deals,
  onLeadUpdate,
  onDealsChanged,
  onShowDeals,
}: {
  lead: Lead;
  team: Option[];
  deals: DealSummary[];
  onLeadUpdate?: (updated: Lead) => void;
  onDealsChanged: () => void;
  onShowDeals: () => void;
}) {
  const { role, permissions, callerId } = useAuthRole();
  const canReply = role === "owner" || permissions.includes("conversations.reply");
  const canManageDeals = role === "owner" || permissions.includes("deals.manage");
  const canSeeMoney = role === "owner" || permissions.includes("deals.view") || canManageDeals;
  // Real bookings: only people who can make them ask, and only when at least one service is offered.
  const canBook = role === "owner" || permissions.includes("bookings.manage");
  const { data: bookingSetup } = useSWR(canBook ? "bookings/setup" : null, () => bookingsApi.setup(), {
    revalidateOnFocus: false,
    dedupingInterval: 30_000,
  });
  const realBookings = canReply && canBook && !!bookingSetup && bookingSetup.services.some((s) => s.active);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [bookingOpen, setBookingOpen] = useState(false);
  const [bookFor, setBookFor] = useState("");
  const [bookNote, setBookNote] = useState("");
  const [lostOpen, setLostOpen] = useState(false);
  const [busy, setBusy] = useState<null | "book" | "lost" | "undo">(null);
  const [payOpen, setPayOpen] = useState(false);
  const lostRef = useRef<HTMLDivElement>(null);
  const firstName = (lead.name || "").trim().split(/\s+/)[0] || "this customer";

  useEffect(() => {
    setBookingOpen(false);
    setPickerOpen(false);
    setLostOpen(false);
  }, [lead.id]);

  useEffect(() => {
    if (!lostOpen) return;
    function onDown(e: MouseEvent) {
      if (lostRef.current && !lostRef.current.contains(e.target as Node)) setLostOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [lostOpen]);

  async function run(kind: "book" | "lost" | "undo", fn: () => Promise<Lead>, done: string) {
    setBusy(kind);
    try {
      const updated = await fn();
      onLeadUpdate?.({ ...lead, ...updated });
      toast.success(done);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save that");
    } finally {
      setBusy(null);
    }
  }

  const won = deals.filter((d) => d.stage === "won");
  const wonTotal = won.reduce((s, d) => s + (d.total_paise || 0), 0);
  const lastWon = [...won].sort((a, b) => (b.won_at || b.created_at).localeCompare(a.won_at || a.created_at))[0];
  const collected = Object.entries(lead.collected_data || {}).filter(
    ([, v]) => v !== null && v !== undefined && String(v).trim() !== ""
  );
  const seg = SEGMENT_CHIP[lead.segment];

  return (
    <div className="space-y-4 px-4 pt-4">
      {/* ── Actions ── */}
      <div className="space-y-1.5">
        {lead.booked_at ? (
          <div className="flex items-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2.5">
            <CalendarCheck size={16} className="shrink-0 text-sky-700" />
            <div className="min-w-0 flex-1">
              <p className="text-[12.5px] font-bold text-sky-900">
                Booked{lead.booked_for ? ` for ${fmtDateTime(lead.booked_for)}` : ""}
              </p>
              {lead.booking_note && <p className="truncate text-[11.5px] text-sky-800">{lead.booking_note}</p>}
            </div>
            {realBookings ? (
              // A real booking has a time held on a column: it is moved or cancelled in Bookings, never "removed" here.
              <Link
                href={`/dashboard/bookings${lead.booked_for && istOf(lead.booked_for) ? `?date=${istOf(lead.booked_for)?.date}` : ""}`}
                className="shrink-0 rounded-lg px-2 py-1 text-[11.5px] font-semibold text-sky-800 hover:bg-sky-100"
              >
                Open in Bookings
              </Link>
            ) : (
              canReply && (
                <button
                  type="button"
                  onClick={() => void run("undo", () => api.chats.cancelBooking(lead.id), "Booking removed")}
                  disabled={busy !== null}
                  className="shrink-0 rounded-lg px-2 py-1 text-[11.5px] font-semibold text-sky-800 hover:bg-sky-100"
                >
                  Remove
                </button>
              )
            )}
          </div>
        ) : bookingOpen ? (
          <div className="space-y-2 rounded-xl border border-primary/30 bg-white p-3 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-[12.5px] font-bold text-[#0A1528]">Book a visit</p>
              <button type="button" aria-label="Close" onClick={() => setBookingOpen(false)} className="rounded p-0.5 text-[#64748b] hover:bg-slate-100">
                <X size={14} />
              </button>
            </div>
            <input
              type="datetime-local"
              aria-label="Visit date and time"
              value={bookFor}
              onChange={(e) => setBookFor(e.target.value)}
              className="h-9 w-full rounded-lg border border-[#e2e8f0] px-2.5 text-[12.5px] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
            />
            <input
              value={bookNote}
              onChange={(e) => setBookNote(e.target.value)}
              maxLength={300}
              placeholder="Note (optional), e.g. trial for bridal saree"
              className="h-9 w-full rounded-lg border border-[#e2e8f0] px-2.5 text-[12.5px] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
            />
            <button
              type="button"
              disabled={busy !== null}
              onClick={() =>
                void run("book", () => api.chats.book(lead.id, { booked_for: istToIso(bookFor), note: bookNote.trim() || null }), "Marked as booked").then(() => {
                  setBookingOpen(false);
                  setBookFor("");
                  setBookNote("");
                })
              }
              className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-primary text-[12.5px] font-bold text-white hover:bg-[var(--primary-900)] disabled:opacity-50"
            >
              {busy === "book" && <Loader2 size={13} className="animate-spin" />} Save booking
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => (realBookings ? setPickerOpen(true) : setBookingOpen(true))}
            disabled={!canReply}
            title={canReply ? undefined : "You have read-only access to conversations"}
            className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-primary text-[12.5px] font-bold text-white shadow-sm hover:bg-[var(--primary-900)] disabled:cursor-not-allowed disabled:opacity-45"
          >
            <CalendarCheck size={14} /> Book a visit
          </button>
        )}

        <button
          type="button"
          onClick={() => setPayOpen(true)}
          disabled={!canManageDeals}
          title={canManageDeals ? undefined : "You need permission to manage deals"}
          className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-[#e2e8f0] bg-white text-[12.5px] font-bold text-[#0A1528] hover:bg-[#f8fafc] disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Receipt size={14} className="text-[#64748b]" /> Record payment
        </button>

        {lead.lost_at ? (
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
            <X size={15} className="shrink-0 text-slate-500" />
            <p className="min-w-0 flex-1 truncate text-[12.5px] text-slate-700">
              <span className="font-bold">Not buying</span>{lead.lost_reason ? ` · ${lead.lost_reason}` : ""}
            </p>
            {canReply && (
              <button
                type="button"
                onClick={() => void run("undo", () => api.chats.undoNotBuying(lead.id), "Marked as still interested")}
                disabled={busy !== null}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[11.5px] font-semibold text-slate-700 hover:bg-slate-100"
              >
                <Undo2 size={12} /> Undo
              </button>
            )}
          </div>
        ) : (
          <div className="relative" ref={lostRef}>
            <button
              type="button"
              onClick={() => setLostOpen((o) => !o)}
              disabled={!canReply || busy !== null}
              aria-expanded={lostOpen}
              className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-[#e2e8f0] bg-white text-[12.5px] font-bold text-[#0A1528] hover:bg-[#f8fafc] disabled:cursor-not-allowed disabled:opacity-45"
            >
              <X size={14} className="text-[#64748b]" /> Not buying <ChevronDown size={13} className="text-[#64748b]" />
            </button>
            {lostOpen && (
              <div className="absolute inset-x-0 top-full z-30 mt-1 overflow-hidden rounded-xl border border-[#e2e8f0] bg-white py-1 shadow-xl">
                <p className="px-3 pb-1 pt-1.5 font-label text-[10px] font-bold uppercase tracking-[0.08em] text-[#94a3b8]">Why?</p>
                {NOT_BUYING_REASONS.map((reason) => (
                  <button
                    key={reason}
                    type="button"
                    onClick={() => { setLostOpen(false); void run("lost", () => api.chats.notBuying(lead.id, reason), "Marked as not buying"); }}
                    className="w-full px-3 py-2 text-left text-[12.5px] text-[#334155] hover:bg-slate-50"
                  >
                    {reason}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── About ── */}
      <div>
        <p className="mb-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">About {firstName}</p>
        <div className="flex flex-wrap gap-1.5">
          {seg && <span className={cn("rounded-md px-2 py-1 text-[11.5px] font-bold", seg.className)}>{seg.label}</span>}
          {lead.ad_campaign_name && (
            <span className="rounded-md border border-primary/30 px-2 py-1 text-[11.5px] font-semibold text-primary">{lead.ad_campaign_name}</span>
          )}
        </div>
        {collected.length > 0 ? (
          <dl className="mt-2.5 space-y-1.5">
            {collected.slice(0, 6).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-[12.5px]">
                <dt className="shrink-0 text-[#64748b]">{humanKey(k)}</dt>
                <dd className="min-w-0 truncate font-semibold text-[#0A1528]">{String(v)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-2 text-[11.5px] text-[#94a3b8]">Details the AI agent picks up in the chat show here.</p>
        )}
      </div>

      {/* ── What they've bought ── */}
      {won.length > 0 && (
        <button
          type="button"
          onClick={onShowDeals}
          className="flex w-full items-center gap-2 rounded-xl bg-[#f1f5f9] px-3 py-2.5 text-left hover:bg-[#e8edf3]"
        >
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-bold text-[#0A1528]">
              Bought {won.length === 1 ? "once" : `${won.length} times`} · {formatRupees(wonTotal)}
            </p>
            {lastWon && (
              <p className="truncate text-[11.5px] text-[#64748b]">
                Last: {lastWon.item_summary || lastWon.deal_label}, {fmtDate(lastWon.won_at || lastWon.created_at)}
              </p>
            )}
          </div>
          <ChevronRight size={15} className="shrink-0 text-[#94a3b8]" />
        </button>
      )}

      <RecordPaymentDialog
        open={payOpen}
        onClose={() => setPayOpen(false)}
        lead={lead}
        team={team}
        defaultMethod="cash"
        defaultSoldBy={lead.assigned_to ?? callerId}
        onRecorded={onDealsChanged}
      />
      {pickerOpen && bookingSetup && (
        <NewBookingDialog
          setup={bookingSetup}
          canSeeMoney={canSeeMoney}
          prefill={{ phone: lead.phone ?? "", name: lead.name ?? "", leadId: lead.id, source: "chat" }}
          onClose={() => setPickerOpen(false)}
          onCreated={(b) => {
            setPickerOpen(false);
            onLeadUpdate?.({ ...lead, booked_at: lead.booked_at ?? new Date().toISOString(), booked_for: b.start_at });
          }}
        />
      )}
    </div>
  );
}
