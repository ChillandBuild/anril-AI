"use client";
import { useEffect, useMemo, useState } from "react";
import {
  Check, Sparkles, RadioTower, MessageSquare, Phone, Upload as UploadIcon,
  Users, Layers, Minus, Plus, Brain, ChevronDown,
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { featureLabel, formatRupees } from "@/lib/displayLabels";

interface CatalogRow {
  feature_key: string;
  display_name: string;
  category: string;
  monthly_price: number;
  unit_price: number | null;
  included_qty: number | null;
  usage_metric: string | null;
}

interface PackageRow {
  id: string;
  name: string;
  monthly_price: number;
  feature_keys: { feature_key: string; quantity: number }[];
  discount_percent: number;
}

export interface SubscriptionItem {
  feature_key: string;
  quantity: number;
}

const TELECALLING_TYPE_KEYS = ["telecalling_sim", "telecalling_telecmi"];
const AI_TIER_KEYS = ["ai_tier.basic", "ai_tier.standard", "ai_tier.premium"];

const ICONS: Record<string, typeof Phone> = {
  inbound_messaging: RadioTower,
  outbound_messaging: MessageSquare,
  "ai_tier.basic": Brain,
  "ai_tier.standard": Brain,
  "ai_tier.premium": Brain,
  telecalling_sim: Phone,
  telecalling_telecmi: Phone,
  bulk_lead_upload: UploadIcon,
  telecaller_seats: Users,
  numbers_pool: Layers,
};

const inboundFeatures = [
  "Instagram Direct Integration",
  "Facebook Messenger Integration",
  "Telegram Chat Support Integration",
  "Unified Live Chat Inbox",
  "Real-time Admin Notifications",
  "Internal FAQs & Knowledge Base answers"
];

const outboundFeatures = [
  "WhatsApp Business Cloud API",
  "Bulk Outbound Broadcast Campaigns",
  "Broadcast History & Analytics",
  "Audience Segmentation",
  "Interactive WhatsApp Templates",
  "Automated Sequence Rules",
  "Fallback Push Notifications"
];

async function apiGet<T>(path: string): Promise<T> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, { headers: auth });
  if (!res.ok) throw new Error("Failed to load");
  return res.json();
}

function priceForItem(row: CatalogRow, quantity: number, existingQuantity: number): number {
  if (row.monthly_price > 0) return row.monthly_price;
  if (row.unit_price == null) return 0;
  if (row.included_qty == null) return row.unit_price * quantity;
  const included = row.included_qty;
  const alreadyBillable = Math.max(0, existingQuantity - included);
  const newBillable = Math.max(0, existingQuantity + quantity - included);
  return row.unit_price * (newBillable - alreadyBillable);
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-3 text-[13px] font-bold uppercase tracking-wide text-ink-muted">{children}</h3>;
}

