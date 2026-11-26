"use client";
import { toast } from "sonner";
import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Upload, Check, AlertTriangle, ChevronRight, ChevronDown, RotateCcw, MessageSquare, Clock, Send, Download, CheckCircle2, BarChart3, Eye, XCircle, Calendar, Phone, Search, Smartphone, ShieldCheck, FileSpreadsheet, PlayCircle, MapPin, Copy, Globe, Image as ImageIcon, FileText, Tag, Plus, Trash2, RefreshCw, Info, Sparkles, Users } from "lucide-react";
import { API_URL, api, getAuthHeaders, type CustomerGroup } from "@/lib/api";
import { convertScanToCsv } from "@/lib/scanUpload";
import { timeLeftText } from "./reachSchedule";
import { checkRow, parseScanCsv, rowsToCsv, type ScanRow } from "@/lib/scanReview";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { usePolling } from "@/hooks/usePolling";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { Loader2 } from "lucide-react";
import { TickMark } from "@/components/ui/controls";
import { Select } from "@/components/ui/Select";
import { NO_REACH_OFFER, ReachOfferBox, reachOfferPayload, reachOfferProblem, type ReachOfferDraft } from "./ReachOfferBox";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { CampaignResultsDrawer } from "./CampaignResultsDrawer";
import { SCHEDULE_HOURS_NOTE, dripTimeProblem, scheduleChoices, scheduleProblem } from "./reachSchedule";

// ─── Types ────────────────────────────────────────────────────────────────────

type ParsedData = {
  columns: string[];
  suggested_mapping: { name: string | null; phone: string | null; email: string | null; course: string | null };
  total_rows: number;
  // Different valid numbers in the file; bulk-send messages each number once.
  unique_phone_count?: number;
  duplicate_count: number;
  preview: Record<string, string>[];
  csv_file_url: string | null;
  csv_file_path: string | null;
  csv_file_name: string | null;
};

type OptInValidation = {
  allowed: boolean;
  template_type: string;
  message: string;
};

type SendResult = {
  queued: number;
  failed: number;
  opted_out_skipped: number;
  number_used: string;
  // People left out at send time: they already got the monthly limit of offers, or are blocked.
  skipped_monthly_limit?: number;
  skipped_blocked?: number;
};

// Who a campaign would reach, from POST /upload/reach-preview.
type ReachPreview = {
  audience: "group" | "list";
  group: { id: string; name: string; kind: string; members: number } | null;
  in_audience: number;
  said_stop: number;
  no_opt_in: number;
  no_number: number;
  blocked: number;
  negative_reply: number;
  over_cap: number;
  will_get: number;
  monthly_limit: number;
  rate_inr: number;
  cost_inr: number;
};

type ScheduleResult = {
  status: "scheduled" | "drip_scheduled";
  total: number;
  fire_at?: string;
  batches?: number;
};

type QueuedResult = {
  status: "queued";
  broadcast_id: string;
  total: number;
};

type BroadcastHistoryItem = {
  timestamp: string;
  broadcast_id?: string;
  template_name: string;
  opt_in_source: string;
  sent: number;
  delivered: number;
  opened: number;
  failed: number;
  total_leads: number;
  number_used: string;
  csv_file_url?: string;
  csv_file_path?: string;
  csv_file_name?: string;
  tag_id?: string;
  tag_name?: string;
  hot?: number;
  warm?: number;
  cold?: number;
  replied_positive?: number;
  replied_negative?: number;
  replied_neutral?: number;
  // "group" when the campaign went to a Customers group; group_name is that group's name.
  audience_type?: "list" | "group";
  group_name?: string;
  // People left out when it went out: already got the monthly limit of offers, or blocked.
  skipped_monthly_limit?: number;
  skipped_blocked?: number;
  // Paid within 7 days of the send. paid_amount_inr is missing without the deals.view permission.
  paid_count?: number | null;
  paid_amount_inr?: number | null;
  paid_window_open?: boolean;
  // People who said stop after it. back_per_rupee (estimated, deals.view only): rupees paid per rupee of message cost.
  said_stop?: number;
  back_per_rupee?: number | null;
};

type BroadcastTag = {
  id: string;
  name: string;
  color: string;
  created_at: string;
};

type OptedOutLead = {
  lead_id: string;
  phone: string | null;
  name: string | null;
  opted_out_at: string | null;
  scope: "global" | "tag";
  tag_id: string | null;
  tag_name: string | null;
  // How they stopped (stop_reply / chat_ai / call / staff), and the last campaign sent to them before it.
  source?: string | null;
  last_campaign?: string | null;
  last_campaign_at?: string | null;
};

const STOP_HOW: Record<string, string> = {
  stop_reply: "Replied STOP",
  chat_ai: "Said no in chat",
  call: "Asked on a call",
  staff: "Added by staff",
};

const istDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true });
const istDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" });

type TagStats = {
  tag_id: string;
  total_sent: number;
  hot: number;
  warm: number;
  cold: number;
  disqualified: number;
  opted_out: number;
  failed: number;
};

const PRESET_COLORS = [
  "#FFFFFF", "#FBBF24", "#22C55E", "#EF4444", "#3B82F6",
  "#F97316", "var(--primary-500)", "#1F2937", "#EC4899", "#14B8A6",
  "#6366F1", "#84CC16",
];

function getTagStyle(hex: string): { background: string; colorClass: string } {
  const hexUpper = (hex || "").toUpperCase();
  const styles: Record<string, { bg: string, text: string }> = {
    "#FFFFFF": { bg: "linear-gradient(135deg, #f8f9fa, #e9ecef)", text: "text-gray-800" },
    "#FBBF24": { bg: "linear-gradient(135deg, #FDE68A, #F59E0B)", text: "text-yellow-900" },
    "#22C55E": { bg: "linear-gradient(135deg, #4ADE80, #16A34A)", text: "text-white" },
    "#EF4444": { bg: "linear-gradient(135deg, #F87171, #DC2626)", text: "text-white" },
    "#3B82F6": { bg: "linear-gradient(135deg, #60A5FA, #2563EB)", text: "text-white" },
    "#F97316": { bg: "linear-gradient(135deg, #FDBA74, #EA580C)", text: "text-white" },
    "var(--primary-500)": { bg: "linear-gradient(135deg, var(--primary-400), var(--primary-600))", text: "text-white" },
    "#1F2937": { bg: "linear-gradient(135deg, #4B5563, #111827)", text: "text-white" },
    "#EC4899": { bg: "linear-gradient(135deg, #F472B6, #DB2777)", text: "text-white" },
    "#14B8A6": { bg: "linear-gradient(135deg, #2DD4BF, #0D9488)", text: "text-white" },
    "#6366F1": { bg: "linear-gradient(135deg, #818CF8, #4F46E5)", text: "text-white" },
    "#84CC16": { bg: "linear-gradient(135deg, #A3E635, #65A30D)", text: "text-white" },
  };

  if (styles[hexUpper]) {
    return { background: styles[hexUpper].bg, colorClass: styles[hexUpper].text };
  }

  if (!hex || hex.length < 7) {
    return { background: "linear-gradient(135deg, #f8f9fa, #e9ecef)", colorClass: "text-gray-800" };
  }

  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const r2 = Math.max(0, r - 40);
  const g2 = Math.max(0, g - 40);
  const b2 = Math.max(0, b - 40);
  
  const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return {
    background: `linear-gradient(135deg, ${hex}, rgb(${r2}, ${g2}, ${b2}))`,
    colorClass: luma > 180 ? "text-gray-900" : "text-white"
  };
}

// A sender line as returned by GET /api/v1/numbers.
type SenderRow = {
  id: string;
  number: string;
  display_name: string;
  role: "primary" | "standby" | "archived";
  status: string;
  quality_rating: "green" | "yellow" | "red" | null;
  messaging_tier: number | null;
  paused_outbound: boolean;
  locked: boolean;
  health?: {
    state: "archived" | "meta_pending" | "resting" | "warming" | "active";
    meta_status?: string | null;
    meta_code_verification?: string | null;
    warm_up_day?: number | null;
    warm_up_days?: number | null;
    rest_day?: number | null;
    rest_days?: number | null;
    broadcast_cap: number | null;
    // Meta's measure: people sent a template outside their 24h window, last 24 hours.
    sent_24h?: number;
  };
};

function canBroadcast(r: SenderRow): boolean {
  const cap = r.health?.broadcast_cap;
  return (
    (r.health?.state === "active" || r.health?.state === "warming") &&
    !r.paused_outbound &&
    r.quality_rating !== "red" &&
    !r.locked &&
    cap != null &&
    (r.health?.sent_24h ?? 0) < cap
  );
}

const BROADCAST_SHARE_OF_LIMIT = 0.9;

// Mirrors the backend's sender choice: primary first, then green quality,
// then the least-used line relative to its cap. Also enforces the shared
// portfolio limit across all non-archived lines.
function pickSender(rows: SenderRow[]): {
  sender: SenderRow | null;
  primary: SenderRow | null;
  leftToday: number;
} {
  const live = rows.filter(r => r.role !== "archived");
  const tiers = live.map(r => r.messaging_tier).filter((t): t is number => t != null);
  // Broadcasts stop at 90% of Meta's limit, leaving room for templates sent
  // outside Anril (backend: outbound_router.BROADCAST_SHARE_OF_LIMIT).
  const portfolioLimit = tiers.length > 0 ? Math.floor(Math.max(...tiers) * BROADCAST_SHARE_OF_LIMIT) : null;
  const poolUsed = live.reduce((sum, r) => sum + (r.health?.sent_24h ?? 0), 0);
  const primary = rows.find(r => r.role === "primary") ?? null;

  const poolOpen = portfolioLimit !== null && poolUsed < portfolioLimit;
  const candidates = poolOpen
    ? rows.filter(canBroadcast).sort((a, b) => {
        const byPrimary = (a.role === "primary" ? 0 : 1) - (b.role === "primary" ? 0 : 1);
        if (byPrimary !== 0) return byPrimary;
        const byQuality = (a.quality_rating === "green" ? 0 : 1) - (b.quality_rating === "green" ? 0 : 1);
        if (byQuality !== 0) return byQuality;
        const loadA = (a.health?.sent_24h ?? 0) / (a.health?.broadcast_cap ?? 1);
        const loadB = (b.health?.sent_24h ?? 0) / (b.health?.broadcast_cap ?? 1);
        return loadA - loadB;
      })
    : [];

  const sender = candidates[0] ?? null;
  const cap = sender?.health?.broadcast_cap;
  const leftToday =
    sender && cap != null && portfolioLimit !== null
      ? Math.min(cap - (sender.health?.sent_24h ?? 0), portfolioLimit - poolUsed)
      : 0;

  return { sender, primary, leftToday };
}

const UNLIMITED_DAILY = 1000000;

function formatDaily(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= UNLIMITED_DAILY) return "Unlimited";
  return `${n.toLocaleString()} / day`;
}

// Highest {{n}} index used in a template body; 0 when it has no variables.
function templateVarCount(body?: string | null): number {
  const found = (body ?? "").match(/\{\{(\d+)\}\}/g) ?? [];
  return found.reduce((max, tok) => Math.max(max, Number(tok.slice(2, -2))), 0);
}

type ScheduleType = "now" | "scheduled" | "drip";

type Button = {
  type: "QUICK_REPLY" | "URL" | "PHONE_NUMBER" | "WHATSAPP_CALL" | "COPY_CODE";
  text: string;
  url?: string;
  phone?: string;
  country?: string;
  offer_code?: string;
  active_for_days?: number;
};

type Template = {
  id: string;
  name: string;
  category: string;
  body_text: string;
  header_text?: string | null;
  header_media_type?: string | null;
  header_media_url?: string | null;
  header_media_id?: string | null;
  footer_text?: string | null;
  buttons?: Button[] | null;
  status: string;
};

// v9.2 #115: four plain answers instead of six jargon ones. Values stay inside the leads.opt_in_source
// CHECK list (migration 117), so the backend rules and stored data are unchanged. "Not sure" counts as no.
const OPT_IN_OPTIONS: { value: string; label: string; description: string }[] = [
  { value: "website_form", label: "They asked us to WhatsApp them", description: "A form, a sign-up or our WhatsApp ad where they said yes to messages. Offers and updates are fine." },
  { value: "previous_enquiry", label: "They bought from us or asked us before", description: "Past customers and people who enquired. Best for updates and reminders." },
  { value: "offline_event", label: "They agreed in person", description: "At the shop, an event or on a signed form. Best for updates and reminders." },
  { value: "manual", label: "Not sure", description: "If you're not sure they agreed, treat it as no. Call them instead of messaging." },
];

const OPT_IN_RESULT: Record<string, string> = {
  marketing: "You can send offers and updates to this list.",
  utility: "Best for updates and reminders. Offers to people who only enquired get more of them saying stop.",
  blocked: "Don't WhatsApp people who haven't agreed — they report you and WhatsApp lowers your number's quality. Call them instead.",
};

// ─── Step Indicator ───────────────────────────────────────────────────────────

const STEPS = ["Upload", "Opt-in", "Preview", "Template", "Confirm", "Done"];

function StepIndicator({ current }: { current: number }) {
  return (
    <>
    <div className="mb-4 md:hidden">
      <p className="font-label text-xs font-semibold text-primary">Step {current} of {STEPS.length} · {STEPS[current - 1]}</p>
      <div className="mt-1.5 h-1 w-full rounded-full bg-surface-mid">
        <div className="h-1 rounded-full bg-primary transition-all" style={{ width: `${(current / STEPS.length) * 100}%` }} />
      </div>
    </div>
    <div className="-mx-1 mb-8 flex w-[calc(100%+0.5rem)] items-start overflow-x-auto px-1 pb-2 max-md:hidden md:mb-10 md:w-full md:overflow-visible">
      {STEPS.map((label, i) => {
        const step = i + 1;
        const done = step < current;
        const active = step === current;
        return (
          <div key={label} className="relative flex min-w-[72px] flex-1 flex-col items-center">
            {i > 0 && (
              <div className={`absolute top-5 right-1/2 w-full h-0.5 -translate-y-1/2 transition-colors ${step <= current ? "bg-primary" : "bg-surface-mid"}`} />
            )}
            <div className={`relative z-10 w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-colors
              ${done ? "bg-primary text-white shadow-sm" : active ? "bg-primary text-white ring-4 ring-primary/20 shadow-md" : "bg-surface text-on-surface-muted border-2 border-surface-mid"}`}>
              {done ? <Check size={16} /> : step}
            </div>
            <span className={`mt-2 font-label text-[10px] text-center whitespace-nowrap md:text-xs ${active ? "text-primary font-semibold" : done ? "text-primary/50" : "text-on-surface-muted"}`}>
              {label}
            </span>
          </div>
        );
      })}
    </div>
    </>
  );
}

// ─── Segment Dropdown ─────────────────────────────────────────────────────────

const SEGMENT_OPTIONS = [
  { label: "All Segments", value: "", color: "text-primary-700 bg-primary-50 border-primary-200 hover:bg-primary-100" },
  { label: "Hot", value: "A", color: "text-green-700 bg-green-50 border-green-200 hover:bg-green-100" },
  { label: "Warm", value: "B", color: "text-amber-700 bg-amber-50 border-amber-200 hover:bg-amber-100" },
  { label: "Cold", value: "C", color: "text-gray-700 bg-gray-50 border-gray-200 hover:bg-gray-100" },
  { label: "Not Interested", value: "D", color: "text-red-700 bg-red-50 border-red-200 hover:bg-red-100" },
  { label: "Opted Out", value: "opted_out", color: "text-orange-700 bg-orange-50 border-orange-200 hover:bg-orange-100" },
];

