"use client";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, InboundLead, InboundLeadFilters, InboundResult, InboundResultLabels, Lead } from "@/lib/api";
import { useInboundAds, useInboundLeads, useInboundLeadsSummary } from "@/hooks/useApi";
import {
  Download, X, RefreshCw, Link2, Copy, Check, Search, MessageSquare, Clock, CheckCircle2,
  CalendarCheck, ChevronLeft, ChevronRight, Bot, UserRound, AlertCircle, Inbox, Receipt, Pencil, Undo2, Repeat,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PAGE_SIZE } from "@/lib/pagination";
import { Pagination } from "@/components/ui/Pagination";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { FilterMenu, FilterMenuOption } from "@/app/dashboard/leads/FilterMenu";
import { LeadDetailsPanel } from "@/components/lead-details-panel";
import { ChatThread } from "@/components/chat-thread";
import type { Option } from "@/components/chats/inboxFilters";
import { CheckTick } from "@/components/ui/controls";
import { SendMessageModal } from "@/app/dashboard/leads/SendMessageModal";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { followUpHrefForGroup, savePickedPeopleAsGroup, tagsApi, type TagCount } from "@/lib/customersApi";
import { InboundTabs, InsightsList, MoneyTodayCards, type InboundTab } from "./InboundInsights";
import { SendTemplateAudience } from "./SendTemplateAudience";

// ─── Constants ───────────────────────────────────────────────────────────────

const TZ = "Asia/Kolkata";

const CHANNEL_DOT: Record<string, string> = {
  whatsapp: "bg-emerald-500",
  instagram: "bg-pink-500",
  facebook: "bg-blue-500",
  meta_form: "bg-violet-500",
  telegram: "bg-sky-500",
  indiamart: "bg-amber-500",
  justdial: "bg-orange-500",
  qr: "bg-teal-500",
};

const CAME_FROM_OPTIONS: FilterMenuOption[] = [
  { value: "all", label: "All" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
  { value: "meta_form", label: "Instant form" },
  { value: "telegram", label: "Telegram" },
  { value: "indiamart", label: "IndiaMART" },
  { value: "justdial", label: "JustDial" },
  { value: "qr", label: "QR" },
];

const ORIGIN_OPTIONS: FilterMenuOption[] = [
  { value: "all", label: "All" },
  { value: "ad", label: "From an ad" },
  { value: "organic", label: "No ad" },
];

const ADDED_OPTIONS: FilterMenuOption[] = [
  { value: "any", label: "Any time" },
  { value: "1", label: "Today" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const INTEREST_CHIPS: { value: "A" | "B" | "C" | "D"; label: string; on: string; off: string }[] = [
  { value: "A", label: "Hot", on: "bg-[#b93815] text-white", off: "bg-[#fef6ee] text-[#b93815] hover:bg-[#fdead7]" },
  { value: "B", label: "Warm", on: "bg-[#b54708] text-white", off: "bg-[#fffaeb] text-[#b54708] hover:bg-[#fef0c7]" },
  { value: "C", label: "Cold", on: "bg-[#175cd3] text-white", off: "bg-[#eff8ff] text-[#175cd3] hover:bg-[#d1e9ff]" },
  { value: "D", label: "Not interested", on: "bg-[#475467] text-white", off: "bg-[#f2f4f7] text-[#475467] hover:bg-[#e4e7ec]" },
];

const DEFAULT_LABELS: InboundResultLabels = { booked: "Booked", paid: "Came / Paid", lost: "Lost" };

const RESULT_CHIPS: { value: Exclude<InboundResult, "none">; label: string; on: string; off: string }[] = [
  { value: "booked", label: "Booked", on: "bg-[#3538cd] text-white", off: "bg-[#eef4ff] text-[#3538cd] hover:bg-[#e0eaff]" },
  { value: "paid", label: "Came / Paid", on: "bg-[#067647] text-white", off: "bg-[#ecfdf3] text-[#067647] hover:bg-[#dcfae6]" },
  { value: "lost", label: "Lost", on: "bg-[#475467] text-white", off: "bg-[#f2f4f7] text-[#475467] hover:bg-[#e4e7ec]" },
];

const SEGMENT_PILL: Record<string, { label: string; className: string }> = {
  A: { label: "Hot", className: "bg-[#fef6ee] text-[#b93815]" },
  B: { label: "Warm", className: "bg-[#fffaeb] text-[#b54708]" },
  C: { label: "Cold", className: "bg-[#eff8ff] text-[#175cd3]" },
  D: { label: "Not interested", className: "bg-[#f2f4f7] text-[#475467]" },
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function istDate(daysBack: number): string {
  const d = new Date(Date.now() - (daysBack - 1) * 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(d); // YYYY-MM-DD
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  const sameYear = new Intl.DateTimeFormat("en-IN", { year: "numeric", timeZone: TZ }).format(d)
    === new Intl.DateTimeFormat("en-IN", { year: "numeric", timeZone: TZ }).format(new Date());
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }), timeZone: TZ });
}

function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: TZ,
  });
}

