import { describe, expect, it } from "vitest";
import { groupAlertsByArea, hourLabel, statusWords, type AlertRow } from "./automationsApi";

describe("hourLabel", () => {
  it("writes hours the way people say them", () => {
    expect(hourLabel(21)).toBe("9 PM");
    expect(hourLabel(9)).toBe("9 AM");
    expect(hourLabel(0)).toBe("12 AM");
    expect(hourLabel(12)).toBe("12 PM");
    expect(hourLabel(23)).toBe("11 PM");
  });
});

describe("statusWords", () => {
  it("uses plain words", () => {
    expect(statusWords("APPROVED")).toBe("Approved");
    expect(statusWords("PENDING")).toBe("Waiting for WhatsApp to approve");
    expect(statusWords("REJECTED")).toBe("Turned down by WhatsApp");
    expect(statusWords(null)).toBe("");
  });
});

describe("groupAlertsByArea", () => {
  const row = (key: string, area: string): AlertRow => ({
    key, label: key, area, who: ["owner"], how: ["bell"], on: true, comes_through_in_quiet_time: false,
  });
  it("keeps first-seen order and groups by area", () => {
    const g = groupAlertsByArea([row("a", "Chats"), row("b", "Money"), row("c", "Chats")]);
    expect(g.map((x) => x.area)).toEqual(["Chats", "Money"]);
    expect(g[0].rows.map((r) => r.key)).toEqual(["a", "c"]);
  });
});