function SegmentDropdown({ tagId, dark }: { tagId: string, dark?: boolean }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, right: 0 });

  useEffect(() => {
    if (!open || !btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    setPosition({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        btnRef.current && !btnRef.current.contains(t) &&
        dropdownRef.current && !dropdownRef.current.contains(t)
      ) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  async function download(segment: string) {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/tag-csv?tag_id=${tagId}&segment=${segment}`, { headers: auth });
      if (!res.ok) throw new Error("failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tag_leads_${segment ? segment.toLowerCase() : "all"}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Download failed");
    }
    setOpen(false);
  }

  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        className={cn("text-xs px-2.5 py-1.5 rounded-lg transition-colors flex items-center gap-1 font-medium",
          dark ? "border border-white/40 text-white hover:bg-white/20" : "border border-primary-200 text-primary-700 hover:bg-primary-50"
        )}
      >
        <Download size={12} /> Segment Leads
        <ChevronDown size={12} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && createPortal(
        <div
          ref={dropdownRef}
          className="fixed w-40 bg-white rounded-xl shadow-xl border border-surface-mid z-[9999] overflow-hidden"
          style={{ top: position.top, right: position.right }}
        >
          {SEGMENT_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => download(opt.value)}
              className={cn("w-full text-left text-xs px-3 py-2.5 font-label font-semibold transition-colors border-b border-surface-mid/30 last:border-0", opt.color)}
            >
              {opt.label}
            </button>
          ))}
        </div>,
        document.body
      )}
    </>
  );
}

// ─── Live sending visualizer (immediate broadcast in flight) ─────────────────
function SendingProgress({ names, index, total }: { names: string[]; index: number; total: number }) {
  const [startedAt] = useState(() => Date.now());
  const ROW = 46;
  const VISIBLE = 5;
  const safeTotal = Math.max(total, 1);
  const done = Math.min(index + 1, safeTotal);
  const pct = Math.min(96, Math.round((done / safeTotal) * 100));
  const offset = (Math.floor(VISIBLE / 2) - index) * ROW;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-lg md:text-2xl font-bold text-on-surface mb-1">Your offer is going out</h2>
        <p className="font-body text-sm text-on-surface-muted">
          You can close this page: it keeps sending. Replies come to Chats and the AI agent answers them. Tomorrow at
          9 AM you get a summary in your Anril alerts: sent, read and replied.
        </p>
      </div>

      <div className="rounded-2xl border border-surface-mid bg-surface-low p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="flex items-center gap-2 font-label text-sm font-semibold text-on-surface">
            <Loader2 size={15} className="animate-spin text-primary" />
            Sending <span className="text-primary">{done.toLocaleString()}</span> of {total.toLocaleString()} contacts
          </span>
          <span className="font-body text-xs text-on-surface-muted tabular-nums">
            {timeLeftText(done, safeTotal, Date.now() - startedAt) ?? `${pct}%`}
          </span>
        </div>

        <div className="h-2 w-full rounded-full bg-surface-mid overflow-hidden mb-4">
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>

        <div className="relative overflow-hidden rounded-xl" style={{ height: VISIBLE * ROW }}>
          {/* center focus band */}
          <div
            className="absolute inset-x-0 top-1/2 -translate-y-1/2 rounded-xl bg-primary/10 border border-primary/25 pointer-events-none"
            style={{ height: ROW }}
          />
          <div
            className="transition-transform duration-300 ease-out"
            style={{ transform: `translateY(${offset}px)` }}
          >
            {names.map((n, i) => {
              const state = i < index ? "done" : i === index ? "current" : "pending";
              const opacity = Math.max(0.12, 1 - Math.abs(i - index) * 0.34);
              return (
                <div
                  key={i}
                  className="flex items-center gap-3 px-4"
                  style={{ height: ROW, opacity }}
                >
                  <span className="shrink-0">
                    {state === "done" ? (
                      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-green-100">
                        <Check size={12} strokeWidth={3} className="text-green-600" />
                      </span>
                    ) : state === "current" ? (
                      <Loader2 size={18} className="animate-spin text-primary" />
                    ) : (
                      <span className="block h-2 w-2 rounded-full bg-on-surface-muted/40 ml-1.5" />
                    )}
                  </span>
                  <span
                    className={`font-body text-sm truncate ${
                      state === "current" ? "text-on-surface font-semibold" : "text-on-surface-muted"
                    }`}
                  >
                    {n || "—"}
                  </span>
                </div>
              );
            })}
          </div>
          {/* top + bottom fades */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-10 bg-gradient-to-b from-surface-low to-transparent" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-surface-low to-transparent" />
        </div>
      </div>

      <p className="font-body text-xs text-on-surface-muted text-center">
        Large lists take a little while — delivery receipts arrive afterward in Broadcast History.
      </p>
    </div>
  );
}

// ─── Per-broadcast Segment Dropdown ──────────────────────────────────────────
function BroadcastSegmentDropdown({ broadcastId, tagId, onDownload }: {
  broadcastId: string;
  tagId?: string;
  onDownload: (broadcastId: string, tagId: string | undefined, segment: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, right: 0 });

  useEffect(() => {
    if (!open || !btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    setPosition({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        btnRef.current && !btnRef.current.contains(t) &&
        dropdownRef.current && !dropdownRef.current.contains(t)
      ) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        className="inline-flex h-8 items-center gap-1.5 px-3 rounded-lg border font-label text-[11px] font-semibold transition-colors shrink-0 whitespace-nowrap bg-primary-50 hover:bg-primary-100 text-primary-700 border-primary-200"
      >
        <Download size={12} />
        Segment Leads
        <ChevronDown size={10} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && createPortal(
        <div
          ref={dropdownRef}
          className="fixed w-44 bg-white rounded-xl shadow-xl border border-surface-mid z-[9999] overflow-hidden"
          style={{ top: position.top, right: position.right }}
        >
          <button
            onClick={() => { onDownload(broadcastId, tagId, ""); setOpen(false); }}
            className="w-full text-left text-xs px-3 py-2.5 font-label font-semibold transition-colors border-b border-surface-mid/30 text-primary-700 bg-primary-50 hover:bg-primary-100"
          >
            All Segments
          </button>
          {SEGMENT_OPTIONS.filter(opt => opt.value !== "").map(opt => (
            <button
              key={opt.value}
              onClick={() => { onDownload(broadcastId, tagId, opt.value); setOpen(false); }}
              className={cn("w-full text-left text-xs px-3 py-2.5 font-label font-semibold transition-colors border-b border-surface-mid/30 last:border-0", opt.color)}
            >
              {opt.label}
            </button>
          ))}
        </div>,
        document.body
      )}
    </>
  );
}

// ─── Per-broadcast "Download leads" Dropdown (Delivered / Opened / Failed) ───
type ReachedKind = "delivered" | "opened" | "failed";

function BroadcastLeadsDropdown({ broadcastId, counts, onDownload }: {
  broadcastId: string;
  counts: Record<ReachedKind, number>;
  onDownload: (broadcastId: string, kind: ReachedKind) => void;
}) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, right: 0 });

  useEffect(() => {
    if (!open || !btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    setPosition({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        btnRef.current && !btnRef.current.contains(t) &&
        dropdownRef.current && !dropdownRef.current.contains(t)
      ) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const options: { kind: ReachedKind; label: string; icon: typeof CheckCircle2; tone: string }[] = [
    { kind: "delivered", label: "Delivered", icon: CheckCircle2, tone: "text-emerald-600" },
    { kind: "opened", label: "Opened", icon: Eye, tone: "text-amber-600" },
    { kind: "failed", label: "Failed", icon: XCircle, tone: "text-red-600" },
  ];

  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex h-8 items-center gap-1.5 px-3 rounded-lg border font-label text-[11px] font-semibold transition-colors shrink-0 whitespace-nowrap bg-white hover:bg-gray-50 text-gray-700 border-gray-200"
      >
        <Download size={12} />
        Download leads
        <ChevronDown size={10} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && createPortal(
        <div
          ref={dropdownRef}
          role="menu"
          className="fixed w-48 bg-white rounded-xl shadow-xl border border-surface-mid z-[9999] overflow-hidden py-1"
          style={{ top: position.top, right: position.right }}
        >
          {options.map(({ kind, label, icon: Icon, tone }) => {
            const n = counts[kind] || 0;
            return (
              <button
                key={kind}
                role="menuitem"
                disabled={n === 0}
                onClick={() => { onDownload(broadcastId, kind); setOpen(false); }}
                className="w-full flex items-center gap-2 text-left text-xs px-3 py-2 font-label font-semibold text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300 disabled:hover:bg-white"
              >
                <Icon size={13} className={n === 0 ? "text-gray-300" : tone} />
                <span className="flex-1">{label}</span>
                <span className="tabular-nums text-[11px] font-medium text-gray-400">{n.toLocaleString()}</span>
              </button>
            );
          })}
        </div>,
        document.body
      )}
    </>
  );
}

// ─── Export All Dropdown ──────────────────────────────────────────────────────

function ExportAllDropdown({ tagCount }: { tagCount: number }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, right: 0 });

  useEffect(() => {
    if (!open || !btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    setPosition({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        btnRef.current && !btnRef.current.contains(t) &&
        dropdownRef.current && !dropdownRef.current.contains(t)
      ) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  async function download(mode: string) {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/all-tags-combined?mode=${mode}`, { headers: auth });
      if (!res.ok) throw new Error("failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `all_tags_combined_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Download failed");
    }
    setOpen(false);
  }

  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        className="flex h-8 items-center gap-1.5 px-2.5 rounded-lg bg-white border border-primary-100/80 text-gray-700 hover:border-primary-200 hover:bg-primary-50/40 font-label text-xs font-semibold shadow-xs transition-colors"
      >
        <Download size={12} className="text-[var(--primary-800)]" />
        <span>Export All</span>
        <ChevronDown size={11} className={cn("text-gray-400 transition-transform", open && "rotate-180")} />
      </button>
      {open && createPortal(
        <div
          ref={dropdownRef}
          className="fixed w-60 bg-white rounded-2xl shadow-xl border border-primary-100 z-[9999] overflow-hidden animate-in fade-in zoom-in-95 duration-100"
          style={{ top: position.top, right: position.right }}
        >
          <button
            onClick={() => download("all")}
            className="w-full text-left text-xs px-4 py-3 font-label transition-colors border-b border-primary-100/60 hover:bg-primary-50/60 group"
          >
            <p className="font-semibold text-gray-900 group-hover:text-[var(--primary-800)] transition-colors">All Tags (Combined)</p>
            <p className="text-gray-500 text-[11px] mt-0.5">Combine all {tagCount} tags without deduplication</p>
          </button>
          <button
            onClick={() => download("cross")}
            className="w-full text-left text-xs px-4 py-3 font-label transition-colors hover:bg-primary-50/60 group"
          >
            <p className="font-semibold text-gray-900 group-hover:text-[var(--primary-800)] transition-colors">Cross-Tag Ranked</p>
            <p className="text-gray-500 text-[11px] mt-0.5">Best segment per lead across all tags</p>
          </button>
        </div>,
        document.body
      )}
    </>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function OutboundLeadsPage() {
  const { role, permissions, loading: roleLoading } = useAuthRole();
  const canViewOutbound = role === "owner" || permissions.includes("outbound_leads.view") || permissions.includes("outbound_leads.manage");
  const canManageOutbound = role === "owner" || permissions.includes("outbound_leads.manage");
  // Marking a campaign as an offer teaches the AI agent, so it needs the Knowledge Base edit right.
  const canTeachAi = role === "owner" || permissions.includes("knowledge.manage");
  const [currentStep, setCurrentStep] = useState(1);

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [parsedData, setParsedData] = useState<ParsedData | null>(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  // v9.2 #116: what we read off a notebook photo, checked by the owner before it becomes a list.
  const [scanRows, setScanRows] = useState<ScanRow[] | null>(null);
  const [scanFileName, setScanFileName] = useState("scan.csv");
  const [optInSource, setOptInSource] = useState("");
  const [optInValidation, setOptInValidation] = useState<OptInValidation | null>(null);
  const [optInLoading, setOptInLoading] = useState(false);

  const router = useRouter();
  const searchParams = useSearchParams();
  const [templateName, setTemplateName] = useState(searchParams.get("template") ?? "");
  const [scheduleType, setScheduleType] = useState<ScheduleType>("now");
  const [reachOffer, setReachOffer] = useState<ReachOfferDraft>(NO_REACH_OFFER);
  const [scheduleAt, setScheduleAt] = useState("");
  const [dripDays, setDripDays] = useState("");
  const [dripSendTime, setDripSendTime] = useState("");
  const [resultsFor, setResultsFor] = useState<{ id: string; title: string } | null>(null);
  const [variableMapping, setVariableMapping] = useState<string[]>([]); // column name per {{N}}

  const [sendLoading, setSendLoading] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sendResult, setSendResult] = useState<SendResult | ScheduleResult | null>(null);
  const [sendingNames, setSendingNames] = useState<string[]>([]);
  const [sendingIndex, setSendingIndex] = useState(0);
  const [activeBroadcastId, setActiveBroadcastId] = useState<string | null>(null);
  const [aborting, setAborting] = useState(false);

  // Who the campaign goes to: an uploaded list, or a Customers group (Customers → Groups).
  // ?group=<id> (from Customers → Groups → Send a campaign) opens with that group picked.
  const [audience, setAudience] = useState<"list" | "group">(searchParams.get("group") ? "group" : "list");
  const isGroup = audience === "group";
  const [groups, setGroups] = useState<CustomerGroup[] | null>(null);
  const [groupsError, setGroupsError] = useState<string | null>(null);
  const [groupId, setGroupId] = useState(searchParams.get("group") ?? "");
  const selectedGroup = groups?.find((g) => g.id === groupId) ?? null;
  // v9.2: an uploaded list (file or notebook photo) can also take a Customers group. Each keeps its own
  // consent: the group's from Customers, the list's from step 2. Repeated numbers get one message.
  const [addGroupId, setAddGroupId] = useState("");
  const addedGroup = groups?.find((g) => g.id === addGroupId) ?? null;
  // The confirm step's numbers: who is left out and why, who will get it, and Meta's charge.
  const [reachPreview, setReachPreview] = useState<ReachPreview | null>(null);
  const [reachLoading, setReachLoading] = useState(false);
  const [reachError, setReachError] = useState<string | null>(null);
  const reachRequestRef = useRef(0);
  // How many people the confirm step is about (a group: those who will get it; a list: its rows),
  // and how many different numbers that is.
  const audienceTotal = isGroup ? (reachPreview?.will_get ?? selectedGroup?.member_count ?? 0)
    : addedGroup ? (reachPreview?.will_get ?? (parsedData?.total_rows ?? 0) + addedGroup.member_count)
    : (parsedData?.total_rows ?? 0);
  const uniqueAudience = isGroup ? audienceTotal : (parsedData?.unique_phone_count ?? parsedData?.total_rows ?? 0);

  // Load the groups once, the first time "Customers group" is picked.
  useEffect(() => {
    if (groups !== null) return;
    let cancelled = false;
    api.customerGroups.list()
      .then((rows) => { if (!cancelled) { setGroups(rows); setGroupsError(null); } })
      .catch((err) => {
        if (cancelled) return;
        setGroups([]);
        setGroupsError(err instanceof Error ? err.message : "Could not load your groups.");
      });
    return () => { cancelled = true; };
  }, [isGroup, groups]);

  // Drive the sending ticker off the real backend counts while an immediate
  // broadcast runs as a background job — never claims progress the server hasn't
  // confirmed. Stops polling and reveals the final tally once the job finishes.
  useEffect(() => {
    if (!activeBroadcastId) return;
    let cancelled = false;

    async function poll() {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/upload/broadcast/${activeBroadcastId}/progress`, { headers: auth });
        if (!res.ok || cancelled) return;
        const data: { status: string; sent?: number; failed?: number; opted_out_skipped?: number; number_used?: string; total?: number; skipped_monthly_limit?: number; skipped_blocked?: number; note?: string } = await res.json();
        const sentSoFar = data.sent ?? 0;
        const failedSoFar = data.failed ?? 0;
        setSendingIndex((i) => Math.max(i, Math.min(sentSoFar + failedSoFar, sendingNames.length - 1)));

        if (data.status === "done" || data.status === "aborted" || data.status === "failed") {
          setSendResult({
            queued: sentSoFar,
            failed: failedSoFar,
            opted_out_skipped: data.opted_out_skipped ?? 0,
            number_used: data.number_used ?? "",
            skipped_monthly_limit: data.skipped_monthly_limit ?? 0,
            skipped_blocked: data.skipped_blocked ?? 0,
          });
          setSendLoading(false);
          setAborting(false);
          setActiveBroadcastId(null);
          setCurrentStep(6);
          setActiveTab("history");
          refreshHistory();
          if (data.status === "aborted" && data.note === "stopped_pushback") {
            toast.error("We stopped this campaign: more than 2 in 100 people said stop or turned off offers. The ones already sent stay sent.", { duration: 12000 });
          } else if (data.status === "aborted") toast("Broadcast stopped — leads already sent stay sent.");
          if (data.status === "failed") toast.error("Broadcast failed before it could finish.");
        }
      } catch {
        // transient — next poll tick will retry
      }
    }

    poll();
    const interval = setInterval(poll, 1500);
    return () => { cancelled = true; clearInterval(interval); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeBroadcastId]);

  async function handleAbortSend() {
    if (!activeBroadcastId) return;
    setAborting(true);
    try {
      const auth = await getAuthHeaders();
      await fetch(`${API_URL}/api/v1/upload/broadcast/${activeBroadcastId}/abort`, { method: "POST", headers: auth });
    } catch {
      toast.error("Failed to stop broadcast");
      setAborting(false);
    }
  }

  const [templates, setTemplates] = useState<Template[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesError, setTemplatesError] = useState(false);
  // Fetch once per visit: an empty list is a valid answer, so "length === 0"
  // alone re-fetched forever and the hint under the field flickered.
  const [templatesFetched, setTemplatesFetched] = useState(false);
  const [stepTagsFetched, setStepTagsFetched] = useState(false);

  // The fetch effects below run one render after step 4 / the history tab opens, so
  // "not fetched yet" must read as loading too or the empty hints flash first.
  const templatesPending = templatesLoading || !templatesFetched;

  const activeTemplateForVars = templates.find(t => t.name === templateName);
  const varCount = templateVarCount(activeTemplateForVars?.body_text);

  // One mapping slot per {{n}} the selected template uses. Positions are kept
  // as-is; only a template change clears them.
  const prevTemplateNameRef = useRef(templateName);
  useEffect(() => {
    const count = templateVarCount(templates.find(t => t.name === templateName)?.body_text);
    const nameChanged = prevTemplateNameRef.current !== templateName;
    prevTemplateNameRef.current = templateName;
    setVariableMapping(prev => {
      if (nameChanged) return Array(count).fill("");
      if (prev.length === count) return prev;
      return Array.from({ length: count }, (_, i) => prev[i] ?? "");
    });
  }, [templateName, templates]);

  const [tags, setTags] = useState<{ id: string; name: string; color: string }[]>([]);
  const [tagsLoading, setTagsLoading] = useState(false);
  const stepTagsPending = tagsLoading || !stepTagsFetched;
  const [selectedTag, setSelectedTag] = useState("");

  const [poolNumbers, setPoolNumbers] = useState<SenderRow[] | null>(null);
  const [primaryNumberLoading, setPrimaryNumberLoading] = useState(false);
  const senderInfo = poolNumbers ? pickSender(poolNumbers) : null;
  const sender = senderInfo?.sender ?? null;
  const primaryRow = senderInfo?.primary ?? null;
  const noRows = poolNumbers !== null && poolNumbers.length === 0;
  const noSenderText =
    primaryRow?.health?.state === "resting"
      ? "Your primary number is Red and resting, so it isn't sending broadcasts. It still replies to chats. Add a standby number to keep broadcasting."
      : primaryRow?.health?.state === "meta_pending"
        ? "Meta hasn't verified your primary number yet, so it can't send."
        : "Today's sending limit is used up. Schedule this for tomorrow, or it will wait until tomorrow morning.";

  const [riskSummary, setRiskSummary] = useState<{
    total: number;
    negative_reply_count: number;
    high_no_reply_count: number;
    opted_out_count: number;
    tag_opted_out_count: number;
    total_opted_out_count: number;
    safe_count: number;
  } | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [excludeNegativeReplies, setExcludeNegativeReplies] = useState(false);
  const [includeOptedOut, setIncludeOptedOut] = useState(false);

  // The confirm step asks the server who this would reach. It asks again when a switch on that
  // step changes who is included.
  useEffect(() => {
    if (currentStep !== 5) return;
    fetchReachPreview();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStep, excludeNegativeReplies, includeOptedOut, selectedTag, isGroup, groupId, addGroupId]);

  // Tags management state
  const [tagsList, setTagsList] = useState<BroadcastTag[]>([]);
  const [tagStats, setTagStats] = useState<Record<string, TagStats>>({});
  const [tagsListLoading, setTagsListLoading] = useState(false);
  const [tagsLoaded, setTagsLoaded] = useState(false);
  const [showCreateTag, setShowCreateTag] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState(PRESET_COLORS[0]);
  const [customTagColor, setCustomTagColor] = useState("");
  const [creatingTag, setCreatingTag] = useState(false);
  const [deletingTagId, setDeletingTagId] = useState<string | null>(null);

  const [broadcastHistory, setBroadcastHistory] = useState<BroadcastHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true); // fetched on mount
  const [historyRefreshing, setHistoryRefreshing] = useState(false);
  const [historySearch, setHistorySearch] = useState("");
  const [historyStatusFilter, setHistoryStatusFilter] = useState<"all" | "failures" | "clean">("all");

  const [optedOutList, setOptedOutList] = useState<OptedOutLead[]>([]);
  const [optedOutLoading, setOptedOutLoading] = useState(false);
  const [optedOutLoaded, setOptedOutLoaded] = useState(false);
  const [optedOutError, setOptedOutError] = useState(false);
  const [reactivatingId, setReactivatingId] = useState<string | null>(null);

  const [testSendPhone, setTestSendPhone] = useState("");
  const [testSendLoading, setTestSendLoading] = useState(false);

  const loadOptedOut = useCallback(async () => {
    setOptedOutLoading(true);
    setOptedOutError(false);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/opted-out`, { headers: auth });
      if (!res.ok) throw new Error(String(res.status));
      const data: { data: OptedOutLead[] } = await res.json();
      setOptedOutList(data.data || []);
    } catch {
      // Never show "nobody opted out" when we simply couldn't load the list.
      setOptedOutError(true);
    } finally {
      setOptedOutLoaded(true); // also on failure, so the tab doesn't retry in a loop
      setOptedOutLoading(false);
    }
  }, []);

  async function reactivateOptedOut(lead: OptedOutLead) {
    if (!canManageOutbound) {
      toast.error("Read-only role: reactivating leads is disabled.");
      return;
    }
    const scopeLabel = lead.scope === "tag" ? `for "${lead.tag_name}"` : "account-wide";
    if (!confirm(`Re-include ${lead.name || lead.phone} in future broadcasts (${scopeLabel})? Only do this with their actual consent.`)) return;
    setReactivatingId(`${lead.lead_id}:${lead.tag_id ?? ""}`);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/opted-out/reactivate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ lead_id: lead.lead_id, tag_id: lead.tag_id || undefined }),
      });
      if (!res.ok) throw new Error(await res.text());
      setOptedOutList((prev) => prev.filter((l) => !(l.lead_id === lead.lead_id && l.tag_id === lead.tag_id)));
      toast.success("Lead re-included in future broadcasts");
    } catch {
      toast.error("Failed to reactivate lead");
    } finally {
      setReactivatingId(null);
    }
  }
  const rawTab = searchParams.get("tab");
  const activeTab = (rawTab === "history" || rawTab === "tags" || rawTab === "opted-out" ? rawTab : "upload") as "upload" | "history" | "tags" | "opted-out";

  const setActiveTab = (val: "upload" | "history" | "tags" | "opted-out") => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", val);
    router.replace(`/dashboard/outbound-leads?${params.toString()}`, { scroll: false });
  };
  const [tagsSearch, setTagsSearch] = useState("");

  const filteredTagsList = tagsList.filter((tag) =>
    tag.name.toLowerCase().includes(tagsSearch.toLowerCase())
  );

  const filteredHistory = broadcastHistory.filter(item => {
    const s = historySearch.toLowerCase();
    const matchesSearch = !s ||
      item.template_name.toLowerCase().includes(s) ||
      (item.number_used || "").toLowerCase().includes(s);
    const matchesFilter = historyStatusFilter === "all" ||
      (historyStatusFilter === "failures" && item.failed > 0) ||
      (historyStatusFilter === "clean" && item.failed === 0);
    return matchesSearch && matchesFilter;
  });
  const historyPages = usePagedList(filteredHistory, `${historySearch}|${historyStatusFilter}`);
  const tagPages = usePagedList(filteredTagsList, tagsSearch);
  const optedOutPages = usePagedList(optedOutList);

  // Re-count delivery metrics live from the DB, then refresh the list in place.
  // Silent (no full-list spinner) so cards update without flicker.
  const refreshHistory = useCallback(async () => {
    setHistoryRefreshing(true);
    try {
      const auth = await getAuthHeaders();
      await fetch(`${API_URL}/api/v1/upload/history/refresh`, { method: "POST", headers: auth });
      const r = await fetch(`${API_URL}/api/v1/upload/history`, { headers: auth });
      const res: { data: BroadcastHistoryItem[] } = await r.json();
      setBroadcastHistory(res.data || []);
    } catch {
      // best-effort — keep showing the last known numbers
    } finally {
      setHistoryRefreshing(false);
    }
  }, []);

  // Auto-refresh to live numbers whenever the History tab is opened, so the cards
  // are never a stale snapshot. The mount fetch already showed the snapshot instantly.
  useEffect(() => {
    if (activeTab === "history") {
      refreshHistory();
    }
  }, [activeTab, refreshHistory]);

  // Supabase client for realtime updates
  // Realtime subscription for message status updates
  useEffect(() => {
    if (activeTab === "tags" && !tagsLoaded && !tagsListLoading) {
      loadTags();
    }
    if (activeTab === "opted-out" && !optedOutLoaded && !optedOutLoading) {
      loadOptedOut();
    }
    if (activeTab !== "history") return;

    const channel = supabase
      .channel("messages_status_updates")
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "messages",
          filter: "delivery_status=in.(delivered,read,failed)",
        },
        () => {
          refreshHistory();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [activeTab, tagsLoaded, tagsListLoading, refreshHistory, optedOutLoaded, optedOutLoading, loadOptedOut]);

  usePolling(() => {
    if (activeTab === "tags") loadTags();
  }, 30000, activeTab === "tags");

  const [csvFileUrl, setCsvFileUrl] = useState<string | null>(null);
  const [csvFilePath, setCsvFilePath] = useState<string | null>(null);
  const [csvFileName, setCsvFileName] = useState<string | null>(null);

  async function openBroadcastCsv(item: BroadcastHistoryItem) {
    try {
      let url = item.csv_file_url;
      if (item.csv_file_path) {
        const auth = await getAuthHeaders();
        const params = new URLSearchParams({ path: item.csv_file_path });
        const res = await fetch(`${API_URL}/api/v1/upload/csv-signed-url?${params}`, { headers: auth });
        if (!res.ok) throw new Error("Signed CSV URL unavailable");
        const data: { url: string } = await res.json();
        url = data.url;
      }
      if (!url) {
        toast.error("CSV is not available for this broadcast.");
        return;
      }
      window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      toast.error("Failed to open CSV");
    }
  }

  async function downloadLeadsCsv(broadcastId: string, kind: ReachedKind) {
    if (kind === "failed") return downloadFailedCsv(broadcastId);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/reached-csv?broadcast_id=${broadcastId}&kind=${kind}`, { headers: auth });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${kind}_${broadcastId.slice(0, 8)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast.error("Failed to download CSV");
    }
  }

  async function downloadFailedCsv(broadcastId: string) {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/failed-csv?broadcast_id=${broadcastId}`, { headers: auth });
      if (!res.ok) throw new Error("Download failed");
      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("text/csv")) {
        const body = await res.json().catch(() => ({}));
        toast.error(body.message || "No failure data available for this broadcast.");
        return;
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `failed_${broadcastId.slice(0, 8)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast.error("Failed to download CSV");
    }
  }

  async function downloadBroadcastTagCsv(broadcastId: string, tagId?: string, segment?: string) {
    try {
      const auth = await getAuthHeaders();
      const params = new URLSearchParams({ broadcast_id: broadcastId });
      if (tagId) params.set("tag_id", tagId);
      if (segment) params.set("segment", segment);
      const res = await fetch(
        `${API_URL}/api/v1/upload/broadcast-tag-csv?${params.toString()}`,
        { headers: auth }
      );
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const segLabel = segment ? `_${segment.toLowerCase()}` : "";
      a.download = `broadcast_${broadcastId.slice(0, 8)}${segLabel}_leads.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast.error("Failed to download interest CSV");
    }
  }

  async function downloadHistoryCsv() {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/history-csv`, { headers: auth });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `broadcast_history_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Broadcast history downloaded");
    } catch {
      toast.error("Failed to download broadcast history");
    }
  }

  const [deletingHistoryId, setDeletingHistoryId] = useState<string | null>(null);

  async function handleDeleteHistoryEntry(broadcastId: string) {
    if (!canManageOutbound) {
      toast.error("Read-only role: deleting history is disabled.");
      return;
    }
    if (!confirm("Remove this broadcast from history? Sent messages and leads are not affected.")) return;
    setDeletingHistoryId(broadcastId);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/history/${broadcastId}`, { method: "DELETE", headers: auth });
      if (!res.ok) throw new Error("Delete failed");
      setBroadcastHistory((prev) => prev.filter((h) => h.broadcast_id !== broadcastId));
      toast.success("Removed from history");
    } catch {
      toast.error("Failed to delete history entry");
    } finally {
      setDeletingHistoryId(null);
    }
  }

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch broadcast history once on mount
  useEffect(() => {
    setHistoryLoading(true);
    getAuthHeaders().then(auth => {
      fetch(`${API_URL}/api/v1/upload/history`, { headers: auth })
        .then(r => r.json())
        .then((res: { data: BroadcastHistoryItem[] }) => setBroadcastHistory(res.data || []))
        .catch(() => {})
        .finally(() => setHistoryLoading(false));
    });
  }, []);

  useEffect(() => {
    if (currentStep === 4 || activeTab === "history") {
      if (!templatesFetched && !templatesLoading) {
        setTemplatesFetched(true);
        setTemplatesLoading(true);
        setTemplatesError(false);
        getAuthHeaders().then(auth => {
          fetch(`${API_URL}/api/v1/templates`, { headers: auth })
            .then(r => r.json())
            .then((res: { data: Template[] }) => {
              setTemplates((res.data || []).filter(t => t.status === "APPROVED"));
            })
            .catch(() => setTemplatesError(true))
            .finally(() => setTemplatesLoading(false));
        });
      }

      if (!stepTagsFetched && !tagsLoading) {
        setStepTagsFetched(true);
        setTagsLoading(true);
        getAuthHeaders().then(auth => {
          fetch(`${API_URL}/api/v1/broadcast-tags`, { headers: auth })
            .then(r => r.json())
            .then((res: { data: { id: string; name: string; color: string }[] }) => {
              setTags(res.data || []);
            })
            .catch(() => {})
            .finally(() => setTagsLoading(false));
        });
      }

      if (poolNumbers === null && !primaryNumberLoading) {
        setPrimaryNumberLoading(true);
        getAuthHeaders().then(auth => {
          fetch(`${API_URL}/api/v1/numbers`, { headers: auth })
            .then(r => r.json())
            .then((data: { data: SenderRow[] }) => {
              setPoolNumbers(data.data || []);
            })
            // Settle on empty so a failing request doesn't refetch on every render.
            .catch(() => setPoolNumbers([]))
            .finally(() => setPrimaryNumberLoading(false));
        });
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStep, activeTab, templatesFetched, templatesLoading, stepTagsFetched, tagsLoading, poolNumbers, primaryNumberLoading]);

  if (roleLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  if (!canViewOutbound) {
    return (
      <div className="text-center py-20">
        <p className="text-on-surface-muted font-body">
          You do not have access to outbound leads.
        </p>
      </div>
    );
  }

  function resetAll() {
    setCurrentStep(1);
    setCsvFile(null);
    setParsedData(null);
    setParseError(null);
    setCsvFileUrl(null);
    setCsvFilePath(null);
    setCsvFileName(null);
    setOptInSource("");
    setOptInValidation(null);
    setTemplateName("");
    setScheduleType("now");
    setReachOffer(NO_REACH_OFFER);
    setScheduleAt("");
    setDripDays("");
    setSendError(null);
    setSendResult(null);
    setTemplatesLoading(false);
    setTemplatesError(false);
    setPoolNumbers(null);
    setRiskSummary(null);
    setRiskLoading(false);
    setExcludeNegativeReplies(false);
    setIncludeOptedOut(false);
    setAudience("list");
    setGroupId("");
    setReachPreview(null);
    setReachError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function loadTags() {
    setTagsListLoading(true);
    try {
      const auth = await getAuthHeaders();
      const [tagsRes, statsRes] = await Promise.all([
        fetch(`${API_URL}/api/v1/broadcast-tags`, { headers: auth }),
        fetch(`${API_URL}/api/v1/broadcast-tags/stats`, { headers: auth }),
      ]);
      const tagsData = tagsRes.ok ? ((await tagsRes.json()).data ?? []) : [];
      const statsData = statsRes.ok ? ((await statsRes.json()).data ?? []) : [];
      setTagsList(tagsData);
      // Keep the broadcast step's tag dropdown in step with tags made here.
      setTags(tagsData);
      const sm: Record<string, TagStats> = {};
      for (const s of statsData) sm[s.tag_id] = s;
      setTagStats(sm);
      setTagsLoaded(true);
    } catch { /* best-effort */ } finally {
      setTagsListLoading(false);
    }
  }

  async function handleCreateTag() {
    if (!canManageOutbound) {
      toast.error("Read-only role: tag creation is disabled.");
      return;
    }
    if (!newTagName.trim()) return;
    setCreatingTag(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/broadcast-tags`, {
        method: "POST",
        headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({ name: newTagName.trim(), color: customTagColor || newTagColor }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed");
      toast.success(`Tag "${newTagName}" created`);
      setNewTagName("");
      setShowCreateTag(false);
      await loadTags();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create tag");
    } finally {
      setCreatingTag(false);
    }
  }

  async function handleDeleteTag(tag: BroadcastTag) {
    if (!canManageOutbound) {
      toast.error("Read-only role: tag deletion is disabled.");
      return;
    }
    if (!confirm(`Delete tag "${tag.name}"?`)) return;
    setDeletingTagId(tag.id);
    try {
      const auth = await getAuthHeaders();
      await fetch(`${API_URL}/api/v1/broadcast-tags/${tag.id}`, { method: "DELETE", headers: auth });
      toast.success(`Tag "${tag.name}" deleted`);
      await loadTags();
    } catch { toast.error("Failed to delete tag"); } finally {
      setDeletingTagId(null);
    }
  }

  // Excel uploads are converted to CSV in the browser so the rest of the pipeline
  // (server parse + client-side row split) stays unchanged. xlsx is dynamically
  // imported so it only loads when an Excel file is actually chosen.
  async function toCsvFile(file: File): Promise<File> {
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".xlsx") && !lower.endsWith(".xls")) return file;
    const XLSX = await import("xlsx");
    const wb = XLSX.read(await file.arrayBuffer(), { type: "array" });
    const ws = wb.Sheets[wb.SheetNames[0]];
    if (!ws) throw new Error("The spreadsheet has no sheets");
    const csv = XLSX.utils.sheet_to_csv(ws, { blankrows: false, rawNumbers: false });
    return new File([csv], file.name.replace(/\.(xlsx|xls)$/i, ".csv"), { type: "text/csv" });
  }

  async function processFile(picked: File) {
    setCsvFile(null);
    setParsedData(null);
    setParseError(null);
    setCsvFileUrl(null);
    setCsvFilePath(null);
    setCsvFileName(null);

    setScanRows(null);

    setParseLoading(true);
    try {
      const lowerName = picked.name.toLowerCase();
      const isScan = lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg") || lowerName.endsWith(".png") || lowerName.endsWith(".pdf");
      if (isScan) {
        // Stop here: the owner checks what we read (names, wrong numbers) before the normal upload runs.
        const scanned = await convertScanToCsv(picked);
        const rows = parseScanCsv(await scanned.text());
        if (!rows.length) throw new Error("We couldn't read any phone numbers in this photo. Try a clearer photo, or type them into a sheet.");
        setScanFileName(scanned.name);
        setScanRows(rows);
        return;
      }
      await parseCsvFile(await toCsvFile(picked));
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "Parse failed");
    } finally {
      setParseLoading(false);
    }
  }

  async function useScanRows() {
    if (!scanRows?.length) return;
    setParseError(null);
    setParseLoading(true);
    try {
      const f = new File([rowsToCsv(scanRows)], scanFileName, { type: "text/csv" });
      await parseCsvFile(f);
      setScanRows(null); // only once it worked: a failed upload keeps the owner's fixes on screen
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "Parse failed");
    } finally {
      setParseLoading(false);
    }
  }

  async function parseCsvFile(f: File) {
    setCsvFile(f);
    const auth = await getAuthHeaders();
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch(`${API_URL}/api/v1/upload/parse`, { method: "POST", body: fd, headers: auth });
    if (!res.ok) throw new Error(await res.text());
    const data: ParsedData = await res.json();
    setParsedData(data);
    setCsvFileUrl(data.csv_file_url ?? null);
    setCsvFilePath(data.csv_file_path ?? null);
    setCsvFileName(data.csv_file_name ?? null);
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    if (!picked) return;
    await processFile(picked);
  }

  async function handleDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;
    const lowerName = dropped.name.toLowerCase();
    if (lowerName.endsWith(".csv") || lowerName.endsWith(".xlsx") || lowerName.endsWith(".xls") || lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg") || lowerName.endsWith(".png") || lowerName.endsWith(".pdf")) {
      await processFile(dropped);
    } else {
      setParseError("Invalid file format. Please upload a .csv, .xlsx, .xls, .jpg, .png, or .pdf file.");
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    e.stopPropagation();
  }

  async function handleOptInSelect(value: string) {
    setOptInSource(value);
    setOptInValidation(null);
    setOptInLoading(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/validate-optin`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ opt_in_source: value }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data: OptInValidation = await res.json();
      setOptInValidation(data);
    } catch {
      setOptInValidation(null);
    } finally {
      setOptInLoading(false);
    }
  }

  // The uploaded file's rows as the server wants them (phone, name, consent, every column).
  async function buildCsvLeads() {
    if (!parsedData || !csvFile) return [];
    const text = await csvFile.text();
    const lines = text.split(/\r?\n/).filter(Boolean);
    const headers = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
    const mapping = parsedData.suggested_mapping;
    const phoneIdx = mapping.phone ? headers.indexOf(mapping.phone) : -1;
    const nameIdx = mapping.name ? headers.indexOf(mapping.name) : -1;
    return lines.slice(1).map((line) => {
      const cols = line.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
      const extra_cols: Record<string, string> = {};
      headers.forEach((h, i) => { extra_cols[h] = cols[i] ?? ""; });
      return {
        phone: phoneIdx >= 0 ? cols[phoneIdx] ?? "" : "",
        name: nameIdx >= 0 ? cols[nameIdx] ?? undefined : undefined,
        opt_in_source: optInSource,
        extra_cols,
      };
    }).filter((l) => l.phone);
  }

  async function fetchRiskAudit() {
    if (!parsedData || !csvFile) return;
    setRiskLoading(true);
    setRiskSummary(null);
    try {
      const leads = await buildCsvLeads();
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/risk-audit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ leads, tag_id: selectedTag || undefined }),
      });
      if (res.ok) setRiskSummary(await res.json());
    } catch {
      // risk audit is best-effort; don't block the flow
    } finally {
      setRiskLoading(false);
    }
  }

  // Who this campaign would reach and what Meta charges for it. Only the latest answer is kept.
  async function fetchReachPreview() {
    const mine = ++reachRequestRef.current;
    if (isGroup ? !groupId : !parsedData || !csvFile) return;
    setReachLoading(true);
    setReachError(null);
    try {
      const leads = isGroup ? [] : await buildCsvLeads();
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/reach-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({
          group_id: isGroup ? groupId : addGroupId || undefined,
          leads,
          tag_id: selectedTag || undefined,
          exclude_negative_replies: isGroup ? false : excludeNegativeReplies,
          include_opted_out: isGroup ? false : includeOptedOut,
        }),
      });
      if (!res.ok) throw new Error(res.status === 404 ? "This group no longer exists." : "Could not work out who this will reach.");
      const data: ReachPreview = await res.json();
      if (mine === reachRequestRef.current) setReachPreview(data);
    } catch (err) {
      if (mine === reachRequestRef.current) {
        setReachPreview(null);
        setReachError(err instanceof Error ? err.message : "Could not work out who this will reach.");
      }
    } finally {
      if (mine === reachRequestRef.current) setReachLoading(false);
    }
  }

  async function handleTestSend() {
    if (!testSendPhone.trim() || !templateName) return;
    setTestSendLoading(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/test-send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ phone: testSendPhone.trim(), template_name: templateName }),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success(`Test message sent to ${testSendPhone.trim()}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Test send failed");
    } finally {
      setTestSendLoading(false);
    }
  }

  async function handleSend() {
    if (isGroup ? !groupId : !parsedData || !csvFile) return;
    if (!canManageOutbound) {
      setSendError("Read-only role: campaign dispatch is disabled.");
      return;
    }
    setSendError(null);
    const offerProblem = reachOfferProblem(reachOffer);
    if (offerProblem) {
      setSendError(offerProblem);
      return;
    }

    try {
      let leads: Awaited<ReturnType<typeof buildCsvLeads>> = [];
      if (isGroup) {
        // The server reads the group's people itself; the browser sends only the group's id.
        const count = reachPreview?.will_get ?? selectedGroup?.member_count ?? 0;
        if (count === 0) {
          setSendError("Nobody in this group can get this message right now.");
          return;
        }
        setSendingNames(Array.from({ length: count }, () => "Customer"));
      } else {
        const mapping = parsedData!.suggested_mapping;
        leads = await buildCsvLeads();
        if (!mapping.phone) {
          setSendError("We couldn't find a phone number column in this CSV. Rename that column to \"Phone\" or \"Mobile\" and upload it again.");
          return;
        }
        if (leads.length === 0) {
          setSendError(`The "${mapping.phone}" column has no phone numbers in it.`);
          return;
        }
        setSendingNames(leads.map((l) => l.name || l.phone));
      }
      setSendingIndex(0);
      setSendLoading(true);

      const payload = {
        leads,
        group_id: isGroup ? groupId : addGroupId || undefined,
        template_name: templateName,
        schedule_type: scheduleType,
        // scheduleAt is a naive local wall-clock string from <input type="datetime-local">
        // (browser's local time, not UTC) — convert before sending, or the backend
        // stores it as if it were already UTC and the send fires at the wrong instant.
        schedule_at: scheduleType === "scheduled" && scheduleAt ? new Date(scheduleAt).toISOString() : undefined,
        drip_days: scheduleType === "drip" && dripDays ? parseInt(dripDays, 10) : undefined,
        drip_send_time: scheduleType === "drip" && dripSendTime ? dripSendTime : undefined,
        csv_file_url: isGroup ? null : csvFileUrl,
        csv_file_path: isGroup ? null : csvFilePath,
        csv_file_name: isGroup ? null : csvFileName,
        variable_mapping: isGroup ? [] : variableMapping,
        tag_id: selectedTag || undefined,
        exclude_negative_replies: isGroup ? false : excludeNegativeReplies,
        include_opted_out: isGroup ? false : includeOptedOut,
        offer: reachOfferPayload(reachOffer),
      };

      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/upload/bulk-send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const result: QueuedResult | ScheduleResult = await res.json();

      if (result.status === "queued") {
        // Immediate send now runs as a background job — start polling for real
        // progress instead of claiming it's done. sendLoading stays true until
        // the poll effect sees a terminal status.
        setActiveBroadcastId(result.broadcast_id);
        return;
      }

      setSendResult(result);
      setCurrentStep(6);
      setActiveTab("history");
      refreshHistory();
      setSendLoading(false);
      toast.success("Scheduled. Manage it in Scheduled templates.");
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Send failed");
      setSendLoading(false);
    }
  }

  function downloadSampleCSV() {
    const csvContent = "data:text/csv;charset=utf-8,phone,name,course,city\n919876543210,John Doe,Full Stack Development,Chennai\n919988776655,Jane Smith,Data Science,Bangalore\n";
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "aira_sample_contacts.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  const formatPreviewText = (text: string) => {
    if (!text) return null;
    const parts = text.split(/(\{\{\d+\}\})/g);
    return parts.map((part, i) => {
      const match = part.match(/\{\{(\d+)\}\}/);
      if (match) {
        const num = parseInt(match[1], 10);
        const mappedVal = variableMapping[num - 1];
        return (
          <span key={i} className="inline-block px-1.5 py-0.5 rounded bg-primary/10 text-primary font-bold text-[10px] mx-0.5 border border-primary/20">
            {mappedVal ? `[${mappedVal}]` : `{{${num}}}`}
          </span>
        );
      }
      return part;
    });
  };

  const inputCls = "w-full px-4 py-3 bg-surface-low rounded-xl font-body text-sm text-on-surface border-0 focus:ring-2 focus:ring-primary outline-none";

  return (
    <div className="min-w-0">
      {/* Upload Wizard */}
      {activeTab === "upload" && (
        <div className="flex min-h-[600px] flex-col rounded-2xl bg-surface p-4 shadow-lg ring-1 ring-[#c4c7c7]/20 md:rounded-[2rem] md:p-8">
          <StepIndicator current={currentStep} />

          {/* ── Step 1: Upload CSV ─────────────────────────────────────────── */}
          {currentStep === 1 && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start flex-1">
              {/* Left Column: Upload Controls (7 cols) */}
                <div className="lg:col-span-7 space-y-6">
                  <div>
                    <h2 className="font-display text-lg md:text-2xl font-bold text-on-surface mb-1 break-words">
                      {isGroup ? "Pick a Customers group" : "Upload your CSV, Excel, or scanned notebook"}
                    </h2>
                    <p className="font-body text-sm text-on-surface-muted">
                      {isGroup ? "Send to a group you made under Customers. It is read fresh when you send." : "We\u2019ll detect column mappings automatically."}
                    </p>
                  </div>

                  <div className="space-y-2">
                    <p id="audience-label" className="font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider">Who gets it</p>
                    <SegmentedControl
                      aria-labelledby="audience-label"
                      value={audience}
                      onChange={(v) => { setAudience(v); setReachPreview(null); setReachError(null); }}
                      options={[
                        { value: "list", label: "Uploaded list" },
                        { value: "group", label: "Customers group" },
                      ]}
                    />
                  </div>

                  {isGroup && (
                    <div className="space-y-3">
                      <label htmlFor="group-select" className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider">
                        Group
                      </label>
                      <Select
                        id="group-select"
                        value={groupId}
                        onChange={(v) => { setGroupId(v); setReachPreview(null); }}
                        placeholder={groups === null ? "Loading groups…" : "Pick a group…"}
                        disabled={groups === null || groups.length === 0}
                        options={(groups ?? []).map((g) => ({
                          value: g.id,
                          label: `${g.name} (${g.member_count.toLocaleString()} ${g.member_count === 1 ? "person" : "people"}${g.kind === "rule" ? ", fills itself" : ""})`,
                          text: g.name,
                        }))}
                      />
                      {groupsError && (
                        <p className="font-body text-xs text-red-700">{groupsError}</p>
                      )}
                      {groups !== null && groups.length === 0 && !groupsError && (
                        <p className="font-body text-xs text-on-surface-muted">
                          You have no groups yet. <Link href="/dashboard/leads" className="underline text-primary">Make one under Customers →</Link>
                        </p>
                      )}
                      {selectedGroup && (
                        <div className="rounded-xl border border-surface-mid bg-surface-low p-4 space-y-1.5">
                          <p className="font-body text-sm font-semibold text-on-surface">
                            {selectedGroup.name}: {selectedGroup.member_count.toLocaleString()} {selectedGroup.member_count === 1 ? "person" : "people"}
                          </p>
                          {selectedGroup.rule_text && (
                            <p className="font-body text-xs text-on-surface-muted">{selectedGroup.rule_text}</p>
                          )}
                          {selectedGroup.stop_count > 0 && (
                            <p className="font-body text-xs text-on-surface-muted">
                              {selectedGroup.stop_count.toLocaleString()} said stop and will be left out.
                            </p>
                          )}
                        </div>
                      )}
                      <p className="font-body text-xs text-on-surface-muted">
                        People who said stop, are blocked, or never agreed to messages are left out. You will see the exact numbers before you send.
                      </p>
                    </div>
                  )}

                  {!isGroup && (<>
                  <label
                    onDrop={handleDrop}
                    onDragOver={handleDragOver}
                    className={`relative flex flex-col items-center justify-center gap-3 py-6 md:gap-5 md:py-12 rounded-2xl border-2 border-dashed cursor-pointer transition-colors group
                    ${csvFile ? "border-primary bg-primary/5" : "border-primary/30 hover:border-primary/70 hover:bg-primary/[0.04]"}`}
                  >
                    <div className={`w-12 h-12 md:w-16 md:h-16 rounded-2xl flex items-center justify-center transition-colors shadow-sm
                      ${csvFile ? "bg-primary text-white" : "bg-primary/10 text-primary group-hover:bg-primary/20"}`}>
                      {csvFile ? <Check size={28} /> : <Upload size={28} />}
                    </div>
                    <div className="text-center px-4 w-full min-w-0">
                      <p className="font-display text-base md:text-lg font-bold text-on-surface break-words md:truncate max-w-md mx-auto">
                        {csvFile ? csvFile.name : (<><span className="md:hidden">Tap to choose a file</span><span className="max-md:hidden">Drop your CSV, Excel, or scanned notebook photo here</span></>)}
                      </p>
                      <p className="font-body text-xs text-on-surface-muted mt-1.5 break-words">
                        {csvFile
                          ? `${(csvFile.size / 1024).toFixed(1)} KB · click to change file`
                          : "or click to browse — .csv, .xlsx, .xls, .jpg, .png, .pdf · name and phone columns required"}
                      </p>
                    </div>
                    {!csvFile && (
                      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[10px] text-on-surface-muted font-label border-t border-dashed border-primary/20 w-full justify-center pt-4 mt-1">
                        <span>✓ Auto-detects columns</span>
                        <span>✓ Deduplicates leads</span>
                        <span>✓ OCRs handwritten scans</span>
                      </div>
                    )}
                    <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls,.jpg,.jpeg,.png,.pdf" className="hidden" onChange={handleFileSelect} />
                  </label>

                  {parseLoading && (
                    <div className="flex items-center gap-2 py-2">
                      <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                      <p className="font-body text-sm text-on-surface-muted">Parsing file…</p>
                    </div>
                  )}
                  {parseError && (
                    <div className="flex items-start gap-2 p-3.5 bg-red-50 text-red-700 rounded-xl font-body text-sm">
                      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                      {parseError}
                    </div>
                  )}

                  {scanRows && (
                    <ScanReview rows={scanRows} onChange={setScanRows} onUse={useScanRows} onCancel={() => setScanRows(null)} busy={parseLoading} />
                  )}

                  {parsedData && (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <div className="p-4 bg-primary/5 border border-primary/15 rounded-xl text-center">
                        <p className="font-display text-2xl font-bold text-primary">{parsedData.total_rows.toLocaleString()}</p>
                        <p className="font-label text-xs text-on-surface-muted mt-1">Total Rows</p>
                      </div>
                      <div className={`p-4 rounded-xl text-center border ${parsedData.duplicate_count > 0 ? "bg-amber-50 border-amber-200" : "bg-surface-low border-surface-mid"}`}>
                        <p className={`font-display text-2xl font-bold ${parsedData.duplicate_count > 0 ? "text-amber-700" : "text-on-surface-muted"}`}>{parsedData.duplicate_count}</p>
                        <p className="font-label text-xs text-on-surface-muted mt-1">Duplicates</p>
                      </div>
                      <div className="p-4 bg-green-50 border border-green-200 rounded-xl text-center">
                        <p className="font-display text-2xl font-bold text-green-700">{(parsedData.total_rows - parsedData.duplicate_count).toLocaleString()}</p>
                        <p className="font-label text-xs text-on-surface-muted mt-1">New Leads</p>
                      </div>
                      <div className="rounded-xl bg-surface-low p-3 sm:col-span-3">
                        <p className="font-label text-xs text-on-surface-muted mb-1.5">Columns detected</p>
                        <div className="flex flex-wrap gap-1.5">
                          {parsedData.columns.map(col => (
                            <span key={col} className={`px-2.5 py-0.5 rounded-md text-[10px] font-semibold tracking-wide
                              ${Object.values(parsedData.suggested_mapping).includes(col) ? "bg-primary/10 text-primary border border-primary/10" : "bg-surface-mid text-on-surface-muted"}`}>
                              {col}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Also send to a Customers group: one campaign, two lists, a running total. */}
                  <div className="space-y-2 rounded-2xl border border-surface-mid bg-surface-low p-4">
                    <label htmlFor="add-group" className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider">
                      Also send to a Customers group <span className="normal-case font-normal">(optional)</span>
                    </label>
                    <Select
                      id="add-group"
                      value={addGroupId}
                      onChange={(v) => { setAddGroupId(v === "none" ? "" : v); setReachPreview(null); }}
                      placeholder={groups === null ? "Loading groups…" : "No group"}
                      disabled={groups === null || groups.length === 0}
                      options={[{ value: "none", label: "No group" }, ...(groups ?? []).map((g) => ({
                        value: g.id,
                        label: `${g.name} (${g.member_count.toLocaleString()} ${g.member_count === 1 ? "person" : "people"})`,
                        text: g.name,
                      }))]}
                    />
                    {addedGroup && (
                      <p className="font-body text-sm text-on-surface">
                        Selected: <b>{addedGroup.member_count.toLocaleString()}</b> from the group
                        {parsedData ? <> + <b>{parsedData.total_rows.toLocaleString()}</b> from {csvFile?.name ?? "your list"}</> : null}
                        {" "}= <b>{(addedGroup.member_count + (parsedData?.total_rows ?? 0)).toLocaleString()} people</b>.
                        {" "}Repeats get one message. The group&apos;s consent comes from Customers; the list&apos;s from the next step.
                      </p>
                    )}
                  </div>
                  </>)}
                  <div className="flex justify-end pt-2">
                    <button
                      onClick={() => setCurrentStep(isGroup ? 4 : 2)}
                      disabled={isGroup ? !groupId : !parsedData}
                      className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
                    >
                      Next <ChevronRight size={16} />
                    </button>
                  </div>
                </div>

                {/* Right Column: Templates Guide & Policy (5 cols) */}
                <div className="lg:col-span-5 lg:border-l lg:border-surface-mid lg:pl-8 space-y-6">
                  {isGroup ? (
                    <div>
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-8 h-8 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600">
                          <Users size={16} />
                        </div>
                        <h3 className="font-display font-bold text-on-surface text-base">How a group send works</h3>
                      </div>
                      <ul className="space-y-2 font-body text-xs text-on-surface-muted">
                        <li className="flex gap-2"><span className="text-emerald-500 font-bold">✓</span><span>The people are read from the group when you send, so a group that fills itself is always up to date.</span></li>
                        <li className="flex gap-2"><span className="text-emerald-500 font-bold">✓</span><span>Anyone who said stop, is blocked, or never agreed to messages is left out.</span></li>
                        <li className="flex gap-2"><span className="text-emerald-500 font-bold">✓</span><span>Each person gets at most 2 offers a month.</span></li>
                      </ul>
                    </div>
                  ) : (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <div className="w-8 h-8 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600">
                        <FileSpreadsheet size={16} />
                      </div>
                      <h3 className="font-display font-bold text-on-surface text-base">CSV Template</h3>
                    </div>

                    {parsedData ? (
                      <div className="space-y-3 text-xs">
                        <div className="p-3 bg-surface-low rounded-xl">
                          <p className="font-label text-[10px] text-on-surface-muted uppercase font-bold">Uploaded File</p>
                          <p className="font-body font-semibold text-on-surface truncate mt-0.5">{csvFile?.name}</p>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-center">
                          <div className="p-2 bg-green-50 border border-green-100 rounded-xl">
                            <p className="font-label text-[9px] text-green-700 uppercase font-bold">Leads</p>
                            <p className="font-display font-bold text-green-700 mt-0.5">{(parsedData.total_rows - parsedData.duplicate_count).toLocaleString()}</p>
                          </div>
                          <div className="p-2 bg-surface-low rounded-xl">
                            <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold">Headers</p>
                            <p className="font-display font-bold text-on-surface mt-0.5">{parsedData.columns.length}</p>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <p className="font-body text-xs text-on-surface-muted leading-relaxed">
                          Make sure your CSV file includes these headers. Match additional variables with custom columns.
                        </p>

                        <div className="divide-y divide-surface-mid border-t border-b border-surface-mid">
                          <div className="py-2 flex justify-between text-xs font-body">
                            <span className="font-mono text-on-surface font-semibold">phone</span>
                            <span className="text-red-700 font-bold bg-red-50 px-1.5 py-0.5 rounded text-[9px]">Required</span>
                          </div>
                          <div className="py-2 flex justify-between text-xs font-body">
                            <span className="font-mono text-on-surface font-semibold">name</span>
                            <span className="text-on-surface-muted bg-surface-low px-1.5 py-0.5 rounded text-[9px]">Optional</span>
                          </div>
                          <div className="py-2 flex justify-between text-xs font-body">
                            <span className="font-mono text-on-surface font-semibold">course / other</span>
                            <span className="text-on-surface-muted bg-surface-low px-1.5 py-0.5 rounded text-[9px]">Optional</span>
                          </div>
                        </div>

                        <button
                          onClick={downloadSampleCSV}
                          className="w-full flex items-center justify-center gap-2 py-2.5 bg-surface-low hover:bg-surface-mid rounded-xl font-label text-xs font-bold text-on-surface transition-colors border border-surface-mid/60"
                        >
                          <Download size={13} />
                          Download Sample CSV
                        </button>
                      </div>
                    )}
                  </div>
                  )}

                  <div className="border-t border-surface-mid/40 pt-6">
                    <div className="flex items-center gap-2 mb-3">
                      <div className="w-8 h-8 rounded-xl bg-orange-50 flex items-center justify-center text-orange-600">
                        <ShieldCheck size={16} />
                      </div>
                      <h3 className="font-display font-bold text-on-surface text-base">Policy Guide</h3>
                    </div>
                    <ul className="space-y-2 font-body text-xs text-on-surface-muted">
                      <li className="flex gap-2">
                        <span className="text-emerald-500 font-bold">✓</span>
                        <span><strong>Opt-in rule</strong>: Only send messages to leads who explicitly agreed to receive updates.</span>
                      </li>
                      <li className="flex gap-2">
                        <span className="text-emerald-500 font-bold">✓</span>
                        <span><strong>Limits</strong>: Keep dispatches below your tier limits to protect WABA quality rating.</span>
                      </li>
                      <li className="flex gap-2">
                        <span className="text-emerald-500 font-bold">✓</span>
                        <span><strong>24h rule</strong>: Users can reply to template broadcasts to open a 24h custom chat session.</span>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
          )}

          {/* ── Step 2: Opt-in Source ──────────────────────────────────────── */}
          {currentStep === 2 && (
            <div className="space-y-6 flex-1">
              <div>
                <h2 className="font-display text-lg md:text-2xl font-bold text-on-surface mb-1">Did these people agree to hear from you?</h2>
                <p className="font-body text-sm text-on-surface-muted">Pick the one that fits most of the list. Meta doesn&apos;t see this answer — it only decides what we let you send, so answer honestly.</p>
              </div>

              <div className="space-y-2">
                {OPT_IN_OPTIONS.map((opt) => (
                  <label
                    key={opt.value}
                    className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors
                      ${optInSource === opt.value ? "border-primary bg-primary/5" : "border-surface-mid bg-surface-low hover:border-primary/40"}`}
                  >
                    <input
                      type="radio"
                      name="opt_in_source"
                      value={opt.value}
                      checked={optInSource === opt.value}
                      onChange={() => handleOptInSelect(opt.value)}
                      className="mt-0.5 accent-[var(--color-primary)]"
                    />
                    <div>
                      <p className="font-label text-sm font-semibold text-on-surface">{opt.label}</p>
                      <p className="font-body text-xs text-on-surface-muted mt-0.5">{opt.description}</p>
                    </div>
                  </label>
                ))}
              </div>

              {optInLoading && (
                <div className="flex items-center gap-2 py-2">
                  <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  <p className="font-body text-sm text-on-surface-muted">Validating consent rule…</p>
                </div>
              )}

              {optInValidation && (
                <div className={`flex items-start gap-2.5 p-3.5 rounded-xl font-body text-sm border
                  ${optInValidation.allowed ? "bg-green-50 text-green-700 border-green-100" : "bg-red-50 text-red-700 border-red-100"}`}>
                  {optInValidation.allowed ? <Check size={16} className="mt-0.5 shrink-0" /> : <AlertTriangle size={16} className="mt-0.5 shrink-0" />}
                  <span>
                    {OPT_IN_RESULT[optInValidation.template_type] ?? optInValidation.message}
                    {!optInValidation.allowed && (
                      <Link href="/dashboard/telecalling/upload" className="ml-1 font-semibold underline underline-offset-2">Upload this list for calling</Link>
                    )}
                  </span>
                </div>
              )}

              <div className="flex items-center justify-between pt-4 border-t border-surface-mid/30">
                <button
                  onClick={() => setCurrentStep(1)}
                  className="px-4 py-2.5 rounded-xl font-label text-sm text-on-surface-muted hover:bg-surface-low transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => setCurrentStep(3)}
                  disabled={!optInValidation?.allowed}
                  className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
                >
                  Next <ChevronRight size={16} />
                </button>
              </div>
            </div>
          )}

          {/* ── Step 3: Preview ───────────────────────────────────────────── */}
          {currentStep === 3 && parsedData && (
            <div className="space-y-6 flex-1">
              <div>
                <h2 className="font-display text-lg md:text-2xl font-bold text-on-surface mb-1">Preview Data</h2>
                <p className="font-body text-sm text-on-surface-muted">
                  Showing first {parsedData.preview.length} of {parsedData.total_rows.toLocaleString()} rows.
                </p>
              </div>

              <div className="overflow-x-auto rounded-xl ring-1 ring-[#c4c7c7]/20 bg-white max-h-[350px]">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 z-20">
                    <tr className="bg-surface-low border-b border-surface-mid">
                      {parsedData.columns.map((col) => (
                        <th key={col} className="px-3.5 py-3 font-label font-bold text-on-surface-muted whitespace-nowrap bg-surface-low">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {parsedData.preview.map((row, ri) => (
                      <tr key={ri} className="border-b border-surface-mid/50 hover:bg-surface-low transition-colors">
                        {parsedData.columns.map((col) => (
                          <td key={col} className="px-3.5 py-3 font-body text-on-surface whitespace-nowrap">
                            {row[col] ?? "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-surface-mid/30">
                <button
                  onClick={() => setCurrentStep(2)}
                  className="px-4 py-2.5 rounded-xl font-label text-sm text-on-surface-muted hover:bg-surface-low transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => setCurrentStep(4)}
                  className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 transition-colors shadow-sm"
                >
                  Next <ChevronRight size={16} />
                </button>
              </div>
            </div>
          )}

          {/* ── Step 4: Template & Schedule ───────────────────────────────── */}
          {currentStep === 4 && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start flex-1">
              {/* Left Column: Template Selection & Settings (7 cols) */}
              <div className="lg:col-span-7 space-y-6">
                <div>
                  <h2 className="font-display text-lg md:text-2xl font-bold text-on-surface mb-1">Template & Schedule</h2>
                  <p className="font-body text-sm text-on-surface-muted">Choose which template to send and when.</p>
                </div>

                <div className="bg-surface-low border border-surface-mid rounded-xl p-4 flex items-center justify-between">
                  <div>
                    <p className="font-label text-[10px] text-on-surface-muted uppercase tracking-wider mb-1 font-bold">Sender Number</p>
                    {primaryNumberLoading || poolNumbers === null ? (
                      <p className="font-body text-xs text-on-surface-muted">Loading primary number...</p>
                    ) : sender ? (
                      <>
                        <p className="font-body text-sm font-semibold text-on-surface">{sender.display_name} ({sender.number})</p>
                        {primaryRow && primaryRow.id !== sender.id && (
                          <p className="font-body text-xs text-on-surface-muted mt-1">
                            Your primary {primaryRow.number} can&apos;t broadcast right now, so this goes out from the standby.
                          </p>
                        )}
                      </>
                    ) : noRows || poolNumbers === null ? (
                      <p className="font-body text-xs text-red-600 font-semibold">No primary number found! Broadcast may fail.</p>
                    ) : (
                      <p className="font-body text-xs text-amber-700 font-semibold">No number can send broadcasts right now.</p>
                    )}
                  </div>
                  <Link href="/dashboard/numbers" className="px-3 py-1.5 bg-white border border-surface-mid rounded-lg font-label text-xs font-semibold text-on-surface hover:bg-surface-low transition-colors shadow-sm">
                    Change
                  </Link>
                </div>

                <div>
                  <label htmlFor="template-select" className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider mb-2">
                    Template Name
                  </label>
                  <Select
                    id="template-select"
                    value={templateName}
                    onChange={setTemplateName}
                    placeholder="Select a template…"
                    options={templates.map(t => ({ value: t.name, label: `${t.name} (${t.category.toLowerCase()})` }))}
                  />
                  {!isGroup && optInValidation?.template_type === "utility" &&
                    templates.find((t) => t.name === templateName)?.category?.toUpperCase() === "MARKETING" && (
                    <p className="flex items-start gap-1.5 font-label text-xs text-amber-700 mt-2">
                      <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                      This is an offer message, but you said these people only enquired or agreed in person. Offers to them
                      bring more &quot;stop&quot; replies; a campaign is stopped on its own if more than 2 in 100 say stop.
                    </p>
                  )}
                  {templatesPending && (
                    <p className="font-label text-xs text-on-surface-muted mt-2">Loading templates…</p>
                  )}
                  {!templatesPending && templatesError && (
                    <p className="font-label text-xs text-red-600 mt-2 font-semibold">
                      Failed to load templates. <button onClick={() => { setTemplatesError(false); setTemplatesFetched(false); }} className="underline">Retry</button>
                    </p>
                  )}
                  {!templatesPending && !templatesError && templates.length === 0 && (
                    <p className="font-label text-xs text-amber-600 mt-2 font-semibold">
                      No approved templates yet. <Link href="/dashboard/templates" className="underline">Create one →</Link>
                    </p>
                  )}
                </div>

                {/* ── Broadcast Tag ─────────────────────────────────────── */}
                <div>
                  <label htmlFor="tag-select" className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider mb-2">
                    Broadcast Tag <span className="normal-case font-normal text-on-surface-muted">(optional)</span>
                  </label>
                  <Select
                    id="tag-select"
                    value={selectedTag}
                    onChange={setSelectedTag}
                    options={[
                      { value: "", label: "No tag — skip interest tracking" },
                      ...tags.map(t => ({ value: t.id, label: t.name })),
                    ]}
                  />
                  {stepTagsPending && (
                    <p className="font-label text-xs text-on-surface-muted mt-2">Loading tags…</p>
                  )}
                  {!stepTagsPending && tags.length === 0 && (
                    <p className="font-label text-xs text-on-surface-muted mt-2">
                      No tags yet. <button onClick={() => setActiveTab("tags")} className="underline text-primary-600">Create one →</button>
                    </p>
                  )}
                </div>

                {/* ── Template Variable Mapping ─────────────────────────── */}
                {templateName && varCount > 0 && parsedData && parsedData.columns.length > 0 && (
                  <div className="bg-surface-low border border-surface-mid rounded-xl p-4 space-y-4">
                    <div>
                      <p className="font-label text-xs font-bold text-on-surface uppercase tracking-wider">
                        Template Variables <span className="normal-case font-normal text-on-surface-muted font-body text-xs">(optional)</span>
                      </p>
                      <p className="font-body text-xs text-on-surface-muted mt-0.5">
                        This template has {varCount} variable{varCount === 1 ? "" : "s"}. Pick a CSV column for each, or leave it — <code className="bg-surface-mid px-1.5 py-0.5 rounded font-mono text-[10px]">{"{{1}}"}</code> then uses the lead&apos;s name, others say &quot;Customer&quot;.
                      </p>
                    </div>
                    <div className="space-y-2">
                      {Array.from({ length: varCount }, (_, idx) => (
                        <div key={idx} className="flex items-center gap-2 bg-white p-2 rounded-lg border border-surface-mid/60">
                          <span className="font-mono text-xs text-on-surface-muted w-10 shrink-0 font-bold">{`{{${idx + 1}}}`}</span>
                          <Select
                            size="sm"
                            aria-label={`Column for {{${idx + 1}}}`}
                            value={variableMapping[idx] ?? ""}
                            onChange={(v) => {
                              const next = Array.from({ length: varCount }, (_, i) => variableMapping[i] ?? "");
                              next[idx] = v;
                              setVariableMapping(next);
                            }}
                            className="flex-1"
                            options={[
                              { value: "", label: "— pick a column —" },
                              ...parsedData.columns.map(c => ({ value: c, label: c })),
                            ]}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <label className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider mb-2">
                    Schedule Type
                  </label>
                  <div className="grid grid-cols-3 gap-1 max-md:rounded-xl max-md:bg-surface-low max-md:p-1 md:gap-2">
                    {(["now", "scheduled", "drip"] as ScheduleType[]).map((type) => (
                      <label
                        key={type}
                        className={`flex items-center justify-center gap-3 max-md:h-9 max-md:px-1 md:justify-start md:p-3.5 rounded-xl border cursor-pointer transition-colors
                          ${scheduleType === type ? "border-primary bg-primary/5" : "border-surface-mid bg-surface-low hover:border-primary/40"}`}
                      >
                        <input
                          type="radio"
                          name="schedule_type"
                          value={type}
                          checked={scheduleType === type}
                          onChange={() => setScheduleType(type)}
                          className="accent-[var(--color-primary)] max-md:sr-only"
                        />
                        <span className="font-label text-xs font-bold text-on-surface whitespace-nowrap">
                          {type === "now" ? "Send Now" : type === "scheduled" ? "Later" : "Spread over days"}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                {isGroup && templateName && varCount > 0 && (
                  <p className="rounded-xl border border-surface-mid bg-surface-low p-4 font-body text-xs text-on-surface-muted">
                    This template has {varCount} variable{varCount === 1 ? "" : "s"}. A group has no spreadsheet columns, so {"{{1}}"} is filled with the person&apos;s name and the others say &quot;Customer&quot;.
                  </p>
                )}

                {scheduleType === "scheduled" && (
                  <div>
                    <label className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider mb-2">
                      Send At
                    </label>
                    <div className="mb-2 flex gap-2 overflow-x-auto">
                      {scheduleChoices(new Date()).map((c) => (
                        <button
                          key={c.value}
                          type="button"
                          onClick={() => setScheduleAt(c.value)}
                          className={cn(
                            "h-8 shrink-0 whitespace-nowrap rounded-full border px-3 font-label text-xs font-bold transition-colors",
                            scheduleAt === c.value
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-surface-mid bg-surface-low text-on-surface hover:border-primary/40",
                          )}
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>
                    <input
                      type="datetime-local"
                      value={scheduleAt}
                      onChange={(e) => setScheduleAt(e.target.value)}
                      className={inputCls}
                    />
                    <p className={cn("mt-1.5 font-body text-xs", scheduleProblem(scheduleAt) ? "text-red-600" : "text-on-surface-muted")}>
                      {scheduleProblem(scheduleAt) ?? SCHEDULE_HOURS_NOTE}
                    </p>
                  </div>
                )}

                {scheduleType === "drip" && (
                  <div className="space-y-4">
                    <div>
                      <label className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider mb-2">
                        Spread over how many days?
                      </label>
                      <input
                        type="number"
                        min={1}
                        value={dripDays}
                        onChange={(e) => setDripDays(e.target.value)}
                        placeholder="e.g. 7"
                        className={inputCls}
                      />
                    </div>
                    <div>
                      <label className="block font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider mb-2">
                        Send time each day (IST) <span className="text-on-surface-muted/60 normal-case font-normal">— optional, leave blank to send at upload time</span>
                      </label>
                      <input
                        type="time"
                        value={dripSendTime}
                        onChange={(e) => setDripSendTime(e.target.value)}
                        className={inputCls}
                      />
                      <p className={cn("mt-1.5 font-body text-xs", dripTimeProblem(dripSendTime) ? "text-red-600" : "text-on-surface-muted")}>
                        {dripTimeProblem(dripSendTime) ?? SCHEDULE_HOURS_NOTE}
                      </p>
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between pt-4 border-t border-surface-mid/30">
                  <button
                    onClick={() => setCurrentStep(isGroup ? 1 : 3)}
                    className="px-4 py-2.5 rounded-xl font-label text-sm text-on-surface-muted hover:bg-surface-low transition-colors"
                  >
                    Back
                  </button>
                  <button
                    onClick={async () => { setReachPreview(null); setCurrentStep(5); if (!isGroup) await fetchRiskAudit(); }}
                    disabled={!templateName.trim() || !sender || (scheduleType === "scheduled" && !!scheduleProblem(scheduleAt)) || (scheduleType === "drip" && !!dripTimeProblem(dripSendTime))}
                    title={!sender ? "No number can send broadcasts right now" : undefined}
                    className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
                  >
                    Next <ChevronRight size={16} />
                  </button>
                </div>
              </div>

              {/* Right Column: Previews & Sender Info (5 cols) */}
              <div className="lg:col-span-5 lg:border-l lg:border-surface-mid lg:pl-8 space-y-6">
                {/* Sender Stats */}
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
                        <Phone size={16} />
                      </div>
                      <h3 className="font-display font-bold text-on-surface text-base">Sender Line</h3>
                    </div>
                    {sender && sender.health?.state === "warming" ? (
                      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-sky-50 text-sky-700 text-[10px] font-bold border border-sky-100">
                        <span className="w-1.5 h-1.5 rounded-full bg-sky-500" />
                        Warming · day {sender.health.warm_up_day} of {sender.health.warm_up_days}
                      </div>
                    ) : sender ? (
                      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-bold border border-emerald-100">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                        Active
                      </div>
                    ) : null}
                  </div>

                  {primaryNumberLoading ? (
                    <div className="py-4 text-center">
                      <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-1" />
                      <p className="font-body text-xs text-on-surface-muted">Fetching line details...</p>
                    </div>
                  ) : sender ? (
                    <div className="space-y-3 text-xs">
                      <div>
                        <p className="font-label text-[10px] text-on-surface-muted uppercase tracking-wider font-bold">Display Name</p>
                        <p className="font-body text-sm font-semibold text-on-surface">{sender.display_name}</p>
                      </div>
                      <div>
                        <p className="font-label text-[10px] text-on-surface-muted uppercase tracking-wider font-bold">WhatsApp Number</p>
                        <p className="font-body text-sm font-semibold text-on-surface">{sender.number}</p>
                      </div>
                      <div className="pt-2.5 border-t border-surface-mid grid grid-cols-2 gap-2 text-center">
                        <div className="p-2 bg-surface-low rounded-xl">
                          <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold">
                            {sender.health?.state === "warming" ? "WARM-UP LIMIT" : "DAILY LIMIT"}
                          </p>
                          <p className="font-display text-xs font-bold text-on-surface mt-0.5">{formatDaily(sender.health?.broadcast_cap)}</p>
                          {sender.health?.broadcast_cap != null && sender.health.broadcast_cap < UNLIMITED_DAILY && (
                            <p className="font-body text-[10px] text-on-surface-muted mt-0.5">{senderInfo?.leftToday.toLocaleString()} left today</p>
                          )}
                        </div>
                        <div className="p-2 bg-surface-low rounded-xl">
                          <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold">Quality</p>
                          {sender.quality_rating === "green" ? (
                            <p className="font-display text-xs font-bold text-emerald-600 mt-0.5">High</p>
                          ) : sender.quality_rating === "yellow" ? (
                            <p className="font-display text-xs font-bold text-amber-600 mt-0.5">Medium</p>
                          ) : sender.quality_rating === "red" ? (
                            <p className="font-display text-xs font-bold text-red-600 mt-0.5">Low</p>
                          ) : (
                            <p className="font-body text-xs text-on-surface-muted mt-0.5">No rating yet</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : noRows || poolNumbers === null ? (
                    <div className="p-3 bg-amber-50 text-amber-700 rounded-xl text-xs font-body flex items-start gap-2 border border-amber-100">
                      <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                      <span>No primary sender configured. Broadcasts will fail until you map a primary sender.</span>
                    </div>
                  ) : (
                    <div className="p-3 bg-amber-50 text-amber-700 rounded-xl text-xs font-body flex items-start gap-2 border border-amber-100">
                      <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                      <span>
                        {noSenderText}{" "}
                        <Link href="/dashboard/numbers" className="font-bold underline">Go to Sender Numbers</Link>
                      </span>
                    </div>
                  )}
                </div>

                {/* WhatsApp Live Preview */}
                <div className="border-t border-surface-mid/40 pt-6">
                  <div className="flex items-center gap-2 mb-4">
                    <div className="w-8 h-8 rounded-xl bg-primary-50 flex items-center justify-center text-primary-600">
                      <Smartphone size={16} />
                    </div>
                    <h3 className="font-display font-bold text-on-surface text-base">Live Preview</h3>
                  </div>

                  {/* Phone Mockup */}
                  <div className="border border-surface-mid rounded-[24px] overflow-hidden bg-[#efeae2] shadow-inner relative max-w-sm mx-auto">
                    {/* Phone Header */}
                    <div className="bg-primary-950 text-white px-3 py-2 flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-white/20 flex items-center justify-center font-display text-[10px] font-bold shrink-0">
                        A
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-label text-[10px] font-semibold truncate leading-tight">Anril Assistant</p>
                        <p className="font-body text-[8px] text-white/80 leading-none">Online</p>
                      </div>
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                    </div>

                    {/* Chat Container */}
                    <div className="p-3 space-y-3 min-h-[180px] flex flex-col justify-end">
                      {templateName ? (
                        (() => {
                          const activeTemplate = templates.find(t => t.name === templateName);
                          if (!activeTemplate) return (
                            <p className="font-body text-xs text-on-surface-muted text-center py-8">Loading template structure...</p>
                          );

                          return (
                            <div className="space-y-1.5 max-w-[90%] self-start w-full">
                              {/* Message Bubble */}
                              <div className="bg-white rounded-2xl rounded-tl-none p-2.5 shadow-sm text-[#111B21] relative border border-white/5 w-full">
                                {/* Header Media */}
                                {activeTemplate.header_media_type && activeTemplate.header_media_type !== "NONE" && (
                                  <div className="mb-2 bg-surface-low rounded-lg p-3 flex flex-col items-center justify-center border border-surface-mid text-on-surface-muted gap-1">
                                    {activeTemplate.header_media_type === "IMAGE" && <ImageIcon size={20} className="text-on-surface-muted" />}
                                    {activeTemplate.header_media_type === "VIDEO" && <PlayCircle size={20} className="text-on-surface-muted" />}
                                    {activeTemplate.header_media_type === "DOCUMENT" && <FileText size={20} className="text-on-surface-muted" />}
                                    {activeTemplate.header_media_type === "LOCATION" && <MapPin size={20} className="text-on-surface-muted" />}
                                    <span className="font-label text-[9px] font-bold tracking-wide uppercase mt-0.5 text-on-surface-muted">
                                      {activeTemplate.header_media_type} Header
                                    </span>
                                  </div>
                                )}

                                {/* Header Text */}
                                {activeTemplate.header_text && (
                                  <p className="font-label text-xs font-bold text-[#111b21] mb-1 leading-tight">
                                    {activeTemplate.header_text}
                                  </p>
                                )}

                                {/* Body Text */}
                                <p className="font-body text-[11px] whitespace-pre-wrap break-words leading-relaxed text-[#111b21]">
                                  {formatPreviewText(activeTemplate.body_text)}
                                </p>

                                {/* Footer Text */}
                                {activeTemplate.footer_text && (
                                  <p className="font-body text-[9px] text-gray-500 mt-1 leading-tight border-t border-surface-mid/40 pt-1.5">
                                    {activeTemplate.footer_text}
                                  </p>
                                )}

                                {/* Timestamp & checkmarks */}
                                <div className="text-right mt-1 leading-none">
                                  <span className="font-body text-[8px] text-gray-400">12:30 PM</span>
                                  <span className="text-[#53bdeb] ml-1 font-body text-[9px] font-bold">✓✓</span>
                                </div>
                              </div>

                              {/* Action Buttons underneath bubble */}
                              {activeTemplate.buttons && activeTemplate.buttons.length > 0 && (
                                <div className="space-y-1 w-full">
                                  {activeTemplate.buttons.map((btn, bidx) => (
                                    <button
                                      key={bidx}
                                      type="button"
                                      className="w-full bg-white/95 hover:bg-white text-[#008069] font-label text-[10px] font-bold py-2 px-2.5 rounded-lg shadow-sm border border-white/5 flex items-center justify-center gap-1.5 transition-colors"
                                    >
                                      {btn.type === "URL" && <Globe size={10} />}
                                      {btn.type === "PHONE_NUMBER" && <Phone size={10} />}
                                      {btn.type === "WHATSAPP_CALL" && <Phone size={10} />}
                                      {btn.type === "COPY_CODE" && <Copy size={10} />}
                                      {btn.text}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })()
                      ) : (
                        <div className="flex flex-col items-center justify-center gap-2 py-8 text-center text-on-surface-muted/60 w-full">
                          <MessageSquare size={20} className="opacity-40" />
                          <p className="font-body text-xs">Select a template in step 4 to view live message layout</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Step 5: Confirm & Send ────────────────────────────────────── */}
          {currentStep === 5 && (parsedData || isGroup) && sendLoading && scheduleType === "now" && (
            <div className="space-y-4">
              <SendingProgress
                names={sendingNames}
                index={sendingIndex}
                total={sendingNames.length || audienceTotal}
              />
              <div className="flex flex-wrap justify-center gap-3">
                <a href="/dashboard/conversations" className="inline-flex items-center rounded-xl border border-surface-mid bg-white px-5 py-2.5 font-label text-sm font-semibold text-on-surface hover:bg-surface-low">
                  See replies in Chats
                </a>
                <button type="button" onClick={() => setActiveTab("history")} className="inline-flex items-center rounded-xl bg-primary px-5 py-2.5 font-label text-sm font-semibold text-white hover:bg-primary-dark">
                  See results
                </button>
              </div>
              {activeBroadcastId && (
                <button
                  onClick={handleAbortSend}
                  disabled={aborting}
                  className="w-full flex items-center justify-center gap-2 px-5 py-3 bg-red-50 text-red-700 rounded-xl font-label text-sm font-semibold hover:bg-red-100 transition-colors border border-red-200 disabled:opacity-50"
                >
                  <XCircle size={16} />
                  {aborting ? "Stopping…" : "Stop sending"}
                </button>
              )}
            </div>
          )}
          {currentStep === 5 && (parsedData || isGroup) && !(sendLoading && scheduleType === "now") && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start flex-1">
              {/* Left Column: Confirm details (7 cols) */}
              <div className="lg:col-span-7 space-y-6">
                <div>
                  <h2 className="font-display text-lg md:text-2xl font-bold text-on-surface mb-1">Confirm & Send</h2>
                  <p className="font-body text-sm text-on-surface-muted">Review campaign configurations before dispatches.</p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {[
                    isGroup
                      ? { label: "Will Get It", value: reachLoading && !reachPreview ? "Checking…" : audienceTotal.toLocaleString() }
                      : { label: "People", value: audienceTotal.toLocaleString() },
                    isGroup
                      ? { label: "Customers Group", value: selectedGroup?.name ?? "—" }
                      : { label: "Consent Source", value: optInSource.replace(/_/g, " ") },
                    { label: "Active Template", value: templateName },
                    { label: "When to send", value: scheduleType === "now" ? "Send Immediately" : scheduleType === "scheduled" ? `At ${scheduleAt ? new Date(scheduleAt).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true }) : "—"}` : `Spread over ${dripDays} days${dripSendTime ? ` · ${dripSendTime} IST daily` : ""}` },
                  ].map(({ label, value }) => (
                    <div key={label} className="p-4 bg-surface-low rounded-xl border border-surface-mid">
                      <p className="font-label text-[10px] text-on-surface-muted uppercase tracking-wider mb-1 font-bold">{label}</p>
                      <p className="font-body text-sm font-bold text-on-surface capitalize truncate">{value}</p>
                    </div>
                  ))}
                </div>

                {/* bulk-send sends once per number, so repeated rows don't get a second message */}
                {parsedData && parsedData.unique_phone_count !== undefined && parsedData.unique_phone_count < parsedData.total_rows && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 flex items-start gap-2.5 font-body text-xs text-amber-900">
                    <Info size={14} className="text-amber-700 shrink-0 mt-0.5" />
                    <span>
                      {parsedData.total_rows.toLocaleString()} rows, <strong>{parsedData.unique_phone_count.toLocaleString()} unique numbers</strong> will be messaged.
                      {" "}The other {(parsedData.total_rows - parsedData.unique_phone_count).toLocaleString()} rows repeat a number already in this file or have no valid number, so they&apos;re skipped. Each person gets one message.
                    </span>
                  </div>
                )}

                {/* The rest carries over to when Meta's moving 24h limit frees up, in the daytime (broadcast_executor.carry_over_time) */}
                {scheduleType === "now" && sender && senderInfo && uniqueAudience > senderInfo.leftToday && (() => {
                  const today = Math.max(senderInfo.leftToday, 0);
                  const rest = uniqueAudience - today;
                  const cap = sender.health?.broadcast_cap ?? 0;
                  return (
                    <div className="rounded-xl border border-sky-200 bg-sky-50/70 px-4 py-3 flex items-start gap-2.5 font-body text-xs text-sky-900">
                      <Clock size={14} className="text-sky-700 shrink-0 mt-0.5" />
                      <span>
                        {sender.number} can send <strong>{today.toLocaleString()}</strong> more right now. The first {today.toLocaleString()} go out now and the remaining <strong>{rest.toLocaleString()}</strong>{" "}
                        {rest > cap
                          ? "go out over the next days as Meta's 24-hour limit frees up, between 10:00 AM and 9:00 PM (India time)."
                          : "go out automatically once Meta's 24-hour limit frees up, between 10:00 AM and 9:00 PM (India time)."}
                        {" "}They&apos;ll show under Scheduled templates.
                      </span>
                    </div>
                  );
                })()}

                {/* Who this reaches, who is left out and why, and what Meta charges */}
                {reachLoading && !reachPreview && (
                  <div className="flex items-center gap-2 p-3.5 bg-surface-low rounded-xl border border-surface-mid font-body text-sm text-on-surface-muted">
                    <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                    Working out who this will reach…
                  </div>
                )}
                {reachError && !reachLoading && (
                  <div className="flex items-start gap-2 p-3.5 bg-amber-50 text-amber-900 rounded-xl font-body text-sm border border-amber-200">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    {reachError}
                  </div>
                )}
                {reachPreview && (() => {
                  const r = reachPreview;
                  const parts: string[] = [`${r.in_audience.toLocaleString()} in ${r.audience === "group" ? "group" : "list"}`];
                  if (r.said_stop > 0) parts.push(`${r.said_stop.toLocaleString()} said stop`);
                  if (r.no_opt_in > 0) parts.push(`${r.no_opt_in.toLocaleString()} never agreed to messages`);
                  if (r.no_number > 0) parts.push(`${r.no_number.toLocaleString()} with no usable number`);
                  if (r.blocked > 0) parts.push(`${r.blocked.toLocaleString()} blocked`);
                  if (r.negative_reply > 0) parts.push(`${r.negative_reply.toLocaleString()} said no to an earlier offer`);
                  if (r.over_cap > 0) parts.push(`${r.over_cap.toLocaleString()} already got ${r.monthly_limit} offers this month`);
                  const cost = r.cost_inr;
                  return (
                    <div className="rounded-xl border border-surface-mid bg-surface-low p-4 space-y-3">
                      <p className="font-body text-sm text-on-surface">
                        {parts.join(" · ")} · <strong>{r.will_get.toLocaleString()} will get it</strong>
                      </p>
                      <p className="font-body text-sm text-on-surface">
                        Meta charges about <strong>₹{cost.toLocaleString("en-IN", { maximumFractionDigits: cost < 100 ? 2 : 0 })}</strong> for this
                        {" "}({r.will_get.toLocaleString()} × ₹{r.rate_inr.toFixed(2)}, before GST).
                      </p>
                      <p className="font-body text-xs text-on-surface-muted">
                        Each person gets at most {r.monthly_limit} offers a month. This is checked again when the message goes out, so anyone who reaches the limit by then is skipped.
                      </p>
                    </div>
                  );
                })()}

                {/* Risk Audit Card */}
                {riskLoading && (
                  <div className="flex items-center gap-2 p-3.5 bg-surface-low rounded-xl border border-surface-mid font-body text-sm text-on-surface-muted">
                    <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                    Checking audience health…
                  </div>
                )}
                {!isGroup && !riskLoading && riskSummary && (riskSummary.negative_reply_count > 0 || riskSummary.high_no_reply_count > 0 || riskSummary.opted_out_count > 0 || riskSummary.tag_opted_out_count > 0) && (
                  <div className="rounded-2xl border border-amber-300/80 bg-gradient-to-br from-amber-50 via-orange-50 to-white p-4 shadow-sm space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-2.5">
                        <div className="w-7 h-7 rounded-full bg-amber-100 border border-amber-200 flex items-center justify-center shrink-0 mt-0.5">
                          <AlertTriangle size={14} className="text-amber-700" />
                        </div>
                        <div>
                          <p className="font-label text-sm font-semibold text-amber-900">Audience Risk Summary</p>
                          <p className="font-body text-xs text-amber-700/90 mt-0.5">Review risky contacts before dispatching this broadcast.</p>
                        </div>
                      </div>
                      <span className="px-2.5 py-1 rounded-full bg-white/80 border border-amber-200 text-[10px] font-label font-semibold uppercase tracking-wide text-amber-700">
                        Pre-send Check
                      </span>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-center">
                      <div className="p-2.5 bg-white/95 rounded-xl border border-red-100">
                        <p className="font-display text-xl font-bold text-red-600">{riskSummary.negative_reply_count}</p>
                        <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold mt-0.5">Said No</p>
                      </div>
                      <div className="p-2.5 bg-white/95 rounded-xl border border-amber-100">
                        <p className="font-display text-xl font-bold text-amber-600">{riskSummary.high_no_reply_count}</p>
                        <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold mt-0.5">Silent 2+</p>
                      </div>
                      <div className="p-2.5 bg-white/95 rounded-xl border border-[#e2e8f0]">
                        <p className="font-display text-xl font-bold text-[#334155]">{riskSummary.opted_out_count}</p>
                        <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold mt-0.5">Opted Out</p>
                      </div>
                      <div className="p-2.5 bg-white/95 rounded-xl border border-[#e2e8f0]">
                        <p className="font-display text-xl font-bold text-[#334155]">{riskSummary.tag_opted_out_count}</p>
                        <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold mt-0.5">Tag Opt-Out</p>
                      </div>
                      <div className="p-2.5 bg-white/95 rounded-xl border border-green-100">
                        <p className="font-display text-xl font-bold text-green-600">{riskSummary.safe_count}</p>
                        <p className="font-label text-[9px] text-on-surface-muted uppercase font-bold mt-0.5">Safe</p>
                      </div>
                    </div>

                    {riskSummary.negative_reply_count > 0 && (
                      <div className="rounded-xl border border-amber-200 bg-white/80 p-3">
                        <button
                          type="button"
                          role="checkbox"
                          aria-checked={excludeNegativeReplies}
                          onClick={() => setExcludeNegativeReplies(!excludeNegativeReplies)}
                          className="flex select-none items-center gap-2.5 text-left"
                        >
                          <TickMark checked={excludeNegativeReplies} size="sm" />
                          <span className="font-body text-sm text-amber-900">
                            Exclude {riskSummary.negative_reply_count} lead{riskSummary.negative_reply_count !== 1 ? "s" : ""} who previously said no
                          </span>
                        </button>
                      </div>
                    )}

                    {(riskSummary.total_opted_out_count ?? riskSummary.tag_opted_out_count ?? 0) > 0 && (
                      <div className="rounded-xl border border-orange-200 bg-orange-50/70 p-3 space-y-2">
                        <div className="flex items-center gap-2 text-orange-900 font-body text-sm">
                          <AlertTriangle size={14} className="shrink-0" />
                          {(() => {
                            const n = riskSummary.total_opted_out_count ?? riskSummary.tag_opted_out_count ?? 0;
                            const tagOnly = (riskSummary.tag_opted_out_count ?? 0) > 0 && (riskSummary.opted_out_count ?? 0) === 0;
                            const globalOnly = (riskSummary.opted_out_count ?? 0) > 0 && (riskSummary.tag_opted_out_count ?? 0) === 0;
                            const suffix = globalOnly ? " globally" : tagOnly ? " of this tag" : " of this tag or globally";
                            return `${n} contact${n !== 1 ? "s" : ""} opted out${suffix}.`;
                          })()}
                        </div>
                        <button
                          type="button"
                          role="checkbox"
                          aria-checked={includeOptedOut}
                          onClick={() => setIncludeOptedOut(!includeOptedOut)}
                          className="flex select-none items-center gap-2.5 text-left"
                        >
                          <TickMark checked={includeOptedOut} size="sm" />
                          <span className="font-body text-sm text-orange-900">
                            {(() => {
                              const n = riskSummary.total_opted_out_count ?? riskSummary.tag_opted_out_count ?? 0;
                              return `Send to opted-out contact${n !== 1 ? "s" : ""} anyway`;
                            })()}
                          </span>
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {canManageOutbound && canTeachAi && (
                  <ReachOfferBox templateName={templateName} value={reachOffer} onChange={setReachOffer} />
                )}

                {sendError && (
                  <div className="flex items-start gap-2 p-3.5 bg-red-50 text-red-700 rounded-xl font-body text-sm border border-red-100">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    {sendError}
                  </div>
                )}

                <div className="flex items-center justify-between pt-4 border-t border-surface-mid/30">
                  <button
                    onClick={() => setCurrentStep(4)}
                    className="px-4 py-2.5 rounded-xl font-label text-sm text-on-surface-muted hover:bg-surface-low transition-colors"
                  >
                    Back
                  </button>
                  <button
                    onClick={handleSend}
                    disabled={sendLoading || !canManageOutbound || (isGroup && (reachLoading || !reachPreview || reachPreview.will_get === 0))}
                    title={canManageOutbound ? "Dispatch campaign" : "Read-only role: dispatch is disabled"}
                    className="flex items-center gap-2 px-6 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:blur-[0.5px] disabled:cursor-not-allowed transition-colors shadow-sm"
                  >
                    <Upload size={14} />
                    {sendLoading ? "Sending…" : scheduleType === "scheduled" ? "Schedule" : "Send now"}
                  </button>
                </div>

                {canManageOutbound && (
                  <div className="flex items-center gap-2 pt-2">
                    <input
                      type="tel"
                      value={testSendPhone}
                      onChange={(e) => setTestSendPhone(e.target.value)}
                      placeholder="Your WhatsApp number, e.g. 91987654XXXX"
                      className="flex-1 min-w-0 px-3 py-2 rounded-lg border border-surface-mid font-body text-xs focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                    />
                    <button
                      onClick={handleTestSend}
                      disabled={testSendLoading || !testSendPhone.trim() || !templateName}
                      className="shrink-0 flex items-center gap-1.5 px-3 py-2 bg-surface-low hover:bg-surface-mid text-on-surface rounded-lg font-label text-xs font-semibold border border-surface-mid disabled:opacity-50 transition-colors"
                    >
                      <Send size={12} />
                      {testSendLoading ? "Sending…" : "Send test"}
                    </button>
                  </div>
                )}
              </div>

              {/* Right Column: Template preview (5 cols) */}
              <div className="lg:col-span-5 lg:border-l lg:border-surface-mid lg:pl-8 space-y-6">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-8 h-8 rounded-xl bg-primary-50 flex items-center justify-center text-primary-600">
                    <Smartphone size={16} />
                  </div>
                  <h3 className="font-display font-bold text-on-surface text-base">Live Preview</h3>
                </div>

                {/* Phone Mockup */}
                <div className="border border-surface-mid rounded-[24px] overflow-hidden bg-[#efeae2] shadow-inner relative max-w-sm mx-auto">
                  {/* Phone Header */}
                  <div className="bg-primary-950 text-white px-3 py-2 flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-white/20 flex items-center justify-center font-display text-[10px] font-bold shrink-0">
                      A
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-label text-[10px] font-semibold truncate leading-tight">Anril Assistant</p>
                      <p className="font-body text-[8px] text-white/80 leading-none">Online</p>
                    </div>
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                  </div>

                  {/* Chat Container */}
                  <div className="p-3 space-y-3 min-h-[180px] flex flex-col justify-end">
                    {templateName ? (
                      (() => {
                        const activeTemplate = templates.find(t => t.name === templateName);
                        if (!activeTemplate) return (
                          <p className="font-body text-xs text-on-surface-muted text-center py-8">Loading template structure...</p>
                        );

                        return (
                          <div className="space-y-1.5 max-w-[90%] self-start w-full">
                            {/* Message Bubble */}
                            <div className="bg-white rounded-2xl rounded-tl-none p-2.5 shadow-sm text-[#111B21] relative border border-white/5 w-full">
                              {/* Header Media */}
                              {activeTemplate.header_media_type && activeTemplate.header_media_type !== "NONE" && (
                                <div className="mb-2 bg-surface-low rounded-lg p-3 flex flex-col items-center justify-center border border-surface-mid text-on-surface-muted gap-1">
                                  {activeTemplate.header_media_type === "IMAGE" && <ImageIcon size={20} className="text-on-surface-muted" />}
                                  {activeTemplate.header_media_type === "VIDEO" && <PlayCircle size={20} className="text-on-surface-muted" />}
                                  {activeTemplate.header_media_type === "DOCUMENT" && <FileText size={20} className="text-on-surface-muted" />}
                                  {activeTemplate.header_media_type === "LOCATION" && <MapPin size={20} className="text-on-surface-muted" />}
                                  <span className="font-label text-[9px] font-bold tracking-wide uppercase mt-0.5 text-on-surface-muted">
                                    {activeTemplate.header_media_type} Header
                                  </span>
                                </div>
                              )}

                              {/* Header Text */}
                              {activeTemplate.header_text && (
                                <p className="font-label text-xs font-bold text-[#111b21] mb-1 leading-tight">
                                  {activeTemplate.header_text}
                                </p>
                              )}

                              {/* Body Text */}
                              <p className="font-body text-[11px] whitespace-pre-wrap break-words leading-relaxed text-[#111b21]">
                                {formatPreviewText(activeTemplate.body_text)}
                              </p>

                              {/* Footer Text */}
                              {activeTemplate.footer_text && (
                                <p className="font-body text-[9px] text-gray-500 mt-1 leading-tight border-t border-surface-mid/40 pt-1.5">
                                  {activeTemplate.footer_text}
                                </p>
                              )}

                              {/* Timestamp & checkmarks */}
                              <div className="text-right mt-1 leading-none">
                                <span className="font-body text-[8px] text-gray-400">12:30 PM</span>
                                <span className="text-[#53bdeb] ml-1 font-body text-[9px] font-bold">✓✓</span>
                              </div>
                            </div>

                            {/* Action Buttons underneath bubble */}
                            {activeTemplate.buttons && activeTemplate.buttons.length > 0 && (
                              <div className="space-y-1 w-full">
                                {activeTemplate.buttons.map((btn, bidx) => (
                                  <button
                                    key={bidx}
                                    type="button"
                                    className="w-full bg-white/95 hover:bg-white text-[#008069] font-label text-[10px] font-bold py-2 px-2.5 rounded-lg shadow-sm border border-white/5 flex items-center justify-center gap-1.5 transition-colors"
                                  >
                                    {btn.type === "URL" && <Globe size={10} />}
                                    {btn.type === "PHONE_NUMBER" && <Phone size={10} />}
                                    {btn.type === "WHATSAPP_CALL" && <Phone size={10} />}
                                    {btn.type === "COPY_CODE" && <Copy size={10} />}
                                    {btn.text}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })()
                    ) : (
                      <div className="flex flex-col items-center justify-center gap-2 py-8 text-center text-on-surface-muted/60 w-full">
                        <MessageSquare size={20} className="opacity-40" />
                        <p className="font-body text-xs">Select a template in step 4 to view live message layout</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Step 6: Done ──────────────────────────────────────────────── */}
          {currentStep === 6 && sendResult && "status" in sendResult && (
            <div className="space-y-6 flex-1">
              <div className="flex items-center gap-3 bg-green-50 border border-green-100 p-4 rounded-2xl">
                <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center shrink-0 border border-green-200">
                  <Clock size={20} className="text-green-700" />
                </div>
                <div>
                  <h2 className="font-display text-xl font-bold text-green-950">
                    {sendResult.status === "drip_scheduled" ? "Drip campaign scheduled!" : "Campaign scheduled!"}
                  </h2>
                  <p className="font-body text-xs text-green-700 mt-0.5">
                    {sendResult.status === "drip_scheduled"
                      ? `${sendResult.total.toLocaleString()} leads split across ${sendResult.batches ?? 0} batches.`
                      : sendResult.fire_at
                        ? `${sendResult.total.toLocaleString()} leads will be sent at ${new Date(sendResult.fire_at).toLocaleString()}.`
                        : `${sendResult.total.toLocaleString()} leads queued for scheduled send.`}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-4 border-t border-surface-mid/30">
                <Link
                  href="/dashboard/scheduled-templates"
                  className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 transition-colors shadow-sm"
                >
                  <Clock size={16} />
                  Manage in Scheduled templates
                </Link>
                <button
                  onClick={resetAll}
                  className="flex items-center gap-2 px-5 py-3 bg-surface-low text-on-surface rounded-xl font-label text-sm font-semibold hover:bg-surface-mid transition-colors border border-surface-mid/60"
                >
                  <RotateCcw size={14} />
                  Upload Another
                </button>
              </div>
            </div>
          )}

          {currentStep === 6 && sendResult && !("status" in sendResult) && (
            <div className="space-y-6 flex-1">
              <div className="flex items-center gap-3 bg-green-50 border border-green-100 p-4 rounded-2xl">
                <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center shrink-0 border border-green-200">
                  <Check size={20} className="text-green-700" />
                </div>
                <div>
                  <h2 className="font-display text-xl font-bold text-green-950">Campaign sent successfully!</h2>
                  <p className="font-body text-xs text-green-700 mt-0.5">Leads queued — replies will appear in Conversations.</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="p-3 sm:p-4 bg-green-50/50 border border-green-200/50 rounded-xl text-center">
                  <p className="font-display text-2xl sm:text-3xl font-bold text-green-700">{sendResult.queued.toLocaleString()}</p>
                  <p className="font-label text-[10px] text-green-600 mt-1 uppercase tracking-wide font-bold">Sent</p>
                </div>
                <div className="p-3 sm:p-4 bg-surface-low border border-surface-mid rounded-xl text-center">
                  <p className="font-display text-2xl sm:text-3xl font-bold text-on-surface-muted">{sendResult.failed.toLocaleString()}</p>
                  <p className="font-label text-[10px] text-on-surface-muted mt-1 uppercase tracking-wide font-bold">Failed</p>
                </div>
                <div className="p-3 sm:p-4 bg-gray-50 border border-gray-200 rounded-xl text-center">
                  <p className="font-display text-2xl sm:text-3xl font-bold text-gray-600">{sendResult.opted_out_skipped.toLocaleString()}</p>
                  <p className="font-label text-[10px] text-gray-500 mt-1 uppercase tracking-wide font-bold">Opted Out</p>
                </div>
                <div className="p-3 sm:p-4 bg-primary/5 border border-primary/15 rounded-xl text-center">
                  <p className="font-display text-sm font-bold text-primary truncate leading-10">{sendResult.number_used}</p>
                  <p className="font-label text-[10px] text-on-surface-muted mt-1 uppercase tracking-wide font-bold">Sender Line</p>
                </div>
              </div>

              {((sendResult.skipped_monthly_limit ?? 0) > 0 || (sendResult.skipped_blocked ?? 0) > 0) && (
                <div className="rounded-xl border border-surface-mid bg-surface-low p-4 space-y-1 font-body text-sm text-on-surface">
                  {(sendResult.skipped_monthly_limit ?? 0) > 0 && (
                    <p><strong>{sendResult.skipped_monthly_limit!.toLocaleString()}</strong> skipped: monthly limit (they already got 2 offers this month)</p>
                  )}
                  {(sendResult.skipped_blocked ?? 0) > 0 && (
                    <p><strong>{sendResult.skipped_blocked!.toLocaleString()}</strong> skipped: blocked</p>
                  )}
                </div>
              )}

              <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-4 border-t border-surface-mid/30">
                <Link
                  href="/dashboard/conversations"
                  className="flex-1 flex items-center justify-center gap-2 px-5 py-3 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 transition-colors shadow-sm"
                >
                  <MessageSquare size={16} />
                  View Conversations
                </Link>
                <button
                  onClick={resetAll}
                  className="flex items-center justify-center gap-2 px-5 py-3 bg-surface-low text-on-surface rounded-xl font-label text-sm font-semibold hover:bg-surface-mid transition-colors border border-surface-mid/60"
                >
                  <RotateCcw size={14} />
                  Upload Another
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Broadcast History */}
      {/* Tags Tab */}
      {activeTab === "tags" && (
        <div className="overflow-hidden rounded-2xl border border-primary-100/70 bg-white shadow-lg">
          {/* Header Card Bar */}
          <div className="border-b border-primary-100/70 bg-gradient-to-r from-primary-50/80 via-primary-50/30 to-white px-4 py-5 md:px-8">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              {/* Title with Icon Badge */}
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-100 to-primary-100 border border-primary-200/60 shadow-xs">
                  <Tag size={20} className="text-[var(--primary-800)]" />
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    {tagsList.length > 0 && (
                      <span className="rounded-full bg-primary-100/80 border border-primary-200/60 px-2.5 py-0.5 font-label text-[11px] font-bold text-[var(--primary-800)]">
                        {tagsList.length} {tagsList.length === 1 ? "tag" : "tags"}
                      </span>
                    )}
                  </div>
                  <p className="font-body text-xs md:text-sm text-gray-500 mt-0.5">
                    Tag and label outbound broadcasts by product to track interest per audience segment.
                  </p>
                </div>
              </div>

              {/* Action Controls */}
              <div className="flex flex-wrap items-center gap-2">
                {/* Search */}
                <div className="relative">
                  <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search tags…"
                    value={tagsSearch}
                    onChange={(e) => setTagsSearch(e.target.value)}
                    className="h-8 w-32 sm:w-40 pl-7 pr-6 text-xs bg-white/90 border border-primary-100/80 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary-600)]/20 focus:border-[var(--primary-600)] transition-all placeholder:text-gray-400 text-gray-800 shadow-xs"
                  />
                  {tagsSearch && (
                    <button
                      type="button"
                      onClick={() => setTagsSearch("")}
                      className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs px-1"
                    >
                      ✕
                    </button>
                  )}
                </div>

                {/* Export All */}
                <ExportAllDropdown tagCount={tagsList.length} />

                {/* Refresh */}
                <button
                  onClick={loadTags}
                  disabled={tagsListLoading}
                  className="flex h-8 items-center gap-1.5 px-2.5 rounded-lg bg-white border border-primary-100/80 text-gray-700 hover:border-primary-200 hover:bg-primary-50/40 font-label text-xs font-semibold shadow-xs transition-colors disabled:opacity-50"
                  title="Refresh tags"
                >
                  <RefreshCw size={12} className={cn("text-[var(--primary-800)] transition-transform", tagsListLoading && "animate-spin")} />
                  <span className="hidden sm:inline">Refresh</span>
                </button>

                {/* Standout Primary New Tag CTA with signature brand gradient */}
                <button
                  onClick={() => setShowCreateTag((p) => !p)}
                  className={cn(
                    "flex h-8 items-center gap-1.5 px-3 rounded-lg font-label text-xs font-bold transition-all",
                    showCreateTag
                      ? "bg-primary-100 border border-primary-200 text-[var(--primary-800)] hover:bg-primary-200/70"
                      : "bg-primary hover:bg-primary-dark text-white shadow-[0_2px_8px_rgba(var(--primary-800-rgb),0.25)] hover:opacity-95"
                  )}
                >
                  {showCreateTag ? (
                    <span>Cancel</span>
                  ) : (
                    <>
                      <Plus size={14} />
                      <span>New Tag</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Create Tag Panel */}
          {showCreateTag && (
            <div className="border-b border-primary-100/80 bg-gradient-to-br from-primary-50/50 via-white to-primary-50/30 p-4 md:px-8 animate-in fade-in slide-in-from-top-2 duration-200">
              <div className="max-w-3xl">
                <div className="flex items-center gap-2 mb-2.5">
                  <div className="w-1.5 h-3 rounded-full bg-primary" />
                  <p className="font-label text-[11px] font-bold uppercase tracking-wider text-[var(--primary-800)]">Create New Tag</p>
                </div>
                <div className="flex flex-col sm:flex-row gap-2.5 items-end">
                  <div className="flex-1 w-full">
                    <label className="font-label text-[11px] font-medium text-gray-600 mb-1 block">Tag Name</label>
                    <input
                      type="text"
                      value={newTagName}
                      onChange={(e) => setNewTagName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && canManageOutbound && handleCreateTag()}
                      placeholder="e.g. VIP Customers, Flash Sale, Diapers"
                      autoFocus
                      className="w-full h-8 px-3 rounded-lg border border-primary-100/90 bg-white font-body text-xs text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[var(--primary-600)]/20 focus:border-[var(--primary-600)] shadow-xs transition-all"
                    />
                  </div>
                  <div className="w-full sm:w-auto">
                    <label className="font-label text-[11px] font-medium text-gray-600 mb-1 block">Color Palette</label>
                    <div className="flex items-center gap-1.5 h-8 px-2 bg-white border border-primary-100/90 rounded-lg shadow-xs">
                      {PRESET_COLORS.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => { setCustomTagColor(""); setNewTagColor(c); }}
                          className={cn(
                            "w-[18px] h-[18px] rounded-full transition-transform border border-black/10 shrink-0",
                            newTagColor === c && !customTagColor ? "ring-2 ring-offset-1 ring-[var(--primary-600)] scale-110" : "hover:scale-110"
                          )}
                          style={{ backgroundColor: c }}
                          title={c}
                        />
                      ))}
                      <div className="w-px h-3.5 bg-primary-100 mx-0.5 shrink-0" />
                      {/* Circular multicolor custom color option */}
                      <div className="relative shrink-0 flex items-center justify-center">
                        <div
                          className={cn(
                            "w-[18px] h-[18px] rounded-full transition-transform border border-black/10 cursor-pointer overflow-hidden shadow-2xs hover:scale-110 relative flex items-center justify-center",
                            customTagColor ? "ring-2 ring-offset-1 ring-[var(--primary-600)] scale-110" : ""
                          )}
                          style={{
                            background: customTagColor
                              ? customTagColor
                              : "conic-gradient(from 0deg, #ff0055, #ff5500, #ffcc00, #33cc33, #0099ff, #7700ff, #ff00aa, #ff0055)",
                          }}
                          title={customTagColor ? `Custom color: ${customTagColor}` : "Pick custom multicolor"}
                        >
                          <input
                            type="color"
                            value={customTagColor || newTagColor}
                            onChange={(e) => { setCustomTagColor(e.target.value); setNewTagColor(e.target.value); }}
                            className="absolute -inset-2 w-10 h-10 opacity-0 cursor-pointer"
                            title="Pick custom color"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 w-full sm:w-auto justify-end">
                    <button
                      type="button"
                      onClick={() => setShowCreateTag(false)}
                      className="h-8 px-2.5 rounded-lg border border-primary-100 text-gray-600 hover:bg-primary-50/50 font-label text-xs font-semibold transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleCreateTag}
                      disabled={creatingTag || !newTagName.trim() || !canManageOutbound}
                      title={canManageOutbound ? "Create tag" : "Read-only role: saving is disabled"}
                      className="h-8 px-3 rounded-lg bg-primary hover:bg-primary-dark text-white font-label text-xs font-bold shadow-[0_2px_8px_rgba(var(--primary-800-rgb),0.25)] hover:opacity-95 disabled:opacity-40 flex items-center gap-1.5 transition-all shrink-0"
                    >
                      {creatingTag && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                      <span>Create Tag</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Body Section */}
          {tagsListLoading || !tagsLoaded ? (
            <div className="py-20 flex flex-col items-center justify-center gap-3">
              <div className="w-7 h-7 border-2 border-[var(--primary-600)] border-t-transparent rounded-full animate-spin" />
              <p className="font-label text-xs font-medium text-gray-500">Loading tags...</p>
            </div>
          ) : filteredTagsList.length === 0 ? (
            /* Elevated Empty State */
            <div className="px-6 py-16 text-center">
              {tagsSearch ? (
                <div className="max-w-md mx-auto">
                  <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-50 border border-primary-100 text-[var(--primary-800)]">
                    <Search size={20} />
                  </div>
                  <h3 className="font-display text-base font-bold text-gray-900">No tags found</h3>
                  <p className="font-body text-xs text-gray-500 mt-1">
                    No tags match &ldquo;{tagsSearch}&rdquo;. Try another search term or clear the filter.
                  </p>
                  <button
                    type="button"
                    onClick={() => setTagsSearch("")}
                    className="mt-4 px-3.5 py-1.5 rounded-xl border border-primary-200 bg-white font-label text-xs font-semibold text-[var(--primary-800)] hover:bg-primary-50 transition-colors shadow-xs"
                  >
                    Clear Search
                  </button>
                </div>
              ) : (
                <div className="max-w-lg mx-auto">
                  {/* Glowing Icon Container */}
                  <div className="relative mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-100 via-primary-100 to-primary-50 border border-primary-200/70 shadow-[0_4px_20px_rgba(var(--primary-600-rgb),0.12)]">
                    <Tag size={28} className="text-[var(--primary-800)]" />
                    <Sparkles size={14} className="absolute -top-1 -right-1 text-[var(--primary-600)]" />
                  </div>

                  <h3 className="font-display text-lg font-bold text-gray-900">
                    No broadcast tags created yet
                  </h3>
                  <p className="font-body text-xs md:text-sm text-gray-500 mt-1.5 leading-relaxed max-w-md mx-auto">
                    Tags let you categorize outbound campaigns by product or offer so you can analyze response sentiment, audience interest, and delivery rates per segment.
                  </p>

                  {/* Primary CTA */}
                  <div className="mt-6 flex justify-center">
                    <button
                      type="button"
                      onClick={() => setShowCreateTag(true)}
                      className="flex h-8 items-center gap-1.5 px-3.5 rounded-lg bg-primary hover:bg-primary-dark text-white font-label text-xs font-bold shadow-[0_2px_8px_rgba(var(--primary-800-rgb),0.25)] hover:opacity-95 transition-all hover:scale-[1.02]"
                    >
                      <Plus size={14} />
                      <span>Create Your First Tag</span>
                    </button>
                  </div>

                  {/* Quick Starter Suggestions */}
                  <div className="mt-8 pt-6 border-t border-primary-50">
                    <p className="font-label text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2.5">
                      Suggested starter tags
                    </p>
                    <div className="flex flex-wrap items-center justify-center gap-2">
                      {[
                        { name: "VIP Customers", color: "var(--primary-500)" },
                        { name: "Product Launch", color: "#3B82F6" },
                        { name: "Flash Sale", color: "#F97316" },
                        { name: "Re-engagement", color: "#22C55E" },
                      ].map((item) => (
                        <button
                          key={item.name}
                          type="button"
                          onClick={() => {
                            setNewTagName(item.name);
                            setNewTagColor(item.color);
                            setCustomTagColor("");
                            setShowCreateTag(true);
                          }}
                          className="group inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary-50/70 border border-primary-100 hover:border-primary-200 hover:bg-primary-100/60 transition-all font-label text-xs font-medium text-gray-700 shadow-2xs"
                        >
                          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
                          <span>{item.name}</span>
                          <span className="text-gray-400 group-hover:text-[var(--primary-800)] text-[10px]">＋</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div>
              {/* Mobile View */}
              <div className="space-y-3 p-4 md:hidden">
                {tagPages.pageItems.map((tag) => {
                  const s = tagStats[tag.id];
                  const style = getTagStyle(tag.color);
                  return (
                    <div key={tag.id} className="rounded-2xl p-4 shadow-sm" style={{ background: style.background }}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className={cn("truncate font-label text-base font-bold drop-shadow-sm", style.colorClass)}>{tag.name}</p>
                          <p className={cn("mt-1 font-label text-xs drop-shadow-sm", style.colorClass)}>
                            {(s?.total_sent ?? 0).toLocaleString()} sent
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <SegmentDropdown tagId={tag.id} dark={style.colorClass === "text-white"} />
                          {canManageOutbound && (
                            <button onClick={() => handleDeleteTag(tag)} disabled={deletingTagId === tag.id} className={cn("rounded-lg p-2 transition-colors disabled:opacity-40", style.colorClass === "text-white" ? "text-white/80 hover:bg-white/20 hover:text-white" : "text-gray-600 hover:bg-red-50 hover:text-red-600")}>
                              {deletingTagId === tag.id ? <div className="h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin" /> : <Trash2 size={15} />}
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="mt-4 grid grid-cols-3 gap-2">
                        {[
                          ["Hot", s?.hot ?? 0],
                          ["Warm", s?.warm ?? 0],
                          ["Cold", s?.cold ?? 0],
                          ["DQ", s?.disqualified ?? 0],
                          ["Opted Out", s?.opted_out ?? 0],
                          ["Failed", s?.failed ?? 0],
                        ].map(([label, value]) => (
                          <div key={label} className="rounded-xl bg-white/25 px-2 py-2 text-center backdrop-blur-sm">
                            <p className={cn("font-label text-[10px] font-bold uppercase", style.colorClass)}>{label}</p>
                            <p className={cn("mt-0.5 font-display text-lg font-bold", style.colorClass)}>{value}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Desktop Table View */}
              <div className="overflow-x-auto">
                <table className="hidden w-full md:table">
                  <thead>
                    <tr className="border-b border-primary-100/70 bg-primary-50/40">
                      {["Tag", "Sent", "Hot", "Warm", "Cold"].map((h) => (
                        <th key={h} className={cn("font-label text-xs font-semibold text-gray-600 py-3", h === "Tag" ? "px-6" : "px-3 text-center")}>{h}</th>
                      ))}
                      <th className="font-label text-xs font-semibold text-red-600 text-center px-3 py-3">DQ</th>
                      <th className="font-label text-xs font-semibold text-orange-600 text-center px-3 py-3">Opted Out</th>
                      <th className="font-label text-xs font-semibold text-gray-500 text-center px-3 py-3">Failed</th>
                      <th className="font-label text-xs font-semibold text-gray-600 text-right px-6 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-primary-100/40">
                    {tagPages.pageItems.map((tag) => {
                      const s = tagStats[tag.id];
                      const style = getTagStyle(tag.color);
                      return (
                        <tr key={tag.id} className="hover:brightness-105 transition-all border-b border-surface-mid/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]" style={{ background: style.background }}>
                          <td className="px-6 py-3.5">
                            <span className={cn("font-label text-sm font-semibold drop-shadow-sm", style.colorClass)}>{tag.name}</span>
                          </td>
                          <td className={cn("px-3 py-3.5 text-center font-label text-sm font-medium drop-shadow-sm", style.colorClass)}>{s?.total_sent ?? 0}</td>
                          <td className={cn("px-3 py-3.5 text-center font-label text-sm font-bold drop-shadow-sm", style.colorClass)}>{s?.hot ?? 0}</td>
                          <td className={cn("px-3 py-3.5 text-center font-label text-sm font-bold drop-shadow-sm", style.colorClass)}>{s?.warm ?? 0}</td>
                          <td className={cn("px-3 py-3.5 text-center font-label text-sm font-medium drop-shadow-sm", style.colorClass)}>{s?.cold ?? 0}</td>
                          <td className={cn("px-3 py-3.5 text-center font-label text-sm font-bold drop-shadow-sm", style.colorClass)}>{s?.disqualified ?? 0}</td>
                          <td className={cn("px-3 py-3.5 text-center font-label text-sm font-bold drop-shadow-sm", style.colorClass)}>{s?.opted_out ?? 0}</td>
                          <td className={cn("px-3 py-3.5 text-center font-label text-sm font-medium drop-shadow-sm", style.colorClass)}>{s?.failed ?? 0}</td>
                          <td className="px-6 py-3.5">
                            <div className="flex items-center justify-end gap-2">
                              <SegmentDropdown tagId={tag.id} dark={style.colorClass === "text-white"} />
                              {canManageOutbound && (
                                <button onClick={() => handleDeleteTag(tag)} disabled={deletingTagId === tag.id} className={cn("p-1.5 rounded-lg transition-colors disabled:opacity-40", style.colorClass === "text-white" ? "text-white/70 hover:text-white hover:bg-white/20" : "text-gray-500 hover:text-red-600 hover:bg-red-50")}>
                                  {deletingTagId === tag.id ? <div className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" /> : <Trash2 size={14} />}
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <Pagination page={tagPages.page} total={tagPages.total} onPageChange={tagPages.setPage} noun="tags" />
        </div>
      )}

      {activeTab === "opted-out" && (
        <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-orange-100 bg-gradient-to-r from-orange-50/80 to-white px-4 py-2.5 md:px-6">
            <ShieldCheck size={14} className="shrink-0 text-orange-600" />
            <p className="font-body text-xs text-gray-500">
              People who said stop. Campaigns skip them: from all broadcasts, or from one tag only.
            </p>
            {optedOutLoaded && !optedOutError && optedOutList.length > 0 && (
              <span className="ml-auto shrink-0 rounded-full bg-orange-100/70 px-2 py-0.5 font-label text-[11px] font-semibold text-orange-800">
                {optedOutList.length.toLocaleString()} {optedOutList.length === 1 ? "person" : "people"}
              </span>
            )}
          </div>

          {optedOutLoading || !optedOutLoaded ? (
            <div className="py-12 flex items-center justify-center">
              <div className="w-6 h-6 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : optedOutError ? (
            <div className="py-16 flex flex-col items-center justify-center gap-3">
              <div className="w-14 h-14 rounded-2xl bg-red-50 flex items-center justify-center">
                <AlertTriangle size={24} className="text-red-400" />
              </div>
              <div className="text-center">
                <p className="font-display text-sm font-semibold text-gray-700">Couldn&apos;t load the opted-out list</p>
                <p className="font-body text-xs text-gray-500 mt-1">Something went wrong on our side. Your opt-outs are safe.</p>
              </div>
              <button
                onClick={loadOptedOut}
                className="inline-flex h-8 items-center gap-1.5 px-3 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 font-label text-xs font-semibold text-gray-700 transition-colors"
              >
                <RotateCcw size={12} /> Try again
              </button>
            </div>
          ) : optedOutList.length === 0 ? (
            <div className="py-16 flex flex-col items-center justify-center gap-3">
              <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center">
                <ShieldCheck size={24} className="text-gray-400" />
              </div>
              <div className="text-center">
                <p className="font-display text-sm font-semibold text-gray-700">No opted-out leads</p>
                <p className="font-body text-xs text-gray-500 mt-1">Nobody has opted out of your broadcasts yet</p>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px]">
                <thead>
                  <tr className="border-b border-[#f1f5f9]">
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b] whitespace-nowrap">Name</th>
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b] whitespace-nowrap">Stopped from</th>
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b] whitespace-nowrap">How</th>
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b] whitespace-nowrap">Last broadcast</th>
                    <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b] whitespace-nowrap">Said stop on</th>
                    <th className="px-4 py-3 text-right text-[10px] font-bold uppercase tracking-wider text-[#64748b] whitespace-nowrap">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {optedOutPages.pageItems.map((lead) => {
                    const key = `${lead.lead_id}:${lead.tag_id ?? ""}`;
                    const who = lead.name || lead.phone || "Customer";
                    const initials = (lead.name || "").trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("");
                    const how = (lead.source && STOP_HOW[lead.source]) || "Said stop";
                    return (
                      <tr key={key} className="border-t border-[#f1f5f9] transition-colors hover:bg-[#f8fafc]">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2.5">
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-orange-100 text-[11px] font-bold text-orange-700">
                              {initials || <Users size={15} aria-hidden="true" />}
                            </div>
                            <div className="min-w-0">
                              <div className="whitespace-nowrap text-sm font-bold text-[#0A1528]">{who}</div>
                              {lead.name && lead.phone && (
                                <div className="whitespace-nowrap text-xs tabular-nums text-[#64748b]">{lead.phone}</div>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            title={lead.scope === "global" ? "No campaign is sent to them, whatever the tag." : "Only campaigns under this tag skip them."}
                            className={cn(
                              "inline-block max-w-[160px] truncate rounded-full border px-2 py-0.5 align-middle text-[11px] font-semibold whitespace-nowrap",
                              lead.scope === "global" ? "border-red-100 bg-red-50 text-red-700" : "border-primary-100 bg-primary-50 text-primary-700"
                            )}
                          >
                            {lead.scope === "global" ? "All broadcasts" : `Only ${lead.tag_name || "one tag"}`}
                          </span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-[#334155]">{how}</td>
                        <td className="max-w-[280px] px-4 py-3">
                          {lead.last_campaign ? (
                            <>
                              <div className="truncate text-sm text-[#334155]" title={lead.last_campaign}>{lead.last_campaign}</div>
                              {lead.last_campaign_at && (
                                <div className="whitespace-nowrap text-xs text-[#64748b]">Sent {istDate(lead.last_campaign_at)}</div>
                              )}
                            </>
                          ) : (
                            <span className="text-sm text-[#94a3b8]">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-xs tabular-nums text-[#64748b]">
                          {lead.opted_out_at ? istDateTime(lead.opted_out_at) : "—"}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1.5">
                            <Link
                              href={`/dashboard/conversations?lead=${encodeURIComponent(lead.lead_id)}`}
                              className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg border border-gray-200 bg-white px-3 text-[11px] font-semibold text-gray-700 transition-colors hover:border-primary-200 hover:bg-primary-50 hover:text-primary-700"
                            >
                              <MessageSquare size={12} /> Open chat
                            </Link>
                            {canManageOutbound && (
                              <button
                                onClick={() => reactivateOptedOut(lead)}
                                disabled={reactivatingId === key}
                                className="inline-flex h-8 items-center whitespace-nowrap rounded-lg border border-gray-200 bg-white px-3 text-[11px] font-semibold text-gray-700 transition-colors hover:border-green-200 hover:bg-green-50 hover:text-green-700 disabled:opacity-50"
                              >
                                {reactivatingId === key ? "Reactivating…" : "Reactivate"}
                              </button>
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
          <Pagination page={optedOutPages.page} total={optedOutPages.total} onPageChange={optedOutPages.setPage} noun="people" />
        </div>
      )}

      {activeTab === "history" && (
      <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-lg">
        <div className="border-b border-primary-100/70 bg-gradient-to-r from-primary-50/80 via-primary-50/30 to-white px-4 py-2.5 md:px-6">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-2">
              <Clock size={14} className="shrink-0 text-[var(--primary-800)]" />
              <p className="font-body text-xs text-gray-500">Last 50 campaign dispatches for your account · live counts</p>
              {historyRefreshing && (
                <span className="inline-flex items-center gap-1 font-label text-[11px] font-semibold text-[var(--primary-800)]">
                  <RefreshCw size={11} className="animate-spin" /> Updating…
                </span>
              )}
            </div>
            {!historyLoading && broadcastHistory.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <div className="relative">
                  <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search…"
                    value={historySearch}
                    onChange={(e) => setHistorySearch(e.target.value)}
                    className="w-full min-w-0 pl-8 pr-3 py-1.5 font-body text-xs bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary-600)]/20 focus:border-[var(--primary-600)] transition-all sm:min-w-40"
                  />
                </div>
                <button
                  onClick={downloadHistoryCsv}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-primary hover:bg-primary-dark text-white rounded-lg font-label text-xs font-semibold hover:opacity-95 transition-all shadow-[0_2px_8px_rgba(var(--primary-800-rgb),0.25)]"
                >
                  <Download size={12} />
                  Download list
                </button>
                <div className="flex bg-white border border-gray-200 rounded-lg overflow-hidden">
                  {(["all", "failures", "clean"] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => setHistoryStatusFilter(f)}
                      className={cn(
                        "px-2.5 py-1.5 font-label text-xs font-semibold transition-all",
                        historyStatusFilter === f
                          ? "bg-primary hover:bg-primary-dark text-white font-bold shadow-xs"
                          : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                      )}
                    >
                      {f === "all" ? "All" : f === "failures" ? "Failures" : "Clean"}
                    </button>
                  ))}
                </div>
                <button
                  onClick={refreshHistory}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 rounded-lg font-label text-xs font-semibold text-gray-700 hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm"
                >
                  <RotateCcw size={12} />
                  Refresh
                </button>
              </div>
            )}
          </div>
        </div>

        {historyLoading ? (
          <div className="py-12 flex items-center justify-center">
            <div className="w-6 h-6 border-2 border-[var(--primary-600)] border-t-transparent rounded-full animate-spin" />
          </div>
        ) : broadcastHistory.length === 0 ? (
          <div className="py-16 flex flex-col items-center justify-center gap-3">
            <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center">
              <Send size={24} className="text-gray-400" />
            </div>
            <div className="text-center">
              <p className="font-display text-sm font-semibold text-gray-700">No broadcasts yet</p>
              <p className="font-body text-xs text-gray-500 mt-1">Send your first campaign to see history here</p>
            </div>
          </div>
        ) : filteredHistory.length === 0 ? (
          <div className="py-16 flex flex-col items-center justify-center gap-3">
            <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center">
              <Search size={24} className="text-gray-400" />
            </div>
            <div className="text-center">
              <p className="font-display text-sm font-semibold text-gray-700">No matches found</p>
              <p className="font-body text-xs text-gray-500 mt-1">Try a different search or filter</p>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {historyPages.pageItems.map((item, i) => (
              <div key={i} className="p-4 first:pt-4 last:pb-4 md:p-6">
                {/* Campaign Info Bar */}
                <div className="flex items-center gap-2 mb-3 pb-3 border-b border-gray-100 flex-wrap xl:flex-nowrap">
                  {/* Date */}
                  <div className="flex min-w-0 items-center gap-1.5 sm:min-w-[140px] sm:shrink-0">
                    <Calendar size={14} className="text-gray-400 shrink-0" />
                    <span className="font-display text-xs font-semibold text-gray-800">
                      {new Date(item.timestamp).toLocaleString("en-IN", { 
                        day: "numeric", 
                        month: "short", 
                        year: "numeric",
                        hour: "2-digit", 
                        minute: "2-digit",
                        hour12: false 
                      })}
                    </span>
                  </div>
                  
                  {/* Template Badge */}
                  <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 font-label text-[11px] font-semibold border border-emerald-100 shrink-0 whitespace-nowrap">
                    {item.template_name}
                  </span>
                  {item.tag_name && (
                    <span className="px-2.5 py-1 rounded-full bg-primary-50 text-primary-700 font-label text-[11px] font-semibold border border-primary-100 shrink-0 whitespace-nowrap">
                      {item.tag_name}
                    </span>
                  )}
                  {item.broadcast_id && (
                    <span className="max-md:hidden px-2.5 py-1 rounded-full bg-gray-50 text-gray-600 font-label text-[10px] font-mono border border-gray-200 shrink-0 whitespace-nowrap" title={`Broadcast ID: ${item.broadcast_id}`}>
                      ID: {item.broadcast_id.slice(0, 8)}
                    </span>
                  )}
                  
                  {/* Spacer */}
                  <div className="hidden min-w-[20px] flex-1 sm:block" />
                  
                  {/* Phone Number */}
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Phone size={12} className="text-gray-400" />
                    <span className="font-body text-xs text-gray-600 font-medium whitespace-nowrap">{item.number_used || "—"}</span>
                  </div>
                  
                  {/* Customers group this went to */}
                  {item.audience_type === "group" && (
                    <span className="inline-flex items-center gap-1 px-2 py-1 bg-gray-50 text-gray-700 rounded-md font-label text-xs font-semibold border border-gray-200 shrink-0 whitespace-nowrap" title={item.group_name ? `Group: ${item.group_name}` : "Customers group"}>
                      <Users size={12} />
                      {item.group_name ? (item.group_name.length > 24 ? item.group_name.slice(0, 23) + "…" : item.group_name) : "Customers group"}
                    </span>
                  )}

                  {/* CSV Download */}
                  {(item.csv_file_path || item.csv_file_url) && (
                    <button
                      onClick={() => openBroadcastCsv(item)}
                      className="inline-flex h-8 items-center gap-1.5 px-3 rounded-lg border font-label text-[11px] font-semibold transition-colors shrink-0 whitespace-nowrap bg-white hover:bg-gray-50 text-gray-700 border-gray-200"
                    >
                      <Download size={12} />
                      {item.csv_file_name && item.csv_file_name.length > 15
                        ? item.csv_file_name.slice(0, 8) + "..." + item.csv_file_name.slice(-4)
                        : item.csv_file_name || "CSV"}
                    </button>
                  )}
                  
                  {/* Delivered / Opened / Failed leads CSV */}
                  {item.broadcast_id && (
                    <div className="shrink-0">
                      <BroadcastLeadsDropdown
                        broadcastId={item.broadcast_id}
                        counts={{ delivered: item.delivered, opened: item.opened, failed: item.failed }}
                        onDownload={downloadLeadsCsv}
                      />
                    </div>
                  )}

                  {/* Interest CSV Download */}
                  {item.broadcast_id && (
                    <div className="shrink-0">
                      <BroadcastSegmentDropdown
                        broadcastId={item.broadcast_id}
                        tagId={item.tag_id}
                        onDownload={downloadBroadcastTagCsv}
                      />
                    </div>
                  )}

                  {/* One campaign's results: paid, said stop, who paid */}
                  {item.broadcast_id && item.sent > 0 && (
                    <button
                      onClick={() => setResultsFor({ id: item.broadcast_id!, title: item.template_name })}
                      className="inline-flex h-8 items-center gap-1.5 px-3 rounded-lg border font-label text-[11px] font-semibold transition-colors shrink-0 whitespace-nowrap bg-white hover:bg-gray-50 text-gray-700 border-gray-200"
                    >
                      <BarChart3 size={12} />
                      Results
                    </button>
                  )}

                  {/* Delete history entry */}
                  {item.broadcast_id && canManageOutbound && (
                    <button
                      onClick={() => handleDeleteHistoryEntry(item.broadcast_id!)}
                      disabled={deletingHistoryId === item.broadcast_id}
                      title="Remove from history"
                      className="inline-flex h-8 w-8 items-center justify-center max-md:ml-3 bg-white hover:bg-red-50 text-gray-400 hover:text-red-600 rounded-lg transition-colors border border-gray-200 hover:border-red-200 shrink-0 disabled:opacity-50"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
                
                {/* One line: what it earned, who said stop / was left out, how people replied and how warm they are */}
                {(() => {
                  const chip = "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-label text-xs font-semibold";
                  const chips: ReactNode[] = [];
                  if (item.paid_count !== undefined && item.paid_count !== null) chips.push(
                    <span key="paid" className={cn(chip, "bg-green-50 border-green-200 text-green-800")} title="People who bought within 7 days of getting this message. Each person counts once, for their first order.">
                      Paid within 7 days: {item.paid_count.toLocaleString()}
                      {item.paid_amount_inr !== undefined && item.paid_amount_inr !== null && ` · ₹${item.paid_amount_inr.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
                      {item.paid_window_open && <span className="font-normal text-green-700">(still counting)</span>}
                    </span>);
                  if (item.back_per_rupee !== undefined && item.back_per_rupee !== null) chips.push(
                    <span key="roi" className={cn(chip, "bg-green-50 border-green-200 text-green-800")} title="Rupees paid by these people, divided by the cost of the messages sent (an estimate at the standard rate).">
                      ₹{item.back_per_rupee.toLocaleString("en-IN", { maximumFractionDigits: 2 })} back per ₹1 (estimated)
                    </span>);
                  if ((item.said_stop ?? 0) > 0) chips.push(
                    <span key="stop" className={cn(chip, "bg-gray-50 border-gray-200 text-gray-700")}>{item.said_stop!.toLocaleString()} said stop</span>);
                  if ((item.skipped_monthly_limit ?? 0) > 0) chips.push(
                    <span key="monthly" className={cn(chip, "bg-gray-50 border-gray-200 text-gray-700")}>{item.skipped_monthly_limit!.toLocaleString()} skipped: monthly limit</span>);
                  if ((item.skipped_blocked ?? 0) > 0) chips.push(
                    <span key="blocked" className={cn(chip, "bg-gray-50 border-gray-200 text-gray-700")}>{item.skipped_blocked!.toLocaleString()} skipped: blocked</span>);
                  if ((item.replied_positive ?? 0) > 0) chips.push(
                    <span key="pos" className={cn(chip, "bg-green-50 border-green-200 text-green-700")}>
                      <span className="w-1.5 h-1.5 rounded-full bg-green-500" />{item.replied_positive} positive repl{item.replied_positive === 1 ? "y" : "ies"}
                    </span>);
                  if ((item.replied_negative ?? 0) > 0) chips.push(
                    <span key="neg" className={cn(chip, "bg-red-50 border-red-200 text-red-700")}>
                      <span className="w-1.5 h-1.5 rounded-full bg-red-500" />{item.replied_negative} said no
                    </span>);
                  if ((item.replied_neutral ?? 0) > 0) chips.push(
                    <span key="neu" className={cn(chip, "bg-gray-50 border-gray-200 text-gray-600")}>
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />{item.replied_neutral} neutral
                    </span>);
                  if ((item.hot ?? 0) > 0) chips.push(
                    <span key="hot" className={cn(chip, "bg-orange-50 border-orange-200 text-orange-700")}>🔥 {item.hot} hot</span>);
                  if ((item.warm ?? 0) > 0) chips.push(
                    <span key="warm" className={cn(chip, "bg-amber-50 border-amber-200 text-amber-700")}>✦ {item.warm} warm</span>);
                  if ((item.cold ?? 0) > 0) chips.push(
                    <span key="cold" className={cn(chip, "bg-sky-50 border-sky-200 text-sky-700")}>❄ {item.cold} cold</span>);
                  return chips.length > 0 ? <div className="flex flex-wrap gap-2 mb-3">{chips}</div> : null;
                })()}

                {/* Metrics Grid - 4 Equal Columns */}
                <div className="grid grid-cols-2 gap-2 md:gap-3 xl:grid-cols-4">
                  {/* Sent */}
                  <div className="bg-blue-50/50 rounded-xl p-2 md:p-3 border border-blue-100/50">
                    <div className="flex items-center gap-2 mb-1.5 md:mb-2">
                      <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
                        <Send size={16} className="text-blue-600" />
                      </div>
                      <div className="flex-1">
                        <p className="font-display text-sm font-bold text-gray-900">
                          Sent <span className="text-blue-600 font-semibold">({Math.round((item.sent / item.total_leads) * 100)}%)</span>
                        </p>
                        <p className="font-body text-[11px] text-gray-500 mt-0.5 max-md:hidden">{item.sent} of {item.total_leads} leads</p>
                      </div>
                    </div>
                    <div className="w-full h-2 bg-blue-100 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-blue-500 rounded-full transition-all duration-700 ease-out" 
                        style={{ width: `${(item.sent / item.total_leads) * 100}%` }} 
                      />
                    </div>
                  </div>
                  
                  {/* Delivered */}
                  <div className="bg-emerald-50/50 rounded-xl p-2 md:p-3 border border-emerald-100/50">
                    <div className="flex items-center gap-2 mb-1.5 md:mb-2">
                      <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center shrink-0">
                        <CheckCircle2 size={16} className="text-emerald-600" />
                      </div>
                      <div className="flex-1">
                        <p className="font-display text-sm font-bold text-gray-900">
                          Delivered <span className="text-emerald-600 font-semibold">({Math.round(((item.delivered || 0) / item.total_leads) * 100)}%)</span>
                        </p>
                        <p className="font-body text-[11px] text-gray-500 mt-0.5 max-md:hidden">{item.delivered || 0} of {item.total_leads} leads</p>
                      </div>
                    </div>
                    <div className="w-full h-2 bg-emerald-100 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-emerald-500 rounded-full transition-all duration-700 ease-out" 
                        style={{ width: `${((item.delivered || 0) / item.total_leads) * 100}%` }} 
                      />
                    </div>
                  </div>
                  
                  {/* Opened */}
                  <div className="bg-amber-50/50 rounded-xl p-2 md:p-3 border border-amber-100/50">
                    <div className="flex items-center gap-2 mb-1.5 md:mb-2">
                      <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
                        <Eye size={16} className="text-amber-600" />
                      </div>
                      <div className="flex-1">
                        <p className="font-display text-sm font-bold text-gray-900">
                          Opened <span className="text-amber-600 font-semibold">({Math.round(((item.opened || 0) / item.total_leads) * 100)}%)</span>
                        </p>
                        <p className="font-body text-[11px] text-gray-500 mt-0.5 max-md:hidden">{item.opened || 0} of {item.total_leads} leads</p>
                      </div>
                    </div>
                    <div className="w-full h-2 bg-amber-100 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-amber-500 rounded-full transition-all duration-700 ease-out" 
                        style={{ width: `${((item.opened || 0) / item.total_leads) * 100}%` }} 
                      />
                    </div>
                  </div>
                  
                  {/* Failed */}
                  <div className="bg-red-50/50 rounded-xl p-2 md:p-3 border border-red-100/50">
                    <div className="flex items-center gap-2 mb-1.5 md:mb-2">
                      <div className="w-8 h-8 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                        <XCircle size={16} className="text-red-600" />
                      </div>
                      <div className="flex-1">
                        <p className="font-display text-sm font-bold text-gray-900">
                          Failed <span className="text-red-600 font-semibold">({Math.round(((item.failed || 0) / item.total_leads) * 100)}%)</span>
                        </p>
                        <p className="font-body text-[11px] text-gray-500 mt-0.5 max-md:hidden">{item.failed || 0} of {item.total_leads} leads</p>
                      </div>
                    </div>
                    <div className="w-full h-2 bg-red-100 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-red-500 rounded-full transition-all duration-700 ease-out" 
                        style={{ width: `${((item.failed || 0) / item.total_leads) * 100}%` }} 
                      />
                    </div>
                  </div>
                </div>

                <p className="max-md:hidden mt-2.5 flex items-start gap-1.5 font-body text-[11px] text-gray-400">
                  <Info size={12} className="mt-0.5 shrink-0" />
                  <span>
                    Delivered and Opened are counted <em>within</em> Sent, not extra leads — every Sent lead is either Delivered, Opened, or still waiting on a receipt from WhatsApp (can take a few minutes). Only Failed leads never got the message.
                  </span>
                </p>

              </div>
            ))}
          </div>
        )}
        <Pagination page={historyPages.page} total={historyPages.total} onPageChange={historyPages.setPage} noun="broadcasts" />
      </div>
      )}
      {resultsFor && <CampaignResultsDrawer broadcastId={resultsFor.id} title={resultsFor.title} onClose={() => setResultsFor(null)} />}
    </div>
  );
}

