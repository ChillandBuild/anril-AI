"use client";

import { toast } from "sonner";
import { useEffect, useState, useCallback, Suspense, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  X, Check, Trash2, PauseCircle, PlayCircle, Star, RefreshCw,
  Info, ChevronDown, ChevronUp, ChevronRight, Lock, Copy, Phone,
  ShieldCheck, Activity, CheckCircle2,
  Search, ArrowRightLeft, ExternalLink, ShieldAlert, Hourglass, Sunrise
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { AiraLoader } from "@/components/AiraLoader";
import { usePolling } from "@/hooks/usePolling";
import { cn } from "@/lib/utils";
import { KpiCard } from "@/components/kpi-card";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { Loader2 } from "lucide-react";

// ── Types ───────────────────────────────────────────────────────────────────

type QualityRating = "green" | "yellow" | "red";

type NumberHealth = {
  state: "archived" | "meta_pending" | "resting" | "warming" | "active";
  meta_status: string | null;
  meta_code_verification: string | null;
  warm_up_day: number;
  warm_up_days: number;
  rest_day: number;
  rest_days: number;
  broadcast_cap: number | null;
  // Meta's measure: people sent a template outside their 24h window, last 24 hours.
  sent_24h?: number;
};

type NumbersPool = { limit: number; used: number; meta_limit?: number | null; meta_sent_24h?: number };

type PhoneNumber = {
  id: string;
  provider: "meta_cloud";
  number: string;
  display_name: string;
  role: "primary" | "standby" | "archived";
  status: "active" | "warming" | "restricted" | "archived";
  quality_rating: QualityRating | null;
  messaging_tier: number | null;
  warm_up_day: number;
  paused_outbound: boolean;
  meta_phone_number_id?: string | null;
  created_at: string;
  locked: boolean;
  meta_status?: string | null;
  meta_code_verification?: string | null;
  warm_up_started_at?: string | null;
  rested_since?: string | null;
  health?: NumberHealth;
};

const QUALITY_COLOR: Record<QualityRating, string> = {
  green: "bg-emerald-500",
  yellow: "bg-amber-500",
  red: "bg-red-500",
};

const QUALITY_LABEL: Record<QualityRating, string> = {
  green: "High",
  yellow: "Medium",
  red: "Low",
};

const QUALITY_BG: Record<QualityRating, string> = {
  green: "bg-emerald-50 text-emerald-700 border-emerald-200",
  yellow: "bg-amber-50 text-amber-700 border-amber-200",
  red: "bg-red-50 text-red-700 border-red-200",
};

// Meta's portfolio-level messaging limits (unique people per rolling 24h).
// The backend stores Meta's TIER_UNLIMITED as 1,000,000.
const UNLIMITED_TIER = 1_000_000;

const TIER_LABELS: Record<number, string> = {
  250: "250 / day · Starter",
  1000: "1,000 / day · Legacy",
  2000: "2,000 / day · Tier 1",
  10000: "10,000 / day · Tier 2",
  100000: "100,000 / day · Tier 3",
  [UNLIMITED_TIER]: "Unlimited · Tier 4",
};

function getTierLabel(tier: number): string {
  return TIER_LABELS[tier] ?? `${tier.toLocaleString()} / day`;
}

function formatLimit(tier: number): string {
  return tier >= UNLIMITED_TIER ? "Unlimited" : tier.toLocaleString();
}

// "RATE_LIMITED" -> "Rate limited"
function formatMetaStatus(status: string): string {
  const words = status.toLowerCase().replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `API error ${res.status}`);
  }
  return res.json();
}

// ── Tier Guide Banner ─────────────────────────────────────────────────────────