/** "12m", "3h", "2d" since a moment. */
function waitedFor(iso: string, now: number): string {
  const mins = Math.max(1, Math.round((now - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function displayName(lead: InboundLead): string {
  return lead.name && lead.name !== "—" ? lead.name : lead.phone;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter((p) => /\w/.test(p));
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "#";
}


// ─── Cells ───────────────────────────────────────────────────────────────────

function SegmentPill({ segment }: { segment: string }) {
  const s = SEGMENT_PILL[segment];
  if (!s) return null;
  return <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", s.className)}>{s.label}</span>;
}

/** What they want (saved by the AI agent from the chat, or a form answer), in place of the latest message. */
function WantsCell({ lead }: { lead: InboundLead }) {
  if (!lead.wants) return <span className="text-xs text-[#94a3b8]">Not said yet</span>;
  return <p className="line-clamp-2 text-[13px] font-medium leading-snug text-[#334155]" title={lead.wants}>{lead.wants}</p>;
}

/** `onOpen` / `onUndo` make "Set result", the order and Undo buttons; leave them out inside another button (phone cards). */
function ResultCell({ lead, labels, onOpen, onUndo }: {
  lead: InboundLead; labels: InboundResultLabels; onOpen?: () => void; onUndo?: () => void;
}) {
  if (lead.result === "paid") {
    return (
      <div className="space-y-1">
        <span className="inline-flex items-center gap-1 rounded-full bg-[#ecfdf3] px-2.5 py-0.5 text-xs font-semibold text-[#067647]">
          <CheckCircle2 size={12} aria-hidden /> {labels.paid}
        </span>
        {lead.order && (onOpen ? (
          <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(); }}
            className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
            <Receipt size={12} aria-hidden /> Order{lead.order.number ? ` #${lead.order.number}` : ""} · {rupees(lead.order.total_paise)}
          </button>
        ) : (
          <span className="flex items-center gap-1 text-xs font-semibold text-primary">
            <Receipt size={12} aria-hidden /> Order{lead.order.number ? ` #${lead.order.number}` : ""} · {rupees(lead.order.total_paise)}
          </span>
        ))}
      </div>
    );
  }
  if (lead.result === "booked") {
    return (
      <div className="space-y-1">
        <span className="inline-flex items-center gap-1 rounded-full bg-[#eef4ff] px-2.5 py-0.5 text-xs font-semibold text-[#3538cd]">
          <CalendarCheck size={12} aria-hidden /> {labels.booked}
        </span>
        {lead.booked_for && <p className="text-xs text-[#64748b]">for {dateTime(lead.booked_for)}</p>}
      </div>
    );
  }
  if (lead.result === "lost") {
    return (
      <div className="space-y-1">
        <span className="inline-flex items-center gap-1 rounded-full bg-[#f2f4f7] px-2.5 py-0.5 text-xs font-semibold text-[#475467]">
          {labels.lost}
          {lead.lost_auto && <span className="rounded bg-white px-1 text-[10px] font-bold uppercase tracking-wide text-[#64748b]" title="Anril marked this by itself">auto</span>}
        </span>
        {lead.lost_reason && <p className="line-clamp-1 text-xs text-[#64748b]">{lead.lost_reason}</p>}
        {lead.lost_auto && onUndo && (
          <button type="button" onClick={(e) => { e.stopPropagation(); onUndo(); }}
            className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
            <Undo2 size={12} aria-hidden /> Undo
          </button>
        )}
      </div>
    );
  }
  if (!onOpen) {
    return <span className="rounded-full border border-dashed border-[#cbd5e1] px-2.5 py-0.5 text-xs font-semibold text-[#64748b]">No result yet</span>;
  }
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(); }}
      className="rounded-full border border-dashed border-[#cbd5e1] px-2.5 py-0.5 text-xs font-semibold text-[#64748b] hover:border-primary hover:text-primary">
      Set result
    </button>
  );
}

function HandledBy({ lead }: { lead: InboundLead }) {
  const h = lead.handled_by;
  if (h.kind === "ai") {
    return <span className="inline-flex items-center gap-1 text-xs text-[#475467]"><Bot size={13} aria-hidden /> AI agent</span>;
  }
  if (h.kind === "person") {
    return <span className="inline-flex items-center gap-1 text-xs text-[#475467]"><UserRound size={13} aria-hidden /> {h.name}</span>;
  }
  return <span className="inline-flex items-center gap-1 text-xs font-semibold text-[#b42318]"><AlertCircle size={13} aria-hidden /> Nobody</span>;
}

function CameFrom({ lead }: { lead: InboundLead }) {
  const ad = lead.ad_name || (lead.campaign_name !== "—" ? lead.campaign_name : null);
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5 text-[13px] font-semibold text-[#0A1528]">
        <span className={cn("h-2 w-2 shrink-0 rounded-full", CHANNEL_DOT[lead.source] ?? "bg-slate-400")} aria-hidden />
        {lead.channel_label}
      </p>
      <p className="truncate text-xs text-[#64748b]" title={ad ?? undefined}>
        {ad ? `Ad · ${ad}` : lead.origin === "ad" ? "From an ad" : "No ad"} · {shortDate(lead.created_at)}
      </p>
    </div>
  );
}