/** v9.2 #116: check what we read off a notebook photo — type names we couldn't read, fix or remove wrong numbers. */
function ScanReview({ rows, onChange, onUse, onCancel, busy }: {
  rows: ScanRow[]; onChange: (rows: ScanRow[]) => void; onUse: () => void; onCancel: () => void; busy: boolean;
}) {
  const checks = rows.map(checkRow);
  const wrong = checks.filter((c) => c.phoneWrong).length;
  const noName = checks.filter((c) => c.nameMissing).length;
  const set = (i: number, patch: Partial<ScanRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <section aria-label="Check what we read" className="rounded-xl border border-primary/20 bg-white p-4 space-y-3">
      <div>
        <p className="font-display text-sm font-bold text-on-surface">Check what we read from the photo</p>
        <p className="font-body text-xs text-on-surface-muted mt-0.5" aria-live="polite">
          {rows.length} {rows.length === 1 ? "person" : "people"} found.
          {noName > 0 && (noName === 1 ? " 1 name we couldn't read — type it in or leave it blank." : ` ${noName} names we couldn't read — type them in or leave them blank.`)}
          {wrong > 0 && (wrong === 1 ? " 1 number looks wrong — fix or remove it." : ` ${wrong} numbers look wrong — fix or remove them.`)}
          {noName === 0 && wrong === 0 && " Everything looks readable."}
        </p>
      </div>
      <div className="max-h-80 overflow-y-auto rounded-lg border border-surface-mid divide-y divide-surface-mid">
        {rows.map((r, i) => (
          <div key={i} className={cn("flex items-center gap-2 px-3 py-2", checks[i].phoneWrong && "bg-red-50/60")}>
            <span className="w-6 shrink-0 text-right font-label text-[11px] text-on-surface-muted">{i + 1}</span>
            <input
              aria-label={`Name on line ${i + 1}`}
              value={checks[i].nameMissing && /\?|unclear|illegible|unreadable/i.test(r.name) ? "" : r.name}
              placeholder={checks[i].nameMissing ? "Couldn't read — type the name" : "Name"}
              onChange={(e) => set(i, { name: e.target.value })}
              className={cn("min-w-0 flex-1 rounded-md border px-2 py-1 font-body text-sm",
                checks[i].nameMissing ? "border-amber-300 bg-amber-50 placeholder:text-amber-700" : "border-surface-mid bg-white")}
            />
            <input
              aria-label={`Phone on line ${i + 1}`}
              aria-invalid={checks[i].phoneWrong}
              aria-describedby={checks[i].phoneWrong ? `scan-phone-wrong-${i}` : undefined}
              value={r.phone}
              inputMode="tel"
              onChange={(e) => set(i, { phone: e.target.value })}
              className={cn("w-36 shrink-0 rounded-md border px-2 py-1 font-body text-sm tabular-nums",
                checks[i].phoneWrong ? "border-red-300 bg-red-50 text-red-800" : "border-surface-mid bg-white")}
            />
            {checks[i].phoneWrong && (
              <span id={`scan-phone-wrong-${i}`} className="font-label text-[11px] text-red-700 shrink-0">
                <AlertTriangle size={12} className="inline sm:hidden" aria-hidden="true" />
                <span className="sr-only sm:not-sr-only">Looks wrong</span>
              </span>
            )}
            <button type="button" aria-label={`Remove line ${i + 1}`} onClick={() => onChange(rows.filter((_, j) => j !== i))}
              className="shrink-0 rounded-md p-1 text-on-surface-muted hover:bg-surface-low hover:text-red-700">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onUse} disabled={busy || rows.length === 0}
          className="rounded-lg bg-primary px-4 py-2 font-label text-sm font-semibold text-white disabled:opacity-50">
          Use these {rows.length}
        </button>
        {wrong > 0 && (
          <button type="button" onClick={() => onChange(rows.filter((r) => !checkRow(r).phoneWrong))}
            className="rounded-lg border border-red-200 px-3 py-2 font-label text-sm text-red-700 hover:bg-red-50">
            Remove the {wrong} wrong number{wrong === 1 ? "" : "s"}
          </button>
        )}
        <button type="button" onClick={onCancel} className="rounded-lg px-3 py-2 font-label text-sm text-on-surface-muted hover:bg-surface-low">
          Start again
        </button>
      </div>
    </section>
  );
}
