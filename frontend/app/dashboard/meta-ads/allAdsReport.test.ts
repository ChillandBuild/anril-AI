import { describe, expect, it } from "vitest";
import type { AllAdsRow, MetaField } from "@/lib/api";
import { buildAllAdsCsv, computeTotals, fieldsToFetch } from "./allAdsReport";

const field = (key: string, format: MetaField["format"], label = key): MetaField =>
  ({ key, label, group: "Performance", format, breakdown_ok: true });

const row = (id: string, values: Record<string, unknown>, extra: Partial<AllAdsRow> = {}): AllAdsRow => ({
  meta_ad_id: id,
  ad_name: `Ad ${id}`,
  adset_name: "Set",
  campaign_name: "Camp",
  destination_type: "APP",
  ad_type: "App",
  breakdown: null,
  values,
  ...extra,
});

const FIELDS = [
  field("results", "number"), field("result_type", "text"), field("cost_per_result", "money"),
  field("reach", "number"), field("frequency", "decimal"), field("spend", "money"),
  field("cpm", "money"), field("quality_ranking", "text"), field("delivery", "text"),
];

// Two app-install ads from the Astro Tamil New account (9 Oct - 7 Nov 2026).
const ROWS = [
  row("52758584008890", { results: 641, result_type: "App installs", reach: 143088, impressions: 394526, spend: 11695.59 }),
  row("52758584305490", { results: 62, result_type: "App installs", reach: 18799, impressions: 31110, spend: 1019.64 }),
];

describe("fieldsToFetch", () => {
  it("adds the inputs the Total row needs", () => {
    const keys = fieldsToFetch(["cpm", "cost_per_result"]);
    expect(keys).toEqual(expect.arrayContaining(["spend", "impressions", "results", "result_type"]));
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("computeTotals", () => {
  it("adds counts, recomputes rates and uses Meta's de-duplicated reach", () => {
    const { values, reachEstimated } = computeTotals(ROWS, FIELDS, 155000);
    expect(values.results).toBe(703);
    expect(values.result_type).toBe("App installs");
    expect(values.spend).toBeCloseTo(12715.23);
    expect(values.cost_per_result).toBeCloseTo(12715.23 / 703);
    expect(values.reach).toBe(155000);
    expect(values.frequency).toBeCloseTo((394526 + 31110) / 155000);
    expect(values.cpm).toBeCloseTo((12715.23 / 425636) * 1000);
    expect(values.quality_ranking).toBeNull();
    expect(reachEstimated).toBe(false);
  });

  it("blanks Results when ads count different things", () => {
    const mixed = [...ROWS, row("9", { results: 77, result_type: "Landing page views", spend: 45 })];
    const { values } = computeTotals(mixed, FIELDS, 1);
    expect(values.results).toBeNull();
    expect(values.cost_per_result).toBeNull();
  });

  it("marks reach as an estimate only when Meta could not answer", () => {
    expect(computeTotals(ROWS, FIELDS, null).reachEstimated).toBe(true);
    expect(computeTotals(ROWS, FIELDS, null).values.reach).toBe(143088 + 18799);
    expect(computeTotals(ROWS, FIELDS, undefined).reachEstimated).toBe(false); // still loading
  });
});

describe("buildAllAdsCsv", () => {
  it("starts like an Ads Manager export and keeps Ad IDs whole for Excel", () => {
    const csv = buildAllAdsCsv(
      [row("120254601940750747", { spend: 77, delivery: "ADSET_PAUSED" }, { ad_name: 'Say "hi", Astro' })],
      [field("spend", "money", "Amount spent"), field("delivery", "text", "Delivery")],
      { date_from: "2026-08-01", date_to: "2026-11-07", breakdown: null },
    );
    const [header, line] = csv.replace("﻿", "").split("\r\n");
    expect(header).toBe("Reporting starts,Reporting ends,Ad ID,Campaign name,Ad set name,Ad name,Ad type,Amount spent,Delivery");
    expect(line).toBe('2026-08-01,2026-11-07,"=""120254601940750747""",Camp,Set,"Say ""hi"", Astro",App,77,Ad set off');
  });

  it("adds a Breakdown column only when broken down", () => {
    const csv = buildAllAdsCsv([row("1", {}, { breakdown: "18-24" })], [], {
      date_from: "2026-10-01", date_to: "2026-10-02", breakdown: "age",
    });
    expect(csv.split("\r\n")[0].endsWith(",Ad type,Breakdown")).toBe(true);
    expect(csv.split("\r\n")[1].endsWith(",App,18-24")).toBe(true);
  });
});
