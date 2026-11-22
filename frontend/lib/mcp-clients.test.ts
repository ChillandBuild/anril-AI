import { describe, expect, it } from "vitest";
import { formatAllowedDate } from "./claude-access";
import { connectionLabel, sentLabel, statusTag, withSwitch, type McpClientRow } from "./mcp-clients";

const row = (over: Partial<McpClientRow> = {}): McpClientRow => ({
  tenant_id: "t1",
  name: "Astro Tamil",
  status: "active",
  on: true,
  connected: true,
  connected_at: "2026-11-10T08:30:00Z",
  last_used_at: null,
  sent_today: 0,
  daily_cap: 500,
  ...over,
});

describe("connectionLabel", () => {
  it("says Off when the switch is off, even if it was connected before", () => {
    expect(connectionLabel(row({ on: false, connected: true }))).toBe("Off");
    expect(connectionLabel(row({ on: false, connected: false }))).toBe("Off");
  });

  it("says Not connected yet when on but nobody connected", () => {
    expect(connectionLabel(row({ on: true, connected: false, connected_at: null }))).toBe("Not connected yet");
  });

  it("says Connected with the allowed date when on and connected", () => {
    const label = connectionLabel(row());
    expect(label).toBe(`Connected · allowed ${formatAllowedDate("2026-11-10T08:30:00Z")}`);
    expect(label.startsWith("Connected")).toBe(true);
  });

  it("says plain Connected when the date is missing", () => {
    expect(connectionLabel(row({ connected_at: null }))).toBe("Connected");
  });
});

describe("sentLabel", () => {
  it("shows sent / cap", () => {
    expect(sentLabel(row({ sent_today: 12 }))).toBe("12 / 500");
    expect(sentLabel(row({ sent_today: 0 }))).toBe("0 / 500");
  });

  it("shows a dash when off and nothing was sent", () => {
    expect(sentLabel(row({ on: false, sent_today: 0 }))).toBe("—");
  });

  it("still shows the count when off but something was sent today", () => {
    expect(sentLabel(row({ on: false, sent_today: 7 }))).toBe("7 / 500");
  });
});

describe("statusTag", () => {
  it("hides the tag for active clients", () => {
    expect(statusTag("active")).toBeNull();
    expect(statusTag("Active")).toBeNull();
    expect(statusTag("")).toBeNull();
  });

  it("returns the status for any other", () => {
    expect(statusTag("suspended")).toBe("suspended");
  });
});

describe("withSwitch", () => {
  it("changes only the named client and does not mutate the input", () => {
    const list = [row({ tenant_id: "a" }), row({ tenant_id: "b" })];
    const next = withSwitch(list, "b", false);
    expect(next.map((c) => c.on)).toEqual([true, false]);
    expect(list[1].on).toBe(true);
  });
});
