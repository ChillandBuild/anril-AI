import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Metric } from "./reportsUi";
import { OverviewTab, TargetBar } from "./OverviewTab";

vi.mock("@/app/dashboard/contexts/AuthRoleContext", () => ({
  useAuthRole: () => ({ role: "agent", permissions: [] }),
}));

describe("Metric", () => {
  it("a people number is a button with a plain label", () => {
    const html = renderToStaticMarkup(<Metric label="New chats" value={42} people={{ metric: "new_chats" }} onPeople={() => {}} />);
    expect(html).toContain("<button");
    expect(html).toContain("Show the people");
  });
  it("a zero is not a button", () => {
    const html = renderToStaticMarkup(<Metric label="New chats" value={0} people={{ metric: "new_chats" }} onPeople={() => {}} />);
    expect(html).not.toContain("<button");
  });
  it("shows rupees and the before figure with a good-news arrow", () => {
    const html = renderToStaticMarkup(<Metric label="Sales" statKey="sales_paise" kind="paise" value={1840000} before={1000000} />);
    expect(html).toContain("₹18,400");
    expect(html).toContain("before: ₹10,000");
    expect(html).toContain("text-emerald-700");
  });
  it("a rise in cost is shown as bad news", () => {
    const html = renderToStaticMarkup(<Metric label="Cost per chat" statKey="cost_per_chat_paise" kind="paise" value={5000} before={4000} />);
    expect(html).toContain("text-red-700");
  });
});

describe("TargetBar", () => {
  it("shows rupees and a percent", () => {
    const html = renderToStaticMarkup(<TargetBar target={{ this_month: { month: "2026-11", target_paise: 20000000, money_in_paise: 18600000, pct: 93 } }} />);
    expect(html).toContain("₹1,86,000 of ₹2,00,000");
    expect(html).toContain("93%");
  });
  it("without money, only the percent", () => {
    const html = renderToStaticMarkup(<TargetBar target={{ this_month: { month: "2026-11", target_paise: 20000000, money_in_paise: null, pct: 93 } }} />);
    expect(html).not.toContain("₹");
    expect(html).toContain("of the target");
  });
  it("shows the profit estimate under the target for people who may see profit", () => {
    const html = renderToStaticMarkup(<TargetBar target={{ this_month: { month: "2026-11", target_paise: 20000000, money_in_paise: 18600000, pct: 93 }, profit_this_month: { profit_paise: 4250000, month: "2026-11" } }} />);
    expect(html).toContain("Target &amp; profit");
    expect(html).toContain("Estimated profit so far");
    expect(html).toContain("₹42,500");
  });
  it("profit alone still shows when no target is set; nothing at all without either", () => {
    const html = renderToStaticMarkup(<TargetBar target={{ this_month: { month: "2026-11" }, profit_this_month: { profit_paise: -50000, month: "2026-11" } }} />);
    expect(html).toContain("Estimated profit so far");
    expect(html).not.toContain("progressbar");
    expect(renderToStaticMarkup(<TargetBar target={{ this_month: { month: "2026-11" } }} />)).toBe("");
  });
  it("no profit line without the profit figure", () => {
    const html = renderToStaticMarkup(<TargetBar target={{ this_month: { month: "2026-11", target_paise: 20000000, money_in_paise: 1, pct: 1 } }} />);
    expect(html).not.toContain("Estimated profit");
    expect(html).toContain("Target for");
  });
  it("no target, no bar", () => {
    expect(renderToStaticMarkup(<TargetBar target={null} />)).toBe("");
  });
});

describe("Reports Overview while loading", () => {
  it("shows exactly one loader, not one for the report and one for the comparison", () => {
    const html = renderToStaticMarkup(
      <OverviewTab
        query="preset=last_7d"
        range={{ preset: "last_7d", start: "", end: "" }}
        comparison={{ mode: "previous", start: "", end: "" }}
        onMoneyHidden={() => {}}
      />,
    );
    expect(html.match(/aria-label="Loading"/g)?.length).toBe(1);
  });
});
