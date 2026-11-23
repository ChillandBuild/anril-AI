"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CreditCard, Check, ExternalLink, Activity, AlertTriangle } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { SkeletonCard } from "../components/skeleton";
import { AgentRepliesCard } from "./agent-replies";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...auth, ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail || "Request failed");
  }
  const json = await res.json();
  return ((json as { data?: T }).data ?? json) as T;
}

interface FeatureCatalogItem {
  feature_key: string;
  display_name: string;
}

interface SubscriptionItem {
  feature_key: string;
  quantity: number;
  unit_price_snapshot: number;
}

interface UsageMetric {
  metric: string;
  used: number;
  included: number;
  hard_cap: number | null;
}

const METRIC_LABELS: Record<string, string> = {
  message_sent: "Outbound Messages",
  ai_reply: "AI Replies",
  call_minute: "Call Minutes",
  team_seat_active: "Telecaller Seats",
  phone_number: "Phone Numbers",
  storage_gb: "Storage (GB)",
  ai_call_summary: "AI Call Summaries",
  ai_call_scoring: "AI Call Scoring",
  ai_text_to_speech: "TTS",
  ai_speech_to_text: "STT",
  agent_reply: "Agent Replies",
};

function UsageMeterRow({ item }: { item: UsageMetric }) {
  const label = METRIC_LABELS[item.metric] || item.metric;
  const unlimited = item.included <= 0;
  const pct = unlimited ? 0 : (item.used / item.included) * 100;
  const clampedPct = Math.min(100, Math.max(0, pct));
  const nearCap = !unlimited && item.used >= item.included * 0.8;
  const barColor = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-success";
  const textColor = pct >= 100 ? "text-danger" : pct >= 80 ? "text-warning" : "text-success";

  return (
    <div className="py-3.5 first:pt-0 last:pb-0">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium text-ink truncate">{label}</span>
          {nearCap && (
            <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning">
              <AlertTriangle size={11} /> Near cap
            </span>
          )}
        </div>
        <div className="flex items-baseline gap-2 shrink-0 font-mono text-xs">
          <span className="font-semibold text-ink">{item.used.toLocaleString("en-IN")}</span>
          <span className="text-ink-muted">/ {unlimited ? "Unlimited" : item.included.toLocaleString("en-IN")}</span>
          {!unlimited && <span className={`font-semibold ${textColor}`}>{Math.round(pct)}%</span>}
        </div>
      </div>
      {unlimited ? (
        <div className="flex h-2 items-center">
          <span className="text-xs text-ink-muted">—</span>
        </div>
      ) : (
        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-mid">
          <div className={`h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${clampedPct}%` }} />
        </div>
      )}
    </div>
  );
}

/**
 * Read-only view of what a tenant currently has entitled and is using —
 * replaces the old plan-picker Feature Store (migration 128 removed
 * admin-side plan assignment entirely; tenants build their own itemized cart
 * and an admin approves it from the Approval Queue instead) and absorbs the
 * former separate Billing & Usage tab, which called a route the redesign
 * deleted.
 */
export function EntitlementsView({ tenantId }: { tenantId: string }) {
  const router = useRouter();
  const [items, setItems] = useState<SubscriptionItem[]>([]);
  const [catalog, setCatalog] = useState<FeatureCatalogItem[]>([]);
  const [usage, setUsage] = useState<UsageMetric[]>([]);
  const [status, setStatus] = useState<string>("none");
  const [periodEnd, setPeriodEnd] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch<{ items: SubscriptionItem[]; status: string; period_end: string | null }>(`/api/v1/operator/clients/${tenantId}/entitlements`),
      apiFetch<FeatureCatalogItem[]>("/api/v1/operator/features/catalog"),
      apiFetch<UsageMetric[]>(`/api/v1/operator/clients/${tenantId}/usage`),
    ])
      .then(([ent, catalogData, usageData]) => {
        setItems(ent.items || []);
        setStatus(ent.status || "none");
        setPeriodEnd(ent.period_end);
        setCatalog(catalogData || []);
        setUsage(Array.isArray(usageData) ? usageData : []);
      })
      .catch(e => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [tenantId]);

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (error) {
    return <div className="p-4 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger">{error}</div>;
  }

  const catalogByKey = new Map(catalog.map(f => [f.feature_key, f]));
  const total = items.reduce((sum, i) => sum + i.quantity * i.unit_price_snapshot, 0);

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-card border border-border p-5 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-ink flex items-center gap-2">
            <CreditCard size={16} className="text-ink-muted" /> Current Entitlements
          </h3>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-surface-mid text-ink-secondary capitalize">
            {status.replace("_", " ")}
          </span>
        </div>
        {items.length > 0 ? (
          <div>
            <p className="text-lg font-bold text-ink mb-1">
              ₹{total.toLocaleString("en-IN")}<span className="text-xs font-medium text-ink-muted">/mo</span>
            </p>
            {periodEnd && (
              <p className="mb-3 text-xs text-ink-muted">
                Current cycle renews {new Date(periodEnd).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
              </p>
            )}
            <div className="grid gap-1.5 md:grid-cols-2">
              {items.map(item => (
                <div key={item.feature_key} className="flex items-center gap-1.5 text-sm text-ink-secondary">
                  <Check size={13} className="text-success shrink-0" />
                  {catalogByKey.get(item.feature_key)?.display_name || item.feature_key}
                  {item.quantity > 1 && <span className="text-xs text-ink-muted">×{item.quantity}</span>}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm text-ink-muted">Nothing purchased yet — the tenant is either pre-existing (grandfathered) or hasn&apos;t submitted a cart.</p>
        )}
      </div>

      <div className="bg-white rounded-card border border-border p-5 shadow-sm">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
          <Activity size={16} className="text-ink-muted" /> Usage This Cycle
        </h3>
        {usage.length > 0 ? (
          <div className="divide-y divide-border-subtle">
            {usage.map((item) => <UsageMeterRow key={item.metric} item={item} />)}
          </div>
        ) : (
          <p className="py-2 text-sm text-ink-muted">No usage recorded this cycle.</p>
        )}
      </div>

      <AgentRepliesCard tenantId={tenantId} />

      <button
        onClick={() => router.push(`/operator/subscription-requests?tenant_id=${tenantId}`)}
        className="flex items-center gap-1.5 text-sm font-medium text-primary hover:text-primary-dark"
      >
        View this tenant&apos;s request history <ExternalLink size={13} />
      </button>
    </div>
  );
}
