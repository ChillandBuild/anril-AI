import type { AllAdsRow, MetaField } from "@/lib/api";
import { deliveryLabel, formatMetaValue } from "./metaFields";

/** Columns the Total row and the download need even when they aren't on screen. */
const ALWAYS_FETCH = ["spend", "impressions", "inline_link_clicks", "clicks"];

/** A rate column's total is computed from its inputs, so those are fetched too. */
const NEEDS: Record<string, string[]> = {
  results: ["result_type"],
  cost_per_result: ["results", "result_type"],
  cost_per_messaging_conversation: ["messaging_conversations_started"],
  cost_per_lead: ["leads"],
  purchase_roas: ["purchase_value"],
};

export function fieldsToFetch(columns: string[]): string[] {
  const keys = [...columns, ...ALWAYS_FETCH];
  for (const column of columns) keys.push(...(NEEDS[column] ?? []));
  return Array.from(new Set(keys));
}

/** Counts that add up across ads and breakdown rows. Reach and unique clicks are
 * people, not events, so adding them would count someone twice. */
const NOT_ADDITIVE = new Set(["reach", "unique_clicks", "results"]);

function num(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function sum(rows: AllAdsRow[], key: string): number {
  return rows.reduce((total, row) => total + (num(row.values?.[key]) ?? 0), 0);
}

function ratio(top: number, bottom: number, scale = 1): number | null {
  return bottom ? (top / bottom) * scale : null;
}

/**
 * The Total row, the way Ads Manager totals: counts add up, rates are worked out
 * again from the totals, reach comes de-duplicated from Meta (`totalReach`).
 * Results add up only when every ad counts the same thing; mixed types show "—".
 * Rankings, text and budgets have no total.
 */
export function computeTotals(
  rows: AllAdsRow[],
  fields: MetaField[],
  totalReach: number | null | undefined,
): { values: Record<string, unknown>; reachEstimated: boolean } {
  const spend = sum(rows, "spend");
  const impressions = sum(rows, "impressions");
  const linkClicks = sum(rows, "inline_link_clicks");
  const clicks = sum(rows, "clicks");
  // undefined = still loading (no mark yet); null = Meta couldn't answer.
  const reachEstimated = totalReach === null && rows.length > 1;
  const reach = totalReach ?? sum(rows, "reach");

  const resultTypes = new Set(
    rows.map((row) => row.values?.result_type).filter((type): type is string => typeof type === "string" && type !== ""),
  );
  const singleType = resultTypes.size === 1 ? Array.from(resultTypes)[0] : null;
  const results = singleType ? sum(rows, "results") : null;

  const computed: Record<string, unknown> = {
    spend,
    impressions,
    inline_link_clicks: linkClicks,
    clicks,
    reach,
    frequency: ratio(impressions, reach),
    cpm: ratio(spend, impressions, 1000),
    cost_per_inline_link_click: ratio(spend, linkClicks),
    inline_link_click_ctr: ratio(linkClicks, impressions, 100),
    ctr: ratio(clicks, impressions, 100),
    cpc: ratio(spend, clicks),
    results,
    result_type: singleType,
    cost_per_result: results ? spend / results : null,
    cost_per_messaging_conversation: ratio(spend, sum(rows, "messaging_conversations_started")),
    cost_per_lead: ratio(spend, sum(rows, "leads")),
    purchase_value: sum(rows, "purchase_value"),
    purchase_roas: ratio(sum(rows, "purchase_value"), spend),
  };

  const values: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.key in computed) values[field.key] = computed[field.key];
    else if (field.format === "number" && !NOT_ADDITIVE.has(field.key)) values[field.key] = sum(rows, field.key);
    else values[field.key] = null;
  }
  return { values, reachEstimated };
}

/** Excel shows 18-digit Meta ids as 1.20255E+17 and drops the last digits; this
 * formula keeps them as text. Google Sheets reads it the same way. */
function excelText(value: string): string {
  return value ? `="${value}"` : "";
}

function csvCell(value: unknown, field: MetaField): string {
  if (value === null || value === undefined || value === "") return "";
  if (field.key === "delivery") return deliveryLabel(value);
  if (field.format === "image" || field.format === "date") return String(value);
  if (typeof value === "object") {
    const shown = formatMetaValue(value, field.format);
    return typeof shown === "string" && shown !== "—" ? shown : "";
  }
  if (field.format === "text") {
    const shown = formatMetaValue(value, field.format);
    return typeof shown === "string" ? shown : String(value);
  }
  return String(num(value) ?? value);
}

function quote(cell: string): string {
  return /[",\n\r]/.test(cell) ? `"${cell.replaceAll('"', '""')}"` : cell;
}

/** The download: Ads Manager's identity columns first, so the two files line up
 * by Ad ID, then exactly the columns, ad type and breakdown shown on screen. */
export function buildAllAdsCsv(
  rows: AllAdsRow[],
  fields: MetaField[],
  report: { date_from: string; date_to: string; breakdown: string | null },
): string {
  const header = [
    "Reporting starts", "Reporting ends", "Ad ID", "Campaign name", "Ad set name", "Ad name", "Ad type",
    ...(report.breakdown ? ["Breakdown"] : []),
    ...fields.map((field) => field.label),
  ];
  const lines = rows.map((row) => [
    report.date_from,
    report.date_to,
    excelText(row.meta_ad_id),
    row.campaign_name ?? "",
    row.adset_name ?? "",
    row.ad_name ?? "",
    row.ad_type ?? "",
    ...(report.breakdown ? [row.breakdown ?? ""] : []),
    ...fields.map((field) => csvCell(row.values?.[field.key], field)),
  ]);
  return "﻿" + [header, ...lines].map((line) => line.map(quote).join(",")).join("\r\n");
}
