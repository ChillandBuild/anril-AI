"use client";
import { useEffect, useState } from "react";
import { Bot, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { operatorFetch } from "@/lib/operator";

interface AgentRepliesUsage {
  period_start: string;
  period_end: string | null;
  used: number;
  included: number;
  over: number;
  plan: { included: number; monthly_price: number } | null;
}

const inputCls =
  "w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary";

/** The client's Agent replies plan: included replies and monthly price (₹3,000 for 10,000 = ₹0.30 a reply).
 * Over the limit never blocks replies; the client sees it on Agents -> Usage. 0 included removes the plan. */
export function AgentRepliesCard({ tenantId }: { tenantId: string }) {
  const [usage, setUsage] = useState<AgentRepliesUsage | null>(null);
  const [included, setIncluded] = useState("");
  const [price, setPrice] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const show = (u: AgentRepliesUsage) => {
    setUsage(u);
    setIncluded(u.plan ? String(u.plan.included) : "");
    setPrice(u.plan ? String(u.plan.monthly_price) : "");
  };

  useEffect(() => {
    operatorFetch<AgentRepliesUsage>(`/api/v1/operator/clients/${tenantId}/agent-replies`)
      .then(show)
      .catch((e: Error) => setError(e.message || "Could not load agent replies"));
  }, [tenantId]);

  const n = Number(included);
  const p = Number(price);
  const valid = included.trim() !== "" && Number.isInteger(n) && n >= 0 && price.trim() !== "" && p >= 0;
  const perReply = valid && n > 0 ? p / n : null;

  const save = async () => {
    if (!valid) {
      setError("Enter whole included replies (0 removes the plan) and a price of 0 or more");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      show(await operatorFetch<AgentRepliesUsage>(`/api/v1/operator/clients/${tenantId}/agent-replies`, {
        method: "PUT",
        body: JSON.stringify({ included: n, monthly_price: p }),
      }));
      toast.success(n === 0 ? "Agent replies plan removed" : "Agent replies plan saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-card border border-border p-5 shadow-sm">
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink">
        <Bot size={16} className="text-ink-muted" /> Agent replies
      </h3>
      <p className="mb-4 text-xs text-ink-muted">
        {usage
          ? `${usage.used.toLocaleString("en-IN")} used this cycle${usage.plan ? ` of ${usage.included.toLocaleString("en-IN")}` : ", no plan"}${usage.over ? ` · ${usage.over.toLocaleString("en-IN")} over` : ""}. Never blocks replies.`
          : "Loading…"}
      </p>
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <label className="text-xs text-ink-secondary">
          Included replies / month
          <input className={`${inputCls} mt-1`} inputMode="numeric" value={included} placeholder="10000"
                 onChange={(e) => { setIncluded(e.target.value); setError(null); }} />
        </label>
        <label className="text-xs text-ink-secondary">
          Monthly price (₹)
          <input className={`${inputCls} mt-1`} inputMode="decimal" value={price} placeholder="3000"
                 onChange={(e) => { setPrice(e.target.value); setError(null); }} />
        </label>
        <button type="button" onClick={save} disabled={saving}
                className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-dark disabled:opacity-60">
          {saving && <Loader2 size={14} className="animate-spin" />} Save
        </button>
      </div>
      {perReply !== null && (
        <p className="mt-2 text-xs text-ink-muted">₹{perReply.toLocaleString("en-IN", { maximumFractionDigits: 4 })} per reply</p>
      )}
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </div>
  );
}
