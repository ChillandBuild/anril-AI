"use client";
import { formatRupees } from "@/components/deals/money";
import type { GoogleAdsReport, GoogleAdsRow } from "@/lib/googleAdsApi";

/**
 * "In short": the one or two things worth knowing this month, in plain words. Money words only
 * when the person may see money. Empty when there is nothing to say.
 */
export function inShort(rows: GoogleAdsRow[], showMoney: boolean): string {
  const withChats = rows.filter((r) => r.chats > 0);
  if (withChats.length === 0) return "";
  const parts: string[] = [];
  if (showMoney) {
    const selling = rows.filter((r) => r.paid_orders > 0 && (r.spent_paise ?? 0) > 0)
      .map((r) => ({ r, perSale: Math.round((r.spent_paise ?? 0) / r.paid_orders) }))
      .sort((a, b) => a.perSale - b.perSale);
    if (selling[0]) parts.push(`"${selling[0].r.name}" brings paying customers at ${formatRupees(selling[0].perSale)} per sale.`);
    const wasted = rows.filter((r) => (r.spent_paise ?? 0) > 0 && r.paid_orders === 0);
    if (wasted.length && selling[0]) {
      parts.push(`${wasted.map((r) => `"${r.name}"`).join(", ")} had no sale this month, so think about moving its money to "${selling[0].r.name}".`);
    } else if (wasted.length) {
      parts.push(`${wasted.map((r) => `"${r.name}"`).join(", ")} had no sale this month yet.`);
    }
  }
  if (parts.length === 0) {
    const best = [...withChats].sort((a, b) => b.hot - a.hot || b.chats - a.chats)[0];
    parts.push(`"${best.name}" brings the most ${best.hot > 0 ? "Hot leads" : "chats"} (${best.hot > 0 ? best.hot : best.chats}).`);
  }
  return parts.join(" ");
}

/** Spent · Clicks · Chats + calls · Hot · Paid. */
export function GoogleAdsSummary({ report, showMoney }: { report: GoogleAdsReport; showMoney: boolean }) {
  const t = report.totals;
  const perClick = showMoney && t.spent_paise && t.clicks ? formatRupees(Math.round(t.spent_paise / t.clicks)) : null;
  const perPaying = showMoney && t.spent_paise && t.paid_orders ? formatRupees(Math.round(t.spent_paise / t.paid_orders)) : null;
  const boxes = [
    ...(showMoney ? [{ label: "Spent", value: t.spent_paise != null ? formatRupees(t.spent_paise) : "—", hint: t.spent_paise != null ? "this month" : "add the spend below" }] : []),
    { label: "Clicks", value: t.clicks != null ? t.clicks.toLocaleString("en-IN") : "—", hint: perClick ? `${perClick} per click` : "from the spend report" },
    { label: "Chats + calls", value: (t.chats + t.calls).toLocaleString("en-IN"), hint: `${t.chats} WhatsApp · ${t.calls} calls` },
    { label: "Hot", value: t.hot.toLocaleString("en-IN"), hint: "scored by the AI agent", tone: "text-[#b42318]" },
    {
      label: "Paid",
      value: showMoney && t.paid_paise != null ? `${t.paid_orders} · ${formatRupees(t.paid_paise)}` : String(t.paid_orders),
      hint: perPaying ? `${perPaying} per paying customer` : "customers who paid", tone: "text-[#067647]",
    },
  ];
  const summary = inShort(report.rows, showMoney);
  return (
    <div className="space-y-3">
      <div className={`grid grid-cols-2 gap-3 ${boxes.length === 5 ? "lg:grid-cols-5" : "lg:grid-cols-4"}`}>
        {boxes.map((b) => (
          <div key={b.label} className="card rounded-2xl px-4 py-3">
            <p className="text-xs font-semibold text-on-surface-muted">{b.label}</p>
            <p className={`text-2xl font-bold tabular-nums ${b.tone ?? "text-on-surface"}`}>{b.value}</p>
            <p className="truncate text-xs text-on-surface-muted">{b.hint}</p>
          </div>
        ))}
      </div>
      {summary && (
        <p className="rounded-2xl border border-primary/20 bg-primary-light/40 px-4 py-3 text-sm text-on-surface">💡 In short: {summary}</p>
      )}
    </div>
  );
}