function TierGuide({
  isOpen,
  onToggleOpen,
  visible = true,
  onDismiss,
}: {
  isOpen?: boolean;
  onToggleOpen?: () => void;
  visible?: boolean;
  onDismiss?: () => void;
}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const [isFading, setIsFading] = useState(false);

  const open = isOpen !== undefined ? isOpen : internalOpen;
  const toggleOpen = onToggleOpen ?? (() => setInternalOpen((v) => !v));

  useEffect(() => {
    // If the guide is open to read, don't dismiss
    if (open) return;

    // Disappear after 15 seconds
    const timer = setTimeout(() => {
      setIsFading(true);
      const hideTimer = setTimeout(() => {
        onDismiss?.();
      }, 500);
      return () => clearTimeout(hideTimer);
    }, 15000);

    return () => clearTimeout(timer);
  }, [open, onDismiss]);

  const handleManualDismiss = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsFading(true);
    setTimeout(() => {
      onDismiss?.();
    }, 350);
  };

  if (!visible) return null;

  const tiers = [
    { limit: "250 / day", label: "Starter", color: "bg-red-50 text-red-700 border-red-200", trigger: "Where every new portfolio starts" },
    { limit: "2,000 / day", label: "Tier 1", color: "bg-amber-50 text-amber-700 border-amber-200", trigger: "Verify your business, or send 2,000 good-quality template messages in 30 days. Meta then reviews." },
    { limit: "10,000 / day", label: "Tier 2", color: "bg-blue-50 text-blue-700 border-blue-200", trigger: "Automatic: use half your limit in 7 days with high-quality messages" },
    { limit: "100,000 / day", label: "Tier 3", color: "bg-primary-50 text-primary-700 border-primary-200", trigger: "Automatic: same rule" },
    { limit: "Unlimited", label: "Tier 4", color: "bg-emerald-50 text-emerald-700 border-emerald-200", trigger: "Automatic: same rule" },
  ];

  return (
    <div
      className={cn(
        "rounded-2xl border border-primary-200/70 bg-gradient-to-br from-primary-50/40 via-white to-blue-50/30 overflow-hidden shadow-xs transition-all duration-300",
        isFading
          ? "opacity-0 -translate-y-1 max-h-0 pointer-events-none border-transparent py-0"
          : "opacity-100 max-h-[1000px]"
      )}
    >
      <div
        onClick={toggleOpen}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left hover:bg-primary-50/50 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
            <Info size={15} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-sm font-bold text-on-surface">
              How WhatsApp messaging limits work
            </span>
            <span className="px-2 py-0.5 rounded-full bg-primary-100/80 text-primary font-label text-[10px] font-bold">
              Portfolio-level · Since Oct 2025
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-primary font-label text-xs font-semibold">
          <span className="hover:underline flex items-center gap-1">
            {open ? "Hide guide" : "View guide"}
            {open ? (
              <ChevronUp size={15} className="text-primary shrink-0" />
            ) : (
              <ChevronDown size={15} className="text-primary shrink-0" />
            )}
          </span>
          <button
            type="button"
            onClick={handleManualDismiss}
            className="p-1 rounded-lg hover:bg-primary-100 text-on-surface-muted hover:text-on-surface transition-colors ml-1"
            title="Dismiss notice"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {open && (
        <div className="px-5 pb-5 pt-1 border-t border-primary-100/80 space-y-4">
          <p className="font-body text-xs text-on-surface-muted leading-relaxed">
            Meta sets <strong>one limit for your whole business portfolio</strong>. Every number shares it, so adding numbers doesn&apos;t add capacity.
            The limit counts <strong>unique people you message outside a 24-hour customer-service window</strong>, in any rolling 24 hours. Replies inside that window don&apos;t count.
          </p>

          {/* Tier progression cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-2.5">
            {tiers.map((t, idx) => (
              <div key={t.label} className="p-3 rounded-xl bg-white border border-border/70 shadow-2xs flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between gap-1 mb-1.5">
                    <span className={`px-2 py-0.5 rounded-md font-label text-[10px] font-bold border ${t.color}`}>
                      {t.label}
                    </span>
                    <span className="font-mono text-[10px] text-on-surface-muted font-bold">#{idx + 1}</span>
                  </div>
                  <p className="font-display text-sm font-bold text-on-surface">{t.limit}</p>
                </div>
                <p className="font-body text-[11px] text-on-surface-muted mt-2 leading-tight">{t.trigger}</p>
              </div>
            ))}
          </div>

          {/* Key rules */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 pt-1">
            {[
              { icon: "✅", title: "Verify your business", text: "Fastest route to 2,000/day. Meta still checks your message quality before approving." },
              { icon: "✅", title: "Message opted-in people", text: "Relevant templates to people who asked to hear from you keep quality high." },
              { icon: "✅", title: "Use half your limit in 7 days", text: "With high-quality messages, Meta raises you one level within 6 hours." },
              { icon: "❌", title: "Avoid cold lists", text: "Blocks and reports lower your quality. Low quality stops upgrades, and if it stays low Meta can cut your limit." },
            ].map((r, i) => (
              <div key={i} className="flex items-start gap-2.5 bg-white/90 rounded-xl p-3 border border-border/60">
                <span className="text-sm shrink-0 mt-0.5">{r.icon}</span>
                <div>
                  <p className="font-label text-xs font-bold text-on-surface">{r.title}</p>
                  <p className="font-body text-[11px] text-on-surface-muted leading-relaxed mt-0.5">{r.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Quality: what to do next ─────────────────────────────────────────────────

type MetaHealth = {
  quality_rating: string;
  quality_reasons: string[];
  can_send_message: string | null;
  notes: string[];
  errors: { code: number | null; description: string | null; solution: string | null }[];
};

const SEND_STATE: Record<string, { label: string; className: string }> = {
  AVAILABLE: { label: "Can send", className: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  LIMITED: { label: "Sending limited", className: "bg-amber-50 text-amber-800 border-amber-200" },
  BLOCKED: { label: "Sending blocked", className: "bg-red-50 text-red-700 border-red-200" },
};

const WHATSAPP_MANAGER_URL = "https://business.facebook.com/wa/manage/phone-numbers/";

function QualityNextSteps({ num, hasStandby }: { num: PhoneNumber; hasStandby: boolean }) {
  const [health, setHealth] = useState<MetaHealth | null>(null);
  const [failed, setFailed] = useState(false);
  const isLow = num.quality_rating === "red";

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    apiFetch<MetaHealth>(`/api/v1/numbers/${num.id}/meta-health`)
      .then((h) => { if (!cancelled) setHealth(h); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [num.id, num.quality_rating]);

  const steps = [
    "Pause cold or bulk Marketing broadcasts. Message only people who opted in or chatted with you recently.",
    "Keep templates relevant and add a “Stop” quick reply, so people opt out instead of blocking.",
    ...(isLow && !hasStandby
      ? ["Add a standby number. When Meta flags a number Low, Anril moves sending to the standby."]
      : []),
    isLow
      ? "Quality recovers as blocks stop. If it stays Low, Meta can lower your messaging limit."
      : "If blocks continue, quality drops to Low and upgrades stop.",
  ];

  const metaLines = [...(health?.quality_reasons ?? []), ...(health?.notes ?? [])];
  const sendState = health?.can_send_message ? SEND_STATE[health.can_send_message] : undefined;

  return (
    <div className={cn(
      "mt-4 rounded-xl border p-4 grid gap-4 md:grid-cols-2",
      isLow ? "border-red-200/80 bg-red-50/40" : "border-amber-200/80 bg-amber-50/40"
    )}>
      {/* Meta's own explanation, read live */}
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldAlert size={15} className={isLow ? "text-red-600" : "text-amber-600"} />
          <p className="font-label text-xs font-bold text-on-surface">What Meta says</p>
          {sendState && (
            <span className={`px-2 py-0.5 rounded-full font-label text-[10px] font-bold border ${sendState.className}`}>
              {sendState.label}
            </span>
          )}
        </div>
        {health === null && !failed ? (
          <div className="space-y-1.5" aria-label="Loading Meta details">
            <div className="h-3 w-4/5 rounded bg-surface-mid animate-pulse" />
            <div className="h-3 w-3/5 rounded bg-surface-mid animate-pulse" />
          </div>
        ) : failed ? (
          <p className="font-body text-[11px] text-on-surface-muted">
            Couldn&apos;t load Meta&apos;s details right now. Press Sync to try again.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {metaLines.length === 0 && (
              <li className="font-body text-[11px] text-on-surface-muted">Meta didn&apos;t give a specific reason.</li>
            )}
            {metaLines.map((line) => (
              <li key={line} className="flex gap-2 font-body text-[11px] leading-relaxed text-on-surface">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-on-surface-muted shrink-0" />
                <span>{line}</span>
              </li>
            ))}
            {health?.errors.map((err) => (
              <li key={`${err.code}`} className="flex gap-2 font-body text-[11px] leading-relaxed text-on-surface">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-on-surface-muted shrink-0" />
                <span>{err.description}{err.solution ? ` — ${err.solution}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="font-body text-[10px] text-on-surface-muted leading-relaxed">
          Meta rates quality from recent blocks and reports, and doesn&apos;t say which messages caused it.
        </p>
      </div>

      {/* Our steps */}
      <div className="min-w-0 space-y-2">
        <p className="font-label text-xs font-bold text-on-surface">
          {isLow ? "Low quality · what to do next" : "Medium quality · keep it from dropping"}
        </p>
        <ol className="space-y-1.5">
          {steps.map((step, i) => (
            <li key={step} className="flex gap-2 font-body text-[11px] leading-relaxed text-on-surface">
              <span className={cn(
                "w-4 h-4 rounded-full flex items-center justify-center shrink-0 font-label text-[9px] font-bold mt-px",
                isLow ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-800"
              )}>
                {i + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
        <a
          href={WHATSAPP_MANAGER_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 font-label text-[11px] font-bold text-primary hover:underline"
        >
          Open WhatsApp Manager <ExternalLink size={10} />
        </a>
      </div>
    </div>
  );
}

// ── Incidents Types & Components ─────────────────────────────────────────────

type Incident = {
  id: string;
  type: string;
  phone_number_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

const TYPE_LABELS: Record<string, string> = {
  quality_yellow: "Quality dropped to Medium — warning only, sending continues",
  quality_red: "Quality dropped to Low — number resting for 7 days, broadcasts stopped on it",
  failover: "Standby promoted to primary sender",
  migration_sent: "Channel migration notice sent to recent leads",
  appeal_filed: "Meta policy appeal filed",
  standby_promoted: "Standby number promoted to primary line",
  warm_up_complete: "Number warm-up completed — now fully active",
  number_recovered: "Number recovered — rested 7 days and Meta shows it Green",
  quality_snapshot: "Quality rating & tier synced from Meta",
  whatsapp_alert_failed: "Admin WhatsApp alert failed to send",
};

const TYPE_BADGE: Record<string, string> = {
  quality_yellow: "bg-amber-50 text-amber-700 border-amber-200",
  quality_red: "bg-red-50 text-red-700 border-red-200",
  failover: "bg-blue-50 text-blue-700 border-blue-200",
  migration_sent: "bg-primary-50 text-primary-700 border-primary-200",
  appeal_filed: "bg-orange-50 text-orange-700 border-orange-200",
  standby_promoted: "bg-blue-50 text-blue-700 border-blue-200",
  warm_up_complete: "bg-green-50 text-green-700 border-green-200",
  number_recovered: "bg-green-50 text-green-700 border-green-200",
  quality_snapshot: "bg-emerald-50 text-emerald-700 border-emerald-200",
  whatsapp_alert_failed: "bg-red-50 text-red-700 border-red-200",
};

const INCIDENTS_PAGE_SIZE = 50;

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
    ", " +
    d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

function DetailExpander({ detail }: { detail: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const keys = Object.keys(detail);
  if (keys.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 font-label text-xs text-primary hover:text-primary-dark transition-colors font-semibold"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {open ? "Hide details" : "View payload details"}
      </button>
      {open && (
        <div className="mt-2 p-3.5 rounded-xl bg-surface-low border border-border/80 font-mono text-xs text-on-surface overflow-x-auto">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-2 pb-2 border-b border-border/60">
            {Object.entries(detail).map(([k, v]) => (
              <div key={k} className="flex flex-col">
                <span className="text-[10px] text-on-surface-muted uppercase font-bold">{k}</span>
                <span className="font-semibold text-on-surface truncate">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
              </div>
            ))}
          </div>
          <pre className="text-[11px] text-on-surface-muted">{JSON.stringify(detail, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

const QUALITY_DOT: Record<string, string> = {
  green: "bg-emerald-500",
  yellow: "bg-amber-500",
  red: "bg-red-500",
};

function IncidentRow({ incident }: { incident: Incident }) {
  const badgeClass = TYPE_BADGE[incident.type] ?? "bg-surface-mid text-on-surface-muted border-border";
  const label = incident.detail.message === "no_standby_available"
    ? "No healthy backup number — broadcasts paused until a number recovers or you add one"
    : TYPE_LABELS[incident.type] ?? incident.type.replace(/_/g, " ");
  const isSnapshot = incident.type === "quality_snapshot";
  const snapQuality = isSnapshot ? (incident.detail.quality_rating as string) : null;

  return (
    <div className="flex gap-4 py-4 border-b border-border/60 last:border-0 hover:bg-surface-low/50 px-3 rounded-xl transition-colors">
      <div className="flex flex-col items-center gap-1 pt-1">
        <div className="w-8 h-8 rounded-xl bg-primary-50 text-primary border border-primary-100 flex items-center justify-center shrink-0">
          {incident.type.includes("quality") ? (
            <ShieldCheck size={16} />
          ) : incident.type.includes("failover") || incident.type.includes("promoted") ? (
            <ArrowRightLeft size={16} />
          ) : (
            <Activity size={16} />
          )}
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <span className="font-label text-xs font-semibold text-on-surface-muted whitespace-nowrap">
            {formatTimestamp(incident.created_at)}
          </span>
          <span className={`px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold border ${badgeClass}`}>
            {incident.type.replace(/_/g, " ")}
          </span>
          {isSnapshot && snapQuality && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface-low border border-border text-xs font-medium">
              <span className={`w-2 h-2 rounded-full ${QUALITY_DOT[snapQuality] ?? "bg-surface-mid"}`} />
              <span className="font-label text-[11px] text-on-surface capitalize font-semibold">{snapQuality} Quality</span>
              {incident.detail.messaging_tier != null && (
                <span className="font-label text-[11px] text-on-surface-muted">
                  · {Number(incident.detail.messaging_tier).toLocaleString()} /day
                </span>
              )}
            </span>
          )}
        </div>
        <p className="font-body text-sm font-medium text-on-surface">{label}</p>
        {!isSnapshot && <DetailExpander detail={incident.detail} />}
      </div>
    </div>
  );
}

// ── API helpers ─────────────────────────────────────────────────────────────

const numbersApi = {
  list: () =>
    apiFetch<{ data: PhoneNumber[]; numbers_pool?: NumbersPool }>("/api/v1/numbers"),
  create: (payload: {
    provider: string;
    number: string;
    display_name: string;
    meta_phone_number_id?: string;
    api_key?: string;
  }) =>
    apiFetch<PhoneNumber>("/api/v1/numbers", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  // display_name is deliberately absent: Meta owns it (verified_name), and sync
  // overwrites whatever is in the row, so a local rename would silently revert.
  update: (id: string, data: Partial<Pick<PhoneNumber, "role" | "status" | "paused_outbound">>) =>
    apiFetch<PhoneNumber>(`/api/v1/numbers/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  remove: (id: string) =>
    apiFetch<{ deleted: boolean }>(`/api/v1/numbers/${id}`, { method: "DELETE" }),
  syncMeta: (id: string) =>
    apiFetch<PhoneNumber>(`/api/v1/numbers/${id}/sync-meta`, { method: "POST" }),
  syncFromMeta: () =>
    apiFetch<{ data: PhoneNumber[]; numbers_pool?: NumbersPool; synced: number; failed: number }>(
      "/api/v1/numbers/sync-from-meta",
      { method: "POST" }
    ),
};

// ── Main Page Content ───────────────────────────────────────────────────────

function NumbersPageContent() {
  const { role, permissions, loading: roleLoading } = useAuthRole();
  const canViewNumbers = role === "owner" || permissions.includes("numbers.view") || permissions.includes("numbers.manage");
  const canManageNumbers = role === "owner" || permissions.includes("numbers.manage");
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeTab = (rawTab === "activity" ? "activity" : "pool") as "pool" | "activity";

  const [numbers, setNumbers] = useState<PhoneNumber[]>([]);
  const [numbersPool, setNumbersPool] = useState<NumbersPool | null>(null);
  const [loading, setLoading] = useState(true);

  // Search and filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "primary" | "standby" | "paused">("all");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Tier guide banner state (auto-dismisses after 15s)
  const [showTierGuide, setShowTierGuide] = useState(true);
  const [tierGuideOpen, setTierGuideOpen] = useState(false);

  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncingAll, setSyncingAll] = useState(false);
  const [pausingId, setPausingId] = useState<string | null>(null);

  // Incidents state
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [incidentOffset, setIncidentOffset] = useState(0);
  const [hasMoreIncidents, setHasMoreIncidents] = useState(true);
  const [incidentsLoading, setIncidentsLoading] = useState(true);
  const [loadingMoreIncidents, setLoadingMoreIncidents] = useState(false);

  const handleTabChange = (val: "pool" | "activity") => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", val);
    router.replace(`/dashboard/numbers?${params.toString()}`, { scroll: false });
  };

  async function reload() {
    const res = await numbersApi.list();
    setNumbers(res.data ?? []);
    setNumbersPool(res.numbers_pool ?? null);
  }

  useEffect(() => {
    setLoading(true);
    numbersApi.list().then((res) => {
      setNumbers(res.data ?? []);
      setNumbersPool(res.numbers_pool ?? null);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const fetchIncidents = useCallback(async (currentOffset: number, append: boolean) => {
    try {
      const result = await apiFetch<{ data: Incident[] }>(
        `/api/v1/incidents/?limit=${INCIDENTS_PAGE_SIZE}&offset=${currentOffset}`
      );
      const rows = result.data ?? [];
      setIncidents((prev) => (append ? [...prev, ...rows] : rows));
      setHasMoreIncidents(rows.length === INCIDENTS_PAGE_SIZE);
    } catch {
      // silent — keep stale data visible
    }
  }, []);

  useEffect(() => {
    if (activeTab === "activity") {
      setIncidentsLoading(true);
      fetchIncidents(0, false).finally(() => setIncidentsLoading(false));
    }
  }, [activeTab, fetchIncidents]);

  const refreshIncidents = useCallback(() => {
    if (activeTab === "activity") {
      fetchIncidents(0, false);
    }
  }, [activeTab, fetchIncidents]);

  usePolling(refreshIncidents, 30_000);

  async function handleLoadMoreIncidents() {
    const nextOffset = incidentOffset + INCIDENTS_PAGE_SIZE;
    setLoadingMoreIncidents(true);
    await fetchIncidents(nextOffset, true);
    setIncidentOffset(nextOffset);
    setLoadingMoreIncidents(false);
  }

  const handleCopyNumber = (id: string, phone: string) => {
    navigator.clipboard.writeText(phone);
    setCopiedId(id);
    toast.success("Phone number copied to clipboard");
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Derived metrics
  const activeCount = numbers.filter((n) => n.status === "active").length;
  const healthyCount = numbers.filter((n) => n.status === "active" && n.quality_rating !== "red").length;
  const visible = useMemo(() => numbers.filter((n) => n.status !== "archived"), [numbers]);

  const totalPoolLimit = numbersPool?.limit ?? 5;
  const totalPoolUsed = visible.length;
  const primaryNumber = visible.find((n) => n.role === "primary");
  const standbyCount = visible.filter((n) => n.role === "standby").length;
  // A standby that can take over sending: already live or warming, not Red, not paused or locked.
  const hasReadyStandby = visible.some(
    (n) =>
      n.role === "standby" &&
      (n.health?.state === "active" || n.health?.state === "warming") &&
      n.quality_rating !== "red" &&
      !n.paused_outbound &&
      !n.locked
  );
  const broadcastsPaused = primaryNumber?.health?.state === "resting" && !hasReadyStandby;
  const activeLineCount = visible.filter((n) => n.health?.state === "active").length;
  const pausedCount = visible.filter((n) => n.paused_outbound).length;
  // Meta's one limit for the whole business (shared by every number) and what
  // the last 24 hours used of it, counted the way Meta counts.
  const totalDailySends = numbersPool?.meta_sent_24h ?? 0;
  const totalDailyCapacity = numbersPool?.meta_limit ?? 0;
  const totalSendPct = totalDailyCapacity > 0 ? Math.min((totalDailySends / totalDailyCapacity) * 100, 100) : 0;

  // Portfolio overall quality
  const overallQuality: QualityRating = visible.some((n) => n.quality_rating === "red")
    ? "red"
    : visible.some((n) => n.quality_rating === "yellow")
    ? "yellow"
    : "green";

  // Filtered numbers
  const filteredNumbers = useMemo(() => {
    return visible.filter((num) => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchName = num.display_name.toLowerCase().includes(q);
        const matchPhone = num.number.toLowerCase().includes(q);
        if (!matchName && !matchPhone) return false;
      }
      if (roleFilter === "primary") return num.role === "primary";
      if (roleFilter === "standby") return num.role === "standby";
      if (roleFilter === "paused") return num.paused_outbound;
      return true;
    });
  }, [visible, searchQuery, roleFilter]);

  if (roleLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  if (!canViewNumbers) {
    return (
      <div className="text-center py-20">
        <p className="text-on-surface-muted font-body">
          You do not have access to the numbers pool.
        </p>
      </div>
    );
  }

  async function handleSetPrimary(id: string) {
    if (!canManageNumbers) return;
    try {
      await numbersApi.update(id, { role: "primary" });
      await reload();
      toast.success("Set as primary number");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function handleTogglePause(num: PhoneNumber) {
    if (!canManageNumbers) return;
    setPausingId(num.id);
    try {
      await numbersApi.update(num.id, { paused_outbound: !num.paused_outbound });
      await reload();
      toast.success(num.paused_outbound ? "Outbound messaging resumed" : "Outbound messaging paused");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Update failed");
    } finally {
      setPausingId(null);
    }
  }

  async function handleSyncMeta(id: string) {
    if (!canManageNumbers) return;
    setSyncingId(id);
    try {
      await numbersApi.syncMeta(id);
      await reload();
      toast.success("Synced from Meta");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncingId(null);
    }
  }

  async function handleSyncAllMeta() {
    if (!canManageNumbers) return;
    setSyncingAll(true);
    try {
      const res = await numbersApi.syncFromMeta();
      setNumbers(res.data ?? []);
      setNumbersPool(res.numbers_pool ?? null);
      if (res.failed === 0) {
        toast.success(`Synced ${res.synced} number${res.synced === 1 ? "" : "s"} from Meta`);
      } else if (res.synced > 0) {
        toast.success(`Synced ${res.synced} numbers, ${res.failed} failed`);
      } else {
        toast.error("Failed to sync numbers from Meta");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncingAll(false);
    }
  }

  async function handleDelete(id: string) {
    if (!canManageNumbers) return;
    if (!confirm("Delete this number? It will no longer send or receive messages.")) return;
    try {
      await numbersApi.remove(id);
      await reload();
      toast.success("Number removed from pool");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div>
      {/* Mobile Tab Fallback */}
      <div className="p-1 bg-[#e2e8f0]/60 rounded-2xl flex gap-1 self-start w-fit md:hidden mb-4">
        <button
          onClick={() => handleTabChange("pool")}
          className={cn(
            "px-5 py-2.5 rounded-xl font-label text-xs font-bold transition-all",
            activeTab === "pool"
              ? "bg-white text-primary shadow-sm"
              : "text-[#475569] hover:text-[#13284A]"
          )}
        >
          Active Pool
        </button>
        <button
          onClick={() => handleTabChange("activity")}
          className={cn(
            "px-5 py-2.5 rounded-xl font-label text-xs font-bold transition-all",
            activeTab === "activity"
              ? "bg-white text-primary shadow-sm"
              : "text-[#475569] hover:text-[#13284A]"
          )}
        >
          Activity Log
        </button>
      </div>

      <div className="space-y-3.5">
        {activeTab === "pool" ? (
          <>
          {/* ── KPI Overview Grid ───────────────────────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* KPI 1: Pool Utilization */}
            <KpiCard
              label="Active Pool Capacity"
              value={totalPoolUsed}
              loading={loading}
              suffix={`/ ${totalPoolLimit} Used`}
              edge="bg-primary"
              stacked
              badge={
                <span className="font-label text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-primary-100/70 text-primary">
                  {loading ? "—" : totalPoolUsed >= totalPoolLimit ? "Quota Full" : `${totalPoolLimit - totalPoolUsed} slots free`}
                </span>
              }
            >
              <div className="flex items-center justify-between text-[11px] font-body text-on-surface-muted">
                <span>{loading ? "—" : visible.length} connected</span>
                {!loading && totalPoolUsed >= totalPoolLimit && (
                  <a href="/dashboard/subscriptions" className="font-label text-primary font-bold hover:underline inline-flex items-center gap-0.5">
                    Upgrade <ExternalLink size={10} />
                  </a>
                )}
              </div>
            </KpiCard>

            {/* KPI 2: Meta limit used, moving 24 hours */}
            <KpiCard
              label="Used of Meta's limit (Anril's count)"
              title="People sent a template outside their 24-hour chat window, over the last 24 hours. This is what Meta counts toward your limit. Broadcasts stop at 90% of it, leaving room for messages sent outside Anril; app messages never stop."
              value={totalDailySends.toLocaleString()}
              loading={loading}
              suffix={`/ ${formatLimit(totalDailyCapacity)}`}
              edge="bg-blue-600"
              stacked
              badge={
                <span className="font-mono text-xs font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded-full border border-blue-100">
                  {loading ? "—" : `${Math.round(totalSendPct)}% used`}
                </span>
              }
            >
              <div className="w-full h-1.5 rounded-full bg-surface-mid overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-500",
                    totalSendPct > 85 ? "bg-red-500" : totalSendPct > 50 ? "bg-amber-500" : "bg-emerald-500"
                  )}
                  style={{ width: `${loading ? 0 : Math.max(totalSendPct, 3)}%` }}
                />
              </div>
            </KpiCard>

            {/* KPI 3: Portfolio Health */}
            <KpiCard
              label="Portfolio Health Status"
              value={healthyCount}
              loading={loading}
              suffix="Healthy"
              edge="bg-emerald-500"
              stacked
              badge={
                loading ? (
                  <span className="font-label text-[11px] font-bold text-on-surface-muted">—</span>
                ) : (
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold border ${QUALITY_BG[overallQuality]}`}>
                    <span className={`w-2 h-2 rounded-full animate-pulse ${QUALITY_COLOR[overallQuality]}`} />
                    {QUALITY_LABEL[overallQuality]} Quality
                  </span>
                )
              }
            >
              <div className="flex items-center justify-between text-[11px] font-body text-on-surface-muted">
                <span>
                  {loading ? "—" : pausedCount > 0
                    ? `${pausedCount} paused line${pausedCount > 1 ? "s" : ""}`
                    : activeLineCount === visible.length
                    ? "All lines active"
                    : `${activeLineCount} of ${visible.length} lines active`}
                </span>
                {!loading && <span className="text-emerald-700 font-semibold">Meta synced</span>}
              </div>
            </KpiCard>

            {/* KPI 4: Primary Sender */}
            <KpiCard
              label="Primary Sender"
              value={primaryNumber ? primaryNumber.display_name : "None Set"}
              hint={primaryNumber ? primaryNumber.number : "No primary selected"}
              loading={loading}
              edge="bg-amber-400"
              stacked
              valueClassName="!text-xl min-w-0 !shrink truncate"
              badge={
                <span className="font-label text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-100/70 text-amber-800">
                  Primary Routing
                </span>
              }
            >
              <div className="flex items-center justify-between text-[11px] font-body text-on-surface-muted">
                <span>{loading ? "—" : `${standbyCount} standby failover${standbyCount === 1 ? "" : "s"}`}</span>
                {loading ? null : broadcastsPaused ? (
                  <span className="text-amber-700 font-semibold">Broadcasts paused</span>
                ) : (
                  <span className="text-primary font-semibold">Broadcasting</span>
                )}
              </div>
            </KpiCard>
          </div>

          {/* ── Messaging Tier Guide Banner ──────────────────────────────────── */}
          {showTierGuide && (
            <TierGuide
              visible={showTierGuide}
              onDismiss={() => setShowTierGuide(false)}
              isOpen={tierGuideOpen}
              onToggleOpen={() => setTierGuideOpen((v) => !v)}
            />
          )}

          {/* ── Main Numbers Card ───────────────────────────────────────────── */}
          <div className="rounded-2xl bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 md:rounded-card md:p-8 space-y-6">
            {/* Control Bar: Title + Search + Filters + Sync */}
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between pb-2 border-b border-border/70">
              <div className="flex items-center gap-3">
                <h2 className="font-display text-xl font-bold text-on-surface">Sender Numbers</h2>
                <span className="font-label text-xs font-bold text-primary bg-primary/10 px-2.5 py-0.5 rounded-full">
                  {visible.length} total
                </span>
                {!showTierGuide && (
                  <button
                    onClick={() => {
                      setShowTierGuide(true);
                      setTierGuideOpen(true);
                    }}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-label font-bold text-primary bg-primary-50 hover:bg-primary-100 border border-primary-200/80 transition-colors"
                    title="Re-open WhatsApp messaging limits and tier guide"
                  >
                    <Info size={12} />
                    <span>Limits Guide</span>
                  </button>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                {/* Search Box */}
                <div className="relative min-w-[220px]">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-muted" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search name or number…"
                    className="w-full pl-9 pr-8 py-2 bg-surface-low border border-border/80 rounded-xl font-body text-xs text-on-surface placeholder:text-on-surface-muted/60 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery("")}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-on-surface-muted hover:text-on-surface text-xs"
                    >
                      <X size={13} />
                    </button>
                  )}
                </div>

                {/* Filter Pills */}
                <div className="flex items-center gap-1 p-1 bg-surface-low rounded-xl border border-border/70">
                  {[
                    { key: "all", label: "All" },
                    { key: "primary", label: "Primary" },
                    { key: "standby", label: "Standby" },
                    { key: "paused", label: "Paused" },
                  ].map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => setRoleFilter(tab.key as typeof roleFilter)}
                      className={cn(
                        "px-3 py-1 rounded-lg font-label text-xs font-bold transition-colors",
                        roleFilter === tab.key
                          ? "bg-white text-primary shadow-2xs"
                          : "text-on-surface-muted hover:text-on-surface"
                      )}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                {/* Sync from Meta CTA */}
                {canManageNumbers && (
                  <button
                    onClick={handleSyncAllMeta}
                    disabled={syncingAll}
                    className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-[var(--primary-950)] via-[var(--primary-800)] to-[var(--primary-600)] text-white hover:opacity-95 rounded-xl font-label text-xs font-bold shadow-sm transition-all disabled:opacity-50"
                    title="Discover and sync all numbers from your connected Meta WhatsApp Business account"
                  >
                    <RefreshCw size={13} className={syncingAll ? "animate-spin" : ""} />
                    <span>{syncingAll ? "Syncing Meta…" : "Sync from Meta"}</span>
                  </button>
                )}
              </div>
            </div>

            {/* List / Cards */}
            {loading ? (
              <AiraLoader inline className="min-h-[200px]" />
            ) : visible.length === 0 ? (
              <div className="py-16 text-center max-w-md mx-auto space-y-4">
                <div className="w-14 h-14 rounded-2xl bg-primary-50 text-primary border border-primary-100 flex items-center justify-center mx-auto">
                  <Phone size={26} />
                </div>
                <div>
                  <h3 className="font-display text-lg font-bold text-on-surface">No sender numbers configured</h3>
                  <p className="font-body text-xs text-on-surface-muted mt-1 leading-relaxed">
                    Connect your WhatsApp Business Account in Settings, then click &quot;Sync from Meta&quot; to import your registered sender numbers.
                  </p>
                </div>
                {canManageNumbers && (
                  <button
                    onClick={handleSyncAllMeta}
                    disabled={syncingAll}
                    className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-white hover:bg-primary/90 rounded-xl font-label text-xs font-bold transition-all shadow-sm"
                  >
                    <RefreshCw size={13} className={syncingAll ? "animate-spin" : ""} />
                    {syncingAll ? "Syncing…" : "Sync numbers from Meta"}
                  </button>
                )}
              </div>
            ) : filteredNumbers.length === 0 ? (
              <div className="py-12 text-center">
                <p className="font-body text-sm text-on-surface-muted">
                  No numbers match your search &quot;{searchQuery}&quot; or filter.
                </p>
                <button
                  onClick={() => { setSearchQuery(""); setRoleFilter("all"); }}
                  className="mt-2 font-label text-xs text-primary font-bold hover:underline"
                >
                  Clear search & filters
                </button>
              </div>
            ) : (
              <>
              {broadcastsPaused && (
                <div className="rounded-2xl border border-amber-200 bg-amber-50/70 px-5 py-4 flex items-start gap-3 mb-4">
                  <PauseCircle size={18} className="text-amber-700 shrink-0 mt-0.5" />
                  <div className="min-w-0">
                    <p className="font-display text-sm font-bold text-amber-900">Broadcasts paused</p>
                    <p className="font-body text-xs text-amber-900/80 leading-relaxed mt-0.5">
                      Your primary number is Red and resting. It still replies to chats. Add a standby number so broadcasts can continue from it.
                    </p>
                  </div>
                </div>
              )}
              <div className="space-y-4">
                {filteredNumbers.map((num) => {
                  const isSyncing = syncingId === num.id;
                  const isPausing = pausingId === num.id;
                  // Today's broadcast cap from the backend (lower than the tier during warm-up); null = Meta hasn't reported one.
                  const limit = num.health?.broadcast_cap ?? null;
                  // Resting or not yet verified by Meta: this number sends no broadcasts at all today.
                  const noBroadcasts = num.health?.state === "resting" || num.health?.state === "meta_pending";
                  const sendPct = limit !== null && limit > 0
                    ? Math.min(((num.health?.sent_24h ?? 0) / limit) * 100, 100)
                    : 0;
                  const showsQualitySteps = num.quality_rating !== null && num.quality_rating !== "green";

                  return (
                    <div
                      key={num.id}
                      className={cn(
                        "rounded-2xl border bg-white p-5 transition-all shadow-xs hover:shadow-card",
                        num.locked ? "border-amber-300 bg-amber-50/20" : "border-border/80"
                      )}
                    >
                      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-5">
                        {/* Left: Phone Avatar + Details + Badges */}
                        <div className="flex items-start gap-4 min-w-0">
                          {/* WhatsApp Phone Icon */}
                          <div className={cn(
                            "w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 shadow-xs",
                            num.role === "primary"
                              ? "bg-gradient-to-br from-primary-600 to-[var(--primary-950)] text-white ring-2 ring-primary/20"
                              : "bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
                          )}>
                            <Phone size={22} />
                          </div>

                          <div className="min-w-0 flex-1 space-y-1.5">
                            {/* Line 1: Meta-approved display name (read-only — changed in WhatsApp Manager, pulled in by Sync) */}
                            <div className="flex flex-wrap items-center gap-2">
                              <h3
                                className="font-display text-base font-bold text-on-surface truncate min-w-0"
                                title={`${num.display_name} — display name is set in Meta WhatsApp Manager and pulled in by Sync`}
                              >
                                {num.display_name}
                              </h3>

                              {/* Role Badge */}
                              {num.role === "primary" ? (
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold bg-gradient-to-r from-primary-100 via-primary-50 to-primary-100 text-[var(--primary-800)] border border-primary-200/80 shadow-2xs">
                                  <Star size={11} className="fill-[var(--primary-800)] text-[var(--primary-800)]" />
                                  Primary Sender
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-label text-[11px] font-semibold bg-surface-mid/80 text-on-surface-muted border border-border">
                                  Standby Failover
                                </span>
                              )}

                              {/* Quality Rating */}
                              {num.quality_rating ? (
                                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold border ${QUALITY_BG[num.quality_rating]}`}>
                                  <span className={`w-2 h-2 rounded-full ${QUALITY_COLOR[num.quality_rating]}`} />
                                  {QUALITY_LABEL[num.quality_rating]} Quality
                                </span>
                              ) : (
                                <span
                                  className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold border bg-surface-low text-on-surface-muted border-border"
                                  title="Meta hasn't rated this number yet. It gets a rating once it starts sending."
                                >
                                  <span className="w-2 h-2 rounded-full bg-on-surface-muted/40" />
                                  No rating yet
                                </span>
                              )}

                              {/* Status Badge (from health state) */}
                              {num.health?.state === "meta_pending" && (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-200">
                                  <ShieldAlert size={11} />
                                  {num.health.meta_code_verification === "NOT_VERIFIED" ||
                                  num.health.meta_status === "PENDING" ||
                                  num.health.meta_status === "UNVERIFIED"
                                    ? "Unverified"
                                    : num.health.meta_status === null
                                    ? "Not synced yet"
                                    : `Meta: ${formatMetaStatus(num.health.meta_status)}`}
                                </span>
                              )}
                              {num.health?.state === "resting" && (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold bg-amber-50 text-amber-800 border border-amber-200">
                                  <Hourglass size={11} />
                                  Resting · day {Math.min(num.health.rest_day, num.health.rest_days)} of {num.health.rest_days}
                                </span>
                              )}
                              {num.health?.state === "warming" && (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold bg-sky-50 text-sky-700 border border-sky-200">
                                  <Sunrise size={11} />
                                  Warming · day {num.health.warm_up_day} of {num.health.warm_up_days}
                                </span>
                              )}
                              {num.health?.state === "active" && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-label text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200/80">
                                  <CheckCircle2 size={11} />
                                  Active
                                </span>
                              )}

                              {/* Paused Badge */}
                              {num.paused_outbound && (
                                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-label text-[11px] font-bold bg-amber-50 text-amber-800 border border-amber-200">
                                  <PauseCircle size={11} />
                                  Paused Outbound
                                </span>
                              )}
                            </div>

                            {/* Line 2: Phone number with copy button + Provider info */}
                            <div className="flex flex-wrap items-center gap-3 text-xs text-on-surface-muted">
                              <div className="flex items-center gap-1.5">
                                <span className="font-mono font-bold text-on-surface">{num.number}</span>
                                <button
                                  onClick={() => handleCopyNumber(num.id, num.number)}
                                  className="p-1 rounded hover:bg-surface-low text-on-surface-muted hover:text-on-surface transition-colors"
                                  title="Copy phone number"
                                >
                                  {copiedId === num.id ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} />}
                                </button>
                              </div>

                              <span className="text-border">•</span>

                              <span className="font-label text-[11px] text-on-surface-muted">
                                {num.messaging_tier !== null ? getTierLabel(num.messaging_tier) : "Limit not reported yet"}
                              </span>

                              {num.meta_phone_number_id && (
                                <>
                                  <span className="text-border">•</span>
                                  <span className="font-mono text-[10px] text-on-surface-muted/80 bg-surface-low px-1.5 py-0.5 rounded border border-border/60">
                                    ID: {num.meta_phone_number_id}
                                  </span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Center/Right: Capacity Meter + Action Toolbar */}
                        <div className="flex flex-col sm:flex-row sm:items-center gap-5 shrink-0 pt-3 lg:pt-0 border-t lg:border-t-0 border-border/60">
                          {/* Send Meter */}
                          <div className="min-w-[170px] space-y-1.5">
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-label text-[11px] font-bold text-on-surface-muted">
                                {num.health?.state === "warming" ? "Warm-up limit" : "Daily Limit"}
                              </span>
                              <span className="font-mono font-bold text-on-surface text-[11px]">
                                {limit === null || noBroadcasts ? "—" : `${(num.health?.sent_24h ?? 0).toLocaleString()} / ${formatLimit(limit)}`}
                              </span>
                            </div>
                            <div className="w-full h-2 rounded-full bg-surface-mid overflow-hidden">
                              <div
                                className={cn(
                                  "h-full rounded-full transition-all duration-500",
                                  sendPct > 80 ? "bg-red-500" : sendPct > 50 ? "bg-amber-500" : "bg-emerald-500"
                                )}
                                style={{ width: `${limit === null || noBroadcasts ? 0 : Math.max(sendPct, 2)}%` }}
                              />
                            </div>
                            <div className="flex items-center justify-between text-[10px] text-on-surface-muted font-label">
                              <span>{limit === null || noBroadcasts ? "" : `${Math.round(sendPct)}% sent`}</span>
                              <span>
                                {num.health?.state === "resting"
                                  ? "No broadcasts while resting"
                                  : num.health?.state === "meta_pending"
                                  ? "Can't send until verified"
                                  : limit === null
                                  ? "No limit from Meta yet"
                                  : limit >= UNLIMITED_TIER
                                  ? "No cap"
                                  : limit - (num.health?.sent_24h ?? 0) > 0
                                  ? `${(limit - (num.health?.sent_24h ?? 0)).toLocaleString()} left`
                                  : "Limit reached"}
                              </span>
                            </div>
                          </div>

                          {/* Action Buttons */}
                          <div className="flex items-center gap-2">
                            {/* Set as Primary button */}
                            {canManageNumbers && num.role !== "primary" && num.role !== "archived" && (
                              <button
                                onClick={() => handleSetPrimary(num.id)}
                                disabled={num.health?.state === "meta_pending"}
                                className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-primary-200 bg-primary-50/70 hover:bg-primary-100 text-[var(--primary-800)] font-label text-xs font-bold transition-all shadow-2xs disabled:opacity-50 disabled:cursor-not-allowed"
                                title={
                                  num.health?.state === "meta_pending"
                                    ? "Meta hasn't verified this number yet"
                                    : "Set this line as the active primary sender"
                                }
                              >
                                <Star size={12} className="fill-primary-600/30" />
                                <span>Set Primary</span>
                              </button>
                            )}

                            {/* Pause / Resume */}
                            {canManageNumbers && (
                              <button
                                onClick={() => handleTogglePause(num)}
                                disabled={isPausing || (num.locked && num.paused_outbound)}
                                title={
                                  num.locked && num.paused_outbound
                                    ? "Locked by quota — upgrade to resume"
                                    : num.paused_outbound ? "Resume outbound broadcasts" : "Pause outbound broadcasts"
                                }
                                className={cn(
                                  "flex items-center gap-1.5 px-3 py-2 rounded-xl font-label text-xs font-bold transition-all border shadow-2xs disabled:opacity-50",
                                  num.paused_outbound
                                    ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                                    : "border-amber-200 bg-amber-50/80 text-amber-800 hover:bg-amber-100"
                                )}
                              >
                                {num.paused_outbound ? (
                                  <>
                                    <PlayCircle size={13} />
                                    <span>Resume</span>
                                  </>
                                ) : (
                                  <>
                                    <PauseCircle size={13} />
                                    <span>Pause</span>
                                  </>
                                )}
                              </button>
                            )}

                            {/* Sync Meta */}
                            {canManageNumbers && (
                              <button
                                onClick={() => handleSyncMeta(num.id)}
                                disabled={isSyncing}
                                className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-border bg-white hover:bg-surface-low text-on-surface font-label text-xs font-semibold transition-all shadow-2xs disabled:opacity-50"
                                title="Pull the latest status, quality and limit from Meta"
                              >
                                <RefreshCw size={12} className={isSyncing ? "animate-spin text-primary" : "text-on-surface-muted"} />
                                <span className="hidden sm:inline">Sync</span>
                              </button>
                            )}

                            {/* Delete */}
                            {canManageNumbers && (
                              <button
                                onClick={() => handleDelete(num.id)}
                                disabled={activeCount === 1 && num.status === "active"}
                                title={activeCount === 1 && num.status === "active" ? "Cannot delete the only active number" : "Remove number from pool"}
                                className="p-2 rounded-xl border border-border/80 bg-white hover:border-red-200 hover:bg-red-50 text-on-surface-muted hover:text-red-600 transition-colors disabled:opacity-30 disabled:cursor-not-allowed shadow-2xs"
                              >
                                <Trash2 size={13} />
                              </button>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Medium/Low quality: Meta's reasons + what to do next */}
                      {showsQualitySteps && (
                        <QualityNextSteps num={num} hasStandby={hasReadyStandby} />
                      )}

                      {/* Meta verification: this number can't send until Meta verifies it */}
                      {num.health?.state === "meta_pending" && (
                        <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50/60 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                          <div className="flex items-start gap-2 font-body text-xs text-rose-900 min-w-0">
                            <ShieldAlert size={13} className="text-rose-700 shrink-0 mt-0.5" />
                            <span>Meta hasn&apos;t verified this number yet, so it can&apos;t send or take over as primary. Finish verification in WhatsApp Manager, then press Sync.</span>
                          </div>
                          <a
                            href={WHATSAPP_MANAGER_URL}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 font-label text-[11px] font-bold text-primary hover:underline shrink-0"
                          >
                            Open WhatsApp Manager <ExternalLink size={10} />
                          </a>
                        </div>
                      )}

                      {/* Resting after a Red rating: replies only, no broadcasts */}
                      {num.health?.state === "resting" && (
                        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 flex items-start gap-2 font-body text-xs text-amber-900">
                          <Hourglass size={13} className="text-amber-700 shrink-0 mt-0.5" />
                          <span>
                            Resting after a Red rating: still replying to chats, but no broadcasts. After {num.health.rest_days} days, once Meta shows it Green, it becomes a standby again.
                          </span>
                        </div>
                      )}

                      {/* Warm-up: today's broadcast cap (skipped when the quality steps box is already showing) */}
                      {num.health?.state === "warming" && !showsQualitySteps && (
                        <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50/70 px-4 py-3 flex items-start gap-2 font-body text-xs text-sky-900">
                          <Sunrise size={13} className="text-sky-700 shrink-0 mt-0.5" />
                          <span>
                            {num.health.broadcast_cap !== null
                              ? `Warming up: broadcasts from this number are limited to ${num.health.broadcast_cap.toLocaleString()} today and reach the full limit on day ${num.health.warm_up_days}. Replies aren't limited.`
                              : `Warming up: broadcasts reach the full limit on day ${num.health.warm_up_days}. Replies aren't limited.`}
                          </span>
                        </div>
                      )}

                      {/* Locked Over-Quota Notice */}
                      {num.locked && (
                        <div className="mt-4 pt-3.5 border-t border-amber-200/80 flex flex-wrap items-center justify-between gap-3 bg-amber-50/80 -mx-5 -mb-5 px-5 py-3 rounded-b-2xl">
                          <div className="flex items-center gap-2 font-body text-xs text-amber-900">
                            <Lock size={13} className="text-amber-700 shrink-0" />
                            <span>This number exceeds your current pool quota. Set it as primary to activate it, or upgrade your plan for additional slots.</span>
                          </div>
                          <a
                            href="/dashboard/subscriptions"
                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-primary text-white rounded-lg font-label text-xs font-bold hover:bg-primary/90 transition-colors shadow-2xs"
                          >
                            Upgrade Quota <ArrowRightLeft size={11} />
                          </a>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              </>
            )}
          </div>
        </>
      ) : (
        /* ── Activity Log Tab ──────────────────────────────────────────────── */
        <div className="bg-surface rounded-card p-6 md:p-8 shadow-card ring-1 ring-[#c4c7c7]/15 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-border/70">
            <div>
              <h2 className="font-display text-xl font-bold text-on-surface">Pool Activity & Incidents</h2>
              <p className="font-body text-xs text-on-surface-muted mt-0.5">
                Audit trail of Meta quality adjustments, standby failovers, and tier changes.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 font-label text-xs font-semibold border border-emerald-200/70">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                Live: Polling every 30s
              </span>

              {canManageNumbers && (
                <button
                  onClick={async () => {
                    await handleSyncAllMeta();
                    setIncidentsLoading(true);
                    await fetchIncidents(0, false);
                    setIncidentOffset(0);
                    setIncidentsLoading(false);
                  }}
                  disabled={syncingAll}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-border text-on-surface hover:text-primary hover:border-primary/40 rounded-xl font-label text-xs font-bold transition-all shadow-2xs disabled:opacity-50"
                  title="Discover and sync every number on your connected Meta WhatsApp account"
                >
                  <RefreshCw size={12} className={syncingAll ? "animate-spin" : ""} />
                  {syncingAll ? "Syncing…" : "Sync from Meta"}
                </button>
              )}
            </div>
          </div>

          {incidentsLoading ? (
            <div className="py-16 text-center space-y-3">
              <Loader2 size={24} className="animate-spin text-primary mx-auto" />
              <p className="font-body text-sm text-on-surface-muted">Loading activity log…</p>
            </div>
          ) : incidents.length === 0 ? (
            <div className="py-20 text-center max-w-sm mx-auto space-y-3">
              <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center mx-auto">
                <ShieldCheck size={24} />
              </div>
              <h3 className="font-display text-base font-bold text-on-surface">No incidents recorded</h3>
              <p className="font-body text-xs text-on-surface-muted leading-relaxed">
                All numbers are operating normally with stable Meta quality ratings.
              </p>
            </div>
          ) : (
            <div>
              <div className="divide-y divide-border/60">
                {incidents.map((incident) => (
                  <IncidentRow key={incident.id} incident={incident} />
                ))}
              </div>

              {hasMoreIncidents && (
                <div className="pt-6 text-center">
                  <button
                    onClick={handleLoadMoreIncidents}
                    disabled={loadingMoreIncidents}
                    className="px-5 py-2.5 bg-surface-low border border-border hover:border-border-subtle rounded-xl font-label text-xs font-bold text-on-surface hover:bg-surface-mid transition-all shadow-2xs disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loadingMoreIncidents ? "Loading more incidents…" : "Load older events"}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      </div>
    </div>
  );
}

export default function NumbersPage() {
  return (
    <Suspense fallback={
      <div className="space-y-3.5">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 bg-surface-mid/60 rounded-2xl"></div>
          ))}
        </div>
        <div className="h-48 bg-surface-mid/60 rounded-2xl animate-pulse"></div>
        <div className="h-64 bg-surface-mid/60 rounded-2xl animate-pulse"></div>
      </div>
    }>
      <NumbersPageContent />
    </Suspense>
  );
}
