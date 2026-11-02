"use client";
import { useEffect, useState } from "react";
import { api, API_URL, DealSummary, getAuthHeaders, Lead } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ChevronRight, CheckCircle2, Calendar, TrendingUp, MessageCircle, Plus, Power, PowerOff } from "lucide-react";
import { toast } from "sonner";
import { SegmentBadge } from "./segment-badge";
import { describeScoreEvent, type ScoreEventLike } from "./scoreHistory";
import { NewDealDialog } from "./deals/NewDealDialog";
import { StageBadge } from "./deals/StageBadge";
import { formatRupees } from "./deals/money";
import { useMasterAiEnabled } from "@/lib/useMasterAiEnabled";

// ─── Channel icons ─────────────────────────────────────────────────────────────
function IgIcon({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function TgIcon({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

function FbIcon({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z" />
    </svg>
  );
}

// ─── Types ─────────────────────────────────────────────────────────────────────
type ScoreEvent = ScoreEventLike & {
  id: string;
  created_at: string;
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function SourceBadge({ source }: { source: string }) {
  if (source === "instagram") {
    return (
      <span className="inline-flex items-center gap-1 text-pink-500 font-semibold font-label text-xs">
        <IgIcon size={11} /> Instagram
      </span>
    );
  }
  if (source === "telegram") {
    return (
      <span className="inline-flex items-center gap-1 text-sky-500 font-semibold font-label text-xs">
        <TgIcon size={11} /> Telegram
      </span>
    );
  }
  if (source === "facebook") {
    return (
      <span className="inline-flex items-center gap-1 text-blue-600 font-semibold font-label text-xs">
        <FbIcon size={11} /> Facebook
      </span>
    );
  }
  if (source === "upload") {
    return (
      <span className="inline-flex items-center gap-1 text-primary-600 font-semibold font-label text-xs">
        📊 CSV Upload
      </span>
    );
  }
  if (source === "manual") {
    return (
      <span className="inline-flex items-center gap-1 text-gray-500 font-semibold font-label text-xs">
        ✏️ Manual
      </span>
    );
  }
  if (source === "website" || source === "api" || source === "store") {
    return (
      <span className="inline-flex items-center gap-1 text-primary font-semibold font-label text-xs">
        {source === "website" ? "🌐 Website form" : source === "api" ? "🔗 App / API" : "🏬 Shop counter"}
      </span>
    );
  }
  if (source === "indiamart" || source === "justdial") {
    return (
      <span className="inline-flex items-center gap-1 text-amber-700 font-semibold font-label text-xs">
        🏪 {source === "indiamart" ? "IndiaMART" : "JustDial"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-green-600 font-semibold font-label text-xs">
      <MessageCircle size={11} /> WhatsApp
    </span>
  );
}

const CHANNEL_BADGE: Record<string, string> = {
  whatsapp: "WA",
  instagram: "IG",
  telegram: "TG",
  facebook: "FB",
  indiamart: "IM",
  justdial: "JD",
};

// ─── Score event card ─────────────────────────────────────────────────────────
function ScoreEventCard({ ev }: { ev: ScoreEvent }) {
  const d = describeScoreEvent(ev);
  return (
    <div className="rounded-xl bg-surface-low border border-surface-mid p-3 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 flex-wrap min-w-0">
          {d.changed ? (
            <>
              {d.from && <SegmentBadge segment={d.from} />}
              {d.from && <span className="text-on-surface-muted text-xs" aria-label="became">→</span>}
              {d.to && <SegmentBadge segment={d.to} />}
            </>
          ) : (
            <>
              <span className="font-label text-[10px] text-on-surface-muted">Stayed</span>
              {d.to && <SegmentBadge segment={d.to} />}
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {d.channel && (
            <span className="font-label text-[10px] px-1.5 py-0.5 rounded bg-surface-mid text-on-surface-muted">
              {CHANNEL_BADGE[d.channel] ?? d.channel}
            </span>
          )}
          <span className="font-label text-[10px] text-on-surface-muted">{timeAgo(ev.created_at)}</span>
        </div>
      </div>
      {d.reason && (
        <p className="font-body text-xs text-on-surface leading-snug">{d.reason}</p>
      )}
      {d.snippet && (
        <p className="font-body text-[11px] text-on-surface-muted italic leading-snug line-clamp-2">
          &ldquo;{d.snippet}&rdquo;
        </p>
      )}
    </div>
  );
}

// ─── Section header ───────────────────────────────────────────────────────────
function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-on-surface-muted">{icon}</span>
        <p className="font-label text-[10px] font-semibold text-on-surface-muted uppercase tracking-wider">{title}</p>
      </div>
      {children}
    </div>
  );
}

function DealRow({ deal }: { deal: DealSummary }) {
  return (
    <div className="rounded-lg border border-surface-mid bg-white p-2.5 space-y-1">
      <div className="flex items-center justify-between gap-2">
        <p className="font-label text-xs font-semibold text-on-surface">{formatRupees(deal.total_paise)}</p>
        <StageBadge stage={deal.stage} />
      </div>
      <p className="font-body text-[11px] text-on-surface-muted truncate">
        {deal.deal_label} · {deal.item_summary || "No items"}
      </p>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────
interface LeadDetailsPanelProps {
  lead: Lead;
  onCollapse: () => void;
  onLeadUpdate?: (updated: Lead) => void;
}

export function LeadDetailsPanel({ lead, onCollapse, onLeadUpdate }: LeadDetailsPanelProps) {
  const [activeTab, setActiveTab] = useState<"info" | "actions">("info");
  const [history, setHistory] = useState<ScoreEvent[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState(false);
  const [toggling, setToggling] = useState(false);
  const masterAiEnabled = useMasterAiEnabled();
  const [converting, setConverting] = useState(false);
  const [showNewDeal, setShowNewDeal] = useState(false);
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [loadingDeals, setLoadingDeals] = useState(false);
  const [dealsError, setDealsError] = useState(false);
  const [dealsReload, setDealsReload] = useState(0);

  useEffect(() => {
    let mounted = true;
    setHistory([]);
    setHistoryError(false);
    setLoadingHistory(true);

    (async () => {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/leads/${lead.id}/score-history`, { headers: auth });
        if (!mounted) return;
        if (res.ok) {
          const data = await res.json();
          setHistory(data.data || []);
        } else {
          setHistoryError(true);
        }
      } catch {
        if (mounted) setHistoryError(true);
      } finally {
        if (mounted) setLoadingHistory(false);
      }
    })();

    return () => { mounted = false; };
  }, [lead.id]);

  useEffect(() => {
    let mounted = true;
    setDeals([]);
    setDealsError(false);
    setLoadingDeals(true);

    api.deals
      .byLead(lead.id)
      .then((rows) => { if (mounted) setDeals(rows); })
      .catch(() => { if (mounted) setDealsError(true); })
      .finally(() => { if (mounted) setLoadingDeals(false); });

    return () => { mounted = false; };
  }, [lead.id, dealsReload]);

  async function handleToggleAI() {
    setToggling(true);
    try {
      const updated = await api.leads.toggleAI(lead.id, !lead.ai_enabled);
      onLeadUpdate?.(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Toggle failed");
    } finally { setToggling(false); }
  }

  async function handleMarkConverted() {
    if (!confirm(`Mark ${lead.name || lead.phone} as converted? This feeds AI Auto-Tune.`)) return;
    setConverting(true);
    try {
      const updated = await api.leads.convert(lead.id);
      onLeadUpdate?.(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally { setConverting(false); }
  }

  const initials = lead.name
    ? lead.name.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2)
    : (lead.phone ?? "?").slice(-2);

  const converted = Boolean(lead.converted_at);

  return (
    <div className="w-80 flex-shrink-0 border-l border-surface-mid bg-surface flex flex-col h-full overflow-hidden">
      {/* Panel header */}
      <div className="px-4 pt-3 pb-0 border-b border-surface-mid">
        <div className="flex items-center justify-between mb-2">
          <p className="font-label text-[11px] font-semibold text-on-surface-muted uppercase tracking-wider">
            {lead.name || "Contact"}
          </p>
          <button
            onClick={onCollapse}
            title="Collapse panel"
            className="p-1 rounded-lg hover:bg-surface-low text-on-surface-muted hover:text-on-surface transition-colors"
          >
            <ChevronRight size={15} />
          </button>
        </div>
        {/* Tabs */}
        <div className="flex gap-0">
          {(["info", "actions"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-4 py-2 font-label text-xs font-semibold transition-colors border-b-2 -mb-px",
                activeTab === tab
                  ? "border-primary text-primary"
                  : "border-transparent text-on-surface-muted hover:text-on-surface"
              )}
            >
              {tab === "info" ? "Info" : "Actions"}
            </button>
          ))}
        </div>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto">

        {/* ── INFO tab ── */}
        {activeTab === "info" && (
          <div className="px-4 py-4 space-y-5">
            {/* Identity */}
            <div className="flex items-start gap-3">
              <div className="w-11 h-11 rounded-full bg-surface-low flex items-center justify-center shrink-0">
                <span className="font-display text-sm font-bold text-primary">{initials}</span>
              </div>
              <div className="min-w-0">
                <p className="font-body text-sm font-semibold text-on-surface truncate">
                  {lead.name || "Unnamed lead"}
                </p>
                {lead.phone && (
                  <p className="font-label text-xs text-on-surface-muted mt-0.5">{lead.phone}</p>
                )}
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  <SourceBadge source={lead.source} />
                  {converted && (
                    <span className="inline-flex items-center gap-1 text-green-600 font-label text-xs font-semibold">
                      <CheckCircle2 size={10} /> Converted
                    </span>
                  )}
                </div>
              </div>
            </div>

            <Section icon={<Calendar size={12} />} title="Joined">
              <p className="font-body text-xs text-on-surface">
                {formatDate(lead.created_at)}
                <span className="text-on-surface-muted ml-1.5">({timeAgo(lead.created_at)})</span>
              </p>
            </Section>

            <Section icon={<TrendingUp size={12} />} title="Segment">
              <SegmentBadge segment={lead.segment} />
            </Section>

            <Section icon={<TrendingUp size={12} />} title="Group history">
              {loadingHistory && <p className="font-body text-xs text-on-surface-muted">Loading…</p>}
              {!loadingHistory && historyError && <p className="font-body text-xs text-red-500">Failed to load history.</p>}
              {!loadingHistory && !historyError && history.length === 0 && (
                <p className="font-body text-xs text-on-surface-muted">
                  No group changes yet.
                  <br />
                  <span className="text-[10px]">Appears once this lead sends a message.</span>
                </p>
              )}
              {history.length > 0 && (
                <div className="space-y-2">
                  {history.slice(0, 8).map((ev) => <ScoreEventCard key={ev.id} ev={ev} />)}
                </div>
              )}
            </Section>

            <Section icon={<CheckCircle2 size={12} />} title="Deals">
              {loadingDeals && <p className="font-body text-xs text-on-surface-muted">Loading…</p>}
              {!loadingDeals && dealsError && <p className="font-body text-xs text-red-500">Couldn&apos;t load deals.</p>}
              {!loadingDeals && !dealsError && deals.length === 0 && (
                <p className="font-body text-xs text-on-surface-muted">No deals yet.</p>
              )}
              {deals.length > 0 && (
                <div className="space-y-2">
                  {deals.map((d) => <DealRow key={d.id} deal={d} />)}
                </div>
              )}
              <button
                type="button"
                onClick={() => setShowNewDeal(true)}
                className="mt-2 w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-surface-mid font-label text-xs font-semibold text-on-surface hover:bg-surface-mid transition-colors"
              >
                <Plus size={12} /> New deal
              </button>
            </Section>
          </div>
        )}

        {/* ── ACTIONS tab ── */}
        {activeTab === "actions" && (
          <div className="px-4 py-5 space-y-4">
            {/* AI toggle */}
            <div className={cn("rounded-xl border border-surface-mid bg-surface-low p-4 space-y-3", !masterAiEnabled && "opacity-60")}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-label text-xs font-semibold text-on-surface">AI Auto-Reply</p>
                  <p className="font-body text-[11px] text-on-surface-muted mt-0.5">
                    {!masterAiEnabled
                      ? "AI is off for your whole account — turn it on in Settings → Auto-Reply"
                      : lead.ai_enabled !== false ? "Bot is handling replies" : "You are handling replies"}
                  </p>
                </div>
                <span className={cn(
                  "w-2.5 h-2.5 rounded-full shrink-0",
                  masterAiEnabled && lead.ai_enabled !== false ? "bg-emerald-500" : "bg-amber-500"
                )} />
              </div>
              <button
                onClick={handleToggleAI}
                disabled={toggling || !masterAiEnabled}
                className={cn(
                  "w-full flex items-center justify-center gap-2 py-2 rounded-lg font-label text-xs font-semibold transition-colors disabled:opacity-40",
                  lead.ai_enabled !== false
                    ? "bg-amber-100 text-amber-700 hover:bg-amber-200 border border-amber-200"
                    : "bg-emerald-100 text-emerald-700 hover:bg-emerald-200 border border-emerald-200"
                )}
              >
                {lead.ai_enabled !== false ? <PowerOff size={13} /> : <Power size={13} />}
                {toggling ? "Updating…" : lead.ai_enabled !== false ? "Pause AI" : "Resume AI"}
              </button>
            </div>

            {/* Mark converted */}
            <div className="rounded-xl border border-surface-mid bg-surface-low p-4 space-y-3">
              <div>
                <p className="font-label text-xs font-semibold text-on-surface">Conversion</p>
                <p className="font-body text-[11px] text-on-surface-muted mt-0.5">
                  {converted ? "This lead has been converted" : "Mark when a deal is closed"}
                </p>
              </div>
              {converted ? (
                <div className="flex items-center gap-2 py-2 px-3 rounded-lg bg-green-50 border border-green-200 text-green-700">
                  <CheckCircle2 size={14} />
                  <span className="font-label text-xs font-semibold">Converted</span>
                </div>
              ) : (
                <button
                  onClick={handleMarkConverted}
                  disabled={converting}
                  className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-primary text-white font-label text-xs font-semibold hover:bg-primary/90 transition-colors disabled:opacity-40"
                >
                  <CheckCircle2 size={13} />
                  {converting ? "Saving…" : "Mark as Converted"}
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={() => setShowNewDeal(true)}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-primary text-white font-label text-xs font-semibold hover:bg-primary/90 transition-colors"
            >
              <Plus size={13} /> Log a sale or send a quote
            </button>
          </div>
        )}

      </div>
      <NewDealDialog
        open={showNewDeal}
        onClose={() => setShowNewDeal(false)}
        onCreated={() => { setShowNewDeal(false); setDealsReload((n) => n + 1); }}
        defaultLead={{ id: lead.id, name: lead.name ?? null, phone: lead.phone ?? null }}
      />
    </div>
  );
}