function SelectCard({
  selected, onClick, icon: Icon, title, subtitle, disabled, features,
}: {
  selected: boolean;
  onClick: () => void;
  icon: typeof Phone;
  title: string;
  subtitle: string;
  disabled?: boolean;
  features?: string[];
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="flex flex-col w-full">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={`group relative flex w-full items-start gap-3 rounded-2xl border p-4 text-left transition-all ${
          selected
            ? "border-primary bg-primary-light shadow-sm"
            : "border-border bg-white hover:border-primary/40 hover:bg-primary-light/30"
        } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
      >
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${selected ? "bg-primary text-white" : "bg-surface-mid text-ink-muted"}`}>
          <Icon size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink">{title}</p>
          <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>
        </div>
        <div className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${selected ? "border-primary bg-primary" : "border-border-subtle"}`}>
          {selected && <Check size={12} className="text-white" strokeWidth={3} />}
        </div>
      </button>
      
      {features && features.length > 0 && (
        <div className="px-4 pb-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="flex items-center gap-1 mt-2 text-xs font-semibold text-primary hover:text-primary-dark transition-colors"
          >
            <span>{expanded ? "Hide what's included" : "Show what's included"}</span>
            <ChevronDown size={14} className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`} />
          </button>
          
          {expanded && (
            <ul className="mt-2 space-y-1 pl-5 list-disc text-[11px] text-ink-secondary">
              {features.map((f, idx) => (
                <li key={idx}>{f}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Stepper({ value, onChange, min = 1 }: { value: number; onChange: (v: number) => void; min?: number }) {
  return (
    <div className="flex items-center gap-1 rounded-xl border border-border bg-surface-mid/60 p-1">
      <button
        type="button"
        onClick={() => onChange(Math.max(min, value - 1))}
        className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-ink shadow-sm transition hover:bg-primary-light disabled:opacity-40"
        disabled={value <= min}
      >
        <Minus size={13} />
      </button>
      <span className="w-8 text-center text-sm font-bold text-ink">{value}</span>
      <button
        type="button"
        onClick={() => onChange(value + 1)}
        className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-ink shadow-sm transition hover:bg-primary-light"
      >
        <Plus size={13} />
      </button>
    </div>
  );
}

export function CartBuilder({
  mode, existingItems, onSubmitted, periodStart, periodEnd, canSubmit = true,
}: {
  mode: "initial" | "addon";
  existingItems: SubscriptionItem[];
  onSubmitted: () => void;
  periodStart?: string | null;
  periodEnd?: string | null;
  canSubmit?: boolean;
}) {
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [packages, setPackages] = useState<PackageRow[]>([]);
  const [selected, setSelected] = useState<Record<string, number>>({});
  const [selectedPackage, setSelectedPackage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [startDate, setStartDate] = useState(() => {
    const today = new Date();
    return today.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 15);
    return d.toISOString().slice(0, 10);
  });

  const durationDays = useMemo(() => {
    const start = new Date(startDate);
    const end = new Date(endDate);
    const diff = end.getTime() - start.getTime();
    if (isNaN(diff)) return 15;
    return Math.max(1, Math.round(diff / 86_400_000));
  }, [startDate, endDate]);

  const todayStr = useMemo(() => new Date().toISOString().slice(0, 10), []);

  useEffect(() => {
    apiGet<{ catalog: CatalogRow[]; packages: PackageRow[] }>("/api/v1/subscriptions/catalog")
      .then((data) => {
        setCatalog(data.catalog);
        setPackages(data.packages);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load catalog"))
      .finally(() => setLoading(false));
  }, []);

  const byKey = useMemo(() => new Map(catalog.map((c) => [c.feature_key, c])), [catalog]);
  const existingQtyFor = (key: string) => existingItems.find((i) => i.feature_key === key)?.quantity ?? 0;

  function applyPackage(pkg: PackageRow) {
    setSelectedPackage((prev) => (prev === pkg.id ? null : pkg.id));
    if (selectedPackage === pkg.id) { setSelected({}); return; }
    const next: Record<string, number> = {};
    pkg.feature_keys.forEach((item) => { next[item.feature_key] = item.quantity; });
    setSelected(next);
  }

  function toggleItem(key: string, defaultQty = 1) {
    setSelectedPackage(null);
    setSelected((prev) => {
      const next = { ...prev };
      if (next[key]) delete next[key];
      else next[key] = defaultQty;
      return next;
    });
  }

  function selectTelecallingType(key: string) {
    setSelectedPackage(null);
    setSelected((prev) => {
      const next = { ...prev };
      const otherKey = TELECALLING_TYPE_KEYS.find((k) => k !== key)!;
      delete next[otherKey];
      if (next[key]) delete next[key];
      else next[key] = 1;
      return next;
    });
  }

  function selectAiTier(key: string) {
    setSelectedPackage(null);
    setSelected((prev) => {
      const next = { ...prev };
      for (const tierKey of AI_TIER_KEYS) {
        if (tierKey !== key) delete next[tierKey];
      }
      if (next[key]) delete next[key];
      else next[key] = 1;
      return next;
    });
  }

  const total = Object.entries(selected).reduce((sum, [key, qty]) => {
    const row = byKey.get(key);
    if (!row) return sum;
    return sum + priceForItem(row, qty, existingQtyFor(key));
  }, 0);

  const totalForPeriod = useMemo(() => {
    if (mode !== "initial") return total;
    return Object.entries(selected).reduce((sum, [key, qty]) => {
      const row = byKey.get(key);
      if (!row) return sum;
      const isFlat = row.monthly_price > 0;
      const dailyPrice = isFlat ? (row.monthly_price / 30) : ((row.unit_price ?? 0) / 30);
      return sum + dailyPrice * qty * durationDays;
    }, 0);
  }, [selected, byKey, durationDays, mode, total]);

  const prorationFactor = useMemo(() => {
    if (mode !== "addon" || !periodStart || !periodEnd) return 1;
    const start = new Date(`${periodStart.slice(0, 10)}T00:00:00Z`);
    const end = new Date(`${periodEnd.slice(0, 10)}T00:00:00Z`);
    const today = new Date();
    const todayUtc = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    const cycleDays = Math.max((end.getTime() - start.getTime()) / 86_400_000, 1);
    const remainingDays = Math.max((end.getTime() - todayUtc.getTime()) / 86_400_000, 0);
    return Math.min(1, Math.max(0, remainingDays / cycleDays));
  }, [mode, periodStart, periodEnd]);

  const dueNow = mode === "addon" ? total * prorationFactor : total;

  async function submit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/subscriptions/requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({
          package_id: selectedPackage,
          items: Object.entries(selected).map(([feature_key, quantity]) => ({ feature_key, quantity })),
          start_date: mode === "initial" ? startDate : null,
          end_date: mode === "initial" ? endDate : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to submit");
      }
      onSubmitted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to submit");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 p-12 text-ink-muted">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        Loading pricing…
      </div>
    );
  }

  const inbound = byKey.get("inbound_messaging");
  const outbound = byKey.get("outbound_messaging");
  const aiTiers = AI_TIER_KEYS.map((key) => byKey.get(key)).filter(Boolean) as CatalogRow[];
  const sim = byKey.get("telecalling_sim");
  const telecmi = byKey.get("telecalling_telecmi");
  const upload = byKey.get("bulk_lead_upload");
  const seats = byKey.get("telecaller_seats");
  const numbers = byKey.get("numbers_pool");

  const telecallingTypeSelected = TELECALLING_TYPE_KEYS.some((k) => k in selected);
  const hasTelecallingCoverage = telecallingTypeSelected || TELECALLING_TYPE_KEYS.some((k) => existingQtyFor(k) > 0);

  function fmt(n: number) {
    return `₹${formatRupees(n)}`;
  }

  function formatPricingText(row: CatalogRow, qty = 1, forceUnit = false) {
    const isFlat = row.monthly_price > 0;
    const dailyPrice = isFlat ? (row.monthly_price / 30) : ((row.unit_price ?? 0) / 30);
    const dailyFormatted = fmt(Math.round(dailyPrice * 100) / 100);
    
    if (mode === "initial") {
      const periodTotal = dailyPrice * qty * durationDays;
      const periodTotalFormatted = fmt(Math.round(periodTotal * 100) / 100);
      if (!isFlat && forceUnit) {
        return `${dailyFormatted}/day per unit (${periodTotalFormatted} for ${durationDays} days)`;
      }
      return `${dailyFormatted}/day (${periodTotalFormatted} for ${durationDays} days)`;
    } else {
      if (isFlat) {
        return `${fmt(row.monthly_price)}/mo`;
      } else {
        return `${fmt(row.unit_price ?? 0)} per unit/mo`;
      }
    }
  }

  function itemInAddonMode(row?: CatalogRow) {
    if (!row) return false;
    if (mode !== "addon") return true;
    if (existingQtyFor(row.feature_key) > 0 && row.monthly_price > 0 && row.unit_price == null) {
      return false;
    }
    return true;
  }

  return (
    <div className="space-y-8">
      {error && <div className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {mode === "initial" && (
        <div className="bg-white rounded-3xl border border-border p-6 shadow-sm space-y-4">
          <SectionHeading>Choose Subscription Period</SectionHeading>
          <p className="text-xs text-ink-muted -mt-2">
            Select the period you want your active subscription to run. Default is 15 days.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs font-semibold text-ink-muted block mb-1">Start Date</label>
              <input
                type="date"
                min={todayStr}
                value={startDate}
                onChange={(e) => {
                  setStartDate(e.target.value);
                  const s = new Date(e.target.value);
                  const eD = new Date(endDate);
                  if (eD <= s) {
                    const newEnd = new Date(s);
                    newEnd.setDate(newEnd.getDate() + 15);
                    setEndDate(newEnd.toISOString().slice(0, 10));
                  }
                }}
                className="w-full border border-border rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-ink-muted block mb-1">End Date</label>
              <input
                type="date"
                min={startDate}
                value={endDate}
                onChange={(e) => {
                  const s = new Date(startDate);
                  const eD = new Date(e.target.value);
                  if (eD > s) {
                    setEndDate(e.target.value);
                  }
                }}
                className="w-full border border-border rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
          </div>
          <div className="text-xs font-semibold text-primary">
            Selected duration: {durationDays} days
          </div>
        </div>
      )}

      {packages.length > 0 && mode === "initial" && (
        <div>
          <SectionHeading>Quick-start packages</SectionHeading>
          <div className="grid gap-3 sm:grid-cols-2">
            {packages.map((pkg) => {
              const pkgDailyPrice = pkg.monthly_price / 30;
              const pkgPeriodTotal = pkgDailyPrice * durationDays;
              return (
                <button
                  key={pkg.id}
                  type="button"
                  onClick={() => applyPackage(pkg)}
                  className={`relative rounded-2xl border p-4 text-left transition-all ${
                    selectedPackage === pkg.id
                      ? "border-primary bg-gradient-to-br from-primary-light to-white shadow-sm"
                      : "border-border bg-white hover:border-primary/40"
                  }`}
                >
                  {pkg.discount_percent > 0 && (
                    <span className="absolute -top-2 right-3 rounded-full bg-primary px-2 py-0.5 text-[10px] font-bold text-white">
                      {pkg.discount_percent}% off
                    </span>
                  )}
                  <div className="mb-1 flex items-center gap-1.5 text-primary">
                    <Sparkles size={14} />
                    <p className="font-semibold text-ink">{pkg.name}</p>
                  </div>
                  <p className="text-lg font-bold text-ink">
                    {mode === "initial" ? (
                      <>
                        {fmt(Math.round(pkgDailyPrice * 100) / 100)}
                        <span className="text-xs font-medium text-ink-muted">/day</span>
                        <span className="text-xs font-semibold block text-primary mt-0.5">
                          {fmt(Math.round(pkgPeriodTotal * 100) / 100)} for {durationDays} days
                        </span>
                      </>
                    ) : (
                      <>
                        {fmt(pkg.monthly_price)}
                        <span className="text-xs font-medium text-ink-muted">/mo</span>
                      </>
                    )}
                  </p>

                  <div className="mt-3.5 space-y-1.5 border-t border-border/40 pt-2.5">
                    {pkg.feature_keys.map((item) => {
                      const row = byKey.get(item.feature_key);
                      if (!row) return null;
                      return (
                        <div key={item.feature_key} className="flex items-center justify-between text-xs text-ink-muted">
                          <span>{featureLabel(row.feature_key, row.display_name)}</span>
                          {item.quantity > 1 && (
                            <span className="font-semibold font-mono text-[10px] bg-surface-mid px-1 rounded-xs">
                              ×{item.quantity}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {(inbound || outbound) && (itemInAddonMode(inbound) || itemInAddonMode(outbound)) && (
        <div>
          <SectionHeading>Messaging</SectionHeading>
          <p className="mb-3 -mt-2 text-xs text-ink-muted">
            Conversations, Segments, Numbers Pool, Knowledge Base &amp; Analytics come free with either channel below.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {inbound && itemInAddonMode(inbound) && (
              <SelectCard
                selected={inbound.feature_key in selected}
                onClick={() => toggleItem(inbound.feature_key)}
                icon={ICONS.inbound_messaging}
                title="Inbound Messaging"
                subtitle={formatPricingText(inbound)}
                features={inboundFeatures}
              />
            )}
            {outbound && itemInAddonMode(outbound) && (
              <SelectCard
                selected={outbound.feature_key in selected}
                onClick={() => toggleItem(outbound.feature_key)}
                icon={ICONS.outbound_messaging}
                title="Outbound Messaging"
                subtitle={formatPricingText(outbound)}
                features={outboundFeatures}
              />
            )}
          </div>
        </div>
      )}

      {aiTiers.some((tier) => itemInAddonMode(tier)) && (
        <div>
          <SectionHeading>AI Replies</SectionHeading>
          <p className="mb-3 -mt-2 text-xs text-ink-muted">
            Required for automated replies and knowledge-base answers.
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            {aiTiers.filter(itemInAddonMode).map((tier) => (
              <SelectCard
                key={tier.feature_key}
                selected={tier.feature_key in selected}
                onClick={() => selectAiTier(tier.feature_key)}
                icon={ICONS[tier.feature_key] ?? Brain}
                title={featureLabel(tier.feature_key, tier.display_name)}
                subtitle={formatPricingText(tier)}
              />
            ))}
          </div>
        </div>
      )}

      {(sim || telecmi || upload || seats) && (itemInAddonMode(sim) || itemInAddonMode(telecmi) || itemInAddonMode(upload) || itemInAddonMode(seats)) && (
        <div>
          <SectionHeading>Telecalling</SectionHeading>
          <div className="space-y-3">
            {(sim && itemInAddonMode(sim)) || (telecmi && itemInAddonMode(telecmi)) ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {sim && itemInAddonMode(sim) && (
                  <SelectCard
                    selected={sim.feature_key in selected}
                    onClick={() => selectTelecallingType(sim.feature_key)}
                    icon={ICONS.telecalling_sim}
                    title="SIM-based"
                    subtitle={formatPricingText(sim)}
                  />
                )}
                {telecmi && itemInAddonMode(telecmi) && (
                  <SelectCard
                    selected={telecmi.feature_key in selected}
                    onClick={() => selectTelecallingType(telecmi.feature_key)}
                    icon={ICONS.telecalling_telecmi}
                    title="Cloud Telephony"
                    subtitle={formatPricingText(telecmi)}
                  />
                )}
              </div>
            ) : null}

            {seats && itemInAddonMode(seats) && (
              <div className="flex items-center justify-between rounded-2xl border border-border bg-white p-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-mid text-ink-muted">
                    <ICONS.telecaller_seats size={17} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-ink">Telecaller Seats</p>
                    <p className="text-xs text-ink-muted">
                      {formatPricingText(seats, selected[seats.feature_key] ?? 1, true)}
                      {existingQtyFor(seats.feature_key) > 0 && ` - currently ${existingQtyFor(seats.feature_key)} approved`}
                    </p>
                  </div>
                </div>
                <Stepper
                  value={selected[seats.feature_key] ?? 1}
                  onChange={(v) => setSelected((prev) => ({ ...prev, [seats.feature_key]: v }))}
                />
              </div>
            )}

            {upload && itemInAddonMode(upload) && (
              <SelectCard
                selected={upload.feature_key in selected}
                onClick={() => toggleItem(upload.feature_key)}
                icon={ICONS.bulk_lead_upload}
                title="Bulk Lead Upload"
                subtitle={formatPricingText(upload)}
                disabled={!hasTelecallingCoverage}
              />
            )}
          </div>
        </div>
      )}

      {numbers && itemInAddonMode(numbers) && (
        <div>
          <SectionHeading>Numbers Pool</SectionHeading>
          <div className="flex items-center justify-between rounded-2xl border border-border bg-white p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-mid text-ink-muted">
                <ICONS.numbers_pool size={17} />
              </div>
              <div>
                <p className="text-sm font-semibold text-ink">Phone Numbers</p>
                <p className="text-xs text-ink-muted">
                  {formatPricingText(numbers, selected[numbers.feature_key] ?? 1, true)}
                  {existingQtyFor(numbers.feature_key) > 0 && ` - currently ${existingQtyFor(numbers.feature_key)} approved`}
                </p>
              </div>
            </div>
            <Stepper
              value={selected[numbers.feature_key] ?? 1}
              onChange={(v) => setSelected((prev) => ({ ...prev, [numbers.feature_key]: v }))}
            />
          </div>
        </div>
      )}

      <div className="sticky bottom-0 flex items-center justify-between rounded-2xl border border-border bg-white/95 p-4 shadow-lg backdrop-blur">
        <div>
          <p className="text-xs font-medium text-ink-muted">{mode === "addon" ? "Due now" : "Total"}</p>
          <p className="text-2xl font-bold text-ink">
            {mode === "initial" ? fmt(Math.round(totalForPeriod * 100) / 100) : fmt(dueNow)}
            <span className="text-sm font-medium text-ink-muted">
              {mode === "initial" ? "" : mode === "addon" ? "" : "/mo"}
            </span>
          </p>
          {mode === "initial" ? (
            <p className="text-xs text-ink-muted">
              {fmt(Math.round((totalForPeriod / durationDays) * 100) / 100)}/day total for {durationDays} days
            </p>
          ) : (
            mode === "addon" && <p className="text-xs text-ink-muted">{fmt(total)}/mo from next cycle</p>
          )}
        </div>
        <button
          onClick={submit}
          disabled={submitting || Object.keys(selected).length === 0 || !canSubmit}
          title={canSubmit ? "Submit subscription request" : "Read-only role: submission is disabled"}
          className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-xs font-semibold rounded-lg hover:bg-primary-dark hover:scale-[1.02] active:scale-[0.98] transition-all duration-150 shadow-sm disabled:opacity-40 disabled:blur-[0.5px] disabled:scale-100 disabled:shadow-none"
        >
          {submitting ? "Submitting…" : mode === "addon" ? "Request Increase" : "Submit for Approval"}
        </button>
      </div>
    </div>
  );
}