function ReplyCell({ lead, now }: { lead: InboundLead; now: number }) {
  if (lead.waiting_since) {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-[#fffaeb] px-2.5 py-0.5 text-xs font-semibold text-[#b54708]">
        <Clock size={12} aria-hidden /> Waiting {waitedFor(lead.waiting_since, now)}
      </span>
    );
  }
  if (lead.last_message) {
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-[#ecfdf3] px-2.5 py-0.5 text-xs font-semibold text-[#067647]">
        <Check size={12} aria-hidden /> Answered
      </span>
    );
  }
  return <span className="text-xs text-[#94a3b8]">—</span>;
}

function Chip({ active, onClick, label, count, on, off }: {
  active: boolean; onClick: () => void; label: string; count: number | undefined; on: string; off: string;
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-colors", active ? on : off)}>
      {label}
      <span className={cn("tabular-nums", active ? "opacity-90" : "opacity-80")}>{count ?? "–"}</span>
    </button>
  );
}

function RenameSteps({ labels, onSaved }: { labels: InboundResultLabels; onSaved: (l: InboundResultLabels) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(labels);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const saved = await api.inboundLeads.saveResultLabels({
        booked: draft.booked.trim(), paid: draft.paid.trim(), lost: draft.lost.trim(),
      });
      onSaved(saved);
      setOpen(false);
      toast.success("Step names saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the names");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="relative">
      <button type="button" onClick={() => { setDraft(labels); setOpen(!open); }} aria-expanded={open}
        className="flex items-center gap-1 text-xs font-semibold text-primary hover:opacity-80">
        <Pencil size={12} aria-hidden /> Rename steps
      </button>
      {open && (
        <form onSubmit={(e) => { e.preventDefault(); void save(); }}
          className="absolute right-0 top-full z-30 mt-2 w-[300px] space-y-2.5 rounded-xl border border-[#e2e8f0] bg-white p-4 shadow-lg">
          <p className="text-xs font-bold text-[#0A1528]">Name the steps your way</p>
          <p className="text-xs text-[#64748b]">For example &quot;Site visit booked&quot; and &quot;Advance paid&quot;. Only the names change.</p>
          {([["booked", "First step"], ["paid", "Done step"], ["lost", "Lost step"]] as const).map(([key, hint]) => (
            <label key={key} className="block">
              <span className="text-[11px] font-semibold text-[#64748b]">{hint}</span>
              <input value={draft[key]} maxLength={30} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                className="mt-0.5 w-full rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20" />
            </label>
          ))}
          <div className="flex gap-2 pt-1">
            <button type="submit" disabled={saving || !draft.booked.trim() || !draft.paid.trim() || !draft.lost.trim()}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white disabled:opacity-40">
              {saving ? "Saving…" : "Save"}
            </button>
            <button type="button" onClick={() => setDraft(DEFAULT_LABELS)} className="px-2 text-xs font-semibold text-[#64748b] hover:text-[#0A1528]">
              Back to defaults
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

// ─── Drawer: one lead, with the same actions as Chats ────────────────────────

/** "AI agent is replying · I'll take over": turns the AI off for this chat so you reply yourself. */
function TakeOverBar({ lead, onChange }: { lead: Lead; onChange: (updated: Lead) => void }) {
  const [busy, setBusy] = useState(false);
  const aiOn = lead.ai_enabled !== false;
  async function flip() {
    setBusy(true);
    try {
      const updated = await api.leads.toggleAI(lead.id, !aiOn);
      onChange({ ...lead, ...updated, ai_enabled: !aiOn });
      toast.success(aiOn ? "You're replying now. The AI agent is off for this chat." : "The AI agent is replying again");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't change that");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={cn("flex items-center gap-3 border-b px-4 py-2.5",
      aiOn ? "border-primary/15 bg-primary-light/50" : "border-[#fedf89] bg-[#fffaeb]")}>
      <p className="min-w-0 flex-1 text-[12.5px] text-[#334155]">
        {aiOn
          ? <><span className="font-bold text-primary">✦ AI agent is replying</span> · turn it off to reply yourself</>
          : <><span className="font-bold text-[#b54708]">You&apos;re replying</span> · the AI agent is off for this chat</>}
      </p>
      <button type="button" onClick={() => void flip()} disabled={busy}
        className={cn("shrink-0 rounded-lg px-3 py-1.5 text-xs font-bold disabled:opacity-50",
          aiOn ? "border border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-slate-50" : "text-primary hover:bg-primary/5")}>
        {busy ? "Saving…" : aiOn ? "✋ I'll take over" : "Hand back to AI"}
      </button>
    </div>
  );
}

function LeadDrawer({ leadId, row, team, onClose, onChanged }: {
  leadId: string;
  row: InboundLead | undefined;
  team: Option[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [lead, setLead] = useState<Lead | null>(null);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState<"chat" | "details">("chat");

  useEffect(() => {
    let alive = true;
    setLead(null);
    setFailed(false);
    setView("chat");
    api.leads.get(leadId)
      .then((l) => { if (alive) setLead(l); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [leadId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const name = row ? displayName(row) : lead?.name || "Lead";

  // Portaled to <body> so no transformed parent can shift or clip the overlay.
  return createPortal(
    <div className="fixed inset-0 z-dialog flex justify-end bg-[#0A1528]/30" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label={`${name}: details`}
        className="flex h-full w-full max-w-[600px] flex-col bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start gap-3 border-b border-[#e2e8f0] p-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">
            {initials(name)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate font-display text-base font-bold text-[#0A1528]">
                <Link href={`/dashboard/leads/${leadId}`} title="Open this customer" className="hover:text-primary hover:underline">{name}</Link>
              </h2>
              {row && <SegmentPill segment={row.segment} />}
            </div>
            <p className="mt-0.5 truncate text-xs text-[#64748b]">
              {row ? `${row.channel_label}${row.ad_name ? ` · Ad · ${row.ad_name}` : ""} · came ${dateTime(row.created_at)}` : ""}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-50 hover:text-[#0A1528]">
            <X size={18} />
          </button>
        </header>

        {failed ? (
          <p className="p-4 text-xs text-[#b42318]">Couldn&apos;t load this lead. Close and try again.</p>
        ) : !lead ? (
          <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-xl bg-slate-100" />)}</div>
        ) : view === "details" ? (
          <div className="flex-1 overflow-y-auto">
            <button type="button" onClick={() => setView("chat")}
              className="m-3 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-bold text-primary hover:bg-primary/5">
              <ChevronLeft size={14} /> Back to the chat
            </button>
            {/* The Chats customer panel: Book a visit, Record payment, Not buying, orders, score. */}
            <div className="[&>div]:h-auto [&>div]:w-full [&>div]:overflow-visible [&>div]:border-l-0 [&>div>div:first-child]:hidden">
              <LeadDetailsPanel
                lead={lead}
                team={team}
                onCollapse={onClose}
                onLeadUpdate={(updated) => { setLead(updated); onChanged(); }}
              />
            </div>
          </div>
        ) : (
          <>
            <TakeOverBar lead={lead} onChange={(updated) => { setLead(updated); onChanged(); }} />
            {/* The real chat: every message, the reply box, templates and the free-reply time left. */}
            <div className="flex min-h-0 flex-1 flex-col">
              <ChatThread
                key={lead.id}
                lead={lead}
                team={team}
                onLeadUpdate={(updated) => { setLead(updated); onChanged(); }}
                detailsOpen={false}
                onToggleDetails={() => setView("details")}
              />
            </div>
          </>
        )}
      </aside>
    </div>,
    document.body,
  );
}

// ─── Google Ads link (unchanged) ─────────────────────────────────────────────

// Generates a tracked wa.me link for a Google Ads campaign CTA. The link carries
// a [GADS:<slug>] tag so inbound WhatsApp leads get attributed to Google.
function GoogleAdsLinkModal({ onClose }: { onClose: () => void }) {
  const [campaign, setCampaign] = useState("");
  const [link, setLink] = useState("");
  const [slug, setSlug] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleGenerate() {
    const name = campaign.trim();
    if (!name) {
      toast.error("Enter a campaign name first.");
      return;
    }
    setLoading(true);
    try {
      const res = await api.inboundLeads.googleLink(name);
      setLink(res.link);
      setSlug(res.campaign_slug);
      setCopied(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate link");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(link);
    setCopied(true);
    toast.success("Link copied — paste it into your Google ad");
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div
      className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-md rounded-3xl p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-primary-100 flex items-center justify-center">
              <Link2 size={16} className="text-primary-700" />
            </div>
            <div>
              <h3 className="font-display font-black text-on-surface text-base leading-tight">Google Ads Link</h3>
              <p className="text-[11px] text-on-surface-muted">Track WhatsApp leads from a Google campaign</p>
            </div>
          </div>
          <button onClick={onClose} className="text-[#94a3b8] hover:text-[#1e293b] transition-colors">
            <X size={18} />
          </button>
        </div>

        <label className="block font-label text-[10px] font-bold text-on-surface-muted uppercase tracking-wider mb-1.5">
          Campaign Name
        </label>
        <input
          value={campaign}
          onChange={(e) => setCampaign(e.target.value)}
          placeholder="e.g. Summer Sale 2026"
          className="w-full px-3 py-2 bg-surface-low border border-surface-mid rounded-xl font-body text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-300 mb-3"
        />

        <button
          onClick={handleGenerate}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-primary text-white rounded-xl font-label text-xs font-bold hover:bg-primary/90 transition-all disabled:opacity-40 shadow-sm"
        >
          <Link2 size={13} />
          <span>{loading ? "Generating…" : link ? "Regenerate" : "Generate Link"}</span>
        </button>

        {link && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-label text-[10px] font-bold text-on-surface-muted uppercase tracking-wider">Tracked Link</span>
              <span className="font-mono text-[10px] text-primary-700 bg-primary-50 px-1.5 py-0.5 rounded">[GADS:{slug}]</span>
            </div>
            <div className="flex items-stretch gap-2">
              <code className="flex-1 px-3 py-2 bg-surface-mid rounded-xl font-mono text-[11px] text-on-surface break-all leading-relaxed select-all">
                {link}
              </code>
              <button
                onClick={handleCopy}
                className="shrink-0 flex items-center justify-center px-3 rounded-xl bg-primary-600 text-white hover:bg-primary-700 transition-colors"
                title="Copy link"
              >
                {copied ? <Check size={15} /> : <Copy size={15} />}
              </button>
            </div>
            <p className="mt-3 text-[11px] text-on-surface-muted leading-relaxed">
              Paste this as the destination URL of your Google ad. Every click opens a
              pre-filled WhatsApp chat, and the reply is auto-tagged to this campaign in your dashboard.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}


// ─── Client UI Component ───────────────────────────────────────────────────────

interface InboundLeadsClientProps {
  fallbackInboundLeads: { data: InboundLead[]; total: number; page: number; limit: number } | null;
  /** From ?result= (Reports › Overview links here with "none"). */
  initialResult?: InboundResult;
}

export function InboundLeadsClient({ fallbackInboundLeads, initialResult }: InboundLeadsClientProps) {
  const router = useRouter();
  const [exporting, setExporting] = useState(false);
  const [showGoogleModal, setShowGoogleModal] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("all");
  const [origin, setOrigin] = useState("all");
  /** A customer tag, or "all". */
  const [tag, setTag] = useState("all");
  const [tagCounts, setTagCounts] = useState<TagCount[]>([]);
  const [startingFollowUp, setStartingFollowUp] = useState(false);
  /** One Meta ad (its Meta id), offered once "Ad: From an ad" is picked. */
  const [adId, setAdId] = useState("");
  const [added, setAdded] = useState("30");
  const [segment, setSegment] = useState<string | undefined>();
  const [result, setResult] = useState<InboundResult | undefined>(initialResult);
  const [waiting, setWaiting] = useState(false);
  const [tab, setTab] = useState<InboundTab>("all");
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<string | null>(null);
  const [team, setTeam] = useState<Option[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sendOpen, setSendOpen] = useState(false);
  const [audienceOpen, setAudienceOpen] = useState(false);
  const [audience, setAudience] = useState<{ leads: InboundLead[]; label: string } | null>(null);
  const [labels, setLabels] = useState<InboundResultLabels>(DEFAULT_LABELS);
  const { role, permissions } = useAuthRole();
  const canDownload = role === "owner" || permissions.includes("leads.download");
  const canManageLeads = role === "owner" || permissions.includes("leads.manage");

  useEffect(() => {
    tagsApi.list().then(setTagCounts).catch(() => {});
  }, []);

  useEffect(() => {
    api.inboundLeads.resultLabels().then(setLabels).catch(() => {});
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    api.callers.list()
      .then(({ data }) => setTeam(data.filter((c) => c.active !== false).map((c) => ({ value: c.id, label: c.name }))))
      .catch(() => {});
  }, []);

  // Everything except the chips: the counts on the chips use these.
  const baseFilters: InboundLeadFilters = useMemo(() => ({
    origin: origin === "all" ? undefined : (origin as "ad" | "organic"),
    source: source === "all" ? undefined : source,
    meta_ad_id: origin === "ad" ? adId || undefined : undefined,
    search: search || undefined,
    date_from: added === "any" ? undefined : istDate(Number(added)),
    tag: tag === "all" ? undefined : tag,
  }), [origin, source, adId, search, added, tag]);
  const filters: InboundLeadFilters = { ...baseFilters, segment, result, waiting: waiting || undefined };

  useEffect(() => { setPage(1); }, [origin, source, adId, search, added, tag, segment, result, waiting]);
  useEffect(() => { setSelected(new Set()); }, [origin, source, adId, search, added, tag, segment, result, waiting, page]);

  const isFirstView = page === 1 && !search && source === "all" && origin === "all" && !adId && added === "30" && tag === "all"
    && !segment && !result && !waiting;
  const { data, error, mutate, isValidating } = useInboundLeads(
    { ...filters, page, limit: PAGE_SIZE, sort: waiting ? "waiting" : "newest" },
    true,
    isFirstView ? fallbackInboundLeads ?? undefined : undefined,
  );
  const { data: summary, mutate: mutateSummary } = useInboundLeadsSummary(filters);
  const { data: adsData } = useInboundAds(origin === "ad");

  const leads = data?.data ?? [];
  const total = data?.total ?? 0;
  const loading = !data && !error;
  const ads = adsData ?? [];
  const hasFilters = !!(search || source !== "all" || origin !== "all" || adId || added !== "30" || tag !== "all" || segment || result || waiting);

  function clearFilters() {
    setSearchInput(""); setSearch(""); setSource("all"); setOrigin("all"); setAdId(""); setTag("all");
    setAdded("30"); setSegment(undefined); setResult(undefined); setWaiting(false);
  }

  function refresh() {
    void mutate();
    void mutateSummary();
  }

  async function handleExport() {
    setExporting(true);
    try {
      await api.inboundLeads.exportCsv(filters);
      toast.success("Downloaded the list on screen: inbound_leads.csv");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed");
    } finally {
      setExporting(false);
    }
  }

  const openRow = leads.find((l) => l.id === openId);
  const selectedRows = leads.filter((l) => selected.has(l.id));
  const allOnPage = leads.length > 0 && leads.every((l) => selected.has(l.id));

  function toggle(id: string, on: boolean) {
    const next = new Set(selected);
    if (on) next.add(id);
    else next.delete(id);
    setSelected(next);
  }

  /** The ticked people become a fixed "Picked" group, then Follow-ups opens with that group chosen. */
  async function startFollowUp() {
    if (selectedRows.length === 0 || startingFollowUp) return;
    setStartingFollowUp(true);
    try {
      const group = await savePickedPeopleAsGroup(selectedRows.map((l) => l.id));
      toast.success(`Saved ${selectedRows.length} ${selectedRows.length === 1 ? "person" : "people"} as "${group.name}"`);
      router.push(followUpHrefForGroup(group.id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the group");
      setStartingFollowUp(false);
    }
  }

  async function undoAutoLost(lead: InboundLead) {
    try {
      await api.chats.undoNotBuying(lead.id);
      toast.success(`${displayName(lead)} is back to no result. Anril won't mark them again for that follow-up.`);
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not undo");
    }
  }
  const bookedOrPaid = summary?.booked_or_paid ?? 0;
  const paid = summary?.results.paid ?? 0;
  const neverHadLeads = !loading && !error && total === 0 && !hasFilters && added === "30" && (summary?.total ?? 0) === 0;

  return (
    <div className="space-y-4">
      {/* ── Toolbar ─────────────────────────────────────────── */}
      <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-1.5 p-4">
          <div className="relative min-w-[160px] flex-1">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" aria-hidden />
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search name, number or ad"
              aria-label="Search inbound leads"
              className="h-9 w-full rounded-xl border border-[#e2e8f0] pl-9 pr-3 text-xs text-[#0A1528] placeholder:text-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <FilterMenu label="Came from" options={CAME_FROM_OPTIONS} value={source} onChange={(v) => setSource(v ?? "all")} />
          <FilterMenu label="Ad" options={ORIGIN_OPTIONS} value={origin} onChange={(v) => { setOrigin(v ?? "all"); setAdId(""); }} />
          {origin === "ad" && ads.length > 0 && (
            <Select
              size="sm"
              value={adId}
              onChange={setAdId}
              aria-label="Which ad"
              className="w-auto min-w-0 max-w-fit basis-[140px] grow gap-1.5 pl-2.5 pr-2 text-xs font-bold text-[#0A1528] [&>span>span]:min-w-0 [&>span>span]:overflow-hidden"
              options={[{ value: "", label: "All ads" }, ...ads.map((a) => ({ value: a.meta_ad_id, label: a.name }))]}
            />
          )}
          {tagCounts.length > 0 && (
            <FilterMenu
              label="Tag"
              options={[
                { value: "all", label: "All" },
                ...tagCounts.map((t) => ({ value: t.tag, label: t.count > 0 ? `${t.tag} (${t.count})` : t.tag })),
              ]}
              value={tag}
              onChange={(v) => setTag(v ?? "all")}
            />
          )}
          <FilterMenu label="Added" options={ADDED_OPTIONS} value={added} onChange={(v) => setAdded(v ?? "30")} />
          {hasFilters && (
            <button type="button" onClick={clearFilters} className="shrink-0 whitespace-nowrap px-1 text-xs font-semibold text-primary hover:opacity-70">
              Clear
            </button>
          )}
          <div className="ml-auto flex shrink-0 gap-1.5">
            <button type="button" onClick={refresh} title="Refresh" aria-label="Refresh"
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-[#f8fafc]">
              <RefreshCw size={14} className={cn(isValidating && "animate-spin")} />
            </button>
            <button type="button" onClick={() => setShowGoogleModal(true)} title="Make a tracked WhatsApp link for a Google ad" aria-label="Google Ads link"
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-[#f8fafc]">
              <Link2 size={14} />
            </button>
            <button type="button" onClick={() => setAudienceOpen(true)}
              className="flex h-9 items-center gap-1.5 rounded-xl border border-primary bg-white px-3 text-xs font-bold text-primary hover:bg-primary/5">
              <MessageSquare size={13} /> Send template
            </button>
            {canDownload && (
              <button type="button" onClick={handleExport} disabled={exporting || total === 0} title="Download the list on screen" aria-label="Download"
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-[#f8fafc] disabled:opacity-40">
                <Download size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Interest and Result chips, each with its count */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[#f1f5f9] px-4 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-semibold text-[#64748b]">Interest</span>
            {INTEREST_CHIPS.map((c) => (
              <Chip key={c.value} active={segment === c.value} onClick={() => setSegment(segment === c.value ? undefined : c.value)}
                label={c.label} count={summary?.segments[c.value]} on={c.on} off={c.off} />
            ))}
          </div>
          <span className="hidden h-5 w-px bg-[#e2e8f0] sm:block" aria-hidden />
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-semibold text-[#64748b]">Result</span>
            {RESULT_CHIPS.map((c, i) => (
              <span key={c.value} className="inline-flex items-center gap-1.5">
                {i === 1 && <ChevronRight size={12} className="text-[#94a3b8]" aria-hidden />}
                <Chip active={result === c.value} onClick={() => setResult(result === c.value ? undefined : c.value)}
                  label={labels[c.value]} count={summary?.results[c.value]} on={c.on} off={c.off} />
              </span>
            ))}
          </div>
          {role === "owner" && <div className="ml-auto"><RenameSteps labels={labels} onSaved={setLabels} /></div>}
        </div>
      </div>

      <InboundTabs tab={tab} onChange={setTab} />
      {tab === "all" && <MoneyTodayCards />}

      {/* ── Cards ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-[#e2e8f0] bg-white px-5 py-4 shadow-sm">
          <p className="text-xs font-semibold text-[#64748b]">Leads in this view</p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-[#0A1528]">{summary ? summary.total.toLocaleString("en-IN") : "–"}</p>
          <p className="mt-0.5 text-xs text-[#64748b]">{added === "any" ? "all time" : ADDED_OPTIONS.find((o) => o.value === added)?.label.toLowerCase()}</p>
        </div>
        <button type="button" onClick={() => setWaiting(!waiting)} aria-pressed={waiting}
          className={cn("rounded-2xl border px-5 py-4 text-left shadow-sm transition-colors",
            waiting ? "border-[#fdb022] bg-[#fffaeb]" : "border-[#e2e8f0] bg-white hover:border-[#fedf89]")}>
          <p className="text-xs font-semibold text-[#64748b]">Waiting for your reply</p>
          <p className={cn("mt-1 text-2xl font-bold tabular-nums", (summary?.waiting ?? 0) > 0 ? "text-[#b54708]" : "text-[#0A1528]")}>
            {summary ? summary.waiting.toLocaleString("en-IN") : "–"}
          </p>
          <p className="mt-0.5 text-xs text-[#64748b]">{waiting ? "showing these, longest wait first · tap to show all" : "their message is the latest · tap to see them"}</p>
        </button>
        <div className="rounded-2xl border border-[#e2e8f0] bg-white px-5 py-4 shadow-sm">
          <p className="text-xs font-semibold text-[#64748b]">{labels.booked} → {labels.paid.toLowerCase()}</p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-[#0A1528]">
            {summary ? <>{bookedOrPaid.toLocaleString("en-IN")} <span className="text-[#94a3b8]">→</span> <span className="text-[#067647]">{paid.toLocaleString("en-IN")}</span></> : "–"}
          </p>
          <p className="mt-0.5 text-xs text-[#64748b]">
            {bookedOrPaid > 0 ? `${Math.round((paid / bookedOrPaid) * 100)}% reached ${labels.paid.toLowerCase()}` : "nobody booked yet in this view"}
          </p>
        </div>
      </div>

      {/* ── Table ───────────────────────────────────────────── */}
      {tab !== "all" ? (
        <InsightsList tab={tab} filters={filters} onPick={(text) => { setSearchInput(text); setTab("all"); }} />
      ) : (
      <div className="overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 bg-[#0A1528] px-4 py-2.5 text-white">
            <span className="text-xs font-bold">{selected.size} selected</span>
            <button type="button" onClick={() => setSendOpen(true)}
              className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20">
              <MessageSquare size={12} /> Send message or template
            </button>
            <button type="button" onClick={() => void startFollowUp()} disabled={startingFollowUp || !canManageLeads}
              title={canManageLeads
                ? "Saves these people as a group and opens Follow-ups with it picked"
                : "You need permission to manage customers"}
              className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50">
              <Repeat size={12} /> {startingFollowUp ? "Saving…" : "Start a follow-up"}
            </button>
            <button type="button" onClick={() => setSelected(new Set())} className="ml-auto text-xs font-semibold text-white/70 hover:text-white">
              Clear
            </button>
          </div>
        )}
        {error && !data ? (
          <div className="px-6 py-12 text-center">
            <p className="text-sm font-semibold text-[#0A1528]">Couldn&apos;t load inbound leads.</p>
            <p className="mt-1 text-xs text-[#64748b]">Nothing is lost. Check your connection and try again.</p>
            <button type="button" onClick={refresh} className="mt-4 rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white">Try again</button>
          </div>
        ) : neverHadLeads ? (
          <div className="px-6 py-14 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary"><Inbox size={22} /></div>
            <h3 className="mt-4 font-display text-lg font-bold text-[#0A1528]">No leads in the last 30 days</h3>
            <p className="mx-auto mt-1 max-w-lg text-sm text-[#64748b]">
              When someone messages you on WhatsApp, Instagram or Facebook, or fills an Instant form, they show here and the AI agent replies straight away. Nobody has to add them by hand.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <button type="button" onClick={() => setAdded("any")} className="rounded-xl border border-[#e2e8f0] bg-white px-3.5 py-2 text-xs font-bold text-[#0A1528] hover:bg-slate-50">
                Show all time
              </button>
              <button type="button" onClick={() => router.push("/dashboard/channels")} className="rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white hover:bg-primary-dark">
                Check connected channels
              </button>
            </div>
          </div>
        ) : !loading && leads.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-sm font-semibold text-[#0A1528]">No leads match these filters.</p>
            <button type="button" onClick={clearFilters} className="mt-2 text-xs font-semibold text-primary hover:opacity-70">Clear filters</button>
          </div>
        ) : (
          <>
            {/* Desktop */}
            <div className="hidden overflow-x-auto lg:block">
              <table className="w-full min-w-[1080px]">
                <thead>
                  <tr className="border-b border-[#f1f5f9] bg-[#f8fafc]">
                    <th className="w-10 py-3 pl-4">
                      <CheckTick checked={allOnPage} indeterminate={selected.size > 0 && !allOnPage}
                        onChange={(on) => setSelected(on ? new Set(leads.map((l) => l.id)) : new Set())}
                        aria-label="Select everyone on this page" />
                    </th>
                    {["Customer", "Wants", "Result", "Handled by", "Came from", "Reply", ""].map((h, i) => (
                      <th key={i} className={cn("px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]", i === 6 && "text-right")}>
                        {h || <span className="sr-only">Actions</span>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading
                    ? Array.from({ length: 6 }).map((_, i) => (
                      <tr key={i} className="border-t border-[#f1f5f9]">
                        {Array.from({ length: 8 }).map((__, j) => <td key={j} className="px-4 py-4"><div className="h-4 animate-pulse rounded bg-slate-100" /></td>)}
                      </tr>
                    ))
                    : leads.map((lead) => (
                      <tr key={lead.id} onClick={() => setOpenId(lead.id)}
                        className={cn("cursor-pointer border-t border-[#f1f5f9] transition-colors hover:bg-[#f8fafc]",
                          lead.waiting_since && "bg-[#fffcf5]", selected.has(lead.id) && "bg-primary/5")}>
                        <td className="w-10 py-3 pl-4" onClick={(e) => e.stopPropagation()}>
                          <CheckTick checked={selected.has(lead.id)} onChange={(on) => toggle(lead.id, on)}
                            aria-label={`Select ${displayName(lead)}`} />
                        </td>
                        <td className="max-w-[240px] px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-bold text-[#0A1528]">{displayName(lead)}</span>
                            <SegmentPill segment={lead.segment} />
                          </div>
                          <p className="truncate text-xs text-[#64748b]">
                            {[lead.business, lead.city].filter(Boolean).join(" · ") || lead.phone}
                          </p>
                        </td>
                        <td className="max-w-[280px] px-4 py-3"><WantsCell lead={lead} /></td>
                        <td className="px-4 py-3">
                          <ResultCell lead={lead} labels={labels} onOpen={() => setOpenId(lead.id)} onUndo={() => void undoAutoLost(lead)} />
                        </td>
                        <td className="px-4 py-3"><HandledBy lead={lead} /></td>
                        <td className="max-w-[220px] px-4 py-3"><CameFrom lead={lead} /></td>
                        <td className="px-4 py-3"><ReplyCell lead={lead} now={now} /></td>
                        <td className="px-4 py-3 text-right">
                          <button type="button"
                            onClick={(e) => { e.stopPropagation(); router.push(`/dashboard/conversations?lead=${lead.id}`); }}
                            className={cn("whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-bold",
                              lead.waiting_since ? "bg-primary text-white hover:bg-primary-dark" : "border border-[#e2e8f0] text-[#0A1528] hover:bg-slate-50")}>
                            {lead.waiting_since ? "Reply" : "Open chat"}
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>

            {/* Phone and tablet */}
            <ul className="divide-y divide-[#f1f5f9] lg:hidden">
              {loading
                ? Array.from({ length: 4 }).map((_, i) => <li key={i} className="p-4"><div className="h-16 animate-pulse rounded-xl bg-slate-100" /></li>)
                : leads.map((lead) => (
                  <li key={lead.id}>
                    <button type="button" onClick={() => setOpenId(lead.id)}
                      className={cn("w-full space-y-2 p-4 text-left", lead.waiting_since && "bg-[#fffcf5]")}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-sm font-bold text-[#0A1528]">{displayName(lead)}</span>
                            <SegmentPill segment={lead.segment} />
                          </div>
                          <p className="truncate text-xs text-[#64748b]">{lead.channel_label} · {shortDate(lead.created_at)}</p>
                        </div>
                        <ReplyCell lead={lead} now={now} />
                      </div>
                      <WantsCell lead={lead} />
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <ResultCell lead={lead} labels={labels} />
                        <HandledBy lead={lead} />
                      </div>
                    </button>
                  </li>
                ))}
            </ul>

            <Pagination page={page} total={total} onPageChange={setPage} noun="people" />
          </>
        )}
      </div>
      )}

      {openId && (
        <LeadDrawer
          leadId={openId}
          row={openRow}
          team={team}
          onClose={() => { setOpenId(null); refresh(); }}
          onChanged={refresh}
        />
      )}
      {showGoogleModal && <GoogleAdsLinkModal onClose={() => setShowGoogleModal(false)} />}
      {audienceOpen && (
        <SendTemplateAudience
          base={baseFilters}
          onClose={() => setAudienceOpen(false)}
          onNext={(people, label) => { setAudienceOpen(false); setAudience({ leads: people, label }); }}
        />
      )}
      {audience && (
        <SendMessageModal
          selectedLeads={audience.leads.map((l) => ({ id: l.id, name: l.name === "—" ? null : l.name, last_inbound_at: l.last_inbound_at }))}
          batchLabel={audience.label}
          startWithTemplate
          onClose={() => setAudience(null)}
          onAfterSend={() => { setAudience(null); refresh(); }}
        />
      )}
      {sendOpen && selectedRows.length > 0 && (
        <SendMessageModal
          selectedLeads={selectedRows.map((l) => ({ id: l.id, name: l.name === "—" ? null : l.name, last_inbound_at: l.last_inbound_at }))}
          batchLabel="Inbound leads"
          onClose={() => setSendOpen(false)}
          onAfterSend={() => { setSendOpen(false); setSelected(new Set()); refresh(); }}
        />
      )}
    </div>
  );
}
